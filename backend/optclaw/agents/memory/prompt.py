"""Prompt templates for memory update and injection."""

import math
import re
from typing import Any

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

# Prompt template for updating memory based on conversation
MEMORY_UPDATE_PROMPT = """你是记忆管理系统。分析对话并更新用户记忆档案。

当前记忆状态：
<current_memory>
{current_memory}
</current_memory>

待处理的新对话：
<conversation>
{conversation}
</conversation>

指令：
1. 分析对话中关于用户的重要信息
2. 提取相关事实、偏好和上下文，包含具体细节（数字、名称、技术）
3. 按以下详细长度指南更新各记忆分区

提取事实前，对对话进行结构化反思：
1. 错误/重试检测：Agent 是否遇到错误、需要重试或产生错误结果？
   如是，将根因和正确做法记录为高置信度事实，category 设为 "correction"。
2. 用户纠正检测：用户是否纠正了 Agent 的方向、理解或输出？
   如是，将正确的解释或方法记录为高置信度事实，category 设为 "correction"。
   仅当 category 为 "correction" 且对话中明确存在错误时，才在 "sourceError" 中注明错误内容。
3. 项目约束发现：对话中是否发现了项目特定的约束？
   如是，记录为最合适类别和置信度的事实。

{correction_hint}

记忆分区指南：

**用户上下文**（当前状态 - 简洁摘要）：
- workContext：职业角色、公司、关键项目、主要技术（2-3 句）
  示例：核心贡献者，含指标的项目名称（16k+ stars），技术栈
- personalContext：语言、沟通偏好、关键兴趣（1-2 句）
  示例：双语能力、特定兴趣领域、专业领域
- topOfMind：多个当前关注领域和优先级（3-5 句，详细段落）
  示例：主要项目工作、并行技术调研、持续学习/跟踪
  包含：活跃的实现工作、排障问题、市场/研究兴趣
  注意：此处捕获多个并发关注领域，而非单一任务

**历史记录**（时间上下文 - 丰富段落）：
- recentMonths：近期活动详细摘要（4-6 句或 1-2 段）
  时间线：最近 1-3 个月的交互
  包含：探索的技术、从事的项目、解决的问题、展现的兴趣
- earlierContext：重要的历史模式（3-5 句或 1 段）
  时间线：3-12 个月前
  包含：过往项目、学习历程、已建立的模式
- longTermBackground：持久背景和基础上下文（2-4 句）
  时间线：整体/基础性信息
  包含：核心专长、长期兴趣、基本工作风格

**事实提取**：
- 提取具体、可量化的细节（如 "16k+ GitHub stars"、"200+ 数据集"）
- 包含专有名词（公司名、项目名、技术名）
- 保留技术术语和版本号
- 类别：
  * preference：用户偏好/不喜欢的工具、风格、方法
  * knowledge：特定专长、掌握的技术、领域知识
  * context：背景事实（职位、项目、地点、语言）
  * behavior：工作模式、沟通习惯、问题解决方法
  * goal：明确的目标、学习方向、项目抱负
  * correction：明确的 Agent 错误或用户纠正，含正确做法
- 置信度：
  * 0.9-1.0：明确陈述的事实（"我在做 X"、"我的角色是 Y"）
  * 0.7-0.8：从行为/讨论中强推断
  * 0.5-0.6：推断的模式（谨慎使用，仅用于明显模式）

**内容归属**：
- workContext：当前工作、活跃项目、主要技术栈
- personalContext：语言、个性、工作之外的兴趣
- topOfMind：用户近期关注的多个优先级和焦点（更新最频繁）
  应捕获 3-5 个并发主题：主要工作、副业探索、学习/跟踪兴趣
- recentMonths：近期技术探索和工作的详细记录
- earlierContext：较早但仍有参考价值的交互模式
- longTermBackground：用户不变的底层基础事实

**多语言内容**：
- 专有名词和公司名保留原文
- 技术术语保留原形式（DeepSeek、LangGraph 等）
- 在 personalContext 中注明语言能力

输出格式（JSON）：
{{
  "user": {{
    "workContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "personalContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "topOfMind": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "history": {{
    "recentMonths": {{ "summary": "...", "shouldUpdate": true/false }},
    "earlierContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "longTermBackground": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "newFacts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0 }}
  ],
  "factsToRemove": ["fact_id_1", "fact_id_2"]
}}

重要规则：
- 只有存在有意义的新信息时才设 shouldUpdate=true
- 遵循长度指南：workContext/personalContext 简洁（1-3 句），topOfMind 和历史分区详细（段落）
- 事实中包含具体指标、版本号和专有名词
- 仅添加明确陈述（0.9+）或强推断（0.7+）的事实
- category "correction" 用于明确的 Agent 错误或用户纠正；纠正明确时置信度 >= 0.95
- "sourceError" 仅用于明确的纠正事实，且之前的错误或错误做法在对话中明确陈述；否则省略
- 删除与新信息矛盾的事实
- 更新 topOfMind 时，整合新关注领域，移除已完成/放弃的
  保持 3-5 个仍活跃且相关的并发关注主题
- 历史分区按时间顺序将新信息整合到对应时段
- 保持技术准确性——保留技术、公司、项目的准确名称
- 聚焦对未来交互和个性化有用的信息
- 重要：不要在记忆中记录文件上传事件。上传的文件是会话特定的、临时的——在后续会话中不可访问。
  记录上传事件会在后续对话中造成困惑。

只返回合法 JSON，不要解释或 markdown。

**极其重要：所有输出内容必须使用中文，包括 summary、content、category 等所有字段的值，一律使用简体中文！**"""


