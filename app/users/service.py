from __future__ import annotations

import logging
import re
from threading import Lock
from typing import Literal

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

SessionState = Literal["NEW", "ASK_NAME", "ASK_PHONE", "ACTIVE"]

_SESSIONS: dict[str, dict[str, str | None]] = {}
_SESSION_LOCK = Lock()
_PHONE_PATTERN = re.compile(r"^\+?\d{10,15}$")


def normalize_user_id(value: str | None) -> str:
    if not value:
        return "unknown"
    return value.strip()


def _get_user_from_supabase(phone_number: str) -> dict | None:
    """Query Supabase for existing user by phone number."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        return None

    try:
        from supabase import create_client
    except Exception:
        return None

    try:
        client = create_client(settings.supabase_url, settings.supabase_key)
        result = client.table("users").select("name, phone").eq("phone", phone_number).limit(1).execute()
        rows = getattr(result, "data", None) or []
        if rows:
            return rows[0]
        return None
    except Exception:
        logger.warning("Failed to query user from Supabase for phone=%s", phone_number)
        return None


def get_or_create_session(phone_number: str) -> dict[str, str | None]:
    with _SESSION_LOCK:
        session = _SESSIONS.get(phone_number)
        if session:
            return dict(session)

        supabase_user = _get_user_from_supabase(phone_number)
        if supabase_user:
            session = {
                "state": "ACTIVE",
                "name": supabase_user.get("name") or phone_number,
            }
        else:
            session = {"state": "NEW", "name": None}

        _SESSIONS[phone_number] = session
        return dict(session)


def update_session(phone_number: str, *, state: SessionState | None = None, name: str | None = None) -> dict[str, str | None]:
    with _SESSION_LOCK:
        session = _SESSIONS.setdefault(phone_number, {"state": "NEW", "name": None})
        if state is not None:
            session["state"] = state
        if name is not None:
            session["name"] = name
        return dict(session)


def is_valid_phone_number(value: str) -> bool:
    normalized = value.strip().replace(" ", "")
    return bool(_PHONE_PATTERN.fullmatch(normalized))


def normalize_phone_number(value: str) -> str:
    return value.strip().replace(" ", "")


def insert_user_once(name: str, phone_number: str) -> None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        logger.warning("Supabase is not configured; skipping user insert for %s", phone_number)
        return

    try:
        from supabase import Client, create_client
    except Exception as exc:
        logger.warning("Supabase client unavailable; skipping user insert: %s", exc)
        return

    try:
        client: Client = create_client(settings.supabase_url, settings.supabase_key)
        existing = client.table("users").select("phone").eq("phone", phone_number).limit(1).execute()
        rows = getattr(existing, "data", None) or []
        if rows:
            return

        client.table("users").insert({"name": name, "phone": phone_number}).execute()
    except Exception:
        logger.exception("Failed to insert user into Supabase")
