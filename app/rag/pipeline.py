from __future__ import annotations

import logging
import re

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
    normalized_query = normalize_query(query)
    vector = embed(normalized_query)
    chunks = query_pinecone(vector, top_k=10)
    logger.error("RAG RETRIEVED CONTEXT: %s", chunks)
    context = "\n\n".join(chunks)
    answer = ask_llm(query, context)

    return {
        "query": query,
        "context": chunks,
        "answer": answer,
    }
