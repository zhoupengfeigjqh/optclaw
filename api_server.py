"""FastAPI server that wraps OptClawClient for frontend interaction."""

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from optclaw.client import OptClawClient

client: OptClawClient | None = None


def _sanitize(obj):
    try:
        return json.loads(json.dumps(obj, default=str, ensure_ascii=False))
    except (TypeError, ValueError):
        return str(obj)


def _silent_event_loop_closed_handler(loop, context):
    msg = context.get("message", "")
    exc = context.get("exception")
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
    yield
    client = None


app = FastAPI(title="OptClaw API", lifespan=lifespan)

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:80").split(",")
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


@app.get("/api/models")
async def list_models():
    return _sanitize(client.list_models())


@app.get("/api/skills")
async def list_skills(enabled_only: bool = False):
    return _sanitize(client.list_skills(enabled_only=enabled_only))


@app.get("/api/threads")
async def list_threads(limit: int = Query(default=20, ge=1, le=100)):
    data = await client.list_threads(limit=limit)
    return _sanitize(data)


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str):
    data = await client.get_thread(thread_id)
    return _sanitize(data)


@app.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str):
    return await client.delete_thread(thread_id)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    kwargs = {}
    if req.model_name is not None:
        kwargs["model_name"] = req.model_name
    if req.thinking_enabled is not None:
        kwargs["thinking_enabled"] = req.thinking_enabled
    if req.subagent_enabled is not None:
        kwargs["subagent_enabled"] = req.subagent_enabled

    async def event_generator() -> AsyncGenerator[str, None]:
        async for delta in client.chat_stream(req.message, thread_id=req.thread_id, **kwargs):
            payload = {"type": "delta", "data": {"content": delta}}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/upload/{thread_id}")
async def upload_files(thread_id: str, files: list[UploadFile] = File(...)):
    tmpdir = tempfile.mkdtemp()
    saved_paths = []
    try:
        for f in files:
            dest = Path(tmpdir) / f.filename
            with open(dest, "wb") as out:
                content = await f.read()
                out.write(content)
            saved_paths.append(str(dest))
        result = client.upload_files(thread_id, saved_paths)
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.get("/api/uploads/{thread_id}")
async def list_uploads(thread_id: str):
    return client.list_uploads(thread_id)


@app.delete("/api/uploads/{thread_id}/{filename}")
async def delete_upload(thread_id: str, filename: str):
    return client.delete_upload(thread_id, filename)


@app.get("/api/memory")
async def get_memory():
    return _sanitize(client.get_memory())


@app.get("/api/memory/status")
async def get_memory_status():
    return _sanitize(client.get_memory_status())


@app.patch("/api/memory/config")
async def update_memory_config(req: MemoryConfigUpdateRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        return _sanitize(client.get_memory_config())
    return _sanitize(client.update_memory_config(updates))


@app.post("/api/memory/reload")
async def reload_memory():
    return _sanitize(client.reload_memory())


@app.post("/api/memory/facts")
async def create_memory_fact(req: MemoryFactRequest):
    return client.create_memory_fact(content=req.content, category=req.category, confidence=req.confidence)


@app.delete("/api/memory/facts/{fact_id}")
async def delete_memory_fact(fact_id: str):
    return client.delete_memory_fact(fact_id=fact_id)


@app.patch("/api/memory/facts/{fact_id}")
async def update_memory_fact(fact_id: str, req: MemoryFactUpdateRequest):
    return client.update_memory_fact(
        fact_id=fact_id, content=req.content, category=req.category, confidence=req.confidence
    )


@app.post("/api/memory/clear")
async def clear_memory():
    client.clear_memory()
    return _sanitize(client.reload_memory())


@app.get("/api/health")
async def health():
    return {"status": "ok"}
