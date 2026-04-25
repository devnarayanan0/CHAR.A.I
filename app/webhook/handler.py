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
    get_user_by_access_code,
    get_or_create_session,
    normalize_user_id,
    update_session,
)

logger = logging.getLogger(__name__)
_ACCESS_CODE_PATTERN = re.compile(r"^\d{5}$")
_HELP_COMMANDS = {"help", "/help", ".help"}

_HELP_TEXT = (
    "Available Commands:\n"
    "- help -> show this message\n"
    "- ask -> ask questions to the AI system\n\n"
    "Note:\n"
    "Access is restricted to authorized users."
)

_WELCOME_TEXT = (
    "Enter your 5-digit access code to continue."
)


async def handle_get(req: Request):
    params = req.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    settings = get_settings()
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return PlainTextResponse(content=challenge or "")

    logger.error("Webhook verification failed")
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
    return "@" in value.strip()


def _is_valid_access_code(value: str) -> bool:
    return bool(_ACCESS_CODE_PATTERN.fullmatch(value.strip()))


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


def _message_response(user: str, message: str) -> dict[str, str]:
    return {"user": user, "message": message}


def normalize_phone(phone: str) -> str:
    return "".join(filter(str.isdigit, phone))


def send_whatsapp_message(user_phone: str, response_text: str) -> None:
    settings = get_settings()
    phone_number_id = settings.whatsapp_phone_number_id.strip()
    access_token = settings.whatsapp_access_token.strip()
    if not phone_number_id or not access_token:
        logger.error("WHATSAPP SEND FAILED: missing credentials")
        return

    to = normalize_phone(user_phone)
    if not to:
        logger.error("WHATSAPP SEND FAILED: invalid recipient phone")
        return

    if not response_text:
        response_text = "Something went wrong. Please try again."

    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": response_text},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
    except Exception:
        logger.exception("WHATSAPP SEND FAILED")


def send_whatsapp_test_message(user_phone: str, response_text: str) -> None:
    send_whatsapp_message(user_phone, response_text)


def _compute_reply_and_update_state(user: str, text: str) -> str:
    session = get_or_create_session(user)
    state_before = session.get("state") or "NEW"
    clean_text = text.strip()
    normalized_text = clean_text.lower()

    if normalized_text in _HELP_COMMANDS:
        create_log(user=user, state=str(state_before))
        return _HELP_TEXT

    response_text = ""
    state_after = state_before

    if state_before == "NEW":
        state_after = "ASK_ACCESS_CODE"
        response_text = _WELCOME_TEXT
        update_session(user, state=state_after)

    elif state_before == "ASK_ACCESS_CODE":
        access_code = clean_text
        if not _is_valid_access_code(access_code):
            state_after = "ASK_ACCESS_CODE"
            response_text = "Invalid access code format. Please enter a 5-digit code."
            update_session(user, state=state_after)
        else:
            access_code_int = _to_access_code_int(access_code)
            existing_user = get_user_by_access_code(access_code_int) if access_code_int is not None else None
            if existing_user is not None:
                state_after = "ACTIVE"
                existing_name = str(existing_user.get("name") or "User")
                response_text = f"Welcome back, {existing_name}. You may continue."
                update_session(
                    user,
                    state=state_after,
                    name=(str(existing_user.get("name")) if existing_user.get("name") else None),
                    email=(str(existing_user.get("email")) if existing_user.get("email") else None),
                    access_code=access_code_int,
                    persist_to_db=True,
                )
            else:
                state_after = "ASK_NAME"
                response_text = "New access detected. Please enter your name."
                update_session(user, state=state_after, access_code=access_code_int)

    elif state_before == "ASK_NAME":
        name = clean_text
        if name:
            state_after = "ASK_EMAIL"
            response_text = "Please enter your email address."
            update_session(user, state=state_after, name=name)
        else:
            state_after = "ASK_NAME"
            response_text = "Invalid input. Please try again."
            update_session(user, state=state_after)

    elif state_before == "ASK_EMAIL":
        email = clean_text
        if not _is_valid_email(email):
            state_after = "ASK_EMAIL"
            response_text = "Invalid input. Please try again."
            update_session(user, state=state_after)
        else:
            registration_access_code = _to_access_code_int(session.get("access_code"))
            if registration_access_code is None:
                state_after = "ASK_ACCESS_CODE"
                response_text = "Enter your 5-digit access code to continue."
                update_session(user, state=state_after)
                current_state = (get_or_create_session(user).get("state") or "NEW")
                create_log(user=user, state=current_state)
                return response_text

            state_after = "ACTIVE"
            response_text = "Registration complete. You can now start using the system."
            update_session(
                user,
                state=state_after,
                name=(str(session.get("name")) if session.get("name") else None),
                email=email,
                access_code=registration_access_code,
                persist_to_db=True,
            )

    elif state_before == "ACTIVE":
        state_after = "ACTIVE"
        response_text = "CALL_RAG"
        update_session(user, state=state_after)

    else:
        state_after = "ASK_ACCESS_CODE"
        response_text = _WELCOME_TEXT
        update_session(user, state=state_after)

    if not response_text:
        response_text = "Something went wrong. Please try again."

    current_state = (get_or_create_session(user).get("state") or "NEW")
    create_log(user=user, state=current_state)

    return response_text


