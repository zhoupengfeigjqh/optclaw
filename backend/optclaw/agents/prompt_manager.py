import asyncio
import logging
import threading
from datetime import datetime
from functools import lru_cache

from optclaw.config.agents_config import load_agent_soul
from optclaw.skills import load_skills
from optclaw.skills.types import Skill

from optclaw.log import setup_logging
logger = setup_logging(__name__)

_ENABLED_SKILLS_REFRESH_WAIT_TIMEOUT_SECONDS = 5.0
_enabled_skills_lock = threading.Lock()
_enabled_skills_cache: list[Skill] | None = None
_enabled_skills_refresh_active = False
_enabled_skills_refresh_version = 0
_enabled_skills_refresh_event = threading.Event()


def _load_enabled_skills_sync() -> list[Skill]:
    return list(load_skills(enabled_only=True))


def _start_enabled_skills_refresh_thread() -> None:
    threading.Thread(
        target=_refresh_enabled_skills_cache_worker,
        name="optclaw-enabled-skills-loader",
        daemon=True,
    ).start()


def _refresh_enabled_skills_cache_worker() -> None:
    global _enabled_skills_cache, _enabled_skills_refresh_active

    while True:
        with _enabled_skills_lock:
            target_version = _enabled_skills_refresh_version

        try:
            skills = _load_enabled_skills_sync()
        except Exception:
            logger.exception("Failed to load enabled skills for prompt injection")
            skills = []

        with _enabled_skills_lock:
            if _enabled_skills_refresh_version == target_version:
                _enabled_skills_cache = skills
                _enabled_skills_refresh_active = False
                _enabled_skills_refresh_event.set()
                return

            # A newer invalidation happened while loading. Keep the worker alive
            # and loop again so the cache always converges on the latest version.
            _enabled_skills_cache = None


def _ensure_enabled_skills_cache() -> threading.Event:
    global _enabled_skills_refresh_active

    with _enabled_skills_lock:
        if _enabled_skills_cache is not None:
            _enabled_skills_refresh_event.set()
            return _enabled_skills_refresh_event
        if _enabled_skills_refresh_active:
            return _enabled_skills_refresh_event
        _enabled_skills_refresh_active = True
        _enabled_skills_refresh_event.clear()

    _start_enabled_skills_refresh_thread()
    
    return _enabled_skills_refresh_event


def _invalidate_enabled_skills_cache() -> threading.Event:
    global _enabled_skills_cache, _enabled_skills_refresh_active, _enabled_skills_refresh_version

    _get_cached_skills_prompt_section.cache_clear()
    with _enabled_skills_lock:
        _enabled_skills_cache = None
        _enabled_skills_refresh_version += 1
        _enabled_skills_refresh_event.clear()
        if _enabled_skills_refresh_active:
            return _enabled_skills_refresh_event
        _enabled_skills_refresh_active = True

    _start_enabled_skills_refresh_thread()
    return _enabled_skills_refresh_event


def prime_enabled_skills_cache() -> None:
    _ensure_enabled_skills_cache()


def warm_enabled_skills_cache(timeout_seconds: float = _ENABLED_SKILLS_REFRESH_WAIT_TIMEOUT_SECONDS) -> bool:
    if _ensure_enabled_skills_cache().wait(timeout=timeout_seconds):
        return True

    logger.warning("Timed out waiting %.1fs for enabled skills cache warm-up", timeout_seconds)
    return False


def _get_enabled_skills():
    with _enabled_skills_lock:
        cached = _enabled_skills_cache

    if cached is not None:
        return list(cached)

    _ensure_enabled_skills_cache()
    return []


def _skill_mutability_label(category: str) -> str:
    return "[custom, editable]" if category == "custom" else "[built-in]"


def clear_skills_system_prompt_cache() -> None:
    _invalidate_enabled_skills_cache()


async def refresh_skills_system_prompt_cache_async() -> None:
    await asyncio.to_thread(_invalidate_enabled_skills_cache().wait)


