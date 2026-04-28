"""Runtime response envelope and guided move helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeResponse:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    ledger_pressure: dict[str, Any] = field(default_factory=dict)
    index_pressure: list[dict[str, Any]] = field(default_factory=list)
    source_pressure: list[dict[str, Any]] = field(default_factory=list)
    claim_pressure: list[dict[str, Any]] = field(default_factory=list)
    dedup_pressure: list[dict[str, Any]] = field(default_factory=list)
    valid_moves: list[dict[str, Any]] = field(default_factory=list)
    repair_options: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "ledger_pressure": self.ledger_pressure,
            "index_pressure": self.index_pressure,
            "source_pressure": self.source_pressure,
            "claim_pressure": self.claim_pressure,
            "dedup_pressure": self.dedup_pressure,
            "valid_moves": self.valid_moves,
            "repair_options": self.repair_options,
        }


def move(tool: str, operation_kind: str, why: str, *, writes: bool = False, requires_user: bool = False) -> dict[str, Any]:
    return {
        "priority": 10,
        "tool": tool,
        "operation_kind": operation_kind,
        "why": why,
        "writes": writes,
        "requires_user": requires_user,
        "expected_output": "...",
    }


def ok_response(
    data: dict[str, Any],
    *,
    ledger_pressure: dict[str, Any] | None = None,
    index_pressure: list[dict[str, Any]] | None = None,
    source_pressure: list[dict[str, Any]] | None = None,
    claim_pressure: list[dict[str, Any]] | None = None,
    dedup_pressure: list[dict[str, Any]] | None = None,
    valid_moves: list[dict[str, Any]] | None = None,
) -> RuntimeResponse:
    return RuntimeResponse(
        ok=True,
        data=data,
        ledger_pressure=ledger_pressure or {},
        index_pressure=index_pressure or [],
        source_pressure=source_pressure or [],
        claim_pressure=claim_pressure or [],
        dedup_pressure=dedup_pressure or [],
        valid_moves=valid_moves or [],
    )


def error_response(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    dedup_pressure: list[dict[str, Any]] | None = None,
    repair_options: list[dict[str, Any]] | None = None,
) -> RuntimeResponse:
    return RuntimeResponse(
        ok=False,
        error={"code": code, "message": message, "details": details or {}},
        dedup_pressure=dedup_pressure or [],
        repair_options=repair_options or [],
    )
