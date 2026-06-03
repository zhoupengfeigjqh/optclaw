"""Knowledge base configuration from config.yaml."""

import yaml
from pathlib import Path

_KB_CONFIG: dict = {}
_LAST_MTIME: float = 0.0
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


def _load() -> dict:
    global _KB_CONFIG, _LAST_MTIME
    try:
        mtime = CONFIG_PATH.stat().st_mtime
        if mtime <= _LAST_MTIME and _KB_CONFIG:
            return _KB_CONFIG
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _KB_CONFIG = data.get("knowledge", {})
        _LAST_MTIME = mtime
    except FileNotFoundError:
        _KB_CONFIG = {}
    return _KB_CONFIG


def get_chunk_size() -> int:
    return _load().get("chunk_size", 500)


def get_overlap_size() -> int:
    return _load().get("overlap_size", 50)


def get_embed_model() -> str:
    return _load().get("embed_model", "nomic-embed-text")


def get_rerank_model() -> str:
    return _load().get("rerank_model", "BAAI/bge-reranker-v2-m3")


def get_rerank_api_url() -> str:
    return _load().get("rerank_api_url", "http://reranker:7997/rerank")


def get_ollama_base_url() -> str:
    return _load().get("ollama_base_url", "http://host.docker.internal:11434")


def get_vector_top_k() -> int:
    return _load().get("vector_top_k", 5)


def get_score_threshold() -> float:
    return _load().get("score_threshold", 0.5)


def get_faiss_index_path() -> str:
    return _load().get("faiss_index_path", "/app/knowledge/faiss_index")


def get_supported_file_types() -> list:
    return _load().get("supported_file_types", ["pdf", "csv", "md", "docx", "txt"])
