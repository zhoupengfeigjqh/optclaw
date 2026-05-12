import logging

from langchain.tools import BaseTool

from optclaw.config import get_app_config
from optclaw.reflection import resolve_variable
from optclaw.tools.builtins import ask_clarification_tool, present_file_tool, write_file_tool, read_file_tool, glob_file_tool, grep_file_tool, view_image_tool

from optclaw.log import setup_logging
logger = setup_logging(__name__)


BUILTIN_TOOLS = [
    present_file_tool,
    ask_clarification_tool,
    read_file_tool,
    write_file_tool,
    glob_file_tool, 
    grep_file_tool
]


def get_available_tools(
    groups: list[str] | None = None,
    include_mcp: bool = False,
    model_name: str | None = None,
    subagent_enabled: bool = False,
) -> list[BaseTool]:
    """Get all available tools from config.

    Note: MCP tools should be initialized at application startup using
    `initialize_mcp_tools()` from optclaw.mcp module.

    Args:
        groups: Optional list of tool groups to filter by.
        include_mcp: Whether to include tools from MCP servers (default: True).
        model_name: Optional model name to determine if vision tools should be included.
        subagent_enabled: Whether to include subagent tools (task, task_status).

    Returns:
        List of available tools.
    """
    config = get_app_config()
    tool_configs = [tool for tool in config.tools if groups is None or tool.group in groups]
    logger.info(f"Tool configs after group filtering: {[tool.name for tool in tool_configs]}")

    # config tools
    loaded_tools = [resolve_variable(tool.use, BaseTool) for tool in tool_configs]

    # Conditionally add tools based on config
    builtin_tools = BUILTIN_TOOLS.copy()

    # skill_evolution_config = getattr(config, "skill_evolution", None)
    # if getattr(skill_evolution_config, "enabled", False):
    #     from optclaw.tools.skill_manage_tool import skill_manage_tool

    #     builtin_tools.append(skill_manage_tool)

    # If no model_name specified, use the first model (default)
    if model_name is None and config.models:
        model_name = config.models[0].name

    # If model supports vision, add view_image_tool
    model_config = config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        builtin_tools.append(view_image_tool)
        logger.info(f"Including view_image_tool for model '{model_name}' (supports_vision=True)")

    logger.info(f"Total tools loaded: {len(loaded_tools)}, built-in tools: {len(builtin_tools)}")
    return loaded_tools + builtin_tools