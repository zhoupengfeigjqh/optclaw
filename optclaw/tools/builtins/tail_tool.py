from langchain.tools import tool
from .utiles import resolve_virtual_path
import os
from optclaw.log import setup_logging

logger = setup_logging(__name__)

_DEFAULT_TAIL_MAX_LINES = 20
_MAX_ALLOWED_LINES = 50  # 限制大语言模型单次接收的最大行数，防止 context 撑爆


@tool("tail_file", parse_docstring=True)
def tail_file_tool(path: str, lines: int = _DEFAULT_TAIL_MAX_LINES) -> str:
    """Read the last lines of a specific file (like Linux tail).
    Use this to view recent logs, updates, or the end of a file.

    When to use the tail_file tool:
    - Use this when you need to inspect the latest entries in a log file.
    - Use this to check the output at the end of a file without reading the whole file.

    Args:
        path: The absolute path of the file to read.
        lines: The number of lines to read from the end of the file. Defaults to 100.
    """
    # 1. 解析虚拟路径（保持安全逻辑一致）
    actual_path = resolve_virtual_path(path)

    if not actual_path:
        raise ValueError(f"Path: {path} resolve to None, access denied for security reasons! Please use absolute path.") from None
    
    actual_path = str(actual_path)

    # 2. 参数校验与限制
    if lines <= 0:
        return "Error: The number of lines must be greater than 0."
    
    if lines > _MAX_ALLOWED_LINES:
        lines = _MAX_ALLOWED_LINES
        logger.warning(f"Requested lines exceeded maximum allowed. Capped to {_MAX_ALLOWED_LINES}.")

    try:
        # 3. 检查文件是否存在且是文件
        if not os.path.exists(actual_path):
            return f"Error: File not found: {path}"
        if not os.path.isdir(actual_path) and not os.path.isfile(actual_path):
            return f"Error: Path is not a regular file: {path}"
        if os.path.isdir(actual_path):
            return f"Error: Path is a directory, cannot tail: {path}"

        # 4. 高效读取文件末尾几行（避免一次性将超大文件读入内存）
        # 这里使用标准块读取倒序查找换行符，或者对于中小型文件直接使用后半段切片
        file_size = os.path.getsize(actual_path)
        
        # 提取最后一层文件名展示，隐藏真实路径
        display_name = os.path.basename(actual_path)
        
        # 如果文件为空
        if file_size == 0:
            return f"File '{display_name}' is empty."

        with open(actual_path, 'r', encoding='utf-8', errors='replace') as f:
            # 针对大文件的内存优化方案：如果文件大于 1MB，则使用 seek 移动到尾部读取
            if file_size > 1024 * 1024:
                # 预估 1 行平均 100 字节，多预留 3 倍空间，移动指针
                seek_offset = min(file_size, lines * 100 * 3)
                f.seek(file_size - seek_offset)
                content = f.read()
                lines_list = content.splitlines()
                # 确保首行因为 seek 切割不完整而被抛弃（除非已经到了文件头）
                if len(content) == seek_offset and lines_list:
                    lines_list = lines_list[1:]
            else:
                # 小文件直接读全部
                lines_list = f.read().splitlines()

        # 截取最后 N 行
        tail_lines = lines_list[-lines:]
        actual_read_count = len(tail_lines)

        if actual_read_count == 0:
            return f"File '{display_name}' has no readable lines."

        return f"Showing last {actual_read_count} lines of '{display_name}':\n" + "\n".join(tail_lines)

    except OSError as e:
        raise type(e)(e.errno, e.strerror, path) from None