"""OptClawClient — Embedded Python client for optclaw agent system.

Provides direct programmatic access to optclaw's agent capabilities
without requiring LangGraph Server or Gateway API processes.

Usage:
    from optclaw.client import OptClawClient

    client = OptClawClient()
    response = await client.chat("Analyze this paper for me", thread_id="my-thread")
    print(response)

    # Streaming
    async for event in client.stream("hello"):
        print(event)
"""

import asyncio
import json
import mimetypes
import re
import shutil
import tempfile
import uuid
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from optclaw.agents import apply_prompt_template
from optclaw.agents.thread_state import ThreadState
from optclaw.config.agents_config import AGENT_NAME_PATTERN
from optclaw.config.app_config import get_app_config, reload_app_config
from optclaw.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from optclaw.config.paths import get_paths
from optclaw.models import create_chat_model
from optclaw.skills.installer import install_skill_from_archive
from optclaw.uploads.manager import (
    claim_unique_filename,
    delete_file_safe,
    enrich_file_listing,
    ensure_uploads_dir,
    get_uploads_dir,
    list_files_in_dir,
    upload_artifact_url,
    upload_virtual_path,
)
from optclaw.agents.middlewares import build_leadagent_middlewares
from optclaw.config.agents_config import list_custom_agents, load_agent_soul

from optclaw.log import setup_logging
logger = setup_logging(__name__)


StreamEventType = Literal["values", "messages-tuple", "custom", "end"]


@dataclass
class StreamEvent:
    """A single event from the streaming agent response.

    Event types align with the LangGraph SSE protocol:
        - ``"values"``: Full state snapshot (title, messages, artifacts).
        - ``"messages-tuple"``: Per-message update (AI text, tool calls, tool results).
        - ``"end"``: Stream finished.

    Attributes:
        type: Event type.
        data: Event payload. Contents vary by type.
    """

    type: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)


class OptClawClient:
    """Embedded Python client for optclaw agent system.

    Provides direct programmatic access to optclaw's agent capabilities
    without requiring LangGraph Server or Gateway API processes.

    Note:
        Multi-turn conversations require a ``checkpointer``. Without one,
        each ``stream()`` / ``chat()`` call is stateless — ``thread_id``
        is only used for file isolation (uploads / artifacts).

        The system prompt (including date, memory, and skills context) is
        generated when the internal agent is first created and cached until
        the configuration key changes. Call :meth:`reset_agent` to force
        a refresh in long-running processes.

    Example::

        from optclaw.client import OptClawClient

        client = OptClawClient()

        # Simple one-shot
        print(await client.chat("hello"))

        # Streaming
        async for event in client.stream("hello"):
            print(event.type, event.data)

        # Configuration queries
        print(client.list_models())
        print(client.list_skills())
    """

    def __init__(
        self,
        config_path: str | None = None,
        checkpointer = None,
        *,
        model_name: str | None = None,
        thinking_enabled: bool = False,
        subagent_enabled: bool = False,
        plan_mode: bool = False,
        agent_name: str | None = None,
        available_skills: set[str] | None = None,
        middlewares: Sequence[AgentMiddleware] | None = None,
    ):
        """Initialize the client.

        Loads configuration but defers agent creation to first use.

        Args:
            config_path: Path to config.yaml. Uses default resolution if None.
            checkpointer: LangGraph checkpointer instance for state persistence.
                Required for multi-turn conversations on the same thread_id.
                Without a checkpointer, each call is stateless.
            model_name: Override the default model name from config.
            thinking_enabled: Enable model's extended thinking.
            subagent_enabled: Enable subagent delegation.
            plan_mode: Enable TodoList middleware for plan mode.
            agent_name: Name of the agent to use.
            available_skills: Optional set of skill names to make available. If None (default), all scanned skills are available.
            middlewares: Optional list of custom middlewares to inject into the agent.
        """
        if config_path is not None:
            reload_app_config(config_path)
        self._app_config = get_app_config()

        if agent_name is not None and not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name '{agent_name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")

        self._checkpointer = checkpointer
        self._model_name = model_name
        self._thinking_enabled = thinking_enabled
        self._subagent_enabled = subagent_enabled
        self._plan_mode = plan_mode
        self._agent_name = agent_name
        self._available_skills = set(available_skills) if available_skills is not None else None
        self._middlewares = list(middlewares) if middlewares else []

        # Lazy agent — created on first call, recreated when config changes.
        self._agent = None
        self._agent_config_key: tuple | None = None

        # Async checkpointer lifecycle
        self._async_checkpointer_ctx = None

    # async def close(self) -> None:
    #     """Close the async checkpointer context manager, releasing resources."""
    #     if self._async_checkpointer_ctx is not None:
    #         try:
    #             await self._async_checkpointer_ctx.__aexit__(None, None, None)
    #         except Exception:
    #             logger.warning("Error during async checkpointer cleanup", exc_info=True)
    #         self._async_checkpointer_ctx = None
    #         self._checkpointer = None

    def reset_agent(self) -> None:
        """Force the internal agent to be recreated on the next call.

        Cancels all running background tasks (subagents, memory queue timer)
        and clears the cached agent so the next conversation starts fresh.
        """
        from optclaw.subagents.executor import cancel_all_background_tasks

        cancelled = cancel_all_background_tasks()
        logger.info("Cancelled %d subagent task(s) during reset", cancelled)

        from optclaw.agents.memory.queue import reset_memory_queue
        reset_memory_queue()
        logger.info("Memory queue cleared during reset")

        self._agent = None
        self._agent_config_key = None

    def list_custom_agents_desc(self)->list[dict]:
        """Return a list of descriptions of installed custom agents."""
        list_agents = []
        for item in list_custom_agents():
            list_agents.append({
                "agent_name": item.name,
                "description": item.description,
            })
        return list_agents
    
    def get_custom_agent_soul(self, agent_name:str)->str:
        """Get the full SOUL.md content of a custom agent by its name.
        
        Args:
        agent_name: The name of the custom agent.
        
        Returns:
            The full SOUL.md content of the agent, or None if the agent doesn't exist."""
        return load_agent_soul(agent_name)
    
    def create_custom_agent(self, agent_name: str, description: str,soul: str) -> None:
        """Create new custom agent.

        Args:
            agent_name: Name of the agent.
            soul: Full SOUL.md content defining the agent's personality and behavior.
            description: One-line description of what the agent does.
        """
        import yaml

        try:
            paths = get_paths()
            agent_dir = paths.agent_dir(agent_name) if agent_name else paths.base_dir
            agent_dir.mkdir(parents=True, exist_ok=True)

            if agent_name:
                # If agent_name is provided, we are creating a custom agent in the agents/ directory
                config_data: dict = {"name": agent_name}
                if description:
                    config_data["description"] = description

                config_file = agent_dir / "config.yaml"
                with open(config_file, "w", encoding="utf-8") as f:
                    yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

            soul_file = agent_dir / "SOUL.md"
            soul_file.write_text(soul, encoding="utf-8")

            logger.info(f"[agent_creator] Created agent '{agent_name}' at {agent_dir}")
            return True

        except Exception as e:
            import shutil

            if agent_name and agent_dir.exists():
                # Cleanup the custom agent directory only if it was created but an error occurred during setup
                shutil.rmtree(agent_dir)
            logger.error(f"[agent_creator] Failed to create agent '{agent_name}': {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_checkpointer(self):
        """Ensure an async-compatible checkpointer is available.

        If the user provided a checkpointer at init, use it directly.
        Otherwise, lazily enter the ``make_checkpointer()`` async context
        manager and store the reference for lifecycle management.
        """
        if self._checkpointer is not None:
            return

        from optclaw.agents.checkpointer import make_checkpointer

        ctx = make_checkpointer()
        self._checkpointer = await ctx.__aenter__()
        self._async_checkpointer_ctx = ctx

    @staticmethod
    def _atomic_write_json(path: Path, data: dict) -> None:
        """Write JSON to *path* atomically (temp file + replace)."""
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        )
        try:
            json.dump(data, fd, indent=2)
            fd.close()
            Path(fd.name).replace(path)
        except BaseException:
            fd.close()
            Path(fd.name).unlink(missing_ok=True)
            raise

    def _get_runnable_config(self, thread_id: str, **overrides) -> RunnableConfig:
        """Build a RunnableConfig for agent invocation."""
        configurable = {
            "thread_id": thread_id,
            "model_name": overrides.get("model_name", self._model_name),
            "thinking_enabled": overrides.get("thinking_enabled", self._thinking_enabled),
            "is_plan_mode": overrides.get("plan_mode", self._plan_mode),
            "subagent_enabled": overrides.get("subagent_enabled", self._subagent_enabled),
            "agent_name": overrides.get("agent_name", self._agent_name),
        }
        return RunnableConfig(
            configurable=configurable,
            recursion_limit=overrides.get("recursion_limit", 500),
        )

    async def _ensure_agent(self, config: RunnableConfig):
        """Create (or recreate) the agent when config-dependent params change."""
        cfg = config.get("configurable", {})
        key = (
            cfg.get("model_name"),
            cfg.get("thinking_enabled"),
            cfg.get("is_plan_mode"),
            cfg.get("subagent_enabled"),
            cfg.get("agent_name"),
            frozenset(self._available_skills) if self._available_skills is not None else None,
        )

        if self._agent is not None and self._agent_config_key == key:
            return

        # Update the agent's config params
        self._agent_name = cfg.get("agent_name", None)
        self._plan_mode = cfg.get("is_plan_mode", False)
        self._model_name = cfg.get("model_name")
        self._thinking_enabled = cfg.get("thinking_enabled", False)
        self._subagent_enabled = cfg.get("subagent_enabled", False)
        max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)

        kwargs: dict[str, Any] = {
            "model": create_chat_model(name=self._model_name, thinking_enabled=self._thinking_enabled),
            "tools": self._get_tools(model_name=self._model_name, subagent_enabled=self._subagent_enabled),
            # If an agent_name is provided, the path refers to agent-specific memory; otherwise, it refers to common shared memory.
            "middleware": build_leadagent_middlewares(config=config, model_name=self._model_name, agent_name=self._agent_name, plan_mode=self._plan_mode),
            "system_prompt": apply_prompt_template(
                agent_name=self._agent_name,
                available_skills=self._available_skills,
                subagent_enabled=self._subagent_enabled,
                max_concurrent_subagents=max_concurrent_subagents
            ),
            "state_schema": ThreadState,  # record state info during the chat
            # "context_schema": None  # provide context info such as user id, read-only mode
        }
        checkpointer = self._checkpointer
        if checkpointer is None:
            await self._ensure_checkpointer()
            checkpointer = self._checkpointer

        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer

        self._agent = create_agent(**kwargs)
        self._agent_config_key = key
        logger.warning("Agent created: agent_name=%s, model=%s, thinking=%s", self._agent_name, self._model_name, self._thinking_enabled)

    @staticmethod
    def _get_tools(*, model_name: str | None, subagent_enabled: bool):
        """Lazy import to avoid circular dependency at module level."""
        from optclaw.tools import get_available_tools

        return get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled)

    @staticmethod
    def _serialize_tool_calls(tool_calls) -> list[dict]:
        """Reshape LangChain tool_calls into the wire format used in events."""
        return [{"name": tc["name"], "args": tc["args"], "id": tc.get("id")} for tc in tool_calls]

    @staticmethod
    def _ai_reasoning_text_event(msg_id: str | None, text: str, usage: dict | None) -> "StreamEvent":
        """Build a ``messages-tuple`` AI reasoning text event, attaching usage when present."""
        data: dict[str, Any] = {"type": "ai", "content": text, "id": msg_id, "subtype": "reasoning_text"}
        if usage:
            data["usage_metadata"] = usage
        return StreamEvent(type="messages-tuple", data=data)

    @staticmethod
    def _ai_text_event(msg_id: str | None, text: str, usage: dict | None) -> "StreamEvent":
        """Build a ``messages-tuple`` AI text event, attaching usage when present."""
        data: dict[str, Any] = {"type": "ai", "content": text, "id": msg_id, "subtype": "text"}
        if usage:
            data["usage_metadata"] = usage
        return StreamEvent(type="messages-tuple", data=data)

    @staticmethod
    def _ai_tool_calls_event(msg_id: str | None, tool_calls) -> "StreamEvent":
        """Build a ``messages-tuple`` AI tool-calls event."""
        return StreamEvent(
            type="messages-tuple",
            data={
                "type": "ai",
                "content": "",
                "id": msg_id,
                "tool_calls": OptClawClient._serialize_tool_calls(tool_calls),
                "subtype": "tool_calls"
            },
        )

    @staticmethod
    def _tool_message_event(msg: ToolMessage) -> "StreamEvent":
        """Build a ``messages-tuple`` tool-result event from a ToolMessage."""
        return StreamEvent(
            type="messages-tuple",
            data={
                "type": "tool",
                "content": OptClawClient._extract_text(msg.content),
                "name": msg.name,
                "tool_call_id": msg.tool_call_id,
                "id": msg.id,
                "subtype": "tool_message"
            },
        )

    @staticmethod
    def _serialize_message(msg) -> dict:
        """Serialize a LangChain message to a plain dict for values events."""
        if isinstance(msg, AIMessage):
            d: dict[str, Any] = {"type": "ai", "content": msg.content, "id": getattr(msg, "id", None)}
            if msg.tool_calls:
                d["tool_calls"] = OptClawClient._serialize_tool_calls(msg.tool_calls)
            if getattr(msg, "usage_metadata", None):
                d["usage_metadata"] = msg.usage_metadata
            return d
        if isinstance(msg, ToolMessage):
            return {
                "type": "tool",
                "content": OptClawClient._extract_text(msg.content),
                "name": getattr(msg, "name", None),
                "tool_call_id": getattr(msg, "tool_call_id", None),
                "id": getattr(msg, "id", None),
            }
        if isinstance(msg, HumanMessage):
            content = OptClawClient._strip_uploaded_files(msg.content)
            d: dict[str, Any] = {"type": "human", "content": content, "id": getattr(msg, "id", None)}
            if msg.additional_kwargs:
                d["additional_kwargs"] = msg.additional_kwargs
            return d
        if isinstance(msg, SystemMessage):
            return {"type": "system", "content": msg.content, "id": getattr(msg, "id", None)}
        return {"type": "unknown", "content": str(msg), "id": getattr(msg, "id", None)}

    _UPLOADED_FILES_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)

    @staticmethod
    def _strip_uploaded_files(content):
        """Remove <uploaded_files>...</uploaded_files> block injected by uploads middleware.

        Handles both string and list (multimodal) content formats.
        """
        if isinstance(content, str):
            return OptClawClient._UPLOADED_FILES_RE.sub("", content).strip()
        if isinstance(content, list):
            stripped: list[dict] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = OptClawClient._UPLOADED_FILES_RE.sub("", block.get("text", ""))
                    if text.strip():
                        if stripped and isinstance(stripped[-1], dict) and stripped[-1].get("type") == "text":
                            stripped[-1]["text"] += "\n\n" + text
                        else:
                            stripped.append({"type": "text", "text": text})
                elif isinstance(block, dict) and block.get("type") == "image_url":
                    continue
                else:
                    stripped.append(block)
            return stripped
        return content

    @staticmethod
    def _is_view_image_artifact(msg) -> bool:
        """Detect HumanMessage injected by ViewImageMiddleware.

        These carry image_url blocks with base64 payloads and are internal
        implementation artifacts, not user-generated messages.
        """
        if not isinstance(msg, HumanMessage):
            return False
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            return False
        return any(
            isinstance(b, dict) and b.get("type") == "image_url"
            for b in content
        )

    @staticmethod
    def _extract_text(content) -> str:
        """Extract plain text from AIMessage content (str or list of blocks).

        String chunks are concatenated without separators to avoid corrupting
        token/character deltas or chunked JSON payloads. Dict-based text blocks
        are treated as full text blocks and joined with newlines to preserve
        readability.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            if content and all(isinstance(block, str) for block in content):
                chunk_like = len(content) > 1 and all(isinstance(block, str) and len(block) <= 20 and any(ch in block for ch in '{}[]":,') for block in content)
                return "".join(content) if chunk_like else "\n".join(content)

            pieces: list[str] = []
            pending_str_parts: list[str] = []

            def flush_pending_str_parts() -> None:
                if pending_str_parts:
                    pieces.append("".join(pending_str_parts))
                    pending_str_parts.clear()

            for block in content:
                if isinstance(block, str):
                    pending_str_parts.append(block)
                elif isinstance(block, dict):
                    flush_pending_str_parts()
                    text_val = block.get("text")
                    if isinstance(text_val, str):
                        pieces.append(text_val)

            flush_pending_str_parts()
            return "\n".join(pieces) if pieces else ""
        return str(content)
    
    # ------------------------------------------------------------------
    # Public API — threads
    # ------------------------------------------------------------------
    async def list_threads(self, limit: int = 10, agent_name: str | None = None) -> dict:
        """List the recent N threads.

        Args:
            limit: Maximum number of threads to return. Default is 10.
            agent_name: Filter threads by agent name. None returns all threads.

        Returns:
            Dict with "thread_list" key containing list of thread info dicts,
            sorted by thread creation time descending.
        """
        checkpointer = self._checkpointer
        if checkpointer is None:
            await self._ensure_checkpointer()
            checkpointer = self._checkpointer

        thread_info_map = {}

        cnt = 0

        async for cp in checkpointer.alist(config=None, limit=1000):
            cfg = cp.config.get("configurable", {})
            thread_id = cfg.get("thread_id")

            if not thread_id:
                continue

            channel_values = cp.checkpoint.get("channel_values", {})

            # Filter by agent_name if specified
            if agent_name:
                cp_agent = channel_values.get("agent_name") or ""
                if cp_agent != agent_name:
                    continue

            ts = cp.checkpoint.get("ts")
            checkpoint_id = cfg.get("checkpoint_id")

            if thread_id not in thread_info_map:
                thread_info_map[thread_id] = {
                    "thread_id": thread_id,
                    "created_at": ts,
                    "updated_at": ts,
                    "latest_checkpoint_id": checkpoint_id,
                    "title": channel_values.get("title"),
                    "agent_name": channel_values.get("agent_name") or "",
                }
                cnt = cnt + 1
                if cnt >= limit:
                    break
            else:
                # Explicitly compare timestamps to ensure accuracy when iterating over unordered namespaces.
                # Treat None as "missing" and only compare when existing values are non-None.
                if ts is not None:
                    current_created = thread_info_map[thread_id]["created_at"]
                    if current_created is None or ts < current_created:
                        thread_info_map[thread_id]["created_at"] = ts

                    current_updated = thread_info_map[thread_id]["updated_at"]
                    if current_updated is None or ts > current_updated:
                        thread_info_map[thread_id]["updated_at"] = ts
                        thread_info_map[thread_id]["latest_checkpoint_id"] = checkpoint_id
                        channel_values = cp.checkpoint.get("channel_values", {})
                        thread_info_map[thread_id]["title"] = channel_values.get("title")

        threads = list(thread_info_map.values())
        threads.sort(key=lambda x: x.get("created_at") or "", reverse=True)

        return {"thread_list": threads[:limit]}

    async def get_thread_detail(self, thread_id: str) -> dict:
        """Get the complete thread record, including all node execution records.

        Args:
            thread_id: Thread ID.

        Returns:
            Dict containing the thread's full checkpoint history.
        """
        checkpointer = self._checkpointer
        if checkpointer is None:
            await self._ensure_checkpointer()
            checkpointer = self._checkpointer

        config = {"configurable": {"thread_id": thread_id}}
        checkpoints = []

        async for cp in checkpointer.alist(config):
            channel_values = dict(cp.checkpoint.get("channel_values", {}))
            if "messages" in channel_values:
                channel_values["messages"] = [self._serialize_message(m) if hasattr(m, "content") else m for m in channel_values["messages"]]

            cfg = cp.config.get("configurable", {})
            parent_cfg = cp.parent_config.get("configurable", {}) if cp.parent_config else {}

            checkpoints.append(
                {
                    "checkpoint_id": cfg.get("checkpoint_id"),
                    "parent_checkpoint_id": parent_cfg.get("checkpoint_id"),
                    "ts": cp.checkpoint.get("ts"),
                    "metadata": cp.metadata,
                    "values": channel_values,
                    "pending_writes": [{"task_id": w[0], "channel": w[1], "value": w[2]} for w in getattr(cp, "pending_writes", [])],
                }
            )

        # Sort globally by timestamp to prevent partial ordering issues caused by different namespaces (e.g., subgraphs)
        checkpoints.sort(key=lambda x: x["ts"] if x["ts"] else "")

        return {"thread_id": thread_id, "checkpoints": checkpoints}

    async def get_thread(self, thread_id: str) -> dict:
        """Get the complete thread record, including all node execution records.

        Args:
            thread_id: Thread ID.

        Returns:
            Dict containing the thread's full checkpoint history.
        """
        checkpointer = self._checkpointer
        if checkpointer is None:
            await self._ensure_checkpointer()
            checkpointer = self._checkpointer

        config = {"configurable": {"thread_id": thread_id}}
        checkpoints = []

        async for cp in checkpointer.alist(config):
            channel_values = dict(cp.checkpoint.get("channel_values", {}))
            if "messages" in channel_values:
                channel_values["messages"] = [
                    self._serialize_message(m) for m in channel_values["messages"]
                    if hasattr(m, "content") and m.content
                    and (isinstance(m, HumanMessage)
                    or (isinstance(m, AIMessage) and hasattr(m, "tool_calls") and len(m.tool_calls) == 0))
                    and not self._is_view_image_artifact(m)
                ]

            cfg = cp.config.get("configurable", {})
            parent_cfg = cp.parent_config.get("configurable", {}) if cp.parent_config else {}

            checkpoints.append(
                {
                    "checkpoint_id": cfg.get("checkpoint_id"),
                    "parent_checkpoint_id": parent_cfg.get("checkpoint_id"),
                    "ts": cp.checkpoint.get("ts"),
                    "metadata": cp.metadata,
                    "values": channel_values,
                    "pending_writes": [{"task_id": w[0], "channel": w[1], "value": w[2]} for w in getattr(cp, "pending_writes", [])],
                }
            )

        # Sort globally by timestamp to prevent partial ordering issues caused by different namespaces (e.g., subgraphs)
        checkpoints.sort(key=lambda x: x["ts"] if x["ts"] else "")

        return {"thread_id": thread_id, "checkpoints": checkpoints}

    async def delete_thread(self, thread_id: str) -> dict:
        """Delete a thread: checkpoints + all associated files.

        Args:
            thread_id: Thread ID to delete.

        Returns:
            Dict with success status.
        """
        checkpointer = self._checkpointer
        if checkpointer is None:
            await self._ensure_checkpointer()
            checkpointer = self._checkpointer

        errors: list[str] = []

        # 1. Delete checkpoints from database
        if hasattr(checkpointer, "adelete_thread"):
            await checkpointer.adelete_thread(thread_id)
        elif hasattr(checkpointer, "delete_thread"):
            checkpointer.delete_thread(thread_id)
        else:
            errors.append("Checkpointer does not support delete_thread")

        # 1.1 Reclaim disk space (SQLite does not auto-shrink on DELETE)
        if hasattr(checkpointer, "conn"):
            try:
                await checkpointer.conn.execute("VACUUM")
            except Exception:
                pass  # VACUUM is best-effort only

        # 2. Delete thread directory (uploads, outputs, sandbox files)
        from optclaw.config.paths import get_paths
        import shutil

        thread_dir = get_paths().thread_dir(thread_id)
        if thread_dir.exists():
            try:
                shutil.rmtree(thread_dir)
            except OSError as e:
                errors.append(f"Failed to delete thread directory: {e}")

        if errors:
            return {"success": False, "thread_id": thread_id, "errors": errors}
        return {"success": True, "thread_id": thread_id}

    # ------------------------------------------------------------------
    # Public API — configuration queries
    # ------------------------------------------------------------------

    def list_models(self) -> dict:
        """List available models from configuration.

        Returns:
            Dict with "models" key containing list of model info dicts,
            matching the Gateway API ``ModelsListResponse`` schema.
        """
        return {
            "models": [
                {
                    "name": model.name,
                    "model": getattr(model, "model", None),
                    "display_name": getattr(model, "display_name", None),
                    "description": getattr(model, "description", None),
                    "supports_thinking": getattr(model, "supports_thinking", False),
                    "supports_reasoning_effort": getattr(model, "supports_reasoning_effort", False),
                    "supports_vision": getattr(model, "supports_vision", False),
                }
                for model in self._app_config.models
            ]
        }

    def list_skills(self, enabled_only: bool = False) -> dict:
        """List available skills.

        Args:
            enabled_only: If True, only return enabled skills.

        Returns:
            Dict with "skills" key containing list of skill info dicts,
            matching the Gateway API ``SkillsListResponse`` schema.
        """
        from optclaw.skills.loader import load_skills

        return {
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "license": s.license,
                    "category": s.category,
                    "enabled": s.enabled,
                }
                for s in load_skills(enabled_only=enabled_only)
            ]
        }

    def get_memory(self, agent_name: str | None = None) -> dict:
        """Get current memory data.

        Args:
            agent_name: Agent name for memory scope.

        Returns:
            Memory data dict (see src/agents/memory/updater.py for structure).
        """
        from optclaw.agents.memory.updater import get_memory_data

        logger.info("get_memory called with agent_name: %s" % (agent_name))

        return get_memory_data(agent_name=agent_name)

    def export_memory(self) -> dict:
        """Export current memory data for backup or transfer."""
        from optclaw.agents.memory.updater import get_memory_data

        return get_memory_data(agent_name=self._agent_name)

    def import_memory(self, memory_data: dict) -> dict:
        """Import and persist full memory data."""
        from optclaw.agents.memory.updater import import_memory_data

        return import_memory_data(memory_data)

    def get_model(self, name: str) -> dict | None:
        """Get a specific model's configuration by name.

        Args:
            name: Model name.

        Returns:
            Model info dict matching the Gateway API ``ModelResponse``
            schema, or None if not found.
        """
        model = self._app_config.get_model_config(name)
        if model is None:
            return None
        return {
            "name": model.name,
            "model": getattr(model, "model", None),
            "display_name": getattr(model, "display_name", None),
            "description": getattr(model, "description", None),
            "supports_thinking": getattr(model, "supports_thinking", False),
            "supports_reasoning_effort": getattr(model, "supports_reasoning_effort", False),
        }

    # ------------------------------------------------------------------
    # Public API — skills management
    # ------------------------------------------------------------------

    def get_skill(self, name: str) -> dict | None:
        """Get a specific skill by name.

        Args:
            name: Skill name.

        Returns:
            Skill info dict, or None if not found.
        """
        from optclaw.skills.loader import load_skills

        skill = next((s for s in load_skills(enabled_only=False) if s.name == name), None)
        if skill is None:
            return None
        return {
            "name": skill.name,
            "description": skill.description,
            "license": skill.license,
            "category": skill.category,
            "enabled": skill.enabled,
        }

    def update_skill(self, name: str, *, enabled: bool) -> dict:
        """Update a skill's enabled status.

        Args:
            name: Skill name.
            enabled: New enabled status.

        Returns:
            Updated skill info dict.

        Raises:
            ValueError: If the skill is not found.
            OSError: If the config file cannot be written.
        """
        from optclaw.skills.loader import load_skills

        skills = load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == name), None)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found")

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            raise FileNotFoundError("Cannot locate extensions_config.json. Set OPT_CLAW_EXTENSIONS_CONFIG_PATH or ensure it exists in the project root.")

        extensions_config = get_extensions_config()
        extensions_config.skills[name] = SkillStateConfig(enabled=enabled)

        config_data = {
            "mcpServers": {n: s.model_dump() for n, s in extensions_config.mcp_servers.items()},
            "skills": {n: {"enabled": sc.enabled} for n, sc in extensions_config.skills.items()},
        }

        self._atomic_write_json(config_path, config_data)

        self._agent = None
        self._agent_config_key = None
        reload_extensions_config()

        updated = next((s for s in load_skills(enabled_only=False) if s.name == name), None)
        if updated is None:
            raise RuntimeError(f"Skill '{name}' disappeared after update")

        return {
            "name": updated.name,
            "description": updated.description,
            "license": updated.license,
            "category": updated.category,
            "enabled": updated.enabled,
        }

    def install_skill(self, skill_path: str | Path) -> dict:
        """Install a skill from a .skill archive (ZIP).

        Args:
            skill_path: Path to the .skill file.

        Returns:
            Dict with success, skill_name, message.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is invalid.
        """
        return install_skill_from_archive(skill_path)

    # ------------------------------------------------------------------
    # Public API — MCP server management
    # ------------------------------------------------------------------

    def get_mcp_config(self) -> dict:
        """Get current MCP server configurations.

        Returns:
            Dict with "mcpServers" key containing all MCP server configs.
        """
        from optclaw.config.extensions_config import ExtensionsConfig

        config = ExtensionsConfig.from_file()
        servers = {}
        for name, srv in config.mcp_servers.items():
            servers[name] = {
                "enabled": srv.enabled,
                "type": srv.type,
                "command": srv.command,
                "args": srv.args,
                "env": srv.env,
                "url": srv.url,
                "headers": srv.headers,
                "description": srv.description,
            }
        return {"mcpServers": servers}

    def update_mcp_server(self, server_name: str, updates: dict) -> dict:
        """Update a single MCP server's configuration.

        Args:
            server_name: Name of the MCP server to update.
            updates: Dict of fields to update.

        Returns:
            Updated MCP server config.

        Raises:
            ValueError: If the server is not found.
        """
        import json

        from optclaw.config.extensions_config import ExtensionsConfig, reload_extensions_config
        from optclaw.mcp.cache import reset_mcp_tools_cache

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            raise FileNotFoundError("extensions_config.json not found")

        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        servers = data.get("mcpServers", {})
        if server_name not in servers:
            raise ValueError(f"MCP server '{server_name}' not found")

        for key, value in updates.items():
            if value is not None:
                servers[server_name][key] = value

        data["mcpServers"] = servers
        self._atomic_write_json(config_path, data)

        reload_extensions_config()
        reset_mcp_tools_cache()

        return {"success": True, "server_name": server_name, "config": servers[server_name]}

    def toggle_mcp_server(self, server_name: str, enabled: bool) -> dict:
        """Enable or disable an MCP server.

        Args:
            server_name: Name of the MCP server.
            enabled: New enabled status.

        Returns:
            Updated MCP server config.
        """
        return self.update_mcp_server(server_name, {"enabled": enabled})

    def create_mcp_server(self, server_name: str, config: dict) -> dict:
        """Create a new MCP server entry.

        Args:
            server_name: Unique name for the MCP server.
            config: Server configuration dict.

        Returns:
            Created MCP server config.

        Raises:
            ValueError: If the server name already exists.
        """
        import json

        from optclaw.config.extensions_config import ExtensionsConfig, reload_extensions_config
        from optclaw.mcp.cache import reset_mcp_tools_cache

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            raise FileNotFoundError("extensions_config.json not found")

        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        servers = data.get("mcpServers", {})
        if server_name in servers:
            raise ValueError(f"MCP server '{server_name}' already exists")

        servers[server_name] = {
            "enabled": config.get("enabled", False),
            "type": config.get("type", "stdio"),
            "command": config.get("command"),
            "args": config.get("args", []),
            "env": config.get("env", {}),
            "url": config.get("url"),
            "headers": config.get("headers", {}),
            "oauth": config.get("oauth"),
            "description": config.get("description", ""),
        }
        data["mcpServers"] = servers
        self._atomic_write_json(config_path, data)

        reload_extensions_config()
        reset_mcp_tools_cache()

        return {"success": True, "server_name": server_name, "config": servers[server_name]}

    def delete_mcp_server(self, server_name: str) -> dict:
        """Delete an MCP server entry.

        Args:
            server_name: Name of the MCP server to delete.

        Returns:
            Success status.

        Raises:
            ValueError: If the server is not found.
        """
        import json

        from optclaw.config.extensions_config import ExtensionsConfig, reload_extensions_config
        from optclaw.mcp.cache import reset_mcp_tools_cache

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            raise FileNotFoundError("extensions_config.json not found")

        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        servers = data.get("mcpServers", {})
        if server_name not in servers:
            raise ValueError(f"MCP server '{server_name}' not found")

        del servers[server_name]
        data["mcpServers"] = servers
        self._atomic_write_json(config_path, data)

        reload_extensions_config()
        reset_mcp_tools_cache()

        return {"success": True, "server_name": server_name}

    def rename_mcp_server(self, old_name: str, new_name: str) -> dict:
        """Rename an MCP server entry.

        Args:
            old_name: Current name of the MCP server.
            new_name: New name for the MCP server.

        Returns:
            Success status with old and new server names.

        Raises:
            ValueError: If old name doesn't exist or new name already exists.
        """
        import json

        from optclaw.config.extensions_config import ExtensionsConfig, reload_extensions_config
        from optclaw.mcp.cache import reset_mcp_tools_cache

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            raise FileNotFoundError("extensions_config.json not found")

        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        servers = data.get("mcpServers", {})
        if old_name not in servers:
            raise ValueError(f"MCP server '{old_name}' not found")
        if new_name in servers:
            raise ValueError(f"MCP server '{new_name}' already exists")

        servers[new_name] = servers.pop(old_name)
        data["mcpServers"] = servers
        self._atomic_write_json(config_path, data)

        reload_extensions_config()
        reset_mcp_tools_cache()

        return {"success": True, "old_name": old_name, "new_name": new_name}

    # ------------------------------------------------------------------
    # Public API — memory management
    # ------------------------------------------------------------------

    def reload_memory(self, agent_name: str | None = None) -> dict:
        """Reload memory data from file, forcing cache invalidation.

        Args:
            agent_name: Agent name for memory scope.

        Returns:
            The reloaded memory data dict.
        """
        from optclaw.agents.memory.updater import reload_memory_data

        logger.info("reload_memory called with agent_name: %s" % (agent_name))

        result = reload_memory_data(agent_name)
        # self.reset_agent()
        return result

    def clear_memory(self, agent_name: str | None = None) -> dict:
        """Clear all persisted memory data.

        Args:
            agent_name: Agent name for memory scope. Defaults to self._agent_name.
        """
        from optclaw.agents.memory.updater import clear_memory_data

        logger.info("clear_memory called with agent_name: %s" % (agent_name))

        result = clear_memory_data(agent_name)
        # self.reset_agent()
        return result

    def create_memory_fact(self, content: str, category: str = "context", confidence: float = 0.5, agent_name: str | None = None) -> dict:
        """Create a single fact manually.

        Args:
            agent_name: Agent name for memory scope. Defaults to self._agent_name.
        """
        from optclaw.agents.memory.updater import create_memory_fact

        logger.info("create_memory_fact called with agent_name: %s" % (agent_name))

        result = create_memory_fact(content=content, category=category, confidence=confidence, agent_name=agent_name)
        # self.reset_agent()
        return result

    def delete_memory_fact(self, fact_id: str, agent_name: str | None = None) -> dict:
        """Delete a single fact from memory by fact id.

        Args:
            agent_name: Agent name for memory scope. Defaults to self._agent_name.
        """
        from optclaw.agents.memory.updater import delete_memory_fact

        logger.info("delete_memory_fact called with agent_name: %s" % (agent_name))

        result = delete_memory_fact(fact_id, agent_name=agent_name)
        # self.reset_agent()
        return result

    def update_memory_fact(
        self,
        fact_id: str,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
        agent_name: str | None = None,
    ) -> dict:
        """Update a single fact manually, preserving omitted fields.

        Args:
            agent_name: Agent name for memory scope. Defaults to self._agent_name.
        """
        from optclaw.agents.memory.updater import update_memory_fact

        logger.info("update_memory_fact called with agent_name: %s" % (agent_name))

        result = update_memory_fact(
            fact_id=fact_id,
            content=content,
            category=category,
            confidence=confidence,
            agent_name=agent_name,
        )
        # self.reset_agent()
        return result

    def get_memory_config(self) -> dict:
        """Get memory system configuration.

        Returns:
            Memory config dict.
        """
        from optclaw.config.memory_config import get_memory_config

        config = get_memory_config()
        return {
            "enabled": config.enabled,
            "storage_path": config.storage_path,
            "debounce_seconds": config.debounce_seconds,
            "max_facts": config.max_facts,
            "fact_confidence_threshold": config.fact_confidence_threshold,
            "injection_enabled": config.injection_enabled,
            "max_injection_tokens": config.max_injection_tokens,
            "model_name":config.model_name
        }

    def update_memory_config(self, updates: dict) -> dict:
        """Update memory configuration both in-memory and in config.yaml.

        Args:
            updates: Dict of config fields to update. Supported keys:
                enabled, storage_path, debounce_seconds, max_facts,
                fact_confidence_threshold, injection_enabled,
                max_injection_tokens, model_name.

        Returns:
            Updated config dict.
        """
        import yaml

        from optclaw.config.memory_config import load_memory_config_from_dict
        from optclaw.config.paths import resolve_path

        current = self.get_memory_config()
        merged = {**current, **updates}

        load_memory_config_from_dict(merged)

        # config_path = resolve_path("config.yaml")
        config_path = get_paths().base_dir.parent.parent / "config.yaml"

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except FileNotFoundError:
            cfg = {}

        mem_section = cfg.get("memory", {})
        field_map = {
            "enabled": "enabled",
            "storage_path": "storage_path",
            "debounce_seconds": "debounce_seconds",
            "max_facts": "max_facts",
            "fact_confidence_threshold": "fact_confidence_threshold",
            "injection_enabled": "injection_enabled",
            "max_injection_tokens": "max_injection_tokens",
            "model_name": "model_name",
        }
        for key, yaml_key in field_map.items():
            if key in updates:
                mem_section[yaml_key] = updates[key]
        cfg["memory"] = mem_section

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # self.reset_agent()
        logger.info("update_memory_config called with: %s" % (config_path))

        return self.get_memory_config()

    def reload_memory_config(self) -> dict:
        """Reload memory configuration from config.yaml and reset agent.

        Returns:
            Dict with reloaded config and memory data.
        """
        import yaml

        from optclaw.config.memory_config import load_memory_config_from_dict
        from optclaw.config.paths import resolve_path

        # config_path = resolve_path("config.yaml")
        config_path = get_paths().base_dir.parent.parent / "config.yaml"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except FileNotFoundError:
            cfg = {}

        mem_section = cfg.get("memory", {})
        if mem_section:
            load_memory_config_from_dict(mem_section)

        logger.info("reload_memory_config called with: %s" % (config_path))

        result= {
            "config": self.get_memory_config(),
            "data": self.get_memory(self._agent_name),
        }

        # self.reset_agent()
        return result

    def get_memory_status(self, agent_name: str | None = None) -> dict:
        """Get memory status: config + current data.

        Args:
            agent_name: Agent name for memory scope. Defaults to self._agent_name.

        Returns:
            Dict with "config" and "data" keys.
        """
        logger.info("get_memory_status called with agent_name: %s" % (agent_name))
        return {
            "config": self.get_memory_config(),
            "data": self.get_memory(agent_name=agent_name),
        }

    # ------------------------------------------------------------------
    # Public API — file uploads
    # ------------------------------------------------------------------

    def upload_files(self, thread_id: str, files: list[str | Path]) -> dict:
        """Upload local files into a thread's uploads directory.

        For PDF, PPT, Excel, and Word files, they are also converted to Markdown.

        Args:
            thread_id: Target thread ID.
            files: List of local file paths to upload.

        Returns:
            Dict with success, files, message — matching the Gateway API
            ``UploadResponse`` schema.

        Raises:
            FileNotFoundError: If any file does not exist.
            ValueError: If any supplied path exists but is not a regular file.
        """
        from optclaw.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown

        # Validate all files upfront to avoid partial uploads.
        resolved_files = []
        seen_names: set[str] = set()
        has_convertible_file = False
        for f in files:
            p = Path(f)
            if not p.exists():
                raise FileNotFoundError(f"File not found: {f}")
            if not p.is_file():
                raise ValueError(f"Path is not a file: {f}")
            ext = p.suffix.lower()
            if ext not in (".pdf", ".csv", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
                raise ValueError(f"Unsupported file type: {ext}. Supported: pdf, csv, txt, and image formats")
            dest_name = claim_unique_filename(p.name, seen_names)
            resolved_files.append((p, dest_name))
            if not has_convertible_file and p.suffix.lower() in CONVERTIBLE_EXTENSIONS:
                has_convertible_file = True

        uploads_dir = ensure_uploads_dir(thread_id)
        uploaded_files: list[dict] = []

        conversion_pool = None
        if has_convertible_file:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                conversion_pool = None
            else:
                import concurrent.futures

                # Reuse one worker when already inside an event loop to avoid
                # creating a new ThreadPoolExecutor per converted file.
                conversion_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _convert_in_thread(path: Path):
            return asyncio.run(convert_file_to_markdown(path))

        try:
            for src_path, dest_name in resolved_files:
                dest = uploads_dir / dest_name
                shutil.copy2(src_path, dest)

                info: dict[str, Any] = {
                    "filename": dest_name,
                    "size": str(dest.stat().st_size),
                    "path": str(dest),
                    "virtual_path": upload_virtual_path(dest_name),
                    "artifact_url": upload_artifact_url(thread_id, dest_name),
                }
                if dest_name != src_path.name:
                    info["original_filename"] = src_path.name

                if src_path.suffix.lower() in CONVERTIBLE_EXTENSIONS:
                    try:
                        if conversion_pool is not None:
                            md_path = conversion_pool.submit(_convert_in_thread, dest).result()
                        else:
                            md_path = asyncio.run(convert_file_to_markdown(dest))
                    except Exception:
                        logger.warning(
                            "Failed to convert %s to markdown",
                            src_path.name,
                            exc_info=True,
                        )
                        md_path = None

                    if md_path is not None:
                        info["markdown_file"] = md_path.name
                        info["markdown_path"] = str(uploads_dir / md_path.name)
                        info["markdown_virtual_path"] = upload_virtual_path(md_path.name)
                        info["markdown_artifact_url"] = upload_artifact_url(thread_id, md_path.name)

                uploaded_files.append(info)
        finally:
            if conversion_pool is not None:
                conversion_pool.shutdown(wait=True)

        return {
            "success": True,
            "files": uploaded_files,
            "message": f"Successfully uploaded {len(uploaded_files)} file(s)",
        }

    def list_uploads(self, thread_id: str) -> dict:
        """List files in a thread's uploads directory.

        Args:
            thread_id: Thread ID.

        Returns:
            Dict with "files" and "count" keys, matching the Gateway API
            ``list_uploaded_files`` response.
        """
        uploads_dir = get_uploads_dir(thread_id)
        result = list_files_in_dir(uploads_dir)
        return enrich_file_listing(result, thread_id)

    def delete_upload(self, thread_id: str, filename: str) -> dict:
        """Delete a file from a thread's uploads directory.

        Args:
            thread_id: Thread ID.
            filename: Filename to delete.

        Returns:
            Dict with success and message, matching the Gateway API
            ``delete_uploaded_file`` response.

        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If path traversal is detected.
        """
        from optclaw.utils.file_conversion import CONVERTIBLE_EXTENSIONS

        uploads_dir = get_uploads_dir(thread_id)
        return delete_file_safe(uploads_dir, filename, convertible_extensions=CONVERTIBLE_EXTENSIONS)

    # ------------------------------------------------------------------
    # Public API — artifacts
    # ------------------------------------------------------------------

    def get_artifact(self, thread_id: str, path: str) -> tuple[bytes, str]:
        """Read an artifact file produced by the agent.

        Args:
            thread_id: Thread ID.
            path: Virtual path (e.g. "mnt/user-data/outputs/file.txt").

        Returns:
            Tuple of (file_bytes, mime_type).

        Raises:
            FileNotFoundError: If the artifact does not exist.
            ValueError: If the path is invalid.
        """
        try:
            actual = get_paths().resolve_virtual_path(thread_id, path)
        except ValueError as exc:
            if "traversal" in str(exc):
                from optclaw.uploads.manager import PathTraversalError

                raise PathTraversalError("Path traversal detected") from exc
            raise
        if not actual.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        if not actual.is_file():
            raise ValueError(f"Path is not a file: {path}")

        mime_type, _ = mimetypes.guess_type(actual)
        return actual.read_bytes(), mime_type or "application/octet-stream"

    # ------------------------------------------------------------------
    # Public API — conversation
    # ------------------------------------------------------------------

    async def stream(
        self,
        message: str,
        *,
        thread_id: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream a conversation turn, yielding events incrementally.
        Args:
            message: User message text.
            thread_id: Thread ID for conversation context. Auto-generated if None.
            **kwargs: Override client defaults (model_name, thinking_enabled,
                plan_mode, subagent_enabled, recursion_limit).

        Yields:
            StreamEvent with one of:
            - type="values"          data={"title": str|None, "messages": [...], "artifacts": [...]}
            - type="custom"          data={...}
            - type="messages-tuple"  data={"type": "ai", "content": <delta>, "id": str}
            - type="messages-tuple"  data={"type": "ai", "content": <delta>, "id": str, "usage_metadata": {...}}
            - type="messages-tuple"  data={"type": "ai", "content": "", "id": str, "tool_calls": [...]}
            - type="messages-tuple"  data={"type": "tool", "content": str, "name": str, "tool_call_id": str, "id": str}
            - type="end"             data={"usage": {"input_tokens": int, "output_tokens": int, "total_tokens": int}}
        """
        if thread_id is None:
            thread_id = str(uuid.uuid4())

        config = self._get_runnable_config(thread_id, **kwargs)
        await self._ensure_agent(config)

        files = kwargs.pop("files", None)
        state: dict[str, Any] = {"messages": [HumanMessage(content=message)]}
        if files:
            state["messages"][0].additional_kwargs = {"files": files}
        if self._agent_name:
            state["agent_name"] = self._agent_name
        context = {"thread_id": thread_id}
        if self._agent_name:
            context["agent_name"] = self._agent_name

        seen_ids: set[str] = set()
        # Cross-mode handoff: ids already streamed via LangGraph ``messages``
        # mode so the ``values`` path skips re-synthesis of the same message.
        streamed_ids: set[str] = set()
        # The same message id carries identical cumulative ``usage_metadata``
        # in both the final ``messages`` chunk and the values snapshot —
        # count it only on whichever arrives first.
        counted_usage_ids: set[str] = set()
        cumulative_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        def _account_usage(msg_id: str | None, usage: Any) -> dict | None:
            """Add *usage* to cumulative totals if this id has not been counted.

            ``usage`` is a ``langchain_core.messages.UsageMetadata`` TypedDict
            or ``None``; typed as ``Any`` because TypedDicts are not
            structurally assignable to plain ``dict`` under strict type
            checking.  Returns the normalized usage dict (for attaching
            to an event) when we accepted it, otherwise ``None``.
            """
            if not usage:
                return None
            if msg_id and msg_id in counted_usage_ids:
                return None
            if msg_id:
                counted_usage_ids.add(msg_id)
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            total_tokens = usage.get("total_tokens", 0) or 0
            cumulative_usage["input_tokens"] += input_tokens
            cumulative_usage["output_tokens"] += output_tokens
            cumulative_usage["total_tokens"] += total_tokens
            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }

        async for item in self._agent.astream(
            state,
            config=config,
            context=context,
            stream_mode=["messages"],  # ["values", "messages", "custom"],
        ):
            if isinstance(item, tuple) and len(item) == 2:
                mode, chunk = item
                mode = str(mode)
            else:
                mode, chunk = "values", item

            if mode == "custom":
                yield StreamEvent(type="custom", data=chunk)
                continue

            if mode == "messages":
                # LangGraph ``messages`` mode emits ``(message_chunk, metadata)``.
                if isinstance(chunk, tuple) and len(chunk) == 2:
                    msg_chunk, _metadata = chunk
                else:
                    msg_chunk = chunk

                msg_id = getattr(msg_chunk, "id", None)

                # reasoning content can also show... additional_kwargs['reasoning_content']
                if isinstance(msg_chunk, AIMessage):

                    reasoning_text = self._extract_text(msg_chunk.additional_kwargs.get("reasoning_content", ''))
                    text = self._extract_text(msg_chunk.content)
                    counted_usage = _account_usage(msg_id, msg_chunk.usage_metadata)

                    if reasoning_text:
                        if msg_id:
                            streamed_ids.add(msg_id)
                        yield self._ai_reasoning_text_event(msg_id, reasoning_text, counted_usage)

                    if text:
                        if msg_id:
                            streamed_ids.add(msg_id)
                        yield self._ai_text_event(msg_id, text, counted_usage)

                    if msg_chunk.tool_calls:
                        if msg_id:
                            streamed_ids.add(msg_id)
                        # print("********************tool_calls***************")
                        # print(msg_chunk)
                        yield self._ai_tool_calls_event(msg_id, msg_chunk.tool_calls)

                elif isinstance(msg_chunk, ToolMessage):
                    if msg_id:
                        streamed_ids.add(msg_id)
                    # print("********************tool_message***************")
                    # print(msg_chunk)
                    yield self._tool_message_event(msg_chunk)
                continue

            # mode == "values"
            messages = chunk.get("messages", [])

            for msg in messages:
                msg_id = getattr(msg, "id", None)
                if msg_id and msg_id in seen_ids:
                    continue
                if msg_id:
                    seen_ids.add(msg_id)

                # Already streamed via ``messages`` mode; only (defensively)
                # capture usage here and skip re-synthesizing the event.
                if msg_id and msg_id in streamed_ids:
                    if isinstance(msg, AIMessage):
                        _account_usage(msg_id, getattr(msg, "usage_metadata", None))
                    continue

                if isinstance(msg, AIMessage):
                    counted_usage = _account_usage(msg_id, msg.usage_metadata)

                    if msg.tool_calls:
                        yield self._ai_tool_calls_event(msg_id, msg.tool_calls)

                    text = self._extract_text(msg.content)
                    if text:
                        yield self._ai_text_event(msg_id, text, counted_usage)

                elif isinstance(msg, ToolMessage):
                    yield self._tool_message_event(msg)

            # Emit a values event for each state snapshot
            yield StreamEvent(
                type="values",
                data={
                    "title": chunk.get("title"),
                    "messages": [self._serialize_message(m) for m in messages],
                    "artifacts": chunk.get("artifacts", []),
                },
            )

        yield StreamEvent(type="end", data={"usage": cumulative_usage})

    async def chat_stream(self, message: str, *, thread_id: str | None = None, **kwargs) -> AsyncGenerator[str, None]:
        """Streaming version
           Send messages and yield AI response content word by word for real-time frontend streaming display.
        """
        
        async for event in self.stream(message, thread_id=thread_id, **kwargs):

            # ai response without reason content 有些是tool答复内容
            if event.type == "messages-tuple" and event.data.get("type") == "ai" and event.data.get("subtype") == "text":
                delta_content = event.data.get("content", "")
                # print("text: ", delta_content)
                if delta_content:
                    yield delta_content, "text"

            # ai response with reason content
            if event.type == "messages-tuple" and event.data.get("type") == "ai" and event.data.get("subtype") == "reasoning_text":
                delta_content = event.data.get("content", "")
                # print("reasoning_text: ", delta_content)
                if delta_content:
                    yield delta_content, "reasoning_text"

            # tool calls
            if event.type == "messages-tuple" and event.data.get("type") == "ai" and event.data.get("subtype") == "tool_calls":
                # print(event)
                delta_content = event.data.get("tool_calls", "")
                tool_names = [item.get("name") for item in delta_content if item.get("name", "") != ""]
                if len(tool_names) >= 1:
                    yield "calling tools:" + "|".join(tool_names), "tool_calls"

            # # tool message
            # if event.type == "messages-tuple" and event.data.get("type") == "tool" and event.data.get("subtype") == "tool_message":
            #     delta_content = event.data.get("content", "")
            #     print("tool_message: ", delta_content)
            #     if delta_content:
            #         yield delta_content, "tool_message"

    async def chat(self, message: str, *, thread_id: str | None = None, **kwargs) -> str:
        """Send a message and return the final text response.

        Convenience wrapper around :meth:`stream` that accumulates delta
        ``messages-tuple`` events per ``id`` and returns the text of the
        **last** AI message to complete.  Intermediate AI messages (e.g.
        planner drafts) are discarded — only the final id's accumulated
        text is returned.  Use :meth:`stream` directly if you need every
        delta as it arrives.

        Args:
            message: User message text.
            thread_id: Thread ID for conversation context. Auto-generated if None.
            **kwargs: Override client defaults (same as stream()).

        Returns:
            The accumulated text of the last AI message, or empty string
            if no AI text was produced.
        """
        # Per-id delta lists joined once at the end — avoids the O(n²) cost
        # of repeated ``str + str`` on a growing buffer for long responses.
        chunks: dict[str, list[str]] = {}
        last_id: str = ""
        async for event in self.stream(message, thread_id=thread_id, **kwargs):
            # ai response without reason content
            if event.type == "messages-tuple" and event.data.get("type") == "ai" and event.data.get("reason", False) == False:
                msg_id = event.data.get("id") or ""
                delta = event.data.get("content", "")
                if delta:
                    chunks.setdefault(msg_id, []).append(delta)
                    last_id = msg_id
        return "".join(chunks.get(last_id, ()))