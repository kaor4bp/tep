"""Canonical JSON helpers used by hashes, seals, and dedup keys."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import CanonicalJSONError


def _validate_canonical_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, str) or isinstance(value, bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise CanonicalJSONError(f"floats are forbidden in signed JSON at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONError(f"object key is not a string at {path}")
            _validate_canonical_value(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _validate_canonical_value(item, f"{path}[{index}]")
        return
    raise CanonicalJSONError(f"unsupported canonical JSON value at {path}: {type(value).__name__}")


def canonical_dumps(value: Any) -> str:
    """Return deterministic JSON text.

    This is intentionally stricter than generic JSON. Signed protocol material
    rejects floats to avoid cross-runtime representation drift.
    """

    _validate_canonical_value(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(value: Any) -> bytes:
    return canonical_dumps(value).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def bytes_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def loads_no_duplicates(text: str) -> Any:
    def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CanonicalJSONError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=object_pairs_hook)


def read_json(path: Path) -> Any:
    return loads_no_duplicates(path.read_text(encoding="utf-8"))