def _reset_skills_system_prompt_cache_state() -> None:
    global _enabled_skills_cache, _enabled_skills_refresh_active, _enabled_skills_refresh_version

    _get_cached_skills_prompt_section.cache_clear()
    with _enabled_skills_lock:
        _enabled_skills_cache = None
        _enabled_skills_refresh_active = False
        _enabled_skills_refresh_version = 0
        _enabled_skills_refresh_event.clear()


def _refresh_enabled_skills_cache() -> None:
    """Backward-compatible test helper for direct synchronous reload."""
    try:
        skills = _load_enabled_skills_sync()
    except Exception:
        logger.exception("Failed to load enabled skills for prompt injection")
        skills = []

    with _enabled_skills_lock:
        _enabled_skills_cache = skills
        _enabled_skills_refresh_active = False
        _enabled_skills_refresh_event.set()


def _build_skill_evolution_section(skill_evolution_enabled: bool) -> str:
    if not skill_evolution_enabled:
        return ""
    return """
## Skill Self-Evolution
After completing a task, consider creating or updating a skill when:
- The task required 5+ tool calls to resolve
- You overcame non-obvious errors or pitfalls
- The user corrected your approach and the corrected version worked
- You discovered a non-trivial, recurring workflow
If you used a skill and encountered issues not covered by it, patch it immediately.
Prefer patch over edit. Before creating a new skill, confirm with the user first.
Skip simple one-off tasks.
"""


def _build_subagent_section(max_concurrent: int) -> str:
    """Build the subagent system prompt section with dynamic concurrency limit.

    Args:
        max_concurrent: Maximum number of concurrent subagent calls allowed per response.

    Returns:
        Formatted subagent section string.
    """
    n = max_concurrent
    return f"""<subagent_system>
**🚀 SUBAGENT 模式 — 拆解 → 委托 → 合成**

你是任务编排器。核心原则：复杂任务拆成并行子任务，委托给 subagent 并行执行，最后合成结果。

**⛔ 硬限制：每轮最多 {n} 个 task 调用，超出直接丢弃。**
- ≤{n} 个子任务 → 本轮全部启动
- >{n} 个 → 选最重要的 {n} 个先执行，剩余下轮继续
- 启动前必须在思考中计数，超过 {n} 必须分批

**可用 Subagent：** general-purpose（通用任务）、coder（代码编写执行）

**✅ 使用场景（拆解 + 并行）：**
复杂查询拆成多个独立子任务，并行执行后合成。例如"腾讯股价为何下跌？"→ 3 个 subagent 并行查财报/负面新闻/行业趋势 → 合成结果。

**❌ 不要用（直接执行）：**
- 拆不出 2+ 个有意义的并行子任务
- 简单操作（读文件、改几行代码、单条命令）
- 需要先澄清用户需求
- 步骤间存在强顺序依赖

**工作机制：** task 工具后台异步运行，自动轮询等待结果，调用阻塞直到完成。

**示例（≤{n} 个子任务，单批次）：**
task(description="腾讯财报数据", prompt="...", subagent_type="general-purpose")
task(description="腾讯负面新闻", prompt="...", subagent_type="general-purpose")
task(description="行业市场趋势", prompt="...", subagent_type="general-purpose")
# 3 个并行运行 → 下轮合成结果
</subagent_system>"""


