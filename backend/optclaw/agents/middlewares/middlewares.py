from langchain.agents.middleware import AgentMiddleware
from langchain_core.runnables import RunnableConfig

from optclaw.agents.middlewares.clarification_middleware import ClarificationMiddleware
from optclaw.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from optclaw.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from optclaw.agents.middlewares.summarization_middleware import BeforeSummarizationHook, OptClawSummarizationMiddleware
from optclaw.config.summarization_config import get_summarization_config
from optclaw.config.memory_config import get_memory_config
from optclaw.config import get_app_config
from optclaw.models import create_chat_model
from optclaw.agents.memory.summarization_hook import memory_flush_hook

from optclaw.log import setup_logging
logger = setup_logging(__name__)


# ---------------------------------------------------------------------------
# TodoMiddleware prompts (minimal SDK version)
# ---------------------------------------------------------------------------

_TODO_SYSTEM_PROMPT = """
<todo_list_system>
你可以使用 `write_todos` 工具管理和追踪复杂的多步骤任务。

**关键规则：**
- 每完成一步立即标记为 completed，不要批量完成
- 同一时间只有一项为 in_progress（可并行的任务除外）
- 实时更新 todo 列表，让用户看到进度
- 简单任务（< 3 步）不要用此工具，直接完成
</todo_list_system>
"""

# _TODO_TOOL_DESCRIPTION = "Use this tool to create and manage a structured task list for complex work sessions.  Only use for complex tasks (3+ steps)."
_TODO_TOOL_DESCRIPTION = """仅用于复杂任务（3+ 步），简单请求直接完成。
适用场景
- 复杂多步骤任务（3+ 个独立步骤）
- 需要仔细规划的任务
- 用户明确要求 todo 列表
- 有多个任务需完成
- 计划可能需要更新
不适用场景
- 简单任务（少于 3 步）
- 无追踪价值的琐碎任务
- 纯对话/信息类任务
- 后续步骤清晰的任务（直接做即可）
使用方式
- 开始前标记为 in_progress
- 完成后立即标记为 completed
- 按需更新列表（增/删/改）
任务状态
- pending：未开始
- in_progress：进行中（允许多个）
- completed：已成功完成
关键规则
- 只有完全达成才能标记 completed（无遗留问题、无部分完成、无阻塞）。
- 如遇阻塞，保持任务 in_progress 并新增一个任务来解决阻塞。
- 任务应明确可执行；复杂任务需拆分。
- 至少保持一个 in_progress 任务（除非全部完成）。
"""


def _create_summarization_middleware() -> OptClawSummarizationMiddleware | None:
    """Create and configure the summarization middleware from config."""
    config = get_summarization_config()

    if not config.enabled:
        return None

    # Prepare trigger parameter
    trigger = None
    if config.trigger is not None:
        if isinstance(config.trigger, list):
            trigger = [t.to_tuple() for t in config.trigger]
        else:
            trigger = config.trigger.to_tuple()

    # Prepare keep parameter
    keep = config.keep.to_tuple()

    # Prepare model parameter
    if config.model_name:
        model = create_chat_model(name=config.model_name, thinking_enabled=False)
    else:
        # Use a lightweight model for summarization to save costs
        # Falls back to default model if not explicitly specified
        model = create_chat_model(thinking_enabled=False)

    # Prepare kwargs
    kwargs = {
        "model": model,
        "trigger": trigger,
        "keep": keep,
    }

    if config.trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = config.trim_tokens_to_summarize

    if config.summary_prompt is not None:
        kwargs["summary_prompt"] = config.summary_prompt

    hooks: list[BeforeSummarizationHook] = []
    if get_memory_config().enabled:
        hooks.append(memory_flush_hook)

    return OptClawSummarizationMiddleware(**kwargs, before_summarization=hooks)


