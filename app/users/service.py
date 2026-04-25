from __future__ import annotations

import logging
import re
from functools import lru_cache
from threading import Lock
from typing import Literal
from uuid import uuid4

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

SessionState = Literal["NEW", "ASK_NAME", "ASK_EMAIL", "ASK_ACCESS_CODE", "ACTIVE"]

_SESSIONS: dict[str, dict[str, str | int | None]] = {}
_SESSION_LOCK = Lock()
_PHONE_PATTERN = re.compile(r"^\+?\d{10,15}$")


def _to_access_code_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value

    cleaned = value.strip()
    if not cleaned:
        return None

    try:
        return int(cleaned)
    except ValueError:
        return None


def normalize_user_id(value: str | None) -> str:
    if not value:
        return "unknown"
    return value.strip()


@lru_cache(maxsize=1)
def _get_supabase_client():
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        return None

    try:
        from supabase import create_client
    except Exception as exc:
        logger.error("DB ERROR: %s", str(exc))
        return None

    try:
        return create_client(settings.supabase_url, settings.supabase_key)
    except Exception as exc:
        logger.error("DB ERROR: %s", str(exc))
        return None


def get_user_by_phone(phone: str) -> dict | None:
    client = _get_supabase_client()
    if client is None:
        return None

    try:
        result = (
            client.table("users")
            .select("id, name, email, access_code, phone, state")
            .eq("phone", phone)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if rows:
            return rows[0]
        return None
    except Exception as exc:
        logger.error("DB ERROR: %s", str(exc))
        return None


def get_user_by_access_code(access_code: str | int) -> dict | None:
    client = _get_supabase_client()
    if client is None:
        return None

    access_code_int = _to_access_code_int(access_code)
    if access_code_int is None:
        return None

    try:
        result = (
            client.table("users")
            .select("id, name, email, access_code, phone, state")
            .eq("access_code", access_code_int)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if rows:
            return rows[0]
        return None
    except Exception as exc:
        logger.error("DB ERROR: %s", str(exc))
        return None


def create_user(phone: str) -> dict | None:
    client = _get_supabase_client()
    if client is None:
        return None

    try:
        result = client.table("users").insert({"id": str(uuid4()), "phone": phone, "state": "NEW"}).execute()
        rows = getattr(result, "data", None) or []
        if rows:
            return rows[0]
        return None
    except Exception as exc:
        logger.error("DB ERROR: %s", str(exc))
        return None


def update_user_email(phone: str, email: str) -> bool:
    client = _get_supabase_client()
    if client is None:
        return False

    try:
        client.table("users").update({"email": email}).eq("phone", phone).execute()
        return True
    except Exception as exc:
        logger.error("DB ERROR: %s", str(exc))
        return False


def update_user_state(phone: str, state: str) -> bool:
    client = _get_supabase_client()
    if client is None:
        return False

    try:
        client.table("users").update({"state": state}).eq("phone", phone).execute()
        return True
    except Exception as exc:
        logger.error("DB ERROR: %s", str(exc))
        return False


def update_user_name(phone: str, name: str) -> bool:
    client = _get_supabase_client()
    if client is None:
        return False

    try:
        client.table("users").update({"name": name}).eq("phone", phone).execute()
        return True
    except Exception as exc:
        logger.error("DB ERROR: %s", str(exc))
        return False


def upsert_user(
    phone: str,
    name: str | None = None,
    email: str | None = None,
    access_code: int | None = None,
    state: str | None = None,
) -> dict | None:
    if access_code is not None:
        existing = get_user_by_access_code(access_code)
    else:
        existing = get_user_by_phone(phone)

    if existing is None:
        existing_by_phone = get_user_by_phone(phone)
        if existing_by_phone is not None:
            updates: dict[str, str] = {}
            if name is not None:
                updates["name"] = name
            if email is not None:
                updates["email"] = email
            if access_code is not None:
                updates["access_code"] = access_code
            if state is not None:
                updates["state"] = state

            if updates:
                client = _get_supabase_client()
                if client is not None:
                    try:
                        client.table("users").update(updates).eq("phone", phone).execute()
                    except Exception as exc:
                        logger.error("DB ERROR: %s", str(exc))
            if access_code is not None:
                return get_user_by_access_code(access_code)
            return get_user_by_phone(phone)

        payload: dict[str, str | int] = {"id": str(uuid4()), "phone": phone, "state": state or "NEW"}
        if name:
            payload["name"] = name
        if email:
            payload["email"] = email
        if access_code:
            payload["access_code"] = access_code

        client = _get_supabase_client()
        if client is None:
            return None
        try:
            result = client.table("users").insert(payload).execute()
            rows = getattr(result, "data", None) or []
            if rows:
                return rows[0]
            return None
        except Exception as exc:
            logger.error("DB ERROR: %s", str(exc))
            return None

    updates: dict[str, str | int] = {}
    if name is not None:
        updates["name"] = name
    if email is not None:
        updates["email"] = email
    if access_code is not None:
        updates["access_code"] = access_code
    if state is not None:
        updates["state"] = state

    if updates:
        client = _get_supabase_client()
        if client is not None:
            try:
                if access_code is not None:
                    client.table("users").update(updates).eq("access_code", access_code).execute()
                else:
                    client.table("users").update(updates).eq("phone", phone).execute()
            except Exception as exc:
                logger.error("DB ERROR: %s", str(exc))

    if access_code is not None:
        return get_user_by_access_code(access_code)
    return get_user_by_phone(phone)


def _memory_get_or_create_session(phone_number: str) -> dict[str, str | int | None]:
    with _SESSION_LOCK:
        session = _SESSIONS.get(phone_number)
        if session is None:
            session = {"state": "NEW", "name": None, "email": None, "access_code": None}
            _SESSIONS[phone_number] = session
        return dict(session)


def _memory_update_session(
    phone_number: str,
    *,
    state: SessionState | None = None,
    name: str | None = None,
    email: str | None = None,
    access_code: int | None = None,
) -> dict[str, str | int | None]:
    with _SESSION_LOCK:
        session = _SESSIONS.setdefault(phone_number, {"state": "NEW", "name": None, "email": None, "access_code": None})
        if state is not None:
            session["state"] = state
        if name is not None:
            session["name"] = name
        if email is not None:
            session["email"] = email
        if access_code is not None:
            session["access_code"] = access_code
        return dict(session)


def get_or_create_session(phone_number: str) -> dict[str, str | int | None]:
    return _memory_get_or_create_session(phone_number)


def update_session(
    phone_number: str,
    *,
    state: SessionState | None = None,
    name: str | None = None,
    email: str | None = None,
    access_code: int | None = None,
    persist_to_db: bool = False,
) -> dict[str, str | int | None]:
    memory_session = _memory_update_session(phone_number, state=state, name=name, email=email, access_code=access_code)

    if not persist_to_db:
        return memory_session

    db_user = upsert_user(phone_number, name=name, email=email, access_code=access_code, state=state)
    if db_user is not None:
        session = {
            "state": str(db_user.get("state") or "NEW"),
            "name": (str(db_user.get("name")) if db_user.get("name") else None),
            "email": (str(db_user.get("email")) if db_user.get("email") else None),
            "access_code": (int(db_user.get("access_code")) if db_user.get("access_code") is not None else None),
        }
        with _SESSION_LOCK:
            _SESSIONS[phone_number] = session
        return dict(session)

    return memory_session


def is_valid_phone_number(value: str) -> bool:
    normalized = value.strip().replace(" ", "")
    return bool(_PHONE_PATTERN.fullmatch(normalized))


def normalize_phone_number(value: str) -> str:
    return value.strip().replace(" ", "")


def insert_user_once(name: str, phone_number: str) -> None:
    db_user = upsert_user(phone_number, name=name)
    if db_user is not None:
        return

    logger.error("DB ERROR: unavailable, using memory fallback")
    _memory_update_session(phone_number, name=name)
