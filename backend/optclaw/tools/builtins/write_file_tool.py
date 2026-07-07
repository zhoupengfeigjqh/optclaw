import os
import errno
from langchain.tools import tool

from .utiles import resolve_virtual_path

from optclaw.log import setup_logging
logger = setup_logging(__name__)


@tool("write_file", parse_docstring=True)
def write_file_tool(path: str, content: str, append: bool = False) -> str:
    """将内容写入文本文件，用于创建/修改配置文件、日志、Skill 或任何文本文件。

    Args:
        path: 要写入的文件的绝对路径。
        content: 要写入的内容。
        append: 是否追加到文件末尾，默认 False（覆盖）。
    """
    actual_path = resolve_virtual_path(path)
    if not actual_path:
        # raise ValueError(f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path.") from None
        return f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path."
    
    if os.path.exists(actual_path) and not os.access(actual_path, os.W_OK):
        # raise OSError(errno.EROFS, "Read-only file system", path) from None
        return f"Path:{path} is read-only file!"
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
        # raise type(e)(e.errno, e.strerror, path) from None
        logger.error(f"Error: {str(e)}")
        return f"Error: {str(e)}, write file failed!"