def build_leadagent_middlewares(
    config: RunnableConfig,
    model_name: str | None,
    agent_name: str = "default",
    plan_mode: bool = False
) -> tuple[list[AgentMiddleware]]:
    """Build an ordered middleware chain.

    Middleware order matches ``leadagent`` (13 middlewares):

      0-1. ThreadData and Uploads (always)
      2. DanglingToolCallMiddleware (always)
      3-4. LLMErrorHandlingMiddleware and ToolErrorHandlingMiddleware (always)
      5. SummarizationMiddleware (always)
      6. TodoMiddleware (plan_mode parameter)
      7. TitleMiddleware (always)
      8. MemoryMiddleware (always)
      9. ViewImageMiddleware (supports_vision parameter)
      10. SubagentLimitMiddleware (subagent_enabled parameter)
      11. LoopDetectionMiddleware (always)
      12. ClarificationMiddleware (always last)
    """
    middlewares: list[AgentMiddleware] = []

    # --- [0-1] infrastructure ---
    from optclaw.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from optclaw.agents.middlewares.uploads_middleware import UploadsMiddleware
    middlewares.append(ThreadDataMiddleware(lazy_init=False))
    middlewares.append(UploadsMiddleware())

    # --- [2] DanglingToolCall (always) ---
    middlewares.append(DanglingToolCallMiddleware())

    # --- [3-4] LLMErrorHandling (always) ---
    from optclaw.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    middlewares.append(LLMErrorHandlingMiddleware())
    middlewares.append(ToolErrorHandlingMiddleware())

    # --- [5] ToolErrorHandling (always) ---
    summarization_middleware = _create_summarization_middleware()
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)
        logger.info(f"create summarization_middleware, agent: {agent_name}")
    else:
        raise ValueError("summarization=True requires a custom AgentMiddleware instance (SummarizationMiddleware needs a model argument)")

    # --- [6] TodoMiddleware (plan_mode) ---  ontology can be applied here
    if plan_mode:
        from optclaw.agents.middlewares.todo_middleware import TodoMiddleware
        middlewares.append(TodoMiddleware(system_prompt=_TODO_SYSTEM_PROMPT, tool_description=_TODO_TOOL_DESCRIPTION))
        logger.info(f"create todo_middleware, agent: {agent_name}")

    # --- [7] Auto Title ---
    from optclaw.agents.middlewares.title_middleware import TitleMiddleware
    middlewares.append(TitleMiddleware())

    # --- [8] Memory ---
    from optclaw.agents.middlewares.memory_middleware import MemoryMiddleware
    middlewares.append(MemoryMiddleware(agent_name=agent_name))
    # logger.info(f"create memory middleware, agent: {agent_name}")

    # --- [9] Vision ---
    app_config = get_app_config()
    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        from optclaw.agents.middlewares.view_image_middleware import ViewImageMiddleware
        middlewares.append(ViewImageMiddleware())

    # --- [10] subagent limit ---
    # Add SubagentLimitMiddleware to truncate excess parallel task calls
    subagent_enabled = config.get("configurable", {}).get("subagent_enabled", False)
    if subagent_enabled:
        from optclaw.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
        max_concurrent_subagents = config.get("configurable", {}).get("max_concurrent_subagents", 3)
        middlewares.append(SubagentLimitMiddleware(max_concurrent=max_concurrent_subagents))
        logger.info(f"create subagent_limit_middleware, agent: {agent_name}")

    # --- [11] LoopDetection (always) ---
    from optclaw.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
    middlewares.append(LoopDetectionMiddleware())

    # --- [12] Clarification (always last among built-ins) ---
    middlewares.append(ClarificationMiddleware())

    # --- Insert extra_middleware via @Next/@Prev ---
    # if extra_middleware:
    #     _insert_extra(middlewares, extra_middleware)
    #     # Invariant: ClarificationMiddleware must always be last.
    #     # @Next(ClarificationMiddleware) could push it off the tail.
    #     clar_idx = next(i for i, m in enumerate(middlewares) if isinstance(m, ClarificationMiddleware))
    #     if clar_idx != len(middlewares) - 1:
    #         middlewares.append(middlewares.pop(clar_idx))

    return middlewares


def build_subagent_middlewares() -> tuple[list[AgentMiddleware]]:
    """Build an ordered middleware chain.

    Middleware order matches ``subagent`` (3 middlewares):

      0. ThreadData (always)
      1. LLMErrorHandlingMiddleware (always) 
      2. ToolErrorHandlingMiddleware (always)

    """
    middlewares: list[AgentMiddleware] = [] 

    from optclaw.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    middlewares.append(ThreadDataMiddleware(lazy_init=False))

    from optclaw.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    middlewares.append(LLMErrorHandlingMiddleware())
    middlewares.append(ToolErrorHandlingMiddleware())

    return middlewares