import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.admin.log_store import get_log_index, get_user_messages
from app.rag.client import ingest_rag_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/logs")
async def admin_logs(limit_users: int = 200):
    return get_log_index(limit_users=limit_users)


@router.get("/logs/{phone}")
async def admin_log_messages(phone: str):
    return get_user_messages(phone)


@router.post("/ingest")
async def ingest_documents():
    try:
        result = await asyncio.to_thread(ingest_rag_service)
    except HTTPException:
        logger.error("RAG ingestion HTTP exception")
        raise
    except RuntimeError as exc:
        logger.error("RAG ingestion request failed: %s", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Unexpected RAG ingestion failure: %s", str(exc))
        raise HTTPException(status_code=500, detail="Local ingestion failed") from exc
    return result
