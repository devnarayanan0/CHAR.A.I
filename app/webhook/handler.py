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


def _is_whatsapp_event(data: dict) -> bool:
    return isinstance(data.get("entry"), list)


def _has_whatsapp_messages(data: dict) -> bool:
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            if isinstance(messages, list) and messages:
                return True
    return False


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
        logger.info("Sending reply to %s", user_phone)
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
    except requests.Timeout:
        logger.exception("WhatsApp outbound request timed out")
    except requests.RequestException:
        logger.exception("Failed to send outbound WhatsApp message")


async def _process_user_message(user: str, text: str, *, send_whatsapp_reply: bool) -> str:
    logger.info("Received message from %s: %s", user, text)

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

    if send_whatsapp_reply:
        asyncio.create_task(asyncio.to_thread(_send_whatsapp_message, user, response_text))

    return response_text


async def handle_post(req: Request):
    try:
        data = await req.json()
    except Exception:
        logger.exception("Invalid JSON payload")
        return _message_response("unknown", "Sorry, I could not read your message. Please try again.")

    local_parsed = _parse_local_request(data)
    if local_parsed:
        user, text = local_parsed
        response_text = await _process_user_message(user, text, send_whatsapp_reply=False)
        return _message_response(user, response_text)

    if _is_whatsapp_event(data) and not _has_whatsapp_messages(data):
        logger.info("Ignoring non-message WhatsApp event")
        return {"status": "ignored"}

    parsed = _parse_whatsapp_request(data)
    if not parsed:
        logger.info("Webhook payload does not contain a valid message")
        return {"status": "ignored"}

    user, text = parsed
    asyncio.create_task(_process_user_message(user, text, send_whatsapp_reply=True))
    return {"status": "accepted"}
