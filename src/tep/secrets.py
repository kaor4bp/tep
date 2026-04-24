"""Secret classification and host-key encryption."""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .ids import new_id
from .jsoncanon import bytes_hash, canonical_dumps, read_json
from .storage import utc_now

SECRET_SUITE = "aesgcm-hostkey-v1"


@dataclass(frozen=True)
class SecretFinding:
    kind: str
    start: int
    end: int

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "start": self.start, "end": self.end}


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}\b")),
    ("assignment_secret", re.compile(r"(?i)\b(password|passwd|token|api[_-]?key|secret)\s*=\s*[^\s]{8,}")),
)


def classify_secrets(text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            findings.append(SecretFinding(kind=kind, start=match.start(), end=match.end()))
    findings.sort(key=lambda item: (item.start, item.end, item.kind))
    return findings


def has_secrets(text: str) -> bool:
    return bool(classify_secrets(text))


def load_or_create_host_key(root: str | os.PathLike[str]) -> dict[str, Any]:
    path = host_key_path(root)
    if path.exists():
        return read_json(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "id": new_id("HOSTKEY"),
        "record_type": "host_key",
        "suite": SECRET_SUITE,
        "private_key": _b64(os.urandom(32)),
        "created_at": utc_now(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(canonical_dumps(record) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except PermissionError:
        pass
    return record


def host_key_path(root: str | os.PathLike[str]) -> Path:
    return Path(root).expanduser() / "runtime" / "host_keys" / "default.json"


def encrypt_text(root: str | os.PathLike[str], text: str) -> dict[str, Any]:
    key = load_or_create_host_key(root)
    nonce = os.urandom(12)
    plaintext = text.encode("utf-8")
    ciphertext = AESGCM(_unb64(key["private_key"])).encrypt(nonce, plaintext, None)
    findings = [finding.as_dict() for finding in classify_secrets(text)]
    return {
        "encrypted": True,
        "suite": SECRET_SUITE,
        "key_ref": key["id"],
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
        "plaintext_hash": bytes_hash(plaintext),
        "finding_kinds": sorted({finding["kind"] for finding in findings}),
        "findings": findings,
    }


def decrypt_text(root: str | os.PathLike[str], payload: dict[str, Any]) -> str:
    key = load_or_create_host_key(root)
    if payload.get("suite") != SECRET_SUITE:
        raise ValueError("unsupported encrypted payload suite")
    plaintext = AESGCM(_unb64(key["private_key"])).decrypt(_unb64(payload["nonce"]), _unb64(payload["ciphertext"]), None)
    if bytes_hash(plaintext) != payload.get("plaintext_hash"):
        raise ValueError("encrypted payload plaintext hash mismatch")
    return plaintext.decode("utf-8")


def maybe_encrypt_text(root: str | os.PathLike[str], text: str) -> str | dict[str, Any]:
    return encrypt_text(root, text) if has_secrets(text) else text


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
