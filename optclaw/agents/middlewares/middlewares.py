from langchain.agents.middleware import AgentMiddleware

from optclaw.agents.middlewares.clarification_middleware import ClarificationMiddleware
from optclaw.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from optclaw.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from optclaw.agents.middlewares.summarization_middleware import BeforeSummarizationHook, OptClawSummarizationMiddleware
from optclaw.config.summarization_config import get_summarization_config
from optclaw.config.memory_config import get_memory_config
from optclaw.config import get_app_config
from optclaw.models import create_chat_model
from optclaw.agents.memory.summarization_hook import memory_flush_hook


# ---------------------------------------------------------------------------
# TodoMiddleware prompts (minimal SDK version)
# ---------------------------------------------------------------------------

_TODO_SYSTEM_PROMPT = """
<todo_list_system>
You have access to the `write_todos` tool to help you manage and track complex multi-step objectives.

**CRITICAL RULES:**
- Mark todos as completed IMMEDIATELY after finishing each step - do NOT batch completions
- Keep EXACTLY ONE task as `in_progress` at any time (unless tasks can run in parallel)
- Update the todo list in REAL-TIME as you work - this gives users visibility into your progress
- DO NOT use this tool for simple tasks (< 3 steps) - just complete them directly
</todo_list_system>
"""

# _TODO_TOOL_DESCRIPTION = "Use this tool to create and manage a structured task list for complex work sessions.  Only use for complex tasks (3+ steps)."
_TODO_TOOL_DESCRIPTION = """Use this tool only for complex tasks (3+ steps); for simple requests, complete them directly.
When to Use
- Complex multi-step tasks (3+ distinct steps)
- Tasks needing careful planning
- User explicitly requests a todo list
- Multiple tasks to complete
- Plans that may need updates
When NOT to Use
- Straightforward tasks (fewer than 3 steps)
- Trivial tasks with no tracking benefit
- Purely conversational/informational tasks
- Tasks where next steps are clear (just do them)
How to Use
- Mark tasks as in_progress before starting
- Mark tasks as completed immediately after finishing
- Update the list (add/remove/update tasks) as needed
Task States
- pending: Not started
- in_progress: Currently working on (multiple allowed)
- completed: Finished successfully
Key Rules
- Only mark tasks as completed if fully accomplished (no unresolved issues, partial work, or blockers).
- If blocked, keep the task in_progress and add a new task to resolve the blocker.
- Keep tasks specific/actionable; break down complex ones.
- Always have at least one in_progress task (unless all are completed).
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


def build_middlewares(
    model_name: str | None,
    agent_name: str = "default",
    plan_mode: bool = False,
    extra_middleware: list[AgentMiddleware] | None = None,
) -> tuple[list[AgentMiddleware]]:
    """Build an ordered middleware chain + extra tools from *feat*.

    Middleware order matches ``make_lead_agent`` (11 middlewares):

      0-1. ThreadData and Uploads
      2. DanglingToolCallMiddleware (always)
      3. ToolErrorHandlingMiddleware (always)
      4. SummarizationMiddleware (summarization feature)
      5. TodoMiddleware (plan_mode parameter)
      6. TitleMiddleware (auto_title feature)
      7. MemoryMiddleware (memory feature)
      8. ViewImageMiddleware (vision feature)
      9. LoopDetectionMiddleware (always)
      10. ClarificationMiddleware (always last)

    Two-phase ordering:
      1. Built-in chain — fixed sequential append.
      2. Extra middleware — inserted via @Next/@Prev.

    Each feature value is handled as:
      - ``False``: skip
      - ``True``: create the built-in default middleware (not available for
        ``summarization`` and ``guardrail`` — these require a custom instance)
      - ``AgentMiddleware`` instance: use directly (custom replacement)
    """
    chain: list[AgentMiddleware] = []

    # --- [0-1] Sandbox infrastructure ---
    from optclaw.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from optclaw.agents.middlewares.uploads_middleware import UploadsMiddleware
    chain.append(ThreadDataMiddleware(lazy_init=False))
    chain.append(UploadsMiddleware())

    # --- [2] DanglingToolCall (always) ---
    chain.append(DanglingToolCallMiddleware())

    # safe check
    # if feat.guardrail is not False:
    #     if isinstance(feat.guardrail, AgentMiddleware):
    #         chain.append(feat.guardrail)
    #     else:
    #         raise ValueError("guardrail=True requires a custom AgentMiddleware instance (no built-in GuardrailMiddleware yet)")

    # --- [3] ToolErrorHandling (always) ---
    summarization_middleware = _create_summarization_middleware()
    if summarization_middleware is not None:
        chain.append(summarization_middleware)
    else:
        raise ValueError("summarization=True requires a custom AgentMiddleware instance (SummarizationMiddleware needs a model argument)")

    # --- [4] TodoMiddleware (plan_mode) ---
    if plan_mode:
        from optclaw.agents.middlewares.todo_middleware import TodoMiddleware
        chain.append(TodoMiddleware(system_prompt=_TODO_SYSTEM_PROMPT, tool_description=_TODO_TOOL_DESCRIPTION))

    # --- [5] Auto Title ---
    from optclaw.agents.middlewares.title_middleware import TitleMiddleware
    chain.append(TitleMiddleware())

    # --- [6] Memory ---
    from optclaw.agents.middlewares.memory_middleware import MemoryMiddleware
    chain.append(MemoryMiddleware(agent_name=agent_name))

    # --- [7] Vision ---
    from optclaw.agents.middlewares.view_image_middleware import ViewImageMiddleware
    app_config = get_app_config()
    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        chain.append(ViewImageMiddleware())

    # --- [8] LoopDetection (always) ---
    from optclaw.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
    chain.append(LoopDetectionMiddleware())

    # --- [9] Clarification (always last among built-ins) ---
    chain.append(ClarificationMiddleware())

    # --- Insert extra_middleware via @Next/@Prev ---
    # if extra_middleware:
    #     _insert_extra(chain, extra_middleware)
    #     # Invariant: ClarificationMiddleware must always be last.
    #     # @Next(ClarificationMiddleware) could push it off the tail.
    #     clar_idx = next(i for i, m in enumerate(chain) if isinstance(m, ClarificationMiddleware))
    #     if clar_idx != len(chain) - 1:
    #         chain.append(chain.pop(clar_idx))

    return chain