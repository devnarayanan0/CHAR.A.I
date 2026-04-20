from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse
from typing import Any

import requests

from app.config.settings import get_settings

logger = logging.getLogger(__name__)
QUERY_TIMEOUT_SECONDS = 15
INGEST_TIMEOUT_SECONDS = 30


def _rag_unavailable_response() -> dict[str, Any]:
    return {
        "answer": "RAG service unavailable",
        "context": [],
    }


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


def query_rag_service(query: str) -> dict[str, Any]:
    try:
        base_url = _service_base_url()
    except Exception:
        logger.error("RAG ERROR: RAG_SERVICE_URL configuration error")
        return _rag_unavailable_response()

    query_url = f"{base_url}/query"
    payload_to_send: dict[str, str] = {"query": query}

    try:
        health = requests.get(f"{base_url}/health", timeout=5)
        health.raise_for_status()
    except requests.Timeout:
        logger.error("RAG ERROR: timeout on /health")
        return _rag_unavailable_response()
    except requests.RequestException as e:
        logger.error("RAG ERROR: unreachable: %s", e)
        return _rag_unavailable_response()

    try:
        response = requests.post(query_url, json=payload_to_send, timeout=QUERY_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout:
        logger.error("RAG ERROR: timeout on /query")
        return _rag_unavailable_response()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status == 404:
            logger.error("RAG ERROR: wrong endpoint: %s", query_url)
        elif status == 500:
            logger.error("RAG ERROR: internal error")
        else:
            logger.error("RAG ERROR: query failed with HTTP %s", status)
        return _rag_unavailable_response()
    except requests.RequestException as exc:
        logger.error("RAG ERROR: unreachable: %s", exc)
        return _rag_unavailable_response()
    except ValueError:
        logger.error("RAG ERROR: non-JSON response")
        return _rag_unavailable_response()

    if not isinstance(payload, dict):
        logger.error("RAG ERROR: response is not a JSON object")
        return _rag_unavailable_response()
    if "answer" not in payload or "context" not in payload:
        logger.error("RAG ERROR: missing answer/context keys")
        return _rag_unavailable_response()
    if not isinstance(payload.get("context"), list):
        logger.error("RAG ERROR: context is not a list")
        return _rag_unavailable_response()
    return payload


def ingest_rag_service() -> dict[str, Any]:
    try:
        base_url = _service_base_url()
        ingest_url = f"{base_url}/ingest"
    except Exception:
        logger.error("RAG ERROR: RAG_SERVICE_URL configuration error")
        raise RuntimeError("RAG_SERVICE_URL not configured") from None

    try:
        response = requests.post(ingest_url, timeout=INGEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        logger.error("RAG ERROR: timeout on /ingest")
        raise RuntimeError("RAG ingestion timed out") from exc
    except requests.RequestException as exc:
        logger.error("RAG ERROR: ingestion service unreachable: %s", exc)
        raise RuntimeError("RAG ingestion service is unreachable") from exc
    except ValueError as exc:
        logger.error("RAG ERROR: ingestion returned invalid JSON")
        raise RuntimeError("RAG ingestion returned invalid JSON") from exc

    return payload