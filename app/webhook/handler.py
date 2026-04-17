from __future__ import annotations

import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.admin.log_store import create_log
from app.config.settings import get_settings
from app.rag.pipeline import run_rag
from app.users.service import normalize_user_id

logger = logging.getLogger(__name__)


async def handle_get(req: Request):
    params = req.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    settings = get_settings()
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return PlainTextResponse(content=challenge or "")

    return JSONResponse(content={"error": "verification failed"}, status_code=403)


def _parse_local_request(data: dict) -> tuple[str, str] | None:
    user = normalize_user_id(data.get("user"))
    message = (data.get("message") or "").strip()
    if message:
        return user, message
    return None


def _parse_whatsapp_request(data: dict) -> tuple[str, str] | None:
    entries = data.get("entry", [])
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts", [])
            default_user = None
            if contacts:
                profile = contacts[0].get("profile") or {}
                default_user = profile.get("name") or contacts[0].get("wa_id")

            for message in value.get("messages", []):
                user = normalize_user_id(message.get("from") or default_user)
                text = ((message.get("text") or {}).get("body") or "").strip()
                if text:
                    return user, text
    return None


async def handle_post(req: Request):
    try:
        data = await req.json()
    except Exception as exc:
        logger.exception("Invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    parsed = _parse_local_request(data) or _parse_whatsapp_request(data)
    if not parsed:
        raise HTTPException(status_code=400, detail="No supported message payload found")

    user, text = parsed

    try:
        logger.info("User=%s Query=%s", user, text)
        rag_result = run_rag(text)
        create_log(user=user)
    except Exception as exc:
        logger.exception("RAG request failed")
        raise HTTPException(status_code=500, detail="RAG request failed") from exc

    return {
        "user": user,
        "answer": rag_result["answer"],
        "context": rag_result["context"],
    }
