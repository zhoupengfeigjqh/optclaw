from langchain.tools import tool
from .utiles import resolve_virtual_path
import glob
import os
from optclaw.log import setup_logging

logger = setup_logging(__name__)

_DEFAULT_GLOB_MAX_RESULTS = 100


@tool("glob_file", parse_docstring=True)
def glob_file_tool(path_pattern: str) -> str:
    """使用路径通配符模式查找文件和目录（类似 Linux glob）。

    适用场景：
    - 按命名模式查找或列出匹配的文件
    - 检查目录下存在哪些文件

    Args:
        path_pattern: 带通配符（*、?、[]）的绝对路径模式。
    """
    # 解析虚拟路径（保持和你原有工具一致的安全逻辑）
    actual_pattern = str(resolve_virtual_path(path_pattern))

    if not actual_pattern:
        # raise ValueError(f"Path pattern:{path_pattern} resolve to None, access denied for security reasons! Please use absolute path pattern.") from None
        return f"Path pattern:{path_pattern} resolve to None, access denied for security reasons! Please use absolute path pattern."
    
    try:
        # 执行 glob 匹配文件
        matched_paths = glob.glob(actual_pattern, recursive=False)
        
        if not matched_paths:
            return f"No files or directories found matching pattern: {path_pattern}"

        # 只保留文件名/相对路径展示，不泄露真实路径
        result_lines = []
        for p in matched_paths:
            # 提取最后一层文件名/目录名展示，更安全干净
            display_name = os.path.basename(p) if os.path.isfile(p) else os.path.basename(p.rstrip("/"))
            result_lines.append(f"- {display_name}")
        
        if len(result_lines) > _DEFAULT_GLOB_MAX_RESULTS:
            result_lines = result_lines[:_DEFAULT_GLOB_MAX_RESULTS] + [f"...and {len(matched_paths) - _DEFAULT_GLOB_MAX_RESULTS} more results truncated."]

        return f"Found {len(result_lines)} items matching pattern '{path_pattern}':\n" + "\n".join(result_lines)

    except OSError as e:
        # raise type(e)(e.errno, e.strerror, path_pattern) from None
        logger.error(f"Error: {str(e)}")
        return f"Error: {str(e)}, glob file failed!"