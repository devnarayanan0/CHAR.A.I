from __future__ import annotations

import asyncio
import logging
import re

import requests

from fastapi import Request
from fastapi.responses import PlainTextResponse

from app.admin.log_store import create_log
from app.config.settings import get_settings
from app.rag.client import query_rag_service
from app.users.service import (
    get_or_create_session,
    normalize_user_id,
    update_session,
)

logger = logging.getLogger(__name__)
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def _extract_whatsapp_messages(data: dict) -> list[tuple[str, str]]:
    extracted: list[tuple[str, str]] = []
    entries = data.get("entry", [])
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                user = normalize_user_id(message.get("from"))
                if not user:
                    continue
                text = ((message.get("text") or {}).get("body") or "").strip()
                if text:
                    extracted.append((user, text))
    return extracted


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


def _is_valid_email(value: str) -> bool:
    return bool(_EMAIL_PATTERN.fullmatch(value.strip()))


def _message_response(user: str, message: str) -> dict[str, str]:
    return {"user": user, "message": message}


def send_whatsapp_message(user_phone: str, response_text: str) -> None:
    settings = get_settings()
    phone_number_id = settings.whatsapp_phone_number_id.strip()
    access_token = settings.whatsapp_access_token.strip()
    if not phone_number_id or not access_token:
        logger.warning("WhatsApp outbound config missing; skipping outbound message")
        return

    if not response_text:
        response_text = "Something went wrong. Please try again."

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
        print("Sending reply:", response_text)
        logger.info("Sending reply to %s", user_phone)
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        logger.info("WhatsApp API response status=%s body=%s", response.status_code, response.text)
        print("WHATSAPP STATUS:", response.status_code)
        print("WHATSAPP RESPONSE:", response.text)
        response.raise_for_status()
    except Exception as exc:
        logger.exception("Failed to send outbound WhatsApp message")
        print("WHATSAPP ERROR:", str(exc))


def send_whatsapp_test_message(user_phone: str, response_text: str) -> None:
    send_whatsapp_message(user_phone, response_text)


def _compute_reply_and_update_state(user: str, text: str) -> str:
    session = get_or_create_session(user)
    state_before = session.get("state") or "NEW"
    response_text = ""
    state_after = state_before

    if state_before == "NEW":
        state_after = "ASK_NAME"
        response_text = "Hi! What is your name?"
        update_session(user, state=state_after)

    elif state_before == "ASK_NAME":
        name = text.strip()
        if name:
            state_after = "ASK_EMAIL"
            response_text = "Enter your email"
            update_session(user, state=state_after, name=name)
        else:
            state_after = "ASK_NAME"
            response_text = "Something went wrong. Please try again."
            update_session(user, state=state_after)

    elif state_before == "ASK_EMAIL":
        email = text.strip()
        if not _is_valid_email(email):
            state_after = "ASK_EMAIL"
            response_text = "Invalid email, try again"
            update_session(user, state=state_after)
        else:
            name = str(session.get("name") or "User")
            state_after = "ACTIVE"
            response_text = f"Welcome {name}!"
            update_session(user, state=state_after, email=email)

    elif state_before == "ACTIVE":
        state_after = "ACTIVE"
        response_text = "CALL_RAG"
        update_session(user, state=state_after)

    else:
        state_after = "ASK_NAME"
        response_text = "Hi! What is your name?"
        update_session(user, state=state_after)

    if not response_text:
        response_text = "Something went wrong. Please try again."

    logger.info("State before=%s after=%s reply=%s", state_before, state_after, response_text)
    current_state = (get_or_create_session(user).get("state") or "NEW")
    create_log(user=user, state=current_state)

    return response_text


async def _background_send_reply(user: str, text: str, reply: str) -> None:
    print("=== BACKGROUND START ===")
    final_reply = reply

    if final_reply == "CALL_RAG":
        try:
            rag_result = await asyncio.to_thread(query_rag_service, text)
            final_reply = str(rag_result.get("answer") or "")
        except Exception:
            logger.exception("RAG request failed")
            final_reply = "Sorry, I couldn't process your request right now."

    if not final_reply:
        final_reply = "Something went wrong. Please try again."

    print("Sending reply:", final_reply)
    logger.info("Final reply for %s: %s", user, final_reply)
    await asyncio.to_thread(send_whatsapp_message, user, final_reply)


async def handle_post(req: Request):
    try:
        data = await req.json()
    except Exception:
        logger.exception("Invalid JSON payload")
        return _message_response("unknown", "Sorry, I could not read your message. Please try again.")

    print("=== WEBHOOK HIT ===")
    print("RAW BODY:", data)

    entry = data.get("entry", [])
    changes = entry[0].get("changes", []) if entry else []
    value = changes[0].get("value", {}) if changes else {}
    messages = value.get("messages")
    if _is_whatsapp_event(data) and not messages:
        print("No messages in payload")
        logger.info("Ignoring non-message WhatsApp event")
        return {"status": "accepted"}

    local_parsed = _parse_local_request(data)
    if local_parsed:
        user, text = local_parsed
        print("STEP 1: parsing payload")
        print("STEP 2: sender =", user)
        print("STEP 3: text =", text)
        state_before = (await asyncio.to_thread(get_or_create_session, user)).get("state") or "NEW"
        print("STEP 4: state before =", state_before)
        response_text = await asyncio.to_thread(_compute_reply_and_update_state, user, text)
        print("STEP 5: reply =", response_text)
        if response_text == "CALL_RAG":
            try:
                rag_result = await asyncio.to_thread(query_rag_service, text)
                response_text = str(rag_result.get("answer") or "")
            except Exception:
                response_text = "Sorry, I couldn't process your request right now."
        if not response_text:
            response_text = "Something went wrong. Please try again."
        return _message_response(user, response_text)

    parsed_messages = _extract_whatsapp_messages(data)
    if not parsed_messages:
        logger.info("Webhook payload does not contain valid WhatsApp messages")
        return {"status": "accepted"}

    for user, text in parsed_messages:
        print("STEP 1: parsing payload")
        print("STEP 2: sender =", user)
        print("STEP 3: text =", text)
        state_before = (await asyncio.to_thread(get_or_create_session, user)).get("state") or "NEW"
        print("STEP 4: state before =", state_before)
        logger.info("Received message from %s: %s", user, text)
        reply = await asyncio.to_thread(_compute_reply_and_update_state, user, text)
        if not reply:
            reply = "Something went wrong. Please try again."
        print("STEP 5: reply =", reply)
        print("STEP 6: scheduling background task")
        asyncio.create_task(_background_send_reply(user, text, reply))

    return {"status": "accepted"}
