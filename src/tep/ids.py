"""Protocol identifier helpers."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, date, datetime

_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]*$")


def new_id(prefix: str, *, when: date | datetime | None = None, random_bytes: int = 24) -> str:
    """Create an id like ``CLM-20260424-<long random hex>``."""

    if not _PREFIX_RE.match(prefix):
        raise ValueError(f"invalid id prefix: {prefix!r}")
    if random_bytes < 16:
        raise ValueError("random_bytes must be at least 16")
    if when is None:
        when = datetime.now(UTC)
    if isinstance(when, datetime):
        day = when.astimezone(UTC).strftime("%Y%m%d")
    else:
        day = when.strftime("%Y%m%d")
    return f"{prefix}-{day}-{secrets.token_hex(random_bytes)}"


def ledger_id(number: int) -> str:
    if number < 0:
        raise ValueError("ledger id number must be non-negative")
    return f"L-{number:06d}"


def parse_ledger_id(value: str) -> int:
    if not re.match(r"^L-\d{6}$", value):
        raise ValueError(f"invalid ledger id: {value!r}")
    return int(value[2:])

