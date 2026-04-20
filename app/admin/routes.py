import asyncio
import logging
from collections import defaultdict

from fastapi import APIRouter, HTTPException

from app.admin.log_store import get_recent_logs
from app.config.settings import get_settings
from app.rag.client import ingest_rag_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _fetch_users_from_supabase() -> list[dict[str, str]]:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        logger.warning("Supabase is not configured; returning users from logs only")
        return []

    try:
        from supabase import create_client
    except Exception:
        logger.warning("Supabase client unavailable; returning users from logs only")
        return []

    try:
        client = create_client(settings.supabase_url, settings.supabase_key)
        result = client.table("users").select("name, phone").execute()
        rows = getattr(result, "data", None) or []
        users: list[dict[str, str]] = []
        for row in rows:
            phone = str((row or {}).get("phone") or "").strip()
            if not phone:
                continue
            users.append(
                {
                    "name": str((row or {}).get("name") or "Unknown"),
                    "phone": phone,
                }
            )
        return users
    except Exception:
        logger.exception("Failed to fetch users from Supabase")
        return []


@router.get("/logs")
async def admin_logs(limit: int = 50):
    return get_recent_logs(limit=limit)


@router.get("/users")
async def admin_users():
    users = _fetch_users_from_supabase()
    logs = get_recent_logs(limit=1000)

    grouped_logs: dict[str, list[dict[str, str]]] = defaultdict(list)
    for log in logs:
        phone = str((log or {}).get("user") or "").strip()
        if not phone:
            continue
        grouped_logs[phone].append(
            {
                "state": str((log or {}).get("state") or "UNKNOWN"),
                "timestamp": str((log or {}).get("timestamp") or ""),
            }
        )

    response: list[dict] = []
    known_phones: set[str] = set()

    for user in users:
        phone = user["phone"]
        known_phones.add(phone)
        response.append(
            {
                "name": user["name"],
                "phone": phone,
                "logs": grouped_logs.get(phone, []),
            }
        )

    for phone, phone_logs in grouped_logs.items():
        if phone in known_phones:
            continue
        response.append(
            {
                "name": "Unknown",
                "phone": phone,
                "logs": phone_logs,
            }
        )

    return response


@router.post("/ingest")
async def ingest_documents():
    logger.info("=== /admin/ingest ROUTE HIT ===\")
    logger.info("🚀 Starting ingestion from admin panel...")
    
    try:
        logger.info("📞 Calling RAG ingestion service...")
        result = await asyncio.to_thread(ingest_rag_service)
    except HTTPException:
        logger.exception("❌ HTTPException during RAG ingestion")
        raise
    except RuntimeError as exc:
        logger.exception("❌ RAG ingestion request failed: %s", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("❌ Unexpected RAG ingestion failure")
        raise HTTPException(status_code=500, detail="Local ingestion failed") from exc

    logger.info("✓ Ingestion complete | processed=%d removed=%d skipped=%d uploaded=%d",
                result.get("processed_files", 0),
                result.get("removed_files", 0),
                result.get("skipped_files", 0),
                result.get("uploaded_chunks", 0))
    return result
