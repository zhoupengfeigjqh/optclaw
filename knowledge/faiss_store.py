"""Thread-safe FAISS vector store using faiss directly (no langchain wrapper)."""

import os
import pickle
import shutil
import threading

import faiss
import numpy as np

from .config import get_faiss_index_path


class _ThreadSafeFaiss:
    """Direct FAISS index storing vectors + chunk metadata, thread-safe. Full text lives in MongoDB."""

    def __init__(self):
        self._index: faiss.Index | None = None
        self._id_to_meta: dict[str, dict] = {}
        self._id_list: list[str] = []
        self._lock = threading.RLock()
        self._dim: int | None = None

    @property
    def is_initialized(self) -> bool:
        return self._index is not None

    @property
    def doc_count(self) -> int:
        return len(self._id_list)

    def _ensure_index(self, dim: int):
        if self._index is None:
            self._dim = dim
            self._index = faiss.IndexFlatIP(dim)  # Inner Product = Cosine for L2-normalized vectors

    def add(self, embeddings: np.ndarray, metadatas: list[dict], ids: list[str]):
        with self._lock:
            self._ensure_index(embeddings.shape[1])
            vecs = embeddings.astype(np.float32)
            self._index.add(vecs)
            for i, cid in enumerate(ids):
                self._id_to_meta[cid] = metadatas[i]
                self._id_list.append(cid)

    def search(self, query_embedding: np.ndarray, top_k: int = 5, threshold: float = 0.5) -> list[tuple[str, float]]:
        with self._lock:
            if self._index is None or self._index.ntotal == 0:
                return []
            vec = query_embedding.astype(np.float32).reshape(1, -1)
            actual_k = min(top_k, self._index.ntotal)
            scores, indices = self._index.search(vec, actual_k)
            results = []
            for idx, score in zip(indices[0], scores[0]):
                if idx < 0 or idx >= len(self._id_list):
                    continue
                if score < threshold:
                    continue
                cid = self._id_list[idx]
                results.append((cid, float(score)))
            return results

    def delete_by_ids(self, ids: set[str]) -> int:
        with self._lock:
            removed = 0
            ids_to_remove = set(ids)
            keep_indices = []
            for i, cid in enumerate(self._id_list):
                if cid in ids_to_remove:
                    removed += 1
                else:
                    keep_indices.append(i)

            if removed == 0:
                return 0

            if not keep_indices:
                self._index = None
                self._dim = None
                self._id_to_meta.clear()
                self._id_list.clear()
                return removed

            # Rebuild index without the deleted vectors
            old_vectors = np.zeros((self._index.ntotal, self._dim), dtype=np.float32)
            self._index.reconstruct_n(0, self._index.ntotal, old_vectors)

            new_vectors = old_vectors[keep_indices]
            new_ids = [self._id_list[i] for i in keep_indices]
            new_metas = {self._id_list[i]: self._id_to_meta[self._id_list[i]] for i in keep_indices if self._id_list[i] in self._id_to_meta}

            self._index = faiss.IndexFlatIP(self._dim)
            self._index.add(new_vectors)
            self._id_to_meta = new_metas
            self._id_list = new_ids

            return removed

    def save(self, path: str):
        with self._lock:
            os.makedirs(path, exist_ok=True)
            if self._index:
                faiss.write_index(self._index, os.path.join(path, "index.faiss"))
            with open(os.path.join(path, "meta.pkl"), "wb") as f:
                pickle.dump({
                    "id_to_meta": self._id_to_meta,
                    "id_list": self._id_list,
                    "dim": self._dim,
                }, f)

    def load(self, path: str):
        with self._lock:
            index_file = os.path.join(path, "index.faiss")
            meta_file = os.path.join(path, "meta.pkl")
            if not os.path.exists(index_file) or not os.path.exists(meta_file):
                return
            self._index = faiss.read_index(index_file)
            with open(meta_file, "rb") as f:
                data = pickle.load(f)
            self._id_to_meta = data["id_to_meta"]
            self._id_list = data["id_list"]
            self._dim = data.get("dim")


class KBFaissManager:
    """Singleton manager for the knowledge base FAISS index."""

    _instance: _ThreadSafeFaiss | None = None

    @classmethod
    def get_store(cls) -> _ThreadSafeFaiss:
        if cls._instance is None:
            cls._instance = _ThreadSafeFaiss()
            index_path = get_faiss_index_path()
            cls._instance.load(index_path)
        return cls._instance

    @classmethod
    def reset_store(cls):
        if cls._instance is not None:
            index_path = get_faiss_index_path()
            if os.path.exists(index_path):
                shutil.rmtree(index_path, ignore_errors=True)
        cls._instance = None

    @classmethod
    def save(cls):
        if cls._instance is not None:
            cls._instance.save(get_faiss_index_path())
