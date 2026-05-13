from langchain.tools import tool

from .utiles import resolve_virtual_path

from optclaw.log import setup_logging
logger = setup_logging(__name__)


@tool("read_file", parse_docstring=True)
def read_file_tool(path: str) -> str:
    """Read the contents of a text file. Use this to examine configuration files, logs, skills or any text-based file.

    When to use the read_file tool:
    - This tool is intended for use when the agent needs to read file contents.

    Args:
        path: The ***absolute*** path to the file to read.
    """
    actual_path = resolve_virtual_path(path)

    if not actual_path:
        raise ValueError(f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path.") from None

    try:
        with open(actual_path, encoding="utf-8") as f:
            content = f.read()
        # content = self._reverse_resolve_paths_in_output(content)
        # 将输出中包含的真实路径替换为容器路径，以避免泄露内部实现细节，同时保持输出的一致性和可理解性
        return content
    except OSError as e:
        # Re-raise with the original path for clearer error messages, hiding internal resolved paths
        raise type(e)(e.errno, e.strerror, path) from None