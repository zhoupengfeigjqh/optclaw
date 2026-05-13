import os
import errno
from langchain.tools import tool

from .utiles import resolve_virtual_path

from optclaw.log import setup_logging
logger = setup_logging(__name__)


@tool("write_file", parse_docstring=True)
def write_file_tool(path: str, content: str, append: bool = False) -> str:
    """Write content to a text file. Use this to modify configuration files, logs, skills or any text-based file.

    When to use the write_file tool:
    - This tool is intended for use when the agent needs to write file contents.

    Args:
        path: The ***absolute*** path to the file to write.
        content: The content to write to the file.
        append: Whether to append to the file instead of overwriting it.
    """
    actual_path = resolve_virtual_path(path)
    if not actual_path:
        raise ValueError(f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path.") from None
    if os.path.exists(actual_path) and not os.access(actual_path, os.W_OK):
        raise OSError(errno.EROFS, "Read-only file system", path) from None
    try:
        dir_path = os.path.dirname(actual_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        mode = "a" if append else "w"
        with open(actual_path, mode, encoding="utf-8") as f:
            f.write(content)
        return content
    except OSError as e:
        # Re-raise with the original path for clearer error messages, hiding internal resolved paths
        raise type(e)(e.errno, e.strerror, path) from None