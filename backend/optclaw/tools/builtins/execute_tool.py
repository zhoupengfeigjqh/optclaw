import os
import re
import subprocess
import sys
import tempfile
from langchain.tools import tool
from .utiles import resolve_virtual_path
from optclaw.log import setup_logging

logger = setup_logging(__name__)

_DEFAULT_TIMEOUT = 300
_MAX_OUTPUT_BYTES = 100 * 1024

_FORBIDDEN_COMMANDS = [
    (r'\b(pip|pip3)\s+install', 'pip install'),
    (r'\b(npm|yarn|pnpm)\s+(install|add|i)', 'npm/yarn/pnpm install'),
    (r'\bapt(-get)?\s+install', 'apt install'),
    (r'\bbrew\s+install', 'brew install'),
    (r'\btouch\s+', 'touch'),
    (r'\brm\s+(-rf?|--)', 'rm'),
    (r'\bmv\s+', 'mv'),
    (r'\bcp\s+(-r)?', 'cp'),
    (r'\b(chmod|chown)\s+', 'chmod/chown'),
    (r'\bdd\s+if=', 'dd'),
    (r'\bmkfs\.', 'mkfs'),
    (r'\bshutdown\b', 'shutdown'),
    (r'\breboot\b', 'reboot'),
]

_IMPORT_OS_RE = r'(?:^\s*import\s+os\b|^\s*from\s+os\s+import\s+)'
_CHDIR_LINE = "os.chdir(os.path.dirname(__file__))"

_ALLOWED_PREFIXES = (
    "/mnt/user-data/workspace",
    "/mnt/user-data/uploads",
    "/mnt/user-data/outputs",
)


def _check_forbidden_commands(content: str) -> str | None:
    """Check for forbidden system commands. Returns error message or None."""
    for pattern, name in _FORBIDDEN_COMMANDS:
        if re.search(pattern, content):
            return f"Forbidden command detected: {name}. System-level operations are not allowed."
    return None


_ALLOWED_PATH_RE = re.compile(r'/mnt/user-data/(?:workspace|uploads|outputs)(?:/\S*)?')


def _check_line_paths(text: str) -> str | None:
    """Check a single text fragment — no relative paths, only allowed absolute paths."""
    if re.search(r'(?<![a-zA-Z0-9._])\.\.?(?:[\\/]|$)', text):
        return f"relative path not allowed in '{text[:60]}'. Only absolute paths under /mnt/user-data/{{workspace,uploads,outputs}} permitted."
    if re.search(r'[A-Za-z]:[\\/]', text):
        return f"Windows absolute path not allowed in '{text[:60]}'. Only /mnt/user-data/{{workspace,uploads,outputs}} permitted."
    for m in re.finditer(r'(?<![a-zA-Z0-9._])/[a-zA-Z]\S*', text):
        p = m.group()
        if not p.startswith(_ALLOWED_PREFIXES):
            return f"absolute path '{p[:60]}' not allowed. Only /mnt/user-data/{{workspace,uploads,outputs}} permitted."
    return None


def _check_paths(content: str) -> str | None:
    """Check paths in file content — skips comments and import lines."""
    for i, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith(('import ', 'from ')):
            continue
        err = _check_line_paths(stripped)
        if err:
            return f"Line {i}: {err}"
    return None


def _resolve_paths_in_text(text: str) -> str:
    """Replace allowed virtual paths with resolved host paths."""
    def _replace(m: re.Match) -> str:
        vp = m.group()
        resolved = resolve_virtual_path(vp)
        if not resolved:
            return vp
        result = str(resolved)
        # Preserve trailing separator so Path(dir + filename) stays valid
        if vp.endswith("/") and not result.endswith("/"):
            result += "/"
        return result
    return _ALLOWED_PATH_RE.sub(_replace, text)


def _ensure_chdir(content: str) -> str:
    """Ensure import os and os.chdir(__file__) are present at the top."""
    if not re.search(_IMPORT_OS_RE, content, re.MULTILINE):
        content = f"import os\n{content}"
    if _CHDIR_LINE not in content:
        content = re.sub(
            _IMPORT_OS_RE,
            r'\g<0>' + _CHDIR_LINE + '\n',
            content, count=1, flags=re.MULTILINE,
        )
    return content


def _format_output(display_name: str, result: subprocess.CompletedProcess) -> str:
    out = f"Execution of '{display_name}' finished with exit code {result.returncode}."
    if result.stdout:
        out += f"\n--- Standard Output ---\n{result.stdout}"
    if result.stderr:
        out += f"\n--- Standard Error ---\n{result.stderr}"
    if len(out.encode('utf-8')) > _MAX_OUTPUT_BYTES:
        logger.warning(f"Execution output of {display_name} exceeded max bytes. Truncating.")
        out = out.encode('utf-8')[:_MAX_OUTPUT_BYTES].decode('utf-8', errors='replace')
        return out + "\n\n[Warning: Output was truncated because it exceeded the maximum context limit.]"
    return out


@tool("execute_python", parse_docstring=True)
def execute_python_file_tool(path: str, command_args: list[str] = None) -> str:
    """Execute a specific Python file with optional arguments and return its standard output and error.

    When to use the execute_python_file tool:
    - Use this when you need to run an existing Python script.
    - Pass command-line arguments to the Python script via the command_args parameter.

    Forbiddens:
    - Use this tool to install or uninstall packages, such as `pip`, `npm`, `apt`, `brew`, etc.
    - Use this tool to modify the documents, such as `touch`, `rm`, `mv`, `cp`, etc.

    Args:
        path: The absolute path of the Python file to execute.
        command_args: Optional list of command-line arguments to pass to the Python script. Defaults to None.
    """
    actual_path = resolve_virtual_path(path)
    if not actual_path:
        return f"Path:{path} resolve to None, access denied for security reasons! If it is relative path, please use absolute path."

    try:
        if not actual_path.exists():
            return f"Error: File not found: {path}"
        if actual_path.is_dir():
            return f"Error: Path is a directory, cannot execute: {path}"
        if actual_path.suffix != '.py':
            return f"Error: Target is not a Python (.py) file: {path}"

        content = actual_path.read_text(encoding='utf-8')

        err = _check_forbidden_commands(content) or _check_paths(content)
        if err:
            return f"Error: {err}"

        content = _resolve_paths_in_text(content)
        # content = _ensure_chdir(content)
        # print(content)

        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8')
            tmp.write(content)
            tmp.close()

            command = [sys.executable, tmp.name]
            if command_args:
                args_list = command_args.split() if isinstance(command_args, str) else command_args
                if not isinstance(args_list, list) or not all(isinstance(x, str) for x in args_list):
                    return f"Error: command_args must be a string or list of strings, got {type(command_args).__name__}"
                for arg in args_list:
                    err = _check_line_paths(arg)
                    if err:
                        return f"Error: command argument '{arg[:60]}': {err}"
                    arg = _resolve_paths_in_text(arg)
                    command.append(arg)

            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace', timeout=_DEFAULT_TIMEOUT,
            )
            return _format_output(actual_path.name, result)
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

    except subprocess.TimeoutExpired:
        logger.error(f"Execution of {path} timed out after {_DEFAULT_TIMEOUT} seconds.")
        return f"Error: Execution timed out after {_DEFAULT_TIMEOUT} seconds. The process was terminated."
    except OSError as e:
        logger.error(f"Error: {str(e)}")
        return f"Error: {str(e)}, execute python code failed!"
