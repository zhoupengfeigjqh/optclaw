"""Async MongoDB connection management using motor."""

import os
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

COLLECTION_CHUNKS = "kb_chunks"


def _build_uri() -> str:
    user = os.getenv("MONGO_ROOT_USER", "admin")
    password = os.getenv("MONGO_ROOT_PASSWORD", "changeme")
    host = os.getenv("MONGO_HOST", "mongo")
    port = os.getenv("MONGO_PORT", "27017")
    db = os.getenv("MONGO_INITDB_DATABASE", "optclaw")
    return f"mongodb://{user}:{password}@{host}:{port}/{db}?authSource=admin"


async def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _client is None:
        uri = _build_uri()
        _client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        db_name = os.getenv("MONGO_INITDB_DATABASE", "optclaw")
        _db = _client[db_name]
    return _db


async def close_db():
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None


async def ensure_indexes():
    db = await get_db()
    coll = db[COLLECTION_CHUNKS]
    await coll.create_index("file_name")
    await coll.create_index("chunk_id", unique=True)
    await coll.create_index([("content", "text")])
    await coll.create_index("agent_name")
