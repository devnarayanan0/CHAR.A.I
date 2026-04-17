from __future__ import annotations

from functools import lru_cache
import logging
from typing import Iterable

from pinecone import Pinecone

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_index():
    settings = get_settings()
    if not settings.pinecone_index_name:
        raise RuntimeError("PINECONE_INDEX_NAME is not configured")
    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_index_name)


def _validate_dimension(vector: list[float]) -> None:
    settings = get_settings()
    if len(vector) != settings.pinecone_dimension:
        raise ValueError(
            f"Embedding dimension mismatch: expected {settings.pinecone_dimension}, got {len(vector)}"
        )


def query_pinecone(vector: list[float], top_k: int = 3) -> list[str]:
    _validate_dimension(vector)
    index = get_index()
    result = index.query(
        vector=vector,
        top_k=top_k,
        include_metadata=True,
    )

    chunks: list[str] = []
    matches = result.get("matches", [])
    logger.info("Pinecone retrieval matches=%s top_k=%s", len(matches), top_k)
    for match in matches:
        metadata = match.get("metadata") or {}
        text = metadata.get("text")
        if text:
            chunks.append(text)
    return chunks


def upsert_chunks(records: Iterable[dict]) -> int:
    index = get_index()
    payload = []
    for record in records:
        vector = record["values"]
        _validate_dimension(vector)
        payload.append(record)

    if not payload:
        return 0

    index.upsert(vectors=payload)
    return len(payload)


def delete_vectors(ids: list[str]) -> None:
    if not ids:
        return
    get_index().delete(ids=ids)


def get_vector_count() -> int:
    stats = get_index().describe_index_stats()
    if hasattr(stats, "to_dict"):
        stats = stats.to_dict()
    return int(stats.get("total_vector_count", 0))
