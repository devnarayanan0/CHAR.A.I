import logging
import os
import requests

from app.embeddings.model import embed
from app.vectordb.pinecone_client import query_pinecone
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


def ask_llm(query: str, context: str) -> str:
    """Call Groq LLM with query and retrieved context."""
    settings = get_settings()
    groq_api_key = settings.groq_api_key
    groq_model_name = settings.groq_model_name
    
    if not groq_api_key:
        logger.error("❌ GROQ_API_KEY is not configured")
        raise RuntimeError("GROQ_API_KEY not configured")
    
    if not context.strip():
        logger.warning("⚠ LLM called with empty context")
    
    prompt = f"""Answer the question using ONLY the context provided below. If the context doesn't contain relevant information, say you don't know.

Context:
{context}

Question: {query}"""
    
    logger.debug("🤖 LLM prompt: %s", prompt[:200])
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": groq_model_name,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=30
        )
        logger.info("🤖 LLM response status: %s", response.status_code)
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
        logger.info("🤖 LLM generated answer: %s", answer[:150])
        return answer
    except Exception as exc:
        logger.exception("❌ LLM generation failed")
        raise RuntimeError(f"LLM generation failed: {exc}") from exc


def run_rag(query: str) -> dict[str, any]:
    """Execute full RAG pipeline: embed → retrieve → generate → return."""
    logger.info("=== RAG PIPELINE START ===")
    logger.info("📥 RAG received query: %s", query)
    
    # Step 1: Embed query
    try:
        logger.info("🔤 Embedding query...")
        vector = embed(query)
        logger.info("✓ Embedding created (dimension: %d)", len(vector))
    except Exception as exc:
        logger.exception("❌ Embedding failed")
        raise RuntimeError(f"Embedding failed: {exc}") from exc
    
    # Step 2: Retrieve from Pinecone
    try:
        logger.info("🔍 Querying Pinecone for matches...")
        chunks = query_pinecone(vector)
        logger.info("✓ Pinecone retrieval complete: %d chunks", len(chunks))
        if not chunks:
            logger.warning("⚠ No Pinecone matches found")
            chunks = []
    except Exception as exc:
        logger.exception("❌ Pinecone retrieval failed")
        raise RuntimeError(f"Pinecone retrieval failed: {exc}") from exc
    
    # Step 3: Build context
    context = "\n\n".join(chunks) if chunks else "No relevant context found."
    logger.info("📄 Context prepared: %d chars from %d chunks", len(context), len(chunks))
    
    # Step 4: Generate answer
    try:
        logger.info("💡 Calling LLM to generate answer...")
        answer = ask_llm(query, context)
        logger.info("✓ Answer generated successfully")
    except Exception as exc:
        logger.exception("❌ Answer generation failed")
        raise RuntimeError(f"Answer generation failed: {exc}") from exc
    
    # Step 5: Return formatted response
    result = {
        "answer": answer,
        "context": chunks,
    }
    logger.info("✓ RAG pipeline complete")
    logger.info("=== RAG PIPELINE END ===")
    return result