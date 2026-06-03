"""FastAPI router for knowledge base endpoints."""

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Form

from .models import (
    ChunkSettings,
    KnowledgeConfig,
    RecallRequest,
    UploadResponse,
    DeleteResponse,
    StatsResponse,
)
from .pipeline import process_document, delete_document, get_document_list, get_chunks, get_stats
from .retriever import keyword_search, vector_search, hybrid_search
from .config import get_chunk_size, get_overlap_size, get_embed_model, \
    get_rerank_model, get_vector_top_k, get_score_threshold, CONFIG_PATH
from .faiss_store import KBFaissManager

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

DEFAULT_AGENT = "default"


def _kb_config_response() -> KnowledgeConfig:
    return KnowledgeConfig(
        chunk_size=get_chunk_size(),
        overlap_size=get_overlap_size(),
        embed_model=get_embed_model(),
        rerank_model=get_rerank_model(),
        vector_top_k=get_vector_top_k(),
        score_threshold=get_score_threshold(),
    )


@router.get("/config", response_model=KnowledgeConfig)
async def get_config():
    return _kb_config_response()


@router.put("/config", response_model=KnowledgeConfig)
async def update_config(settings: ChunkSettings, embed_model: str | None = None, rerank_model: str | None = None):
    import yaml
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}
    kb = data.setdefault("knowledge", {})
    if settings.chunk_size:
        kb["chunk_size"] = settings.chunk_size
    if settings.overlap_size:
        kb["overlap_size"] = settings.overlap_size
    if embed_model and embed_model != kb.get("embed_model"):
        kb["embed_model"] = embed_model
        KBFaissManager.reset_store()
    elif embed_model:
        kb["embed_model"] = embed_model
    if rerank_model:
        kb["rerank_model"] = rerank_model
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
    return KnowledgeConfig(
        chunk_size=kb.get("chunk_size", get_chunk_size()),
        overlap_size=kb.get("overlap_size", get_overlap_size()),
        embed_model=kb.get("embed_model", get_embed_model()),
        rerank_model=kb.get("rerank_model", get_rerank_model()),
        vector_top_k=kb.get("vector_top_k", get_vector_top_k()),
        score_threshold=kb.get("score_threshold", get_score_threshold()),
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    agent_name: str = Form(DEFAULT_AGENT),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".csv", ".md", ".docx", ".txt"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Supported: .pdf, .csv, .md, .docx, .txt")

    MAX_SIZE = 1 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        size_mb = len(content) / 1024 / 1024
        raise HTTPException(status_code=413, detail=f"文件大小超过限制（最大 1MB），当前文件: {size_mb:.1f}MB")

    tmpdir = tempfile.mkdtemp()
    dest = Path(tmpdir) / file.filename
    try:
        with open(dest, "wb") as out:
            out.write(content)
        result = await process_document(str(dest), file.filename, agent_name=agent_name)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@router.get("/documents")
async def list_documents(agent_name: str = Query(DEFAULT_AGENT)):
    try:
        docs = await get_document_list(agent_name=agent_name)
        return {"files": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {e}")


@router.delete("/documents/{file_name}", response_model=DeleteResponse)
async def remove_document(file_name: str, agent_name: str = Query(DEFAULT_AGENT)):
    try:
        result = await delete_document(file_name, agent_name=agent_name)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}")


@router.get("/chunks/{file_name}")
async def list_chunks(file_name: str, agent_name: str = Query(DEFAULT_AGENT)):
    try:
        chunks = await get_chunks(file_name, agent_name=agent_name)
        return {"file_name": file_name, "chunks": chunks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chunks: {e}")


@router.post("/recall")
async def recall(req: RecallRequest, agent_name: str = Query(DEFAULT_AGENT)):
    try:
        if req.search_type == "keyword":
            results = await keyword_search(req.query, req.top_k, agent_name=agent_name)
        elif req.search_type == "vector":
            results = await vector_search(req.query, req.top_k, req.score_threshold, agent_name=agent_name)
        else:
            results = await hybrid_search(req.query, req.top_k, req.score_threshold, req.use_rerank, agent_name=agent_name)
        return {"query": req.query, "search_type": req.search_type, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recall failed: {e}")


@router.get("/stats", response_model=StatsResponse)
async def knowledge_stats(agent_name: str = Query(DEFAULT_AGENT)):
    try:
        stats = await get_stats(agent_name=agent_name)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {e}")


@router.get("/test-embed")
async def test_embed(model: str = Query(...)):
    from .embedding import ollama_embed
    try:
        await ollama_embed(["connectivity test"], model=model)
        return {"ok": True, "model": model}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"嵌入模型不可用: {e}")


@router.get("/test-rerank")
async def test_rerank(model: str = Query(...)):
    from .retriever import bge_rerank
    try:
        await bge_rerank("connectivity test", ["connectivity test"], model=model, top_k=1)
        return {"ok": True, "model": model}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"重排模型不可用: {e}")
