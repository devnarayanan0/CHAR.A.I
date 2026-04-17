import os
from functools import lru_cache

os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")

from sentence_transformers import SentenceTransformer

from app.config.settings import get_settings


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    return SentenceTransformer(settings.embedding_model_name)


def embed(text: str) -> list[float]:
    model = get_embedding_model()
    vector = model.encode(
        "Represent this sentence for searching relevant passages: " + text,
        normalize_embeddings=True,
    )
    return vector.tolist()
