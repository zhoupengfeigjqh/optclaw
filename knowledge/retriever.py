"""Recall: keyword search (MongoDB) + vector similarity (FAISS) + rerank."""

import asyncio
import re
import httpx
from .mongo import get_db, COLLECTION_CHUNKS
from .faiss_store import KBFaissManager
from .embedding import ollama_embed, l2_normalize


async def keyword_search(query: str, top_k: int = 5, agent_name: str = "default") -> list[dict]:
    """Keyword search via MongoDB text index + regex fallback."""
    try:
        db = await get_db()
    except Exception:
        return []

    coll = db[COLLECTION_CHUNKS]
    afilter = {"agent_name": agent_name}

    try:
        cursor = coll.find({**afilter, "$text": {"$search": query}}, {"score": {"$meta": "textScore"}})
        cursor = cursor.sort([("score", {"$meta": "textScore"})]).limit(top_k)
        results = await cursor.to_list(length=top_k)
    except Exception:
        results = []

    if not results:
        try:
            escaped = re.escape(query)
            regex = {"$regex": escaped, "$options": "i"}
            cursor = coll.find({**afilter, "content": regex}).limit(top_k)
            results = await cursor.to_list(length=top_k)
        except Exception:
            results = []

    return [
        {
            "chunk_id": r["chunk_id"],
            "file_name": r["file_name"],
            "content": r["content"],
            "score": r.get("score", 0.5),
            "source_type": "keyword",
            "metadata": r.get("metadata", {}),
        }
        for r in results
    ]


async def vector_search(query: str, top_k: int = 5, threshold: float = 0.5, agent_name: str = "default") -> list[dict]:
    """Vector similarity search via FAISS, filtered by agent."""
    store = KBFaissManager.get_store()
    if not store.is_initialized:
        return []

    try:
        emb = await ollama_embed([query])
    except Exception:
        return []

    query_vec = l2_normalize(emb)[0]
    results = store.search(query_vec, max(top_k * 3, 30), threshold)

    try:
        db = await get_db()
    except Exception:
        return []

    coll = db[COLLECTION_CHUNKS]

    output = []
    for chunk_id, score in results:
        try:
            chunk = await coll.find_one({"chunk_id": chunk_id, "agent_name": agent_name})
        except Exception:
            continue
        if chunk:
            output.append({
                "chunk_id": chunk_id,
                "file_name": chunk["file_name"],
                "content": chunk["content"],
                "score": score,
                "source_type": "vector",
                "metadata": chunk.get("metadata", {}),
            })
        if len(output) >= top_k:
            break
    return output


async def hybrid_search(query: str, top_k: int = 5, threshold: float = 0.5,
                        use_rerank: bool = False, agent_name: str = "default") -> list[dict]:
    """Combine keyword and vector search with optional rerank."""
    kw_top = max(top_k * 2, 10)
    vec_top = max(top_k * 2, 10)

    kw_results, vec_results = await asyncio.gather(
        keyword_search(query, kw_top, agent_name=agent_name),
        vector_search(query, vec_top, threshold, agent_name=agent_name),
    )

    merged: dict[str, dict] = {}
    for r in kw_results:
        merged[r["chunk_id"]] = r
    for r in vec_results:
        cid = r["chunk_id"]
        if cid in merged:
            merged[cid]["score"] = max(merged[cid]["score"], r["score"])
            merged[cid]["source_type"] = "hybrid"
        else:
            merged[cid] = r

    results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)

    if use_rerank and len(results) > 1:
        contents = [r["content"] for r in results]
        try:
            ranked = await bge_rerank(query, contents, top_k=top_k)
        except Exception:
            ranked = None

        if ranked:
            reranked = []
            for idx, score in ranked:
                if idx < len(results) and score >= threshold:
                    results[idx]["score"] = score
                    results[idx]["source_type"] = "reranked"
                    reranked.append(results[idx])
            if reranked:
                return reranked[:top_k]

    return [r for r in results[:top_k] if r["score"] >= threshold]


async def bge_rerank(query: str, documents: list[str], model: str | None = None, top_k: int = 5) -> list[tuple[int, float]]:
    """Rerank via dedicated reranker service (Infinity) — native cross-encoder scoring."""
    if not documents:
        return []
    if model is None:
        from .config import get_rerank_model
        model = get_rerank_model()

    from .config import get_rerank_api_url
    api_url = get_rerank_api_url()

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(api_url, json={
            "model": model,
            "query": query,
            "documents": [doc[:1000] for doc in documents],
            "top_n": top_k,
        })
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("results", data.get("data", [])):
        idx = item.get("index", 0)
        score = item.get("relevance_score", item.get("score", 0.0))
        results.append((int(idx), max(0.0, min(1.0, float(score)))))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]
