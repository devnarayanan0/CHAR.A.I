from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


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


def log_message(phone: str, access_code: int | None, role: str, content: str) -> None:
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
    if access_code is not None:
        payload["access_code"] = access_code

    try:
        client.table("user_messages").insert(payload).execute()
    except Exception as exc:
        logger.error("LOG ERROR: %s", str(exc))


def get_grouped_logs(limit_users: int = 200, limit_messages_per_user: int = 50) -> list[dict[str, Any]]:
    client = _get_supabase_client()
    if client is None:
        return []

    try:
        result = (
            client.table("user_messages")
            .select("phone, role, content, created_at")
            .order("created_at", desc=True)
            .limit(max(limit_users * limit_messages_per_user * 4, 1000))
            .execute()
        )
        rows = getattr(result, "data", None) or []
    except Exception as exc:
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
                "name": "Unknown",
                "email": "",
                "last_activity": str((row or {}).get("created_at") or ""),
                "messages": [],
            },
        )

        if len(group["messages"]) >= limit_messages_per_user:
            continue

        group["messages"].append(
            {
                "role": str((row or {}).get("role") or "assistant"),
                "content": str((row or {}).get("content") or ""),
                "time": str((row or {}).get("created_at") or ""),
            }
        )

    if not grouped:
        return []

    for group in grouped.values():
        group["messages"].reverse()

    try:
        user_result = client.table("users").select("name, phone, email").execute()
        user_rows = getattr(user_result, "data", None) or []
        user_map = {
            str((row or {}).get("phone") or "").strip(): {
                "name": str((row or {}).get("name") or "Unknown"),
                "email": str((row or {}).get("email") or ""),
            }
            for row in user_rows
            if str((row or {}).get("phone") or "").strip()
        }
    except Exception as exc:
        logger.error("LOG ERROR: %s", str(exc))
        user_map = {}

    for phone, group in grouped.items():
        user = user_map.get(phone)
        if not user:
            continue
        group["name"] = user["name"]
        group["email"] = user["email"]

    ordered = sorted(
        grouped.values(),
        key=lambda item: str(item.get("last_activity") or ""),
        reverse=True,
    )
    return ordered[:limit_users]
