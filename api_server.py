"""FastAPI server that wraps OptClawClient for frontend interaction."""

import warnings
warnings.filterwarnings("ignore", message=".*PydanticSerializationUnexpectedValue.*context.*")

import asyncio
import json
import os
import traceback
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from pydantic import BaseModel, field_validator

from optclaw.client import OptClawClient
from optclaw.agents import refresh_skills_system_prompt_cache_async
from knowledge.router import router as knowledge_router
from knowledge.mongo import close_db as close_mongo_db, ensure_indexes as ensure_mongo_indexes

from optclaw.log import setup_logging

logger = setup_logging(__name__)

client: OptClawClient | None = None
_active_stop_events: dict[str, asyncio.Event] = {}


def _sanitize(obj):
    try:
        return json.loads(json.dumps(obj, default=str, ensure_ascii=False))
    except (TypeError, ValueError):
        return str(obj)


def _silent_event_loop_closed_handler(loop, context):
    logger.warning("====进入异常处理器,exc=%s", context.get("exception"))
    logger.warning("====进入异常处理器,message=%s", context.get("message"))
    exc = context.get("exception")
    if exc is not None:
        logger.warning("====异常堆栈:\n%s", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    if exc and isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
        return
    loop.default_exception_handler(context)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_silent_event_loop_closed_handler)
    except RuntimeError:
        pass
    client = OptClawClient()
    await client._ensure_checkpointer()
    await ensure_mongo_indexes()
    yield
    logger.warning("Shutting down API server...")
    await close_mongo_db()
    client = None


app = FastAPI(title="OptClaw API", lifespan=lifespan)
app.include_router(knowledge_router)

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:80,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    model_name: str | None = None
    thinking_enabled: bool | None = None
    subagent_enabled: bool | None = None
    plan_mode: bool | None = None
    agent_name: str | None = None
    files: list[dict] | None = None


class MemoryFactRequest(BaseModel):
    content: str
    category: str = "context"
    confidence: float = 0.5


class MemoryFactUpdateRequest(BaseModel):
    content: str | None = None
    category: str | None = None
    confidence: float | None = None


class MemoryConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    storage_path: str | None = None
    debounce_seconds: int | None = None
    max_facts: int | None = None
    fact_confidence_threshold: float | None = None
    injection_enabled: bool | None = None
    max_injection_tokens: int | None = None
    model_name: str | None = None


class CreateAgentRequest(BaseModel):
    agent_name: str
    description: str = ""
    soul: str = ""

    @field_validator("agent_name")
    @classmethod
    def validate_agent_name(cls, v: str) -> str:
        import re
        if not re.match(r"^[A-Za-z0-9-]+$", v):
            raise ValueError("agent_name must match pattern ^[A-Za-z0-9-]+$ (letters, digits, hyphens only)")
        return v


@app.get("/api/models")
async def list_models():
    try:
        return _sanitize(client.list_models())
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"获取模型列表失败: {e}")


@app.get("/api/skills")
async def list_skills(enabled_only: bool = False):
    try:
        return _sanitize(client.list_skills(enabled_only=enabled_only))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取技能列表失败: {e}")


@app.patch("/api/skills/{name}")
async def update_skill(name: str, enabled: bool = True):
    try:
        result = _sanitize(client.update_skill(name, enabled=enabled))
        await refresh_skills_system_prompt_cache_async()
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新技能配置失败: {e}")


@app.get("/api/tools")
async def list_tools(enabled_only: bool = False):
    try:
        return _sanitize(client.list_tools(enabled_only=enabled_only))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {e}")


@app.patch("/api/tools/{name}")
async def update_tool(name: str, enabled: bool):
    try:
        return _sanitize(client.update_tool(name, enabled))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新工具配置失败: {e}")


@app.post("/api/skills/install")
async def install_skill(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".skill"):
        raise HTTPException(status_code=400, detail="仅支持 .skill 后缀的文件")
    tmpdir = tempfile.mkdtemp()
    dest = Path(tmpdir) / file.filename
    try:
        with open(dest, "wb") as out:
            content = await file.read()
            out.write(content)
        result = client.install_skill(str(dest))
        if not result.get("success", False):
            raise HTTPException(status_code=422, detail=result.get("message", "安装失败"))
        return result
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"安装技能失败: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.get("/api/agents")
async def list_agents():
    try:
        return _sanitize(client.list_custom_agents_desc())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取Agent列表失败: {e}")


