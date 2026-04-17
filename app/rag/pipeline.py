from __future__ import annotations

import requests

from app.config.settings import get_settings
from app.embeddings.model import embed
from app.vectordb.pinecone_client import query_pinecone


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
    vector = embed(query)
    chunks = query_pinecone(vector)
    context = "\n\n".join(chunks)
    answer = ask_llm(query, context)

    return {
        "query": query,
        "context": chunks,
        "answer": answer,
    }
