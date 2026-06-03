"""Async Ollama embedding client."""

import asyncio
import httpx
import numpy as np

from .config import get_ollama_base_url, get_embed_model

BATCH_SIZE = 10


async def _embed_single(text: str, model: str, client: httpx.AsyncClient) -> list[float]:
    url = f"{get_ollama_base_url()}/api/embeddings"
    resp = await client.post(url, json={"model": model, "prompt": text})
    resp.raise_for_status()
    return resp.json()["embedding"]


async def ollama_embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Generate embeddings via Ollama API with batching."""
    if model is None:
        model = get_embed_model()
    embeddings = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            tasks = [_embed_single(t, model, client) for t in batch]
            batch_embs = await asyncio.gather(*tasks)
            embeddings.extend(batch_embs)
    return embeddings


def l2_normalize(vectors: list[list[float]]) -> np.ndarray:
    """L2 normalize for cosine similarity via inner product."""
    arr = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return arr / norms


