"""Source ingestion helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ValidationError
from .jsoncanon import bytes_hash


def ingest_text_payload(
    text: str,
    *,
    supplied_by: str = "user",
    document_kind: str = "message",
    evidence_role: str = "assertion",
    authority_scope: str = "user_supplied_context",
    independence_key: str | None = None,
) -> dict[str, Any]:
    if not text:
        raise ValidationError("ingest_text requires non-empty text")
    return {
        "source_kind": "user_message",
        "quote": text,
        "classification": {
            "input_class": "provided_context",
            "source_class": "user" if supplied_by == "user" else "unknown",
            "document_kind": document_kind,
            "evidence_role": evidence_role,
            "authority_scope": authority_scope,
            "independence_key": independence_key or f"{supplied_by}:provided-text",
        },
        "origin": {"kind": "user_supplied_text", "ref": supplied_by},
        "provenance": {
            "entity_ref": supplied_by,
            "activity_ref": "ingest_text",
            "responsible_agent": "runtime",
            "content_hash": bytes_hash(text.encode("utf-8")),
            "locator": "inline",
            "quote_span": {"start": 0, "end": len(text)},
            "retrieved_at": None,
            "published_at": None,
        },
        "critique_status": "accepted" if supplied_by == "user" and evidence_role in {"intent", "approval"} else "audited",
        "reason": "text ingested through typed source API",
    }


def ingest_file_payload(
    path: str,
    *,
    project_refs: list[str] | None = None,
    source_class: str = "user_supplied_document",
    evidence_role: str = "assertion",
    authority_scope: str = "unknown",
    independence_key: str | None = None,
) -> dict[str, Any]:
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        raise ValidationError(f"file_not_found:{file_path}")
    data = file_path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"unsupported_file_encoding:{file_path}") from exc
    if not text:
        raise ValidationError(f"empty_file:{file_path}")
    content_hash = bytes_hash(data)
    return {
        "source_kind": "file_quote",
        "quote": text,
        "classification": {
            "input_class": "provided_context",
            "source_class": source_class,
            "document_kind": document_kind_for_path(file_path),
            "evidence_role": evidence_role,
            "authority_scope": authority_scope,
            "independence_key": independence_key or f"file:{content_hash}",
        },
        "origin": {"kind": "file", "ref": str(file_path)},
        "provenance": {
            "entity_ref": str(file_path),
            "activity_ref": "ingest_file",
            "responsible_agent": "runtime",
            "content_hash": content_hash,
            "locator": str(file_path),
            "quote_span": {"start": 0, "end": len(text)},
            "retrieved_at": None,
            "published_at": None,
        },
        "project_refs": project_refs or [],
        "critique_status": "audited",
        "reason": "file ingested through typed source API",
    }


def document_kind_for_path(path: Path) -> str:
    suffix = path.suffix.casefold()
    mapping = {
        ".md": "markdown",
        ".txt": "text",
        ".json": "json",
        ".jsonl": "jsonl",
        ".py": "source_code",
        ".js": "source_code",
        ".ts": "source_code",
        ".tsx": "source_code",
        ".rs": "source_code",
        ".go": "source_code",
        ".java": "source_code",
        ".yaml": "config",
        ".yml": "config",
        ".toml": "config",
    }
    return mapping.get(suffix, "text")