SYSTEM_PROMPT_TEMPLATE = """
<角色>
你是 {agent_name}，一个超级智能体。
</角色>

{soul}
{memory_context}

<思维准则>
- 行动前先简要分析用户请求：哪些是明确的？哪些含糊？哪些缺失？
- **优先检查：如有任何不明确、缺失或存在多种解读的内容，必须先澄清，禁止直接开始工作**
- 思考过程只写大纲，不要写完整最终答案
- 思考是内部规划，回复才是交付——每次思考后必须给用户可见的回复
{subagent_thinking}</思维准则>

<澄清系统>
**工作流优先级：澄清 → 规划 → 执行**

在以下场景必须调用 ask_clarification，禁止先动手再问：

| 场景 | 类型 | 示例 |
|------|------|------|
| 关键信息缺失 | missing_info | "写个爬虫"但没说目标网站 |
| 需求有歧义 | ambiguous_requirement | "优化代码"可能是性能/可读性/内存 |
| 存在多种方案 | approach_choice | "加认证"可用JWT/OAuth/Session |
| 高危操作 | risk_confirmation | 删文件、改生产配置、数据库操作 |
| 建议需确认 | suggestion | 推荐重构但需用户点头 |

调用方式：ask_clarification(question="...", clarification_type="...", context="...", options=[...])
调用后执行中断，等待用户回复，不要假设答案继续执行。
</澄清系统>

{skills_section}

{subagent_section}

<工作目录 existed="true">
- 用户上传：`/mnt/user-data/uploads` — 自动列在上下文中
- 工作区：`/mnt/user-data/workspace` — 临时文件默认目录
- 输出：`/mnt/user-data/outputs` — 最终交付物存放处
- 优先使用相对路径（如 `hello.txt`、`../uploads/data.csv`），避免硬编码 `/mnt/user-data/...`
- 最终交付物须复制到 `/mnt/user-data/outputs` 并用 present_file 呈现
</工作目录>

<输出规范>
- 简洁清晰，除非要求否则避免过度格式化
- 使用段落和自然语言，默认不用列表
- 引用外部资源时提供引用链接：[描述](URL)
- 鼓励使用图片和 Mermaid 图表（`![描述](路径)` 或 ```mermaid）
- 善用并行工具调用，一次发起多个独立操作
</输出规范>

<关键规则>
- **澄清优先**：需求不清必须先问，禁止假设
{subagent_reminder}- 复杂任务先加载对应 Skill
- 语言与用户保持一致
- 思考内部，回复可见——每次都必须给用户回复
</关键规则>

**极其重要：除了代码等情境外，对话过程中答复的内容，一律使用简体中文输出！**"""


def _get_memory_context(agent_name: str | None = None) -> str:
    """Get memory context for injection into system prompt.

    Args:
        agent_name: If provided, loads per-agent memory. If None, loads global memory.

    Returns:
        Formatted memory context string wrapped in XML tags, or empty string if disabled.
    """
    try:
        from optclaw.agents.memory import format_memory_for_injection, get_memory_data
        from optclaw.config.memory_config import get_memory_config

        config = get_memory_config()

        if not config.enabled or not config.injection_enabled:
            return ""
        
        memory_data = get_memory_data(agent_name)
        # memory_data = {"version":"1.0","lastUpdated":"2026-05-12T08:18:49.407150Z","user":{"workContext":{"summary":"AI Agent、生产调度APS、工业软件架构设计，Python全栈开发、数据分析与知识图谱应用","updatedAt":"2026-05-12"},"personalContext":{"summary":"关注学历升学规划、自驾旅行、中药材行业研究、体育赛事与金融量化资讯","updatedAt":"2026-05-12"},"topOfMind":{"summary":"专注AI Agent框架源码解析、跨环境开发适配、工业系统业务流程设计","updatedAt":"2026-05-12"}},"history":{"recentMonths":{"summary":"深耕大模型智能体、LangChain/LangGraph应用，研究ISA-95、MES/ERP/APS工业标准与系统集成","updatedAt":"2026-05-12"},"earlierContext":{"summary":"具备全栈开发、数据库设计、论文学术研究、专业升学对比规划经验","updatedAt":"2026-05-12"},"longTermBackground":{"summary":"工科背景，擅长技术架构设计、算法与AI应用落地、结构化数据治理","updatedAt":"2026-05-12"}},"facts":[]}

        memory_content = format_memory_for_injection(memory_data, max_tokens=config.max_injection_tokens)

        if not memory_content.strip():
            return ""

        return f"""<memory>{memory_content}</memory>"""
    except Exception as e:
        logger.error("Failed to load memory context: %s", e)
        return ""


