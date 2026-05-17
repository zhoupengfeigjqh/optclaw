from langchain.tools import tool
from .utiles import resolve_virtual_path
import os
import re
from optclaw.log import setup_logging

logger = setup_logging(__name__)


@tool("str_replace", parse_docstring=True)
def str_replace_tool(path: str, old_pattern: str, new_text: str, is_regex: bool = False) -> str:
    """Replace occurrences of a text pattern or regular expression in a specific file.

    When to use the str_replace tool:
    - Use this to update configurations, fix typos, or bulk-replace strings in a file.
    - Use this when you need to modify file content programmatically.

    Args:
        path: The absolute path of the file to modify.
        old_pattern: The text string or regular expression pattern to search for.
        new_text: The replacement text string to insert.
        is_regex: If True, treats old_pattern as a regular expression. Defaults to False.
    """
    # 1. 解析虚拟路径（保持安全逻辑一致）
    actual_path = resolve_virtual_path(path)

    if not actual_path:
        raise ValueError(f"Path: {path} resolve to None, access denied for security reasons! Please use absolute path.") from None
    
    actual_path = str(actual_path)

    # 提取最后一层文件名展示，隐藏真实路径
    display_name = os.path.basename(actual_path)

    try:
        # 2. 检查文件是否存在且是文件
        if not os.path.exists(actual_path):
            return f"Error: File not found: {path}"
        if os.path.isdir(actual_path):
            return f"Error: Path is a directory, cannot replace text: {path}"
        if not os.path.isfile(actual_path):
            return f"Error: Path is not a regular file: {path}"

        # 3. 读取原文件内容
        with open(actual_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        # 4. 执行替换逻辑
        if is_regex:
            try:
                # 编译正则表达式
                compiled_regex = re.compile(old_pattern)
                # 检查是否有匹配项
                if not compiled_regex.search(content):
                    return f"No matches found for regex pattern '{old_pattern}' in file '{display_name}'. No changes made."
                
                # 执行正则替换
                new_content, count = compiled_regex.subn(new_text, content)
            except re.error as e:
                return f"Error: Invalid regular expression '{old_pattern}': {str(e)}"
        else:
            # 普通字符串替换
            if old_pattern not in content:
                return f"No matches found for text '{old_pattern}' in file '{display_name}'. No changes made."
            
            count = content.count(old_pattern)
            new_content = content.replace(old_pattern, new_text)

        # 5. 回写文件
        with open(actual_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        logger.info(f"Successfully replaced {count} occurrence(s) in {display_name}.")
        return f"Success: Replaced {count} occurrence(s) of '{old_pattern}' in file '{display_name}'."

    except OSError as e:
        raise type(e)(e.errno, e.strerror, path) from None