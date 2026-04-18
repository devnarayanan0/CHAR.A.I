from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.admin.local_ingestion import ingest_local_documents
from app.embeddings.model import get_embedding_model
from app.rag.pipeline import run_rag

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        get_embedding_model()
        logger.info("RAG embedding model preloaded")
    except Exception:
        logger.exception("Failed to preload embedding model")
    yield


app = FastAPI(title="CHAR.AI RAG Service", lifespan=lifespan)


class QueryPayload(BaseModel):
    query: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/query")
async def query(payload: QueryPayload):
    try:
        result = run_rag(payload.query)
    except Exception as exc:
        logger.exception("RAG query failed")
        raise HTTPException(status_code=500, detail="RAG query failed") from exc

    context = result.get("context") or []
    if not isinstance(context, list):
        context = [str(context)]

    return {
        "answer": result.get("answer") or "",
        "context": context,
    }


@app.post("/ingest")
async def ingest():
    try:
        result = ingest_local_documents()
    except Exception as exc:
        logger.exception("RAG ingestion failed")
        raise HTTPException(status_code=500, detail="RAG ingestion failed") from exc

    return {
        "processed_files": result["processed_files"],
        "removed_files": result["removed_files"],
        "skipped_files": result["skipped_files"],
        "uploaded_chunks": result["uploaded_chunks"],
        "status": "SUCCESS",
    }