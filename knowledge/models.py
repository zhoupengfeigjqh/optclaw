"""Pydantic models for knowledge base API."""

from pydantic import BaseModel, Field


class ChunkSettings(BaseModel):
    chunk_size: int = Field(default=500, ge=100, le=500, description="切片大小")
    overlap_size: int = Field(default=50, ge=10, le=100, description="切片重叠大小")


class KnowledgeConfig(BaseModel):
    chunk_size: int = 500
    overlap_size: int = 50
    embed_model: str = "nomic-embed-text"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    vector_top_k: int = 5
    score_threshold: float = 0.5


class RecallRequest(BaseModel):
    query: str = Field(..., min_length=1, description="查询文本")
    top_k: int = Field(default=5, ge=1, le=50, description="返回结果数")
    search_type: str = Field(default="hybrid", description="搜索类型: keyword, vector, hybrid")
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    use_rerank: bool = False


class UploadResponse(BaseModel):
    success: bool
    file_name: str
    file_type: str
    chunks_count: int
    message: str


class DeleteResponse(BaseModel):
    success: bool
    file_name: str
    chunks_removed: int
    message: str


class StatsResponse(BaseModel):
    total_documents: int
    total_chunks: int
    faiss_vectors: int
    file_types: dict
