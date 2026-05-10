from langgraph.config import get_config
from langchain.tools import tool

from optclaw.config.paths import get_paths, VIRTUAL_PATH_PREFIX
from optclaw.config import get_app_config

from optclaw.log import setup_logging
logger = setup_logging(__name__)


@tool("read_file", parse_docstring=True)
def read_file_tool(path: str) -> str:
    """Read the contents of a text file. Use this to examine configuration files, logs, skills or any text-based file.

    When to use the read_file tool:
    - This tool is intended for use when the agent needs to read file contents.

    Args:
        path: The **absolute** path to the file to read.
    """

    # 只有两种结构的路径被允许访问，且必须在这两种结构的路径下访问，其他路径一律拒绝访问以保证安全
    container_skill_path = get_app_config().skills.container_path
    if path.startswith(VIRTUAL_PATH_PREFIX):
        config_data = get_config()
        thread_id = config_data.get("configurable", {}).get("thread_id")
        if not thread_id:
            raise ValueError(f"No thread_id in context! Cannot resolve virtual paths ({path}) without thread context.") from None
        actual_path = get_paths().resolve_virtual_path(thread_id, path)
    elif path.startswith(container_skill_path):
        actual_path = get_app_config().skills.get_skills_path() / path[len(container_skill_path):].lstrip("/")
    else:
        raise ValueError(f"Path:{path} is not started with {VIRTUAL_PATH_PREFIX} or {container_skill_path}, access denied for security reasons.") from None

    try:
        with open(actual_path, encoding="utf-8") as f:
            content = f.read()
        # content = self._reverse_resolve_paths_in_output(content)
        # 将输出中包含的真实路径替换为容器路径，以避免泄露内部实现细节，同时保持输出的一致性和可理解性
        return content
    except OSError as e:
        # Re-raise with the original path for clearer error messages, hiding internal resolved paths
        raise type(e)(e.errno, e.strerror, path) from None