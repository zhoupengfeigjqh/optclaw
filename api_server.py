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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    client = OptClawClient()
    await client._ensure_checkpointer()
    yield
    if client:
        await client.close()


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


@app.get("/api/models")
async def list_models():
    return client.list_models()


@app.get("/api/skills")
async def list_skills(enabled_only: bool = False):
    return client.list_skills(enabled_only=enabled_only)


@app.get("/api/threads")
async def list_threads(limit: int = Query(default=20, ge=1, le=100)):
    return await client.list_threads(limit=limit)


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str):
    return await client.get_thread(thread_id)


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
        async for event in client.stream(req.message, thread_id=req.thread_id, **kwargs):
            payload = {"type": event.type, "data": event.data}
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
    return client.get_memory()


@app.post("/api/memory/clear")
async def clear_memory():
    client.clear_memory()
    client.reset_agent()
    return {"success": True}


@app.get("/api/health")
async def health():
    return {"status": "ok"}
