from langgraph.config import get_config

from optclaw.config.paths import get_paths, VIRTUAL_PATH_PREFIX
from optclaw.config import get_app_config

from optclaw.log import setup_logging
logger = setup_logging(__name__)


def resolve_virtual_path(path: str) -> str:
    """Resolve a virtual path to an actual file system path. This is used to securely map virtual paths to real paths within the container.

    Args:
        path: The virtual path to resolve.

    Returns:
        The actual file system path corresponding to the virtual path.
    """
    # only three types of path structures are allowed and must be accessed under these two types of paths, other paths are denied access for security reasons
    VIRTUAL_SKILL_PATH_PREFIX = get_app_config().skills.container_path
    if path.startswith(VIRTUAL_SKILL_PATH_PREFIX):
        actual_path = get_app_config().skills.get_skills_path() / path[len(VIRTUAL_SKILL_PATH_PREFIX):].lstrip("/")
    elif path.startswith(VIRTUAL_PATH_PREFIX):
        config_data = get_config()
        thread_id = config_data.get("configurable", {}).get("thread_id")
        if not thread_id:
            raise ValueError(f"No thread_id in context! Cannot resolve virtual paths ({path}) without thread context.") from None
        actual_path = get_paths().resolve_virtual_path(thread_id, path)
    else:
        actual_path = None
    return actual_path


    