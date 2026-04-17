from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.config.settings import get_settings
from app.embeddings.model import embed
from app.vectordb.pinecone_client import delete_vectors, get_vector_count, upsert_chunks

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
STATE_FILE_NAME = ".ingestion_state.json"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def _data_dir() -> Path:
    settings = get_settings()
    path = Path(settings.data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_file() -> Path:
    return _data_dir() / STATE_FILE_NAME


def _load_state() -> dict[str, Any]:
    state_file = _state_file()
    if not state_file.exists():
        return {"files": {}}

    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read ingestion state, rebuilding it from scratch")
        return {"files": {}}


def _save_state(state: dict[str, Any]) -> None:
    _state_file().write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _compute_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError(f"Unsupported file type: {path.name}")


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def load_local_documents() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    data_dir = _data_dir()
    state = _load_state()
    known_files = state.setdefault("files", {})

    changed_documents: list[dict[str, Any]] = []
    current_paths: set[str] = set()

    for path in sorted(data_dir.rglob("*")):
        if not path.is_file() or path.name == STATE_FILE_NAME or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        relative_path = path.relative_to(data_dir).as_posix()
        current_paths.add(relative_path)

        try:
            file_hash = _compute_md5(path)
            previous = known_files.get(relative_path)
            if previous and previous.get("md5") == file_hash:
                continue

            raw_text = _extract_text(path)
            cleaned_text = _normalize_text(raw_text)
            if not cleaned_text:
                logger.info("Skipping empty file: %s", relative_path)
                continue

            changed_documents.append(
                {
                    "path": path,
                    "source": relative_path,
                    "md5": file_hash,
                    "text": cleaned_text,
                    "previous_ids": previous.get("ids", []) if previous else [],
                }
            )
        except Exception as exc:
            logger.warning("Skipping unreadable file %s: %s", relative_path, exc)

    removed_documents: list[dict[str, Any]] = []
    for relative_path in sorted(set(known_files.keys()) - current_paths):
        removed_documents.append(
            {
                "source": relative_path,
                "ids": known_files.get(relative_path, {}).get("ids", []),
            }
        )

    return changed_documents, removed_documents, state


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    cleaned = _normalize_text(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    text_length = len(cleaned)

    while start < text_length:
        end = min(text_length, start + chunk_size)
        if end < text_length:
            whitespace = cleaned.rfind(" ", start + max(1, chunk_size - 80), end)
            if whitespace > start:
                end = whitespace

        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        next_start = max(0, end - overlap)
        while next_start > start and next_start < text_length and not cleaned[next_start - 1].isspace():
            next_start -= 1
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def generate_embeddings(chunks: list[str]) -> list[list[float]]:
    return [embed(chunk) for chunk in chunks]


def upsert_to_pinecone(source: str, chunks: list[str], embeddings: list[list[float]], file_hash: str) -> list[str]:
    records = []
    ids: list[str] = []
    for index, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=True)):
        record_id = f"{source.replace('/', '--')}::{file_hash[:12]}::{index}"
        ids.append(record_id)
        records.append(
            {
                "id": record_id,
                "values": vector,
                "metadata": {
                    "text": chunk,
                    "source": source,
                },
            }
        )

    upsert_chunks(records)
    return ids


def ingest_local_documents() -> dict[str, int]:
    changed_documents, removed_documents, state = load_local_documents()
    known_files = state.setdefault("files", {})

    removed = 0
    for document in removed_documents:
        delete_vectors(document["ids"])
        known_files.pop(document["source"], None)
        removed += 1

    processed = 0
    skipped = 0
    uploaded = 0

    for document in changed_documents:
        chunks = chunk_text(document["text"])
        if not chunks:
            skipped += 1
            continue

        embeddings = generate_embeddings(chunks)
        delete_vectors(document["previous_ids"])
        ids = upsert_to_pinecone(document["source"], chunks, embeddings, document["md5"])
        known_files[document["source"]] = {
            "md5": document["md5"],
            "ids": ids,
        }
        processed += 1
        uploaded += len(ids)

    _save_state(state)
    result = {
        "processed_files": processed,
        "removed_files": removed,
        "skipped_files": skipped,
        "uploaded_chunks": uploaded,
    }

    logger.info(
        "Ingestion summary processed=%s removed=%s skipped=%s uploaded_chunks=%s",
        result["processed_files"],
        result["removed_files"],
        result["skipped_files"],
        result["uploaded_chunks"],
    )
    try:
        logger.info("Pinecone total_vector_count=%s", get_vector_count())
    except Exception as exc:
        logger.warning("Unable to fetch Pinecone vector count: %s", exc)

    return result
