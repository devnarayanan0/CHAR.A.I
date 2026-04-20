import os
import logging
from functools import lru_cache

os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")

from sentence_transformers import SentenceTransformer

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    model_name = settings.embedding_model_name
    logger.info("🤖 Loading embedding model: %s", model_name)
    try:
        model = SentenceTransformer(model_name)
        logger.info("✓ Embedding model loaded successfully")
        return model
    except Exception as exc:
        logger.exception("❌ Failed to load embedding model: %s", model_name)
        raise RuntimeError(f"Embedding model failed to load: {exc}") from exc


def embed(text: str) -> list[float]:
    """Embed text using SentenceTransformer with retrieval instruction."""
    try:
        model = get_embedding_model()
        enhanced_text = "Represent this sentence for searching relevant passages: " + text
        logger.debug("📝 Embedding text: %s", text[:50])
        vector = model.encode(
            enhanced_text,
            normalize_embeddings=True,
        )
        embedding = vector.tolist()
        logger.debug("✓ Embedding generated (dimension: %d)", len(embedding))
        return embedding
    except Exception as exc:
        logger.exception("❌ Embedding generation failed for text: %s", text[:50])
        raise RuntimeError(f"Embedding failed: {exc}") from exc
