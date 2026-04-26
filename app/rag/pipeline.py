from __future__ import annotations

import logging
import re
from time import perf_counter
from uuid import uuid4

import requests

from app.config.settings import get_settings
from app.embeddings.model import embed
from app.vectordb.pinecone_client import query_pinecone


logger = logging.getLogger(__name__)


def normalize_query(query: str) -> str:
    normalized = query.lower()

    # Preserve product/domain intent before single-word replacements.
    phrase_replacements = {
        r"\bcred\s*scan\b": "credibility scan",
        r"\bcredscan\b": "credibility scan",
    }

    for pattern, replacement in phrase_replacements.items():
        normalized = re.sub(pattern, replacement, normalized)

    replacements = {
        r"\bcred\b": "credibility",
        r"\bacct\b": "account",
        r"\bauth\b": "authentication",
        r"\bscan\b": "scan",
    }

    for pattern, replacement in replacements.items():
        normalized = re.sub(pattern, replacement, normalized)

    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def ask_llm(query: str, context: str) -> str:
    settings = get_settings()
    prompt = f"""
Answer using the context below. If the answer is not in the context, say you do not know.

Context:
{context}

Question: {query}
""".strip()

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.groq_model_name,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    return body["choices"][0]["message"]["content"]


def run_rag(query: str) -> dict:
    trace_id = uuid4().hex[:8]
    start = perf_counter()
    logger.info("[RAG][%s] START query=%r", trace_id, query)

    try:
        normalized_query = normalize_query(query)
        logger.info("[RAG][%s] NORMALIZE original=%r normalized=%r", trace_id, query, normalized_query)

        embed_start = perf_counter()
        vector = embed(normalized_query)
        logger.info("[RAG][%s] EMBED dim=%d took=%.3fs", trace_id, len(vector), perf_counter() - embed_start)

        retrieve_start = perf_counter()
        chunks = query_pinecone(vector, top_k=10)
        logger.info(
            "[RAG][%s] RETRIEVE chunks=%d took=%.3fs", trace_id, len(chunks), perf_counter() - retrieve_start
        )
        logger.info("[RAG][%s] RETRIEVED_CONTEXT %s", trace_id, chunks)

        context = "\n\n".join(chunks)
        logger.info("[RAG][%s] CONTEXT_BUILT chars=%d", trace_id, len(context))

        llm_start = perf_counter()
        answer = ask_llm(query, context)
        logger.info("[RAG][%s] LLM answer_len=%d took=%.3fs", trace_id, len(answer), perf_counter() - llm_start)
    except Exception:
        logger.exception("[RAG][%s] FAILED", trace_id)
        raise

    logger.info("[RAG][%s] DONE total=%.3fs", trace_id, perf_counter() - start)

    return {
        "query": query,
        "context": chunks,
        "answer": answer,
    }
