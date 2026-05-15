# from langchain.tools import tool

# from .utiles import resolve_virtual_path

# from optclaw.log import setup_logging
# logger = setup_logging(__name__)


# @tool("read_file", parse_docstring=True)
# def read_file_tool(path: str) -> str:
#     """Read the contents of a text file. Use this to examine configuration files, logs, skills or any text-based file.

#     When to use the read_file tool:
#     - This tool is intended for use when the agent needs to read file contents.

#     Args:
#         path: The ***absolute*** path to the file to read.
#     """
#     actual_path = resolve_virtual_path(path)

#     if not actual_path:
#         raise ValueError(f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path.") from None

#     try:
#         with open(actual_path, encoding="utf-8") as f:
#             content = f.read()
#         # content = self._reverse_resolve_paths_in_output(content)
#         return content
#     except OSError as e:
#         # Re-raise with the original path for clearer error messages, hiding internal resolved paths
#         raise type(e)(e.errno, e.strerror, path) from None

from langchain.tools import tool
from .utiles import resolve_virtual_path
from optclaw.log import setup_logging

logger = setup_logging(__name__)

# 定义一个安全的默认最大 Token 限制（折算为字符数）
_DEFAULT_MAX_CHARS = 25000


@tool("read_file", parse_docstring=True)
def read_file_tool(path: str, max_tokens: int = None) -> str:
    """Read the contents of a text file. Use this to examine configuration files, logs, skills or any text-based file.

    When to use the read_file tool:
    - This tool is intended for use when the agent needs to read file contents.
    - It has an safety guard to prevent context explosion on large files.

    Args:
        path: The ***absolute*** path to the file to read.
        max_tokens: Optional. The maximum estimated tokens to read to prevent context overflow.
    """
    actual_path = resolve_virtual_path(path)

    if not actual_path:
        raise ValueError(f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path.") from None

    try:
        # 根据传入的 max_tokens 计算允许读取的最大字符数
        # 如果未传入，则使用系统默认的安全限制
        if max_tokens is not None and max_tokens > 0:
            # 严格估算：1 Token 最多约占 4 个字符（针对英文/代码），乘以 4 转换为字符数
            max_chars_to_read = max_tokens * 4
        else:
            max_chars_to_read = _DEFAULT_MAX_CHARS

        with open(actual_path, encoding="utf-8", errors="replace") as f:
            # 核心防御：只读取指定长度加 1 的字符，用来判断是否超限，避免一次性读入几百MB的巨大文件
            content = f.read(max_chars_to_read + 1)
        
        # 判断是否被截断
        if len(content) > max_chars_to_read:
            logger.warning(f"File '{path}' is too large. Content truncated to prevent context explosion.")
            # 截断到准确的字符限制数，并附带优雅的提示尾缀
            content = content[:max_chars_to_read] + "\n\n[... Remaining content truncated by read_file_tool to prevent context explosion ...]"

        return content

    except OSError as e:
        # Re-raise with the original path for clearer error messages, hiding internal resolved paths
        raise type(e)(e.errno, e.strerror, path) from None