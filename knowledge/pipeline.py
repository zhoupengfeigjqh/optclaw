"""Pipeline orchestration: upload -> parse -> chunk -> store -> embed."""

import json
import uuid
from datetime import datetime

from .parser import parse_document, detect_file_type
from .splitter import split_text
from .mongo import get_db, COLLECTION_CHUNKS
from .faiss_store import KBFaissManager
from .embedding import ollama_embed, l2_normalize
from .config import get_chunk_size, get_overlap_size


async def process_document(file_path: str, original_filename: str, agent_name: str = "default") -> dict:
    """Full pipeline: parse, chunk, store in MongoDB, vectorize to FAISS."""
    file_type = detect_file_type(original_filename)

    text, parse_metadata = await parse_document(file_path, file_type)
    if not text or not text.strip():
        raise ValueError(f"No text extracted from {original_filename}")

    chunk_size = get_chunk_size()
    overlap_size = get_overlap_size()
    chunk_texts = split_text(text, chunk_size, overlap_size)
    if not chunk_texts:
        raise ValueError(f"No chunks generated from {original_filename}")

    db = await get_db()
    coll = db[COLLECTION_CHUNKS]
    store = KBFaissManager.get_store()

    now = datetime.utcnow().isoformat()
    chunk_docs = []
    for idx, chunk_text in enumerate(chunk_texts):
        cid = str(uuid.uuid4())
        chunk_docs.append({
            "chunk_id": cid,
            "file_name": original_filename,
            "file_type": file_type,
            "chunk_index": idx,
            "content": chunk_text,
            "metadata": parse_metadata,
            "agent_name": agent_name,
            "created_at": now,
        })
    await coll.insert_many(chunk_docs)

    texts_for_embed = [c["content"] for c in chunk_docs]
    try:
        embeddings = await ollama_embed(texts_for_embed)
    except Exception:
        chunk_ids = [c["chunk_id"] for c in chunk_docs]
        await coll.delete_many({"chunk_id": {"$in": chunk_ids}})
        raise

    norms = l2_normalize(embeddings)
    chunk_ids = [c["chunk_id"] for c in chunk_docs]
    metadatas = [{"chunk_id": c["chunk_id"], "file_name": c["file_name"], "agent_name": agent_name} for c in chunk_docs]
    store.add(norms, metadatas, chunk_ids)

    KBFaissManager.save()

    return {
        "success": True,
        "file_name": original_filename,
        "file_type": file_type,
        "chunks_count": len(chunk_docs),
        "message": f"Successfully processed {len(chunk_docs)} chunks",
    }


async def delete_document(file_name: str, agent_name: str = "default") -> dict:
    """Delete a document from MongoDB and FAISS."""
    db = await get_db()
    coll = db[COLLECTION_CHUNKS]
    q = {"file_name": file_name, "agent_name": agent_name}
    chunks = await coll.find(q).to_list(length=None)
    if not chunks:
        raise FileNotFoundError(f"Document '{file_name}' not found for agent '{agent_name}'")

    chunk_ids = [c["chunk_id"] for c in chunks]
    removed = await coll.delete_many(q)
    store = KBFaissManager.get_store()
    if store.is_initialized:
        store.delete_by_ids(set(chunk_ids))
    KBFaissManager.save()

    return {
        "success": True,
        "file_name": file_name,
        "chunks_removed": removed.deleted_count,
        "message": f"Deleted {removed.deleted_count} chunks",
    }


async def get_document_list(agent_name: str = "default") -> list[dict]:
    """List all uploaded documents with stats for a specific agent."""
    db = await get_db()
    coll = db[COLLECTION_CHUNKS]
    pipeline = [
        {"$match": {"agent_name": agent_name}},
        {"$group": {
            "_id": {"file_name": "$file_name", "file_type": "$file_type"},
            "chunks_count": {"$sum": 1},
            "upload_time": {"$max": "$created_at"},
        }},
        {"$sort": {"upload_time": -1}},
    ]
    result = []
    async for doc in coll.aggregate(pipeline):
        result.append({
            "file_name": doc["_id"]["file_name"],
            "file_type": doc["_id"]["file_type"],
            "chunks_count": doc["chunks_count"],
            "upload_time": doc["upload_time"],
            "status": "completed",
        })
    return result


