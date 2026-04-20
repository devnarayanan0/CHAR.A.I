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
        logger.error("❌ PINECONE_INDEX_NAME is not configured")
        raise RuntimeError("PINECONE_INDEX_NAME is not configured")
    
    index_name = settings.pinecone_index_name.strip()
    logger.info("🔌 Connecting to Pinecone index: %s", index_name)
    try:
        pc = Pinecone(api_key=settings.pinecone_api_key)
        index = pc.Index(index_name)
        logger.info("✓ Connected to Pinecone index: %s", index_name)
        return index
    except Exception as exc:
        logger.exception("❌ Failed to connect to Pinecone index: %s", index_name)
        raise RuntimeError(f"Pinecone connection failed: {exc}") from exc


def _validate_dimension(vector: list[float]) -> None:
    settings = get_settings()
    expected_dim = settings.pinecone_dimension
    actual_dim = len(vector)
    
    if actual_dim != expected_dim:
        logger.error("❌ Embedding dimension mismatch: expected %d, got %d", expected_dim, actual_dim)
        raise ValueError(
            f"Embedding dimension mismatch: expected {expected_dim}, got {actual_dim}"
        )
    
    logger.debug("✓ Vector dimension valid: %d", actual_dim)


def query_pinecone(vector: list[float], top_k: int = 3) -> list[str]:
    """Query Pinecone for similar vectors and retrieve metadata chunks."""
    logger.debug("🔍 Validating query vector...")
    try:
        _validate_dimension(vector)
    except Exception as exc:
        logger.exception("❌ Vector dimension validation failed")
        raise RuntimeError(f"Vector dimension invalid: {exc}") from exc
    
    index = get_index()
    logger.info("🔍 Querying Pinecone: top_k=%d", top_k)
    
    try:
        result = index.query(
            vector=vector,
            top_k=top_k,
            include_metadata=True,
        )
    except Exception as exc:
        logger.exception("❌ Pinecone query failed")
        raise RuntimeError(f"Pinecone query failed: {exc}") from exc

    chunks: list[str] = []
    matches = result.get("matches", [])
    logger.info("📊 Pinecone returned %d matches (top_k=%d)", len(matches), top_k)
    
    if not matches:
        logger.warning("⚠ No matches found in Pinecone")
        return []
    
    for idx, match in enumerate(matches):
        try:
            metadata = match.get("metadata") or {}
            text = metadata.get("text")
            source = metadata.get("source", "unknown")
            score = match.get("score", 0)
            
            if text:
                chunks.append(text)
                logger.debug("📌 Match %d: source=%s score=%.3f text_len=%d", idx + 1, source, score, len(text))
            else:
                logger.warning("❌ Match %d has no text in metadata", idx + 1)
        except Exception as exc:
            logger.exception("❌ Failed to extract chunk from match %d", idx)
    
    logger.info("✓ Retrieved %d chunks from %d matches", len(chunks), len(matches))
    return chunks


def upsert_chunks(records: Iterable[dict]) -> int:
    """Upsert chunk vectors to Pinecone index."""
    logger.debug("🔄 Preparing upsert payload...")
    index = get_index()
    payload = []
    
    for idx, record in enumerate(records):
        try:
            vector = record["values"]
            _validate_dimension(vector)
            payload.append(record)
            if (idx + 1) % 10 == 0:
                logger.debug("🔄 Prepared %d records for upsert", idx + 1)
        except Exception as exc:
            logger.exception("❌ Record validation failed at index %d", idx)
            raise RuntimeError(f"Record validation failed at {idx}: {exc}") from exc

    if not payload:
        logger.warning("⚠ No records to upsert")
        return 0

    logger.info("⬆ Upserting %d records to Pinecone...", len(payload))
    try:
        index.upsert(vectors=payload)
        logger.info("✓ Successfully upserted %d vectors to Pinecone", len(payload))
        return len(payload)
    except Exception as exc:
        logger.exception("❌ Upsert to Pinecone failed")
        raise RuntimeError(f"Pinecone upsert failed: {exc}") from exc


def delete_vectors(ids: list[str]) -> None:
    """Delete vectors from Pinecone by ID."""
    if not ids:
        logger.debug("ℹ No vectors to delete")
        return
    
    logger.info("🗑 Deleting %d vectors from Pinecone...", len(ids))
    try:
        get_index().delete(ids=ids)
        logger.info("✓ Successfully deleted %d vectors from Pinecone", len(ids))
    except Exception as exc:
        logger.exception("❌ Failed to delete vectors from Pinecone")
        raise RuntimeError(f"Vector deletion failed: {exc}") from exc


def get_vector_count() -> int:
    """Get total vector count from Pinecone index."""
    try:
        stats = get_index().describe_index_stats()
        if hasattr(stats, "to_dict"):
            stats = stats.to_dict()
        count = int(stats.get("total_vector_count", 0))
        logger.info("📈 Pinecone index stats: total_vector_count=%d", count)
        return count
    except Exception as exc:
        logger.exception("❌ Failed to fetch Pinecone index stats")
        raise RuntimeError(f"Index stats fetch failed: {exc}") from exc
