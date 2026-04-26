from __future__ import annotations

import asyncio
import logging
import re

import requests

from fastapi import Request
from fastapi.responses import PlainTextResponse

from app.admin.log_store import log_message
from app.config.settings import get_settings
from app.rag.client import FALLBACK_MESSAGE, query_rag_service
from app.users.service import (
    get_user_by_access_code,
    get_or_create_session,
    normalize_user_id,
    reset_session,
    update_session,
)

logger = logging.getLogger(__name__)
_ACCESS_CODE_PATTERN = re.compile(r"^\d{6}$")
_HELP_COMMANDS = {"help", "/help", ".help"}

_HELP_TEXT = (
    "Available Commands:\n"
    "- help -> show this message\n"
    "- ask -> ask questions to the AI system\n\n"
    "Note:\n"
    "Access is restricted to authorized users."
)

_WELCOME_TEXT = (
    "Enter Access Code!"
)

_REGISTRATION_COMPLETE = "__REGISTRATION_COMPLETE__"


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


def _current_access_code(user: str) -> int | None:
    session = get_or_create_session(user)
    return _to_access_code_int(session.get("access_code"))


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
        response_text = FALLBACK_MESSAGE

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
        logger.error("WHATSAPP SEND FAILED")


def send_whatsapp_test_message(user_phone: str, response_text: str) -> None:
    send_whatsapp_message(user_phone, response_text)


def _compute_reply_and_update_state(user: str, text: str) -> str:
    session = get_or_create_session(user)
    state_before = session.get("state") or "NEW"
    clean_text = text.strip()
    normalized_text = clean_text.lower()

    if normalized_text in _HELP_COMMANDS:
        return _HELP_TEXT

    response_text = ""
    state_after = state_before

    if state_before == "NEW":
        session = reset_session(user)
        state_after = str(session.get("state") or "ASK_ACCESS_CODE")
        response_text = _WELCOME_TEXT

    elif state_before == "ASK_ACCESS_CODE":
        access_code = clean_text
        if not _is_valid_access_code(access_code):
            state_after = "ASK_ACCESS_CODE"
            response_text = "Invalid access code format. Please enter a 6-digit code."
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
                response_text = "Please enter your name."
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
                response_text = _WELCOME_TEXT
                update_session(user, state=state_after)
                return response_text

            state_after = "ACTIVE"
            response_text = _REGISTRATION_COMPLETE
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
        session = reset_session(user)
        state_after = str(session.get("state") or "ASK_ACCESS_CODE")
        response_text = _WELCOME_TEXT

    if not response_text:
        response_text = "Something went wrong. Please try again."

    return response_text


async def _post_registration_rag_check(user: str) -> str:
    try:
        rag_result = await asyncio.to_thread(query_rag_service, "hello")
    except Exception:
        logger.error("RAG unavailable → fallback triggered")
        return FALLBACK_MESSAGE

    answer = str(rag_result.get("answer", FALLBACK_MESSAGE))
    if answer == FALLBACK_MESSAGE:
        logger.error("RAG unavailable → fallback triggered")
        return FALLBACK_MESSAGE

    return ""


async def _send_registration_welcome_and_check(user: str) -> None:
    welcome_text = "Welcome to CHAR.A.I !"
    log_message(user, "assistant", welcome_text)
    await asyncio.to_thread(send_whatsapp_message, user, welcome_text)
    fallback_reply = await _post_registration_rag_check(user)
    if fallback_reply:
        log_message(user, "assistant", fallback_reply)
        await asyncio.to_thread(send_whatsapp_message, user, fallback_reply)


async def _background_send_reply(user: str, text: str, reply: str) -> None:
    final_reply = reply

    if final_reply == "CALL_RAG":
        try:
            rag_result = await asyncio.to_thread(query_rag_service, text)
            final_reply = str(rag_result.get("answer", FALLBACK_MESSAGE))
        except Exception:
            logger.error("RAG unavailable → fallback triggered")
            final_reply = FALLBACK_MESSAGE

    if not final_reply:
        final_reply = FALLBACK_MESSAGE

    async def safe_send() -> None:
        try:
            await asyncio.to_thread(send_whatsapp_message, user, final_reply)
        except Exception:
            logger.error("WHATSAPP SEND FAILED")

    await safe_send()


def _schedule_safe_background_send(user: str, text: str, reply: str) -> None:
    async def safe_send() -> None:
        try:
            await _background_send_reply(user, text, reply)
        except Exception:
            logger.error("WHATSAPP SEND FAILED")

    asyncio.create_task(safe_send())


async def handle_post(req: Request):
    try:
        try:
            data = await req.json()
        except Exception:
            logger.error("Invalid JSON payload")
            return _message_response("unknown", FALLBACK_MESSAGE)

        if "entry" not in data:
            return {"status": "ignored"}

        if _is_whatsapp_event(data) and not _has_whatsapp_messages(data):
            return {"status": "accepted"}

        local_parsed = _parse_local_request(data)
        if local_parsed:
            user, text = local_parsed
            log_message(user, "user", text)
            response_text = await asyncio.to_thread(_compute_reply_and_update_state, user, text)
            if response_text == _REGISTRATION_COMPLETE:
                fallback_reply = await _post_registration_rag_check(user)
                response_text = fallback_reply or "Welcome to CHAR.A.I !"
            if response_text == "CALL_RAG":
                try:
                    rag_result = await asyncio.to_thread(query_rag_service, text)
                    response_text = str(rag_result.get("answer", FALLBACK_MESSAGE))
                except Exception:
                    logger.error("RAG unavailable → fallback triggered")
                    response_text = FALLBACK_MESSAGE
            if not response_text:
                response_text = FALLBACK_MESSAGE
            log_message(user, "assistant", response_text)
            return _message_response(user, response_text)

        parsed_messages = _extract_whatsapp_messages(data)
        if not parsed_messages:
            return {"status": "accepted"}

        for user, text in parsed_messages:
            log_message(user, "user", text)
            reply = await asyncio.to_thread(_compute_reply_and_update_state, user, text)
            if reply == _REGISTRATION_COMPLETE:
                asyncio.create_task(_send_registration_welcome_and_check(user))
                continue
            if not reply:
                reply = FALLBACK_MESSAGE
            if reply == "CALL_RAG":
                try:
                    rag_result = await asyncio.to_thread(query_rag_service, text)
                    reply = str(rag_result.get("answer", FALLBACK_MESSAGE))
                except Exception:
                    logger.error("RAG unavailable → fallback triggered")
                    reply = FALLBACK_MESSAGE
            log_message(user, "assistant", reply)
            _schedule_safe_background_send(user, text, reply)

        return {"status": "accepted"}
    except Exception as e:
        logger.error("DB ERROR: %s", str(e))
        return {"status": "error"}