async def get_chunks(file_name: str, agent_name: str = "default") -> list[dict]:
    """Get all chunks for a specific document."""
    db = await get_db()
    coll = db[COLLECTION_CHUNKS]
    chunks = await coll.find(
        {"file_name": file_name, "agent_name": agent_name}
    ).sort("chunk_index", 1).to_list(length=None)
    return [
        {
            "chunk_id": c["chunk_id"],
            "file_name": c["file_name"],
            "chunk_index": c["chunk_index"],
            "content": c["content"],
            "title": c.get("title", ""),
            "keywords": c.get("keywords", []),
            "metadata": c.get("metadata", {}),
            "created_at": c.get("created_at", ""),
        }
        for c in chunks
    ]


async def smart_save_results(results: list[dict], file_name: str, file_type: str,
                            agent_name: str = "default") -> dict:
    """Save LLM-parsed structured results to MongoDB and FAISS."""
    if not results:
        raise ValueError("No results to save")

    db = await get_db()
    coll = db[COLLECTION_CHUNKS]
    store = KBFaissManager.get_store()

    now = datetime.utcnow().isoformat()
    chunk_docs = []
    for idx, item in enumerate(results):
        cid = str(uuid.uuid4())
        content = item.get("content", "") or item.get("text", "") or json.dumps(item, ensure_ascii=False)
        title = item.get("title", "") or item.get("name", "")
        keywords = item.get("keywords", [])
        chunk_docs.append({
            "chunk_id": cid,
            "file_name": file_name,
            "file_type": file_type,
            "chunk_index": idx,
            "content": content,
            "title": title,
            "keywords": keywords,
            "metadata": {"parser": "ollama_smart", "title": title, "keywords": keywords},
            "agent_name": agent_name,
            "created_at": now,
        })
    await coll.insert_many(chunk_docs)

    texts_for_embed = [c["content"] for c in chunk_docs]
    try:
        embeddings = await ollama_embed(texts_for_embed)
    except Exception:
        chunk_ids = [c["chunk_id"] for c in chunk_docs]
        await coll.delete_many({"chunk_id": {"$in": chunk_ids}})
        raise

    norms = l2_normalize(embeddings)
    chunk_ids = [c["chunk_id"] for c in chunk_docs]
    metadatas = [{"chunk_id": c["chunk_id"], "file_name": c["file_name"], "agent_name": agent_name,
                  "title": c["title"], "keywords": c["keywords"]} for c in chunk_docs]
    store.add(norms, metadatas, chunk_ids)
    KBFaissManager.save()

    return {
        "success": True,
        "file_name": file_name,
        "file_type": file_type,
        "chunks_count": len(chunk_docs),
        "message": f"Successfully saved {len(chunk_docs)} chunks",
    }


async def get_stats(agent_name: str = "default") -> dict:
    """Get overall knowledge base stats for a specific agent."""
    db = await get_db()
    coll = db[COLLECTION_CHUNKS]
    afilter = {"agent_name": agent_name}
    total_chunks = await coll.count_documents(afilter)
    pipeline = [
        {"$match": afilter},
        {"$group": {"_id": "$file_name"}},
        {"$count": "count"},
    ]
    doc_count_result = await coll.aggregate(pipeline).to_list(length=1)
    total_docs = doc_count_result[0]["count"] if doc_count_result else 0

    type_pipeline = [
        {"$match": afilter},
        {"$group": {"_id": "$file_type", "count": {"$sum": 1}}},
    ]
    file_types = {}
    async for t in coll.aggregate(type_pipeline):
        file_types[t["_id"]] = t["count"]

    # Count FAISS vectors for this agent
    store = KBFaissManager.get_store()
    faiss_count = 0
    if store.is_initialized:
        faiss_count = sum(1 for m in store._id_to_meta.values() if m.get("agent_name") == agent_name)

    return {
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "faiss_vectors": faiss_count,
        "file_types": file_types,
    }
