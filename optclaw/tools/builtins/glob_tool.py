from langchain.tools import tool
from .utiles import resolve_virtual_path
import glob
import os
from optclaw.log import setup_logging

logger = setup_logging(__name__)

_DEFAULT_GLOB_MAX_RESULTS = 100


@tool("glob_file", parse_docstring=True)
def glob_file_tool(path_pattern: str) -> str:
    """Find files and directories using a path pattern with wildcards (like Linux glob).
    Use this to list files matching a pattern, e.g., *.log, /data/*.txt, /config/*-prod.yml.

    When to use the glob_file tool:
    - Use this when you need to find or list files matching a naming pattern.
    - Use this to check what files exist in a directory.

    Args:
        path_pattern: The absolute path pattern with wildcards (*, ?, []) to match files.
    """
    # 解析虚拟路径（保持和你原有工具一致的安全逻辑）
    actual_pattern = str(resolve_virtual_path(path_pattern))

    if not actual_pattern:
        raise ValueError(f"Path pattern:{path_pattern} resolve to None, access denied for security reasons! Please use absolute path pattern.") from None

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
        raise type(e)(e.errno, e.strerror, path_pattern) from None