@app.get("/api/agents/{agent_name}/soul")
async def get_agent_soul(agent_name: str):
    try:
        soul = client.get_custom_agent_soul(agent_name)
        if soul is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        return {"agent_name": agent_name, "soul": soul}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取Agent Soul失败: {e}")


@app.post("/api/agents")
async def create_agent(req: CreateAgentRequest):
    try:
        existing = {a["agent_name"] for a in client.list_custom_agents_desc()}
        if req.agent_name in existing:
            raise HTTPException(status_code=409, detail=f"Agent '{req.agent_name}' already exists")
        client.create_custom_agent(agent_name=req.agent_name, description=req.description, soul=req.soul)
        return {"success": True, "agent_name": req.agent_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建Agent失败: {e}")


@app.get("/api/threads")
async def list_threads(limit: int = Query(default=10, ge=1, le=20),
                       agent_name: str | None = Query(default=None)):
    try:
        data = await client.list_threads(limit=limit, agent_name=agent_name)
        return _sanitize(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {e}")


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str):
    try:
        data = await client.get_thread(thread_id)
        return _sanitize(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话详情失败: {e}")


@app.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str):
    try:
        return await client.delete_thread(thread_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除会话失败: {e}")


@app.get("/api/threads/{thread_id}/artifacts/{file_path:path}")
async def serve_artifact(thread_id: str, file_path: str):
    """Serve an uploaded file artifact for download/viewing."""
    from urllib.parse import quote

    try:
        file_bytes, mime_type = client.get_artifact(thread_id, file_path)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    filename = Path(file_path).name
    encoded_filename = quote(filename, safe="")
    return Response(
        content=file_bytes,
        media_type=mime_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"},
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    kwargs = {}
    if req.model_name is not None:
        kwargs["model_name"] = req.model_name
    if req.thinking_enabled is not None:
        kwargs["thinking_enabled"] = req.thinking_enabled
    if req.subagent_enabled is not None:
        kwargs["subagent_enabled"] = req.subagent_enabled
    if req.plan_mode is not None:
        kwargs["plan_mode"] = req.plan_mode
    kwargs["agent_name"] = req.agent_name if req.agent_name is not None and req.agent_name != "" else None
    if req.files:
        kwargs["files"] = req.files

    logger.warning(f"agent settings:{kwargs}")

    thread_id = req.thread_id or str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()
    _active_stop_events[thread_id] = stop_event

    async def run_stream():
        try:
            async for delta, delta_type in client.chat_stream(req.message, thread_id=thread_id, **kwargs):
                await queue.put(("delta", delta, delta_type))
            await queue.put(("done",))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await queue.put(("error", str(e)))

    producer_task = asyncio.create_task(run_stream())

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                getter = asyncio.create_task(queue.get())
                stopper = asyncio.create_task(stop_event.wait())
                done, pending = await asyncio.wait(
                    [getter, stopper], return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()

                if stopper in done:
                    producer_task.cancel()
                    payload = {"type": "stopped", "data": {"message": "对话已停止"}}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                item = getter.result()
                kind = item[0]
                if kind == "done":
                    yield "data: [DONE]\n\n"
                    return
                if kind == "error":
                    err_payload = {"type": "error", "data": {"message": item[1]}}
                    yield f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                if kind == "delta":
                    _, delta, delta_type = item
                    payload = {"type": "delta", "data": {"content": delta, "delta_type": delta_type}}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            _active_stop_events.pop(thread_id, None)
            if not producer_task.done():
                producer_task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class StopRequest(BaseModel):
    thread_id: str


@app.post("/api/chat/stop")
async def stop_chat(req: StopRequest):
    """Signal the running chat stream for a thread to stop gracefully."""
    event = _active_stop_events.get(req.thread_id)
    if event is not None:
        event.set()
        return {"success": True, "thread_id": req.thread_id, "message": "Stop signal sent"}
    return {"success": False, "thread_id": req.thread_id, "message": "No active stream for this thread"}


@app.post("/api/upload/{thread_id}")
async def upload_files(thread_id: str, files: list[UploadFile] = File(...)):
    ALLOWED_EXTS = {".pdf", ".csv", ".txt", ".png", ".jpg", ".jpeg"}
    tmpdir = tempfile.mkdtemp()
    saved_paths = []
    try:
        for f in files:
            ext = Path(f.filename).suffix.lower()
            if ext not in ALLOWED_EXTS:
                raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}，仅支持 pdf, csv, txt, png, jpg, jpeg")
            dest = Path(tmpdir) / f.filename
            with open(dest, "wb") as out:
                content = await f.read()
                out.write(content)
            saved_paths.append(str(dest))
        result = client.upload_files(thread_id, saved_paths)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传文件失败: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.get("/api/uploads/{thread_id}")
async def list_uploads(thread_id: str):
    try:
        return client.list_uploads(thread_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取上传列表失败: {e}")


@app.delete("/api/uploads/{thread_id}/{filename}")
async def delete_upload(thread_id: str, filename: str):
    try:
        return client.delete_upload(thread_id, filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除上传文件失败: {e}")


@app.get("/api/memory")
async def get_memory(agent_name: str | None = Query(default=None)):
    try:
        return _sanitize(client.get_memory(agent_name=agent_name))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取记忆数据失败: {e}")


@app.get("/api/memory/config")
async def get_memory_config(agent_name: str | None = Query(default=None)):
    try:
        return _sanitize(client.get_memory_config())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取记忆配置失败: {e}")


@app.patch("/api/memory/update_config")
async def update_memory_config(req: MemoryConfigUpdateRequest):
    try:
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        if not updates:
            return _sanitize(client.get_memory_config())
        return _sanitize(client.update_memory_config(updates))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新记忆配置失败: {e}")


@app.post("/api/memory/reload")
async def reload_memory(agent_name: str | None = Query(default=None)):
    try:
        return _sanitize(client.reload_memory(agent_name=agent_name))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重载记忆失败: {e}")


@app.post("/api/memory/facts")
async def create_memory_fact(req: MemoryFactRequest, agent_name: str | None = Query(default=None)):
    try:
        return client.create_memory_fact(content=req.content, category=req.category, confidence=req.confidence, agent_name=agent_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建记忆事实失败: {e}")


@app.delete("/api/memory/facts/{fact_id}")
async def delete_memory_fact(fact_id: str, agent_name: str | None = Query(default=None)):
    try:
        return client.delete_memory_fact(fact_id=fact_id, agent_name=agent_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除记忆事实失败: {e}")


@app.patch("/api/memory/facts/{fact_id}")
async def update_memory_fact(fact_id: str, req: MemoryFactUpdateRequest, agent_name: str | None = Query(default=None)):
    try:
        return client.update_memory_fact(
            fact_id=fact_id, content=req.content, category=req.category, confidence=req.confidence, agent_name=agent_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新记忆事实失败: {e}")


@app.post("/api/memory/clear")
async def clear_memory(agent_name: str | None = Query(default=None)):
    try:
        client.clear_memory(agent_name=agent_name)
        return _sanitize(client.reload_memory(agent_name=agent_name))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空记忆失败: {e}")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/reset-agent")
async def reset_agent():
    try:
        client.reset_agent()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重置Agent失败: {e}")


class McpServerUpdateRequest(BaseModel):
    enabled: bool | None = None
    type: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    description: str | None = None


class McpServerCreateRequest(BaseModel):
    type: str = "stdio"
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    description: str = ""
    enabled: bool = True


@app.get("/api/mcp")
async def get_mcp_config():
    try:
        return _sanitize(client.get_mcp_config())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取MCP配置失败: {e}")


@app.patch("/api/mcp/{server_name}")
async def update_mcp_server(server_name: str, req: McpServerUpdateRequest):
    try:
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        if not updates:
            return _sanitize(client.get_mcp_config())
        return _sanitize(client.update_mcp_server(server_name, updates))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新MCP服务器失败: {e}")


@app.post("/api/mcp")
async def create_mcp_server(req: McpServerCreateRequest, server_name: str = Query(...)):
    try:
        config = {k: v for k, v in req.model_dump().items() if v is not None}
        return _sanitize(client.create_mcp_server(server_name, config))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建MCP服务器失败: {e}")


@app.delete("/api/mcp/{server_name}")
async def delete_mcp_server(server_name: str):
    try:
        return _sanitize(client.delete_mcp_server(server_name))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除MCP服务器失败: {e}")


class McpRenameRequest(BaseModel):
    new_name: str


@app.put("/api/mcp/{server_name}/rename")
async def rename_mcp_server(server_name: str, req: McpRenameRequest):
    try:
        return _sanitize(client.rename_mcp_server(server_name, req.new_name))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重命名MCP服务器失败: {e}")
