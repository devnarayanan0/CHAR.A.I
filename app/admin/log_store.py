from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


def _is_missing_table_error(exc: Exception) -> bool:
    details = getattr(exc, "args", ())
    if not details:
        return False

    message = str(details[0])
    return "PGRST205" in message or "Could not find the table 'public.user_messages'" in message


@lru_cache(maxsize=1)
def _get_supabase_client():
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        return None

    try:
        from supabase import create_client
    except Exception as exc:
        logger.error("LOG ERROR: %s", str(exc))
        return None

    try:
        return create_client(settings.supabase_url, settings.supabase_key)
    except Exception as exc:
        logger.error("LOG ERROR: %s", str(exc))
        return None


def log_message(phone: str, role: str, content: str) -> None:
    cleaned_phone = str(phone or "").strip()
    cleaned_content = str(content or "").strip()
    cleaned_role = str(role or "").strip().lower()

    if not cleaned_phone or not cleaned_content or cleaned_role not in {"user", "assistant"}:
        return

    client = _get_supabase_client()
    if client is None:
        return

    payload: dict[str, Any] = {
        "phone": cleaned_phone,
        "role": cleaned_role,
        "content": cleaned_content,
    }

    try:
        client.table("user_messages").insert(payload).execute()
    except Exception as exc:
        if not _is_missing_table_error(exc):
            logger.error("LOG ERROR: %s", str(exc))


def get_log_index(limit_users: int = 200) -> list[dict[str, Any]]:
    client = _get_supabase_client()
    if client is None:
        return []

    try:
        result = (
            client.table("user_messages")
            .select("phone, created_at")
            .order("created_at", desc=True)
            .limit(max(limit_users * 100, 1000))
            .execute()
        )
        rows = getattr(result, "data", None) or []
    except Exception as exc:
        if not _is_missing_table_error(exc):
            logger.error("LOG ERROR: %s", str(exc))
        return []

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        phone = str((row or {}).get("phone") or "").strip()
        if not phone:
            continue

        group = grouped.setdefault(
            phone,
            {
                "phone": phone,
                "last_activity": str((row or {}).get("created_at") or ""),
                "message_count": 0,
            },
        )
        group["message_count"] += 1

    if not grouped:
        return []

    ordered = sorted(
        grouped.values(),
        key=lambda item: str(item.get("last_activity") or ""),
        reverse=True,
    )
    return ordered[:limit_users]


def get_user_messages(phone: str) -> list[dict[str, Any]]:
    client = _get_supabase_client()
    cleaned_phone = str(phone or "").strip()
    if client is None or not cleaned_phone:
        return []

    try:
        result = (
            client.table("user_messages")
            .select("role, content, created_at")
            .eq("phone", cleaned_phone)
            .order("created_at", desc=False)
            .execute()
        )
        rows = getattr(result, "data", None) or []
    except Exception as exc:
        if not _is_missing_table_error(exc):
            logger.error("LOG ERROR: %s", str(exc))
        return []

    return [
        {
            "role": str((row or {}).get("role") or "assistant").strip().lower(),
            "content": str((row or {}).get("content") or ""),
            "created_at": str((row or {}).get("created_at") or ""),
        }
        for row in rows
    ]
