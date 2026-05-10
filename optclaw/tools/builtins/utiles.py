# from pathlib import Path


# def _thread_virtual_to_actual_mappings(thread_data: ThreadDataState) -> dict[str, str]:
#     """Build virtual-to-actual path mappings for a thread."""
#     mappings: dict[str, str] = {}

#     workspace = thread_data.get("workspace_path")
#     uploads = thread_data.get("uploads_path")
#     outputs = thread_data.get("outputs_path")

#     if workspace:
#         mappings[f"{VIRTUAL_PATH_PREFIX}/workspace"] = workspace
#     if uploads:
#         mappings[f"{VIRTUAL_PATH_PREFIX}/uploads"] = uploads
#     if outputs:
#         mappings[f"{VIRTUAL_PATH_PREFIX}/outputs"] = outputs

#     # Also map the virtual root when all known dirs share the same parent.
#     actual_dirs = [Path(p) for p in (workspace, uploads, outputs) if p]
#     if actual_dirs:
#         common_parent = str(Path(actual_dirs[0]).parent)
#         if all(str(path.parent) == common_parent for path in actual_dirs):
#             mappings[VIRTUAL_PATH_PREFIX] = common_parent

#     return mappings


# def _resolve_path(self, path: str) -> str:
#     """
#     Resolve container path to actual local path using mappings.

#     Args:
#         path: Path that might be a container path

#     Returns:
#         Resolved local path
#     """
#     path_str = str(path)

#     # Try each mapping (longest prefix first for more specific matches)
#     for mapping in sorted(self.path_mappings, key=lambda m: len(m.container_path), reverse=True):
#         container_path = mapping.container_path
#         local_path = mapping.local_path
#         if path_str == container_path or path_str.startswith(container_path + "/"):
#             # Replace the container path prefix with local path
#             relative = path_str[len(container_path) :].lstrip("/")
#             resolved = str(Path(local_path) / relative) if relative else local_path
#             return resolved

#     # No mapping found, return original path
#     return path_str


# def _reverse_resolve_path(self, path: str) -> str:
#     """
#     Reverse resolve local path back to container path using mappings.

#     Args:
#         path: Local path that might need to be mapped to container path

#     Returns:
#         Container path if mapping exists, otherwise original path
#     """
#     normalized_path = path.replace("\\", "/")
#     path_str = str(Path(normalized_path).resolve())

#     # Try each mapping (longest local path first for more specific matches)
#     for mapping in sorted(self.path_mappings, key=lambda m: len(m.local_path), reverse=True):
#         local_path_resolved = str(Path(mapping.local_path).resolve())
#         if path_str == local_path_resolved or path_str.startswith(local_path_resolved + "/"):
#             # Replace the local path prefix with container path
#             relative = path_str[len(local_path_resolved) :].lstrip("/")
#             resolved = f"{mapping.container_path}/{relative}" if relative else mapping.container_path
#             return resolved

#     # No mapping found, return original path
#     return path_str