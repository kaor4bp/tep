"""Protocol identifier helpers."""

from __future__ import annotations

import re
import secrets
import string
from datetime import UTC, date, datetime

_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]*$")
_TOKEN_ALPHABET = string.ascii_letters + string.digits
LEGACY_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]*)-(\d{8})-([0-9a-f]{32,})\b")
PROTOCOL_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]*)-(\d{8})-([A-Za-z0-9]+)\b")


def new_id(prefix: str, *, when: date | datetime | None = None, random_bytes: int = 16, random_chars: int | None = None) -> str:
    """Create an id like ``CLM-20260424-Ab3x...``."""

    if not _PREFIX_RE.match(prefix):
        raise ValueError(f"invalid id prefix: {prefix!r}")
    if random_chars is None:
        random_chars = max(10, random_bytes)
    if random_chars < 10:
        raise ValueError("random_chars must be at least 10")
    if when is None:
        when = datetime.now(UTC)
    if isinstance(when, datetime):
        day = when.astimezone(UTC).strftime("%Y%m%d")
    else:
        day = when.strftime("%Y%m%d")
    token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(random_chars))
    return f"{prefix}-{day}-{token}"


def is_legacy_hex_id(value: str) -> bool:
    return bool(LEGACY_ID_RE.fullmatch(value))


def shorten_legacy_id(value: str, *, random_chars: int = 16, used: set[str] | None = None) -> str:
    match = LEGACY_ID_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"not a legacy hex id: {value!r}")
    used = used if used is not None else set()
    prefix, day, _hex = match.groups()
    while True:
        candidate = new_id(prefix, when=datetime.strptime(day, "%Y%m%d").replace(tzinfo=UTC), random_chars=random_chars)
        if candidate not in used:
            used.add(candidate)
            return candidate


def ledger_id(number: int) -> str:
    if number < 0:
        raise ValueError("ledger id number must be non-negative")
    return f"L-{number:06d}"


def parse_ledger_id(value: str) -> int:
    if not re.match(r"^L-\d{6}$", value):
        raise ValueError(f"invalid ledger id: {value!r}")
    return int(value[2:])
