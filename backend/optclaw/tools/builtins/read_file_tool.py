# from langchain.tools import tool
# from .utiles import resolve_virtual_path
# from optclaw.log import setup_logging

# logger = setup_logging(__name__)

# # 定义一个安全的默认最大 Token 限制（折算为字符数）
# _DEFAULT_MAX_CHARS = 60000


# @tool("read_file", parse_docstring=True)
# def read_file_tool(path: str) -> str:
#     """Read the contents of a text file. Use this to examine configuration files, logs, skills or any text-based file.

#     When to use the read_file tool:
#     - This tool is intended for use when the agent needs to read file contents.
#     - It has an safety guard to prevent context explosion on large files.

#     Args:
#         path: The ***absolute*** path to the file to read.
#     """
#     actual_path = resolve_virtual_path(path)

#     if not actual_path:
#         # raise ValueError(f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path.") from None
#         return f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path."
    
#     try:
#         # # 根据传入的 max_tokens 计算允许读取的最大字符数
#         # # 如果未传入，则使用系统默认的安全限制
#         # if max_tokens is not None and max_tokens > 0:
#         #     # 严格估算：1 Token 最多约占 4 个字符（针对英文/代码），乘以 4 转换为字符数
#         #     max_chars_to_read = max_tokens * 4
#         # else:
#         max_chars_to_read = _DEFAULT_MAX_CHARS

#         with open(actual_path, encoding="utf-8", errors="replace") as f:
#             # 核心防御：只读取指定长度加 1 的字符，用来判断是否超限，避免一次性读入几百MB的巨大文件
#             content = f.read(max_chars_to_read + 1)
        
#         # 判断是否被截断
#         if len(content) > max_chars_to_read:
#             logger.warning(f"File '{path}' is too large (size:{len(content)}). Content truncated to prevent context explosion.")
#             # 截断到准确的字符限制数，并附带优雅的提示尾缀
#             # content = content[:max_chars_to_read] + "\n\n[... Remaining content truncated by read_file_tool to prevent context explosion ...]"
#             content = content[:max_chars_to_read]

#         return content

#     except OSError as e:
#         # Re-raise with the original path for clearer error messages, hiding internal resolved paths
#         # raise type(e)(e.errno, e.strerror, path) from None
#         logger.error(f"Error: {str(e)}")
#         return f"Error: {str(e)}, read file failed!"

from langchain.tools import tool
from .utiles import resolve_virtual_path
from optclaw.log import setup_logging

logger = setup_logging(__name__)

# 全局安全行数上限，所有读取场景最多返回1000行内容
_DEFAULT_MAX_LINES = 1000


@tool("read_file", parse_docstring=True)
def read_file_tool(
    path: str,
    max_lines: int = _DEFAULT_MAX_LINES,
    start_line: int | None = None,
    end_line: int | None = None
) -> str:
    """读取文本文件内容，用于检查配置文件、日志、Skill 或任何文本文件。

    使用模式：
    1. 仅提供 path：读取文件前 1000 行
    2. 提供 start_line：从 start_line 读到文件末尾，受 max_lines 上限约束
    3. 同时提供 start_line 和 end_line：读取指定行范围 [start_line, end_line]

    Args:
        path: 文件的绝对路径。
        max_lines: 单次读取全局最大行数，默认 1000，防止上下文溢出。
        start_line: 起始行号（从 1 开始），为 None 则从第 1 行开始。
        end_line: 结束行号（从 1 开始），为 None 则读到文件末尾。
    """
    actual_path = resolve_virtual_path(path)

    # 虚拟路径解析失败，安全拦截
    if not actual_path:
        return (
            f"Path:{path} resolve to None, access denied for security reasons! "
            "If it is relative path, please use absolute path."
        )

    # 参数合法性校验
    if max_lines <= 0:
        return f"Invalid max_lines value {max_lines}, must be positive integer."
    if start_line is not None and start_line < 1:
        return f"Invalid start_line {start_line}, line number starts at 1."
    if end_line is not None and end_line < 1:
        return f"Invalid end_line {end_line}, line number starts at 1."
    if start_line is not None and end_line is not None and end_line < start_line:
        return f"Line range error: end_line({end_line}) < start_line({start_line})"

    try:
        matched_lines = []

        with open(actual_path, encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f, start=1):
                # 小于起始行，跳过
                if start_line is not None and line_num < start_line:
                    continue
                # 超过结束行，停止读取
                if end_line is not None and line_num > end_line:
                    break
                # 达到全局最大行数上限，强制截断
                if len(matched_lines) >= max_lines:
                    break
                matched_lines.append((line_num, line))

        # 拼接带行号的文本
        content = ""
        for ln, text in matched_lines:
            content += f"{ln:6d} | {text}"

        # 生成截断提示
        tips = []
        # 触达全局行数上限
        if len(matched_lines) >= max_lines:
            tips.append(f"Content truncated: reached global max line limit {max_lines}")
        # 指定结束行超出文件总行数
        if end_line is not None and matched_lines and matched_lines[-1][0] < end_line:
            tips.append(f"End line {end_line} exceeds total lines of file")

        if tips:
            content += "\n\n[... Truncation hints: " + "; ".join(tips) + " ...]"

        # 无匹配内容提示
        if not matched_lines:
            content += "\n[No content matched your line range or file is empty]"

        return content

    except OSError as e:
        err_msg = f"Failed to read file [{path}]: {str(e)}"
        logger.error(err_msg)
        return f"OS Error: {err_msg}"
    except Exception as e:
        err_msg = f"Unexpected error when reading file [{path}]: {str(e)}"
        logger.exception(err_msg)
        return f"Unexpected Error: {err_msg}"