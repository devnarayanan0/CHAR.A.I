from __future__ import annotations

import asyncio
import logging

import requests

from fastapi import Request
from fastapi.responses import PlainTextResponse

from app.admin.log_store import create_log
from app.config.settings import get_settings
from app.rag.client import query_rag_service
from app.users.service import (
    get_or_create_session,
    insert_user_once,
    is_valid_phone_number,
    normalize_phone_number,
    normalize_user_id,
    update_session,
)

logger = logging.getLogger(__name__)


async def handle_get(req: Request):
    params = req.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    logger.info("Received webhook verification request mode=%s", mode)

    settings = get_settings()
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("Webhook verification succeeded")
        return PlainTextResponse(content=challenge or "")

    logger.warning("Webhook verification failed")
    return PlainTextResponse(content="verification failed", status_code=403)


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


def _message_response(user: str, message: str) -> dict[str, str]:
    return {"user": user, "message": message}


def _send_whatsapp_message(user_phone: str, response_text: str) -> None:
    settings = get_settings()
    phone_number_id = settings.whatsapp_phone_number_id.strip()
    access_token = settings.whatsapp_access_token.strip()
    if not phone_number_id or not access_token:
        logger.warning("WhatsApp outbound config missing; skipping outbound message")
        return

    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": user_phone,
        "type": "text",
        "text": {"body": response_text},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
    except requests.Timeout:
        logger.exception("WhatsApp outbound request timed out")
    except requests.RequestException:
        logger.exception("Failed to send outbound WhatsApp message")


async def handle_post(req: Request):
    try:
        data = await req.json()
    except Exception:
        logger.exception("Invalid JSON payload")
        return _message_response("unknown", "Sorry, I could not read your message. Please try again.")

    parsed = _parse_local_request(data) or _parse_whatsapp_request(data)
    if not parsed:
        return _message_response("unknown", "Sorry, I could not read your message. Please try again.")

    user, text = parsed
    session = get_or_create_session(user)
    state = session["state"] or "NEW"

    response_text = ""

    if state == "NEW":
        update_session(user, state="ASK_NAME")
        response_text = "Welcome to CHAR.AI. What is your name?"

    elif state == "ASK_NAME":
        update_session(user, state="ASK_PHONE", name=text)
        response_text = "Please enter your phone number"

    elif state == "ASK_PHONE":
        if not is_valid_phone_number(text):
            response_text = "Please enter a valid phone number with 10 to 15 digits."
        else:
            phone_number = normalize_phone_number(text)
            name = session.get("name") or "User"
            insert_user_once(name=name, phone_number=phone_number)
            update_session(user, state="ACTIVE")
            response_text = "Welcome to CHAR.AI. You can now ask your queries"

    else:
        try:
            rag_result = await asyncio.to_thread(query_rag_service, text)
            response_text = str(rag_result.get("answer") or "I could not find an answer right now.")
        except RuntimeError:
            logger.exception("RAG request failed")
            response_text = "Sorry, I am unable to answer right now. Please try again."
        except Exception:
            logger.exception("Unexpected error while querying RAG service")
            response_text = "Sorry, I am unable to answer right now. Please try again."

    current_state = (get_or_create_session(user).get("state") or "NEW")
    create_log(user=user, state=current_state)
    asyncio.create_task(asyncio.to_thread(_send_whatsapp_message, user, response_text))
    return _message_response(user, response_text)