@lru_cache(maxsize=32)
def _get_cached_skills_prompt_section(
    skill_signature: tuple[tuple[str, str, str, str], ...],
    available_skills_key: tuple[str, ...] | None,
    container_base_path: str,
    skill_evolution_section: str,
) -> str:
    filtered = [(name, description, category, location) for name, description, category, location in skill_signature if available_skills_key is None or name in available_skills_key]
    skills_list = ""
    if filtered:
        skill_items = "\n".join(
            f"    <skill>\n        <name>{name}</name>\n        <description>{description} {_skill_mutability_label(category)}</description>\n        <location>{location}</location>\n    </skill>"
            for name, description, category, location in filtered
        )
        skills_list = f"<available_skills>\n{skill_items}\n</available_skills>"
    return f"""<skill_system>
You have access to skills that provide optimized workflows for specific tasks. Each skill contains best practices, frameworks, and references to additional resources.

**Progressive Loading Pattern:**
1. When a user query matches a skill's use case, immediately call `read_file` on the skill's main file using the path attribute provided in the skill tag below
2. Read and understand the skill's workflow and instructions
3. The skill file contains references to external resources under the same folder
4. Load referenced resources only when needed during execution
5. Follow the skill's instructions precisely

**Skills are located at:** {container_base_path}
{skill_evolution_section}
{skills_list}

</skill_system>"""


def get_skills_prompt_section(available_skills: set[str] | None = None) -> str:
    """Generate the skills prompt section with available skills list."""
    skills = _get_enabled_skills()
    # print(111)
    # print(skills)
    # print(111)

    try:
        from optclaw.config import get_app_config

        config = get_app_config()
        container_base_path = config.skills.container_path
        skill_evolution_enabled = config.skill_evolution.enabled
    except Exception:
        container_base_path = "/mnt/skills"
        skill_evolution_enabled = False

    if not skills and not skill_evolution_enabled:
        return ""

    if available_skills is not None and not any(skill.name in available_skills for skill in skills):
        return ""

    skill_signature = tuple((skill.name, skill.description, skill.category, skill.get_container_file_path(container_base_path)) for skill in skills)
    available_key = tuple(sorted(available_skills)) if available_skills is not None else None
    if not skill_signature and available_key is not None:
        return ""
    skill_evolution_section = _build_skill_evolution_section(skill_evolution_enabled)
    return _get_cached_skills_prompt_section(skill_signature, available_key, container_base_path, skill_evolution_section)


def get_agent_soul(agent_name: str | None) -> str:
    # Append SOUL.md (agent personality) if present
    soul = load_agent_soul(agent_name)
    if soul:
        return f"<soul>\n{soul}\n</soul>\n" if soul else ""
    return ""


def apply_prompt_template(agent_name: str | None = None, available_skills: set[str] | None = None, subagent_enabled: bool = False, max_concurrent_subagents: int = 2) -> str:
    # Get memory context
    memory_context = _get_memory_context(agent_name)
    # print("***********memory************")
    # print(memory_context)
    # print("***********memory************")

    # Include subagent section only if enabled (from runtime parameter)
    n = max_concurrent_subagents
    subagent_section = _build_subagent_section(n) if subagent_enabled else ""

    # Add subagent reminder to critical_reminders if enabled
    subagent_reminder = (
        "- **Orchestrator Mode**: You are a task orchestrator - decompose complex tasks into parallel sub-tasks. "
        f"**HARD LIMIT: max {n} `task` calls per response.** "
        f"If >{n} sub-tasks, split into sequential batches of ≤{n}. Synthesize after ALL batches complete.\n"
        if subagent_enabled
        else ""
    )

    # Add subagent thinking guidance if enabled
    subagent_thinking = (
        "- **DECOMPOSITION CHECK: Can this task be broken into 2+ parallel sub-tasks? If YES, COUNT them. "
        f"If count > {n}, you MUST plan batches of ≤{n} and only launch the FIRST batch now. "
        f"NEVER launch more than {n} `task` calls in one response.**\n"
        if subagent_enabled
        else ""
    )

    # Get skills section
    skills_section = get_skills_prompt_section(available_skills)
    # print("***********skills_section************")
    # print(skills_section)
    # print("***********skills_section************")

    # Format the prompt with dynamic skills and memory
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=agent_name or "optclaw general agent",
        soul=get_agent_soul(agent_name),
        skills_section=skills_section,
        memory_context=memory_context,
        subagent_reminder=subagent_reminder,
        subagent_thinking=subagent_thinking,
        subagent_section=subagent_section
    )

    return prompt + f"\n<current_date>{datetime.now().strftime('%Y-%m-%d, %A')}</current_date>"
