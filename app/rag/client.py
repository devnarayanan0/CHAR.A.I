from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse
from typing import Any

import requests

from app.config.settings import get_settings

logger = logging.getLogger(__name__)
QUERY_TIMEOUT_SECONDS = 10
INGEST_TIMEOUT_SECONDS = 30
HEALTH_TIMEOUT_SECONDS = 10


def _normalize_service_base_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError("RAG_SERVICE_URL must be an absolute URL")

    if parsed.hostname not in {"localhost", "127.0.0.1"} and parsed.scheme != "https":
        raise RuntimeError("RAG_SERVICE_URL must use HTTPS for remote hosts")

    path = parsed.path.rstrip("/")
    if path.endswith("/query"):
        path = path[: -len("/query")]
    elif path.endswith("/ingest"):
        path = path[: -len("/ingest")]

    normalized = parsed._replace(path=path, params="", query="", fragment="")
    return urlunparse(normalized).rstrip("/")


def _service_base_url() -> str:
    settings = get_settings()
    if not settings.rag_service_url:
        raise RuntimeError("RAG_SERVICE_URL is not configured")
    return _normalize_service_base_url(settings.rag_service_url)


def _health_check_or_raise(base_url: str) -> None:
    health_url = f"{base_url}/health"
    try:
        response = requests.get(health_url, timeout=HEALTH_TIMEOUT_SECONDS)
        logger.info("RAG HEALTH STATUS: %s", response.status_code)
        logger.info("RAG HEALTH RESPONSE: %s", response.text)
        response.raise_for_status()
    except requests.Timeout as exc:
        logger.exception("RAG health timeout url=%s error_type=%s", health_url, type(exc).__name__)
        raise RuntimeError("RAG health check timed out") from exc
    except requests.RequestException as exc:
        logger.exception("RAG health check failed url=%s error_type=%s", health_url, type(exc).__name__)
        raise RuntimeError("RAG health check failed") from exc


def query_rag_service(query: str) -> dict[str, Any]:
    base_url = _service_base_url()
    query_url = f"{base_url}/query"
    payload_to_send: dict[str, str] = {"query": query}

    logger.info("RAG_SERVICE_URL=%s", base_url)
    logger.info("RAG QUERY URL=%s", query_url)
    logger.info("RAG QUERY PAYLOAD=%s", payload_to_send)

    _health_check_or_raise(base_url)

    try:
        response = requests.post(query_url, json=payload_to_send, timeout=QUERY_TIMEOUT_SECONDS)
        logger.info("RAG QUERY STATUS: %s", response.status_code)
        logger.info("RAG QUERY RAW RESPONSE: %s", response.text)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        logger.exception("RAG query timeout url=%s error_type=%s", query_url, type(exc).__name__)
        raise RuntimeError("RAG service timed out") from exc
    except requests.RequestException as exc:
        logger.exception("RAG query request error url=%s error_type=%s", query_url, type(exc).__name__)
        raise RuntimeError("RAG service is unreachable") from exc
    except ValueError as exc:
        logger.exception("RAG query invalid JSON url=%s", query_url)
        raise RuntimeError("RAG service returned invalid JSON") from exc

    if not isinstance(payload, dict):
        logger.error("INVALID RAG RESPONSE FORMAT: response is not an object")
        raise RuntimeError("RAG service returned an invalid response")
    if "answer" not in payload or "context" not in payload:
        logger.error("INVALID RAG RESPONSE FORMAT: missing answer/context keys")
        raise RuntimeError("RAG service response must include answer and context")
    if not isinstance(payload.get("context"), list):
        logger.error("INVALID RAG RESPONSE FORMAT: context is not a list")
        raise RuntimeError("RAG service context must be a list")
    return payload


def test_rag_query(query: str = "hello") -> dict[str, Any]:
    payload_to_send = {"query": query}
    result: dict[str, Any] = {
        "payload": payload_to_send,
    }

    try:
        base_url = _service_base_url()
    except Exception as exc:
        result["config_error"] = f"{type(exc).__name__}: {exc}"
        return result

    query_url = f"{base_url}/query"
    result["rag_service_url"] = base_url
    result["query_url"] = query_url

    try:
        health_response = requests.get(f"{base_url}/health", timeout=HEALTH_TIMEOUT_SECONDS)
        result["health_status"] = health_response.status_code
        result["health_body"] = health_response.text
    except Exception as exc:
        result["health_error"] = f"{type(exc).__name__}: {exc}"
        return result

    try:
        query_response = requests.post(query_url, json=payload_to_send, timeout=QUERY_TIMEOUT_SECONDS)
        result["query_status"] = query_response.status_code
        result["query_body"] = query_response.text
        try:
            result["query_json"] = query_response.json()
        except ValueError:
            result["query_json_error"] = "Response is not valid JSON"
    except Exception as exc:
        result["query_error"] = f"{type(exc).__name__}: {exc}"

    return result


def ingest_rag_service() -> dict[str, Any]:
    try:
        response = requests.post(f"{_service_base_url()}/ingest", timeout=INGEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        raise RuntimeError("RAG ingestion timed out") from exc
    except requests.RequestException as exc:
        raise RuntimeError("RAG ingestion service is unreachable") from exc
    except ValueError as exc:
        raise RuntimeError("RAG ingestion returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("RAG service returned an invalid response")
    return payload