# Prompt template for extracting facts from a single message
FACT_EXTRACTION_PROMPT = """从此消息中提取关于用户的事实信息。

消息：
{message}

按以下 JSON 格式提取事实：
{{
  "facts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0 }}
  ]
}}

类别：
- preference：用户偏好（喜欢/不喜欢、风格、工具）
- knowledge：用户的专长或知识领域
- context：背景上下文（地点、工作、项目）
- behavior：行为模式
- goal：用户的目标或意图
- correction：明确的纠正或应避免重复的错误

规则：
- 仅提取清晰、具体的事实
- 置信度反映确定程度（明确陈述 = 0.9+，推断 = 0.6-0.8）
- 跳过模糊或临时信息

只返回合法 JSON。

**极其重要：所有输出内容必须使用中文，包括 fact 的 content、category 等所有字段的值，一律使用简体中文！**"""


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken.

    Args:
        text: The text to count tokens for.
        encoding_name: The encoding to use (default: cl100k_base for GPT-4/3.5).

    Returns:
        The number of tokens in the text.
    """
    if not TIKTOKEN_AVAILABLE:
        # Fallback to character-based estimation if tiktoken is not available
        return len(text) // 4

    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        # Fallback to character-based estimation on error
        return len(text) // 4


def _coerce_confidence(value: Any, default: float = 0.0) -> float:
    """Coerce a confidence-like value to a bounded float in [0, 1].

    Non-finite values (NaN, inf, -inf) are treated as invalid and fall back
    to the default before clamping, preventing them from dominating ranking.
    The ``default`` parameter is assumed to be a finite value.
    """
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))
    if not math.isfinite(confidence):
        return max(0.0, min(1.0, default))
    return max(0.0, min(1.0, confidence))


def format_memory_for_injection(memory_data: dict[str, Any], max_tokens: int = 2000) -> str:
    """Format memory data for injection into system prompt.

    Args:
        memory_data: The memory data dictionary.
        max_tokens: Maximum tokens to use (counted via tiktoken for accuracy).

    Returns:
        Formatted memory string for system prompt injection.
    """
    if not memory_data:
        return ""

    sections = []

    # Format user context
    user_data = memory_data.get("user", {})
    if user_data:
        user_sections = []

        work_ctx = user_data.get("workContext", {})
        if work_ctx.get("summary"):
            user_sections.append(f"工作: {work_ctx['summary']}")

        personal_ctx = user_data.get("personalContext", {})
        if personal_ctx.get("summary"):
            user_sections.append(f"个人: {personal_ctx['summary']}")

        top_of_mind = user_data.get("topOfMind", {})
        if top_of_mind.get("summary"):
            user_sections.append(f"当前关注: {top_of_mind['summary']}")

        if user_sections:
            sections.append("用户上下文:\n" + "\n".join(f"- {s}" for s in user_sections))

    # Format history
    history_data = memory_data.get("history", {})
    if history_data:
        history_sections = []

        recent = history_data.get("recentMonths", {})
        if recent.get("summary"):
            history_sections.append(f"近期: {recent['summary']}")

        earlier = history_data.get("earlierContext", {})
        if earlier.get("summary"):
            history_sections.append(f"更早: {earlier['summary']}")

        background = history_data.get("longTermBackground", {})
        if background.get("summary"):
            history_sections.append(f"背景: {background['summary']}")

        if history_sections:
            sections.append("历史:\n" + "\n".join(f"- {s}" for s in history_sections))

    # Format facts (sorted by confidence; include as many as token budget allows)
    facts_data = memory_data.get("facts", [])
    if isinstance(facts_data, list) and facts_data:
        ranked_facts = sorted(
            (f for f in facts_data if isinstance(f, dict) and isinstance(f.get("content"), str) and f.get("content").strip()),
            key=lambda fact: _coerce_confidence(fact.get("confidence"), default=0.0),
            reverse=True,
        )

        # Compute token count for existing sections once, then account
        # incrementally for each fact line to avoid full-string re-tokenization.
        base_text = "\n\n".join(sections)
        base_tokens = _count_tokens(base_text) if base_text else 0
        # Account for the separator between existing sections and the facts section.
        facts_header = "事实:\n"
        separator_tokens = _count_tokens("\n\n" + facts_header) if base_text else _count_tokens(facts_header)
        running_tokens = base_tokens + separator_tokens

        fact_lines: list[str] = []
        for fact in ranked_facts:
            content_value = fact.get("content")
            if not isinstance(content_value, str):
                continue
            content = content_value.strip()
            if not content:
                continue
            category = str(fact.get("category", "context")).strip() or "context"
            confidence = _coerce_confidence(fact.get("confidence"), default=0.0)
            source_error = fact.get("sourceError")
            if category == "correction" and isinstance(source_error, str) and source_error.strip():
                line = f"- [{category} | {confidence:.2f}] {content} (避免: {source_error.strip()})"
            else:
                line = f"- [{category} | {confidence:.2f}] {content}"

            # Each additional line is preceded by a newline (except the first).
            line_text = ("\n" + line) if fact_lines else line
            line_tokens = _count_tokens(line_text)

            if running_tokens + line_tokens <= max_tokens:
                fact_lines.append(line)
                running_tokens += line_tokens
            else:
                break

        if fact_lines:
            sections.append("事实:\n" + "\n".join(fact_lines))

    if not sections:
        return ""

    result = "\n\n".join(sections)

    # Use accurate token counting with tiktoken
    token_count = _count_tokens(result)
    if token_count > max_tokens:
        # Truncate to fit within token limit
        # Estimate characters to remove based on token ratio
        char_per_token = len(result) / token_count
        target_chars = int(max_tokens * char_per_token * 0.95)  # 95% to leave margin
        result = result[:target_chars] + "\n..."

    return result


def format_conversation_for_update(messages: list[Any]) -> str:
    """Format conversation messages for memory update prompt.

    Args:
        messages: List of conversation messages.

    Returns:
        Formatted conversation string.
    """
    lines = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))

        # Handle content that might be a list (multimodal)
        if isinstance(content, list):
            text_parts = []
            for p in content:
                if isinstance(p, str):
                    text_parts.append(p)
                elif isinstance(p, dict):
                    text_val = p.get("text")
                    if isinstance(text_val, str):
                        text_parts.append(text_val)
            content = " ".join(text_parts) if text_parts else str(content)

        # Strip uploaded_files tags from human messages to avoid persisting
        # ephemeral file path info into long-term memory.  Skip the turn entirely
        # when nothing remains after stripping (upload-only message).
        if role == "human":
            content = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", "", str(content)).strip()
            if not content:
                continue

        # Truncate very long messages
        if len(str(content)) > 1000:
            content = str(content)[:1000] + "..."

        if role == "human":
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
