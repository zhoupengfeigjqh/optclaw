import os
import time
from typing import Optional
from langchain.tools import tool
from .utiles import resolve_virtual_path
from optclaw.log import setup_logging

logger = setup_logging(__name__)

_DEFAULT_MAX_FILES = 50
_MAX_ALLOWED_FILES = 100


@tool("list_directory", parse_docstring=True)
def list_directory_tool(path: str, max_items: int = _DEFAULT_MAX_FILES) -> str:
    """List the contents of a specific directory (like Linux ls).
    Use this to view files and subdirectories within a given path.

    When to use the list_directory tool:
    - Use this when you need to explore the structure of a directory.
    - Use this to locate files before reading or processing them.

    Args:
        path: The absolute path of the directory to list.
        max_items: The maximum number of items to return. Defaults to 50.
    """
    # 1. 解析虚拟路径（保持安全逻辑一致）
    actual_path = resolve_virtual_path(path)

    if not actual_path:
        raise ValueError(f"Path: {path} resolve to None, access denied for security reasons! Please use absolute path.") from None

    actual_path = str(actual_path)

    # 2. 参数校验与限制
    if max_items <= 0:
        return "Error: The max_items must be greater than 0."
    
    if max_items > _MAX_ALLOWED_FILES:
        max_items = _MAX_ALLOWED_FILES
        logger.warning(f"Requested items exceeded maximum allowed. Capped to {_MAX_ALLOWED_FILES}.")

    try:
        # 3. 检查目录是否存在且确实是目录
        if not os.path.exists(actual_path):
            return f"Error: Directory not found: {path}"
        if not os.path.isdir(actual_path):
            return f"Error: Path is a file, cannot list as directory: {path}"

        # 提取最后一层目录名展示，隐藏真实路径
        display_name = os.path.basename(actual_path.rstrip(os.sep)) or path
        
        # 4. 读取目录内容
        try:
            entries = os.listdir(actual_path)
        except PermissionError:
            return f"Error: Permission denied to access directory: {path}"

        if not entries:
            return f"Directory '{display_name}' is empty."

        # 排序：让输出结果更可预测（文件夹在前，文件在后，按字母排序）
        entries.sort(key=lambda x: (not os.path.isdir(os.path.join(actual_path, x)), x.lower()))

        # 5. 截取最大返回数量
        total_count = len(entries)
        truncated_entries = entries[:max_items]

        # 6. 格式化输出文件信息
        lines = []
        for entry in truncated_entries:
            full_entry_path = os.path.join(actual_path, entry)
            try:
                stat = os.stat(full_entry_path)
                # 转换为可读的修改时间
                mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
                
                if os.path.isdir(full_entry_path):
                    lines.append(f"[DIR]  {entry}/  (Modified: {mtime})")
                else:
                    # 文件大小转换为可读格式 (KB/MB)
                    size = stat.st_size
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024 * 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = f"{size / (1024 * 1024):.1f} MB"
                    
                    lines.append(f"[FILE] {entry}  ({size_str}, Modified: {mtime})")
            except OSError:
                # 针对损坏的软链接或无权限读取状态的文件
                lines.append(f"[UNKNOWN] {entry} (Error retrieving metadata)")

        # 7. 拼接返回信息
        result_header = f"Showing {len(truncated_entries)} of {total_count} items in '{display_name}':\n"
        result_body = "\n".join(lines)
        
        if total_count > max_items:
            result_body += f"\n... and {total_count - max_items} more items (omitted due to limit)."

        return result_header + result_body

    except OSError as e:
        raise type(e)(e.errno, e.strerror, path) from None