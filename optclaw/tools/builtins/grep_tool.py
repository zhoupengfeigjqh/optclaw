from langchain.tools import tool
from .utiles import resolve_virtual_path
from optclaw.log import setup_logging

logger = setup_logging(__name__)


_DEFAULT_GREP_MAX_RESULTS = 500

@tool("grep_file", parse_docstring=True)
def grep_file_tool(path: str, pattern: str) -> str:
    """Search for a keyword/pattern in a text file and return matching lines with line numbers (like Linux grep).
    
    When to use the grep_file tool:
    - Use this when you need to quickly find specific content (errors, keywords, configurations) in a file.
    - Do NOT use this to read the entire file; use read_file instead.

    Args:
        path: The ***absolute*** path to the file to search.
        pattern: The keyword or text pattern to search for (case-sensitive).
    """
    actual_path = resolve_virtual_path(path)

    if not actual_path:
        raise ValueError(f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path.") from None

    try:
        matches = []
        with open(actual_path, encoding="utf-8") as f:
            # 逐行读取 + 匹配 + 记录行号
            for line_num, line in enumerate(f, start=1):
                if pattern in line:
                    matches.append(f"Line {line_num}: {line.strip()}")

        if not matches:
            return f"No matches found for pattern '{pattern}' in {path}"
        
        if len(matches) > _DEFAULT_GREP_MAX_RESULTS:
            matches = matches[:_DEFAULT_GREP_MAX_RESULTS] + [f"...and {len(matches) - _DEFAULT_GREP_MAX_RESULTS} more results truncated."]

        # 返回格式化结果
        return f"Found {len(matches)} matches for '{pattern}' in {path}:\n" + "\n".join(matches)

    except OSError as e:
        raise type(e)(e.errno, e.strerror, path) from None