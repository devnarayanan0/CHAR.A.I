from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse
from typing import Any

import requests

from app.config.settings import get_settings

logger = logging.getLogger(__name__)
QUERY_TIMEOUT_SECONDS = 10
INGEST_TIMEOUT_SECONDS = 30


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
    base_url = _service_base_url()
    query_url = f"{base_url}/query"
    payload_to_send: dict[str, str] = {"query": query}

    try:
        response = requests.post(query_url, json=payload_to_send, timeout=QUERY_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        raise RuntimeError("RAG service timed out") from exc
    except requests.RequestException as exc:
        raise RuntimeError("RAG service is unreachable") from exc
    except ValueError as exc:
        raise RuntimeError("RAG service returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("RAG service returned an invalid response")
    if "answer" not in payload or "context" not in payload:
        raise RuntimeError("RAG service response must include answer and context")
    if not isinstance(payload.get("context"), list):
        raise RuntimeError("RAG service context must be a list")
    return payload


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