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
    logger.info("📂 Scanning data directory: %s", data_dir)
    state = _load_state()
    known_files = state.setdefault("files", {})

    changed_documents: list[dict[str, Any]] = []
    current_paths: set[str] = set()
    
    all_files = []
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file() or path.name == STATE_FILE_NAME or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        all_files.append(path.relative_to(data_dir).as_posix())
    
    logger.info("📄 Files found: %s", all_files)

    for path in sorted(data_dir.rglob("*")):
        if not path.is_file() or path.name == STATE_FILE_NAME or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        relative_path = path.relative_to(data_dir).as_posix()
        current_paths.add(relative_path)
        
        logger.info("🔄 Processing file: %s", relative_path)

        try:
            file_hash = _compute_md5(path)
            previous = known_files.get(relative_path)
            if previous and previous.get("md5") == file_hash:
                logger.info("⏭ File unchanged (md5 match), skipping: %s", relative_path)
                continue

            logger.info("📖 Extracting text from: %s", relative_path)
            raw_text = _extract_text(path)
            logger.debug("📝 Raw text length: %d chars", len(raw_text))
            
            cleaned_text = _normalize_text(raw_text)
            logger.debug("✨ Normalized text length: %d chars", len(cleaned_text))
            
            if not cleaned_text:
                logger.info("⏭ Skipping empty file: %s", relative_path)
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
            logger.info("✓ File queued for processing: %s", relative_path)
        except Exception as exc:
            logger.warning("❌ Skipping unreadable file %s: %s", relative_path, exc)

    removed_documents: list[dict[str, Any]] = []
    for relative_path in sorted(set(known_files.keys()) - current_paths):
        removed_documents.append(
            {
                "source": relative_path,
                "ids": known_files.get(relative_path, {}).get("ids", []),
            }
        )
        logger.info("🗑 Marking for deletion: %s", relative_path)

    return changed_documents, removed_documents, state


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    cleaned = _normalize_text(text)
    if not cleaned:
        logger.warning("⚠ chunk_text called with empty or whitespace-only text")
        return []

    chunks: list[str] = []
    start = 0
    text_length = len(cleaned)
    
    logger.debug("🔪 Chunking text: length=%d chunk_size=%d overlap=%d", text_length, chunk_size, overlap)

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

    logger.info("✓ Chunks created: %d (from %d chars)", len(chunks), text_length)
    return chunks


def generate_embeddings(chunks: list[str]) -> list[list[float]]:
    logger.info("🤖 Generating embeddings for %d chunks...", len(chunks))
    embeddings = []
    for idx, chunk in enumerate(chunks):
        try:
            embedding = embed(chunk)
            embeddings.append(embedding)
            if (idx + 1) % 5 == 0 or idx == len(chunks) - 1:
                logger.debug("🤖 Embedded %d/%d chunks", idx + 1, len(chunks))
        except Exception as exc:
            logger.exception("❌ Embedding generation failed for chunk %d", idx)
            raise RuntimeError(f"Embedding failed for chunk {idx}: {exc}") from exc
    
    logger.info("✓ Embeddings generated for %d chunks", len(embeddings))
    return embeddings


def upsert_to_pinecone(source: str, chunks: list[str], embeddings: list[list[float]], file_hash: str) -> list[str]:
    logger.info("📤 Preparing Pinecone upsert for source: %s", source)
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
        logger.debug("📌 Record prepared: %s", record_id[:50])

    logger.info("⬆ Upserting %d records to Pinecone...", len(records))
    try:
        upsert_chunks(records)
        logger.info("✓ Upserted %d records successfully", len(records))
    except Exception as exc:
        logger.exception("❌ Pinecone upsert failed")
        raise RuntimeError(f"Pinecone upsert failed: {exc}") from exc
    
    return ids


def ingest_local_documents() -> dict[str, int]:
    logger.info("=== INGESTION PIPELINE START ===")
    changed_documents, removed_documents, state = load_local_documents()
    known_files = state.setdefault("files", {})

    logger.info("📊 Ingestion plan: %d changed, %d removed", len(changed_documents), len(removed_documents))

    # Remove deleted files
    removed = 0
    for document in removed_documents:
        logger.info("🗑 Deleting %d vectors for removed source: %s", len(document["ids"]), document["source"])
        try:
            delete_vectors(document["ids"])
            known_files.pop(document["source"], None)
            removed += 1
            logger.info("✓ Deleted %d vectors", len(document["ids"]))
        except Exception as exc:
            logger.exception("❌ Failed to delete vectors for %s", document["source"])
            raise RuntimeError(f"Delete failed for {document['source']}: {exc}") from exc

    processed = 0
    skipped = 0
    uploaded = 0

    # Process changed files
    for document in changed_documents:
        source = document["source"]
        logger.info("🔄 Processing source: %s", source)
        
        try:
            # Step 1: Chunk
            logger.info("1️⃣ Chunking document: %s", source)
            chunks = chunk_text(document["text"])
            if not chunks:
                logger.warning("⏭ No chunks created for %s", source)
                skipped += 1
                continue
            logger.info("✓ Chunk step complete: %d chunks", len(chunks))

            # Step 2: Embed
            logger.info("2️⃣ Embedding %d chunks for: %s", len(chunks), source)
            embeddings = generate_embeddings(chunks)
            logger.info("✓ Embedding step complete: %d embeddings", len(embeddings))

            # Step 3: Delete previous
            if document["previous_ids"]:
                logger.info("3️⃣ Deleting %d previous vectors for: %s", len(document["previous_ids"]), source)
                try:
                    delete_vectors(document["previous_ids"])
                    logger.info("✓ Deleted previous vectors")
                except Exception as exc:
                    logger.warning("❌ Failed to delete previous vectors: %s", exc)

            # Step 4: Upsert
            logger.info("4️⃣ Upserting embeddings for: %s", source)
            ids = upsert_to_pinecone(source, chunks, embeddings, document["md5"])
            known_files[source] = {
                "md5": document["md5"],
                "ids": ids,
            }
            processed += 1
            uploaded += len(ids)
            logger.info("✓ Source complete: %s (uploaded %d vectors)", source, len(ids))
        except Exception as exc:
            logger.exception("❌ Failed to process source: %s", source)
            raise RuntimeError(f"Ingestion failed for {source}: {exc}") from exc

    # Save state
    logger.info("💾 Saving ingestion state...")
    _save_state(state)
    logger.info("✓ State saved")

    result = {
        "processed_files": processed,
        "removed_files": removed,
        "skipped_files": skipped,
        "uploaded_chunks": uploaded,
    }

    logger.info("=== INGESTION PIPELINE COMPLETE ===")
    logger.info("📊 Summary: processed=%d removed=%d skipped=%d uploaded=%d",
                result["processed_files"],
                result["removed_files"],
                result["skipped_files"],
                result["uploaded_chunks"])
    
    try:
        total_vectors = get_vector_count()
        logger.info("📈 Pinecone total_vector_count=%d", total_vectors)
    except Exception as exc:
        logger.warning("⚠ Unable to fetch Pinecone vector count: %s", exc)

    return result
