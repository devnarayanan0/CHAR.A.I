import logging

from fastapi import APIRouter, HTTPException

from app.admin.local_ingestion import ingest_local_documents
from app.admin.log_store import get_recent_logs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/logs")
async def admin_logs(limit: int = 50):
    return get_recent_logs(limit=limit)


@router.post("/ingest")
async def ingest_documents():
    try:
        result = ingest_local_documents()
    except Exception as exc:
        logger.exception("Local ingestion failed")
        raise HTTPException(status_code=500, detail="Local ingestion failed") from exc

    return {
        "processed_files": result["processed_files"],
        "uploaded_chunks": result["uploaded_chunks"],
        "status": "SUCCESS",
    }
