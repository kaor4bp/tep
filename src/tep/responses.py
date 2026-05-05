"""Runtime response envelope and guided move helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PUBLIC_MOVE_TOOL_BY_OPERATION = {
    "brief_current_context": "brief",
    "lookup_facts": "lookup",
    "project_registry_search": "lookup",
    "create_task": "task",
    "attach_agent_to_task": "task",
    "decompose_task": "task",
    "defer_task": "task",
    "compile_context_pack": "task",
    "list_context_packs": "task",
    "revoke_context_pack": "task",
    "create_source": "capture",
    "ingest_text": "capture",
    "ingest_file": "capture",
    "capture_source_excerpt": "capture",
    "capture_source_fragments": "capture",
    "extract_claim_candidates": "capture",
    "confirm_source_for_scope": "capture",
    "capture_input": "capture",
    "capture_bash_command": "capture",
    "capture_run_output_source": "capture",
    "extract_run_claim_candidates": "capture",
    "create_claim": "claim",
    "create_claim_from_evidence": "claim",
    "link_claims": "relate",
    "append_ledger": "reason",
    "validate_ledger": "reason",
    "open_probe": "act",
    "protected_action_preflight": "act",
    "capture_probe_result": "act",
    "close_probe": "act",
    "action_pressure": "act",
    "final_answer_preflight": "finish",
    "task_done_preflight": "finish",
    "final_answer": "finish",
}


@dataclass(frozen=True)
class RuntimeResponse:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    ledger_pressure: dict[str, Any] = field(default_factory=dict)
    index_pressure: list[dict[str, Any]] = field(default_factory=list)
    source_pressure: list[dict[str, Any]] = field(default_factory=list)
    claim_pressure: list[dict[str, Any]] = field(default_factory=list)
    act_pressure: list[dict[str, Any]] = field(default_factory=list)
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
            "act_pressure": self.act_pressure,
            "dedup_pressure": self.dedup_pressure,
            "valid_moves": self.valid_moves,
            "repair_options": self.repair_options,
        }


def move(tool: str, operation_kind: str, why: str, *, writes: bool = False, requires_user: bool = False) -> dict[str, Any]:
    public_tool = PUBLIC_MOVE_TOOL_BY_OPERATION.get(operation_kind)
    effective_tool = public_tool or tool
    return {
        "priority": 10,
        "tool": effective_tool,
        "operation_kind": operation_kind,
        "why": why,
        "writes": writes,
        "requires_user": requires_user,
        "expected_output": "...",
        "legacy_tool": operation_kind if public_tool else None,
    }


def ok_response(
    data: dict[str, Any],
    *,
    ledger_pressure: dict[str, Any] | None = None,
    index_pressure: list[dict[str, Any]] | None = None,
    source_pressure: list[dict[str, Any]] | None = None,
    claim_pressure: list[dict[str, Any]] | None = None,
    act_pressure: list[dict[str, Any]] | None = None,
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
        act_pressure=act_pressure or [],
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