async def _background_send_reply(user: str, text: str, reply: str) -> None:
    final_reply = reply

    if final_reply == "CALL_RAG":
        try:
            rag_result = await asyncio.to_thread(query_rag_service, text)
            final_reply = str(rag_result.get("answer") or "")
        except Exception:
            logger.error("RAG unavailable")
            final_reply = "🚫 Access denied. This service is restricted to authorized users. Please contact the system administrator to request access."

    if not final_reply:
        final_reply = "Something went wrong. Please try again."

    async def safe_send() -> None:
        try:
            await asyncio.to_thread(send_whatsapp_message, user, final_reply)
        except Exception:
            logger.exception("WHATSAPP SEND FAILED")

    await safe_send()


def _schedule_safe_background_send(user: str, text: str, reply: str) -> None:
    async def safe_send() -> None:
        try:
            await _background_send_reply(user, text, reply)
        except Exception:
            logger.exception("WHATSAPP SEND FAILED")

    asyncio.create_task(safe_send())


async def handle_post(req: Request):
    try:
        try:
            data = await req.json()
        except Exception:
            logger.exception("Invalid JSON payload")
            return _message_response("unknown", "Sorry, I could not read your message. Please try again.")

        if "entry" not in data:
            return {"status": "ignored"}

        if _is_whatsapp_event(data) and not _has_whatsapp_messages(data):
            return {"status": "accepted"}

        local_parsed = _parse_local_request(data)
        if local_parsed:
            user, text = local_parsed
            response_text = await asyncio.to_thread(_compute_reply_and_update_state, user, text)
            if response_text == "CALL_RAG":
                try:
                    rag_result = await asyncio.to_thread(query_rag_service, text)
                    response_text = str(rag_result.get("answer") or "")
                except Exception:
                    logger.error("RAG unavailable")
                    response_text = "🚫 Access denied. This service is restricted to authorized users. Please contact the system administrator to request access."
            if not response_text:
                response_text = "Something went wrong. Please try again."
            return _message_response(user, response_text)

        parsed_messages = _extract_whatsapp_messages(data)
        if not parsed_messages:
            return {"status": "accepted"}

        for user, text in parsed_messages:
            reply = await asyncio.to_thread(_compute_reply_and_update_state, user, text)
            if not reply:
                reply = "Something went wrong. Please try again."
            if reply == "CALL_RAG":
                try:
                    rag_result = await asyncio.to_thread(query_rag_service, text)
                    reply = str(rag_result.get("answer") or "")
                except Exception:
                    logger.error("RAG unavailable")
                    reply = "🚫 Access denied. This service is restricted to authorized users. Please contact the system administrator to request access."
            _schedule_safe_background_send(user, text, reply)

        return {"status": "accepted"}
    except Exception as e:
        print("CRASH:", str(e))
        return {"status": "error"}
