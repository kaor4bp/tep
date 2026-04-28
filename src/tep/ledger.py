"""Agent-owned sealed reasoning ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .crypto import SEAL_SUITE, assert_private_key_matches, sign, verify
from .errors import OwnershipError, ValidationError
from .ids import ledger_id
from .jsoncanon import canonical_bytes, canonical_hash
from .pow import mine_pow, verify_pow
from .storage import TEPHome, utc_now


@dataclass(frozen=True)
class LedgerValidation:
    ok: bool
    head: str | None
    row_count: int
    open_act: str | None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LedgerAppendResult:
    row: dict[str, Any]
    state_hash: str
    append_hash: str


@dataclass
class _ReplayState:
    validation: LedgerValidation
    rows: list[dict[str, Any]]
    state_by_id: dict[str, str]
    append_hash: str


class Ledger:
    def __init__(self, store: TEPHome, workspace_ref: str, agent_ref: str) -> None:
        self.store = store
        self.workspace_ref = workspace_ref
        self.agent_ref = agent_ref

    def append_claim(
        self,
        *,
        private_key: str,
        claim_ref: str,
        why: str,
        kind: str = "claim",
        prev: str | None = None,
            difficulty_bits: int = 18,
    ) -> LedgerAppendResult:
        if kind not in {"claim", "relation"}:
            raise ValidationError("append_claim supports only claim or relation rows")
        return self._append_claim_snapshot(
            private_key=private_key,
            claim_ref=claim_ref,
            why=why,
            kind=kind,
            prev=prev,
            difficulty_bits=difficulty_bits,
            require_existing_snapshot=False,
        )

    def open_probe(
        self,
        *,
        private_key: str,
        claim_ref: str,
        why: str,
        intent: str,
        allowed_action_kind: str,
        expected_evidence: str,
        scope: dict[str, Any] | None = None,
        difficulty_bits: int = 18,
    ) -> LedgerAppendResult:
        return self._append_claim_snapshot(
            private_key=private_key,
            claim_ref=claim_ref,
            why=why,
            kind="act",
            difficulty_bits=difficulty_bits,
            require_existing_snapshot=True,
            extra={
                "act": {
                    "intent": intent,
                    "allowed_action_kind": allowed_action_kind,
                    "expected_evidence": expected_evidence,
                    "scope": scope or {},
                }
            },
        )

    def capture_probe_result(
        self,
        *,
        private_key: str,
        claim_ref: str,
        why: str,
        evidence_ref: str,
        summary: str,
        difficulty_bits: int = 18,
    ) -> LedgerAppendResult:
        return self._append_claim_snapshot(
            private_key=private_key,
            claim_ref=claim_ref,
            why=why,
            kind="capture",
            difficulty_bits=difficulty_bits,
            require_existing_snapshot=True,
            extra={"capture": {"evidence_ref": evidence_ref, "summary": summary}},
        )

    def close_probe(
        self,
        *,
        private_key: str,
        claim_ref: str,
        why: str,
        outcome: str,
        result_ref: str | None = None,
        difficulty_bits: int = 18,
    ) -> LedgerAppendResult:
        return self._append_claim_snapshot(
            private_key=private_key,
            claim_ref=claim_ref,
            why=why,
            kind="close_act",
            difficulty_bits=difficulty_bits,
            require_existing_snapshot=True,
            extra={"close_act": {"outcome": outcome, "result_ref": result_ref}},
        )

    def _append_claim_snapshot(
        self,
        *,
        private_key: str,
        claim_ref: str,
        why: str,
        kind: str,
        prev: str | None = None,
        difficulty_bits: int = 18,
        require_existing_snapshot: bool,
        extra: dict[str, Any] | None = None,
    ) -> LedgerAppendResult:
        agent = self._agent()
        assert_private_key_matches(agent["public_key"], agent["key_fingerprint"], private_key)

        replay = self._replay()
        if not replay.validation.ok:
            raise ValidationError("ledger_invalid: " + "; ".join(replay.validation.errors))
        if kind == "act" and replay.validation.open_act is not None:
            raise ValidationError("open_act_exists")
        if kind in {"capture", "close_act"} and replay.validation.open_act is None:
            raise ValidationError("open_act_required")

        rows = replay.rows
        prev = replay.validation.head if prev is None else prev
        append_prev = rows[-1]["id"] if rows else None
        prev_state_hash = self._genesis_state_hash() if prev is None else replay.state_by_id.get(prev)
        if prev_state_hash is None:
            raise ValidationError(f"unknown branch predecessor: {prev}")

        claim = self.store.read_claim(self.workspace_ref, claim_ref)
        claim_snapshot_hash = canonical_hash(claim)
        if require_existing_snapshot:
            existing_snapshot = self._branch_claim_snapshot(rows, prev, claim_ref)
            if existing_snapshot is None:
                raise ValidationError("needs_claim_snapshot")
            claim_snapshot = existing_snapshot["claim_snapshot"]
            claim_snapshot_hash = existing_snapshot["claim_snapshot_hash"]
            rev = claim_snapshot["rev"]
        else:
            self._reject_noop_resnapshot(rows, prev, claim_ref, claim_snapshot_hash)
            rev = self._next_claim_rev(rows, claim_ref)
            claim_snapshot = {
                "ref": claim_ref,
                "rev": rev,
                "canonical_payload": claim,
            }
        source_snapshots = self._source_snapshots(claim)
        source_set_hash = canonical_hash(source_snapshots)
        context_hash = self.ledger_context_hash()
        append_log_hash = replay.append_hash

        core = {
            "id": ledger_id(len(rows) + 1),
            "prev": prev,
            "append_prev": append_prev,
            "kind": kind,
            "ref": claim_ref,
            "rev": rev,
            "created_at": utc_now(),
            "why": why,
            "ledger_context_hash": context_hash,
            "claim_snapshot": claim_snapshot,
            "claim_snapshot_hash": claim_snapshot_hash,
            "source_snapshots": source_snapshots,
            "source_set_hash": source_set_hash,
            "prev_state_hash": prev_state_hash,
            "append_log_hash": append_log_hash,
            "seal_suite": SEAL_SUITE,
        }
        if extra:
            core.update(extra)
        payload_hash = canonical_hash(core)
        pow_base = self._pow_base(payload_hash, context_hash, prev_state_hash, append_log_hash)
        row = dict(core)
        row["payload_hash"] = payload_hash
        row["pow"] = mine_pow(pow_base, difficulty_bits)
        row["seal"] = sign(private_key, canonical_bytes(self._seal_payload(row)))

        state_hash = self._state_hash(row)
        current_append_hash = self._append_hash(row)
        self.store.append_jsonl(self.store.ledger_path(self.workspace_ref, self.agent_ref), row)
        return LedgerAppendResult(row=row, state_hash=state_hash, append_hash=current_append_hash)

    def validate(self) -> LedgerValidation:
        return self._replay().validation

    def current_open_act_row(self) -> dict[str, Any] | None:
        replay = self._replay()
        if not replay.validation.ok:
            raise ValidationError("ledger_invalid: " + "; ".join(replay.validation.errors))
        if replay.validation.open_act is None:
            return None
        for row in replay.rows:
            if row.get("id") == replay.validation.open_act:
                return row
        raise ValidationError("open_act_missing")

    def ledger_context_hash(self) -> str:
        agent = self._agent()
        material = {
            "agent_ref": agent["id"],
            "canonicalization": agent["canonicalization"],
            "created_at": agent["created_at"],
            "key_fingerprint": agent["key_fingerprint"],
            "ledger_path": agent["ledger_path"],
            "pow_policy": agent["pow_policy"],
            "public_key": agent["public_key"],
            "seal_suite": agent["seal_suite"],
            "workspace_ref": agent["workspace_ref"],
        }
        return canonical_hash(material)

    def _replay(self) -> _ReplayState:
        agent = self._agent()
        context_hash = self.ledger_context_hash()
        rows = self.store.read_jsonl(self.store.ledger_path(self.workspace_ref, self.agent_ref))
        source_event_validation = self.store.validate_source_events(self.workspace_ref)
        errors: list[str] = []
        state_by_id: dict[str, str] = {}
        append_hash = self._genesis_append_hash()
        seen: set[str] = set()
        open_act: str | None = None

        if any(row.get("source_snapshots") for row in rows) and not source_event_validation.ok:
            errors.extend(f"source_events: {error}" for error in source_event_validation.errors)

        for index, row in enumerate(rows, start=1):
            row_id = row.get("id")
            expected_id = ledger_id(index)
            if row_id != expected_id:
                errors.append(f"{expected_id}: row id mismatch: {row_id!r}")
            if not isinstance(row_id, str) or row_id in seen:
                errors.append(f"{expected_id}: duplicate or invalid row id")
                continue
            seen.add(row_id)

            if row.get("ledger_context_hash") != context_hash:
                errors.append(f"{row_id}: ledger_context_hash mismatch")
            if row.get("seal_suite") != SEAL_SUITE:
                errors.append(f"{row_id}: unsupported seal_suite")

            expected_append_prev = rows[index - 2]["id"] if index > 1 else None
            if row.get("append_prev") != expected_append_prev:
                errors.append(f"{row_id}: append_prev mismatch")
            if row.get("append_log_hash") != append_hash:
                errors.append(f"{row_id}: append_log_hash mismatch")

            core = self._core_payload(row)
            if row.get("payload_hash") != canonical_hash(core):
                errors.append(f"{row_id}: payload_hash mismatch")

            claim_snapshot = row.get("claim_snapshot")
            if isinstance(claim_snapshot, dict):
                payload = claim_snapshot.get("canonical_payload")
                if row.get("claim_snapshot_hash") != canonical_hash(payload):
                    errors.append(f"{row_id}: claim_snapshot_hash mismatch")
                if claim_snapshot.get("ref") != row.get("ref") or claim_snapshot.get("rev") != row.get("rev"):
                    errors.append(f"{row_id}: claim_snapshot ref/rev mismatch")
            else:
                errors.append(f"{row_id}: missing claim_snapshot")

            for source_snapshot in row.get("source_snapshots", []):
                source_ref = source_snapshot.get("ref")
                if not isinstance(source_ref, str):
                    errors.append(f"{row_id}: invalid source snapshot ref")
                    continue
                try:
                    source = self.store.read_source(self.workspace_ref, source_ref)
                except Exception as exc:  # noqa: BLE001 - validator should collect bad-row reasons.
                    errors.append(f"{row_id}: source snapshot missing: {source_ref}: {exc}")
                    continue
                if source_snapshot.get("source_hash") != canonical_hash(self.store.source_material_payload(source)):
                    errors.append(f"{row_id}: source_hash mismatch for {source_ref}")
                if source_snapshot.get("classification_hash") != canonical_hash(source.get("classification")):
                    errors.append(f"{row_id}: classification_hash mismatch for {source_ref}")
                event_ref = source_snapshot.get("acceptance_event_ref")
                if event_ref is not None:
                    if event_ref not in source_event_validation.event_hashes:
                        errors.append(f"{row_id}: source event not valid in replay: {event_ref}")
                    if source_event_validation.accepted_sources.get(source_ref) != event_ref:
                        errors.append(f"{row_id}: source acceptance event is not current accepted event for {source_ref}")
                    event = self.store.source_event_by_id(self.workspace_ref, event_ref)
                    if event is None:
                        errors.append(f"{row_id}: missing source event {event_ref}")
                    else:
                        event_hash = canonical_hash({key: value for key, value in event.items() if key != "event_hash"})
                        if event_hash != event.get("event_hash"):
                            errors.append(f"{row_id}: source event self-hash mismatch for {event_ref}")
                        if source_snapshot.get("acceptance_event_hash") != event.get("event_hash"):
                            errors.append(f"{row_id}: source event hash mismatch for {event_ref}")
                        if source_snapshot.get("source_event_log_hash") != event.get("event_log_hash"):
                            errors.append(f"{row_id}: source event log hash mismatch for {event_ref}")
            if row.get("source_set_hash") != canonical_hash(row.get("source_snapshots", [])):
                errors.append(f"{row_id}: source_set_hash mismatch")

            prev = row.get("prev")
            if prev is None:
                expected_prev_state = self._genesis_state_hash()
            elif isinstance(prev, str) and prev in state_by_id:
                expected_prev_state = state_by_id[prev]
            else:
                errors.append(f"{row_id}: unknown prev")
                expected_prev_state = None
            if expected_prev_state is not None and row.get("prev_state_hash") != expected_prev_state:
                errors.append(f"{row_id}: prev_state_hash mismatch")

            pow_base = self._pow_base(
                row.get("payload_hash"),
                context_hash,
                row.get("prev_state_hash"),
                row.get("append_log_hash"),
            )
            if not verify_pow(pow_base, row.get("pow", {})):
                errors.append(f"{row_id}: pow validation failed")

            try:
                if not verify(agent["public_key"], canonical_bytes(self._seal_payload(row)), row.get("seal", "")):
                    errors.append(f"{row_id}: seal validation failed")
            except Exception as exc:  # noqa: BLE001 - validator should collect bad-row reasons.
                errors.append(f"{row_id}: seal validation failed: {exc}")

            state_by_id[row_id] = self._state_hash(row)
            append_hash = self._append_hash(row)

            if row.get("kind") == "act":
                if open_act is not None:
                    errors.append(f"{row_id}: open_act_exists")
                open_act = row_id
            elif row.get("kind") == "capture":
                if open_act is None:
                    errors.append(f"{row_id}: capture_without_open_act")
            elif row.get("kind") == "close_act":
                if open_act is None:
                    errors.append(f"{row_id}: close_without_open_act")
                open_act = None

        validation = LedgerValidation(
            ok=not errors,
            head=rows[-1]["id"] if rows else None,
            row_count=len(rows),
            open_act=open_act,
            errors=errors,
        )
        return _ReplayState(validation=validation, rows=rows, state_by_id=state_by_id, append_hash=append_hash)

    def _agent(self) -> dict[str, Any]:
        agent = self.store.read_agent(self.workspace_ref, self.agent_ref)
        if agent["id"] != self.agent_ref or agent["workspace_ref"] != self.workspace_ref:
            raise OwnershipError("agent record does not match selected ledger path")
        return agent

    def _genesis_state_hash(self) -> str:
        return canonical_hash({"kind": "ledger_state_genesis", "ledger_context_hash": self.ledger_context_hash()})

    def _genesis_append_hash(self) -> str:
        return canonical_hash({"kind": "append_log_genesis", "ledger_context_hash": self.ledger_context_hash()})

    @staticmethod
    def _core_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in {"payload_hash", "pow", "seal"}}

    @classmethod
    def _seal_payload(cls, row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key != "seal"}

    @staticmethod
    def _pow_base(
        payload_hash: str | None,
        ledger_context_hash: str,
        prev_state_hash: str | None,
        append_log_hash: str | None,
    ) -> dict[str, Any]:
        return {
            "payload_hash": payload_hash,
            "ledger_context_hash": ledger_context_hash,
            "prev_state_hash": prev_state_hash,
            "append_log_hash": append_log_hash,
        }

    @staticmethod
    def _state_hash(row: dict[str, Any]) -> str:
        return canonical_hash(
            {
                "kind": "ledger_state",
                "ledger_context_hash": row.get("ledger_context_hash"),
                "prev": row.get("prev"),
                "prev_state_hash": row.get("prev_state_hash"),
                "row_id": row.get("id"),
                "payload_hash": row.get("payload_hash"),
                "seal": row.get("seal"),
            }
        )

    @staticmethod
    def _append_hash(row: dict[str, Any]) -> str:
        return canonical_hash(
            {
                "kind": "append_log",
                "ledger_context_hash": row.get("ledger_context_hash"),
                "append_prev_hash": row.get("append_log_hash"),
                "row_id": row.get("id"),
                "payload_hash": row.get("payload_hash"),
                "seal": row.get("seal"),
            }
        )

    @staticmethod
    def _next_claim_rev(rows: list[dict[str, Any]], claim_ref: str) -> int:
        revs = [row.get("rev") for row in rows if row.get("ref") == claim_ref and isinstance(row.get("rev"), int)]
        return max(revs, default=0) + 1

    def _reject_noop_resnapshot(
        self,
        rows: list[dict[str, Any]],
        prev: str | None,
        claim_ref: str,
        claim_snapshot_hash: str,
    ) -> None:
        by_id = {row["id"]: row for row in rows if isinstance(row.get("id"), str)}
        current = prev
        while current is not None:
            row = by_id.get(current)
            if row is None:
                return
            if row.get("ref") == claim_ref and row.get("claim_snapshot_hash") == claim_snapshot_hash:
                raise ValidationError("no_op_snapshot: claim snapshot is already present on this branch")
            current = row.get("prev")

    def _branch_claim_snapshot(
        self,
        rows: list[dict[str, Any]],
        prev: str | None,
        claim_ref: str,
    ) -> dict[str, Any] | None:
        by_id = {row["id"]: row for row in rows if isinstance(row.get("id"), str)}
        current = prev
        while current is not None:
            row = by_id.get(current)
            if row is None:
                return None
            if row.get("ref") == claim_ref and isinstance(row.get("claim_snapshot"), dict):
                return row
            current = row.get("prev")
        return None

    def _source_snapshots(self, claim: dict[str, Any]) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for source_ref in claim.get("source_refs", []):
            source = self.store.read_source(self.workspace_ref, source_ref)
            latest_event = self.store.latest_source_event(self.workspace_ref, source_ref)
            accepted = source.get("critique_status") == "accepted"
            event_hash = latest_event.get("event_hash") if latest_event else None
            event_log_hash = latest_event.get("event_log_hash") if latest_event else None
            snapshots.append(
                {
                    "ref": source_ref,
                    "source_hash": canonical_hash(self.store.source_material_payload(source)),
                    "acceptance_event_ref": latest_event.get("event_id") if accepted and latest_event else None,
                    "acceptance_event_hash": event_hash if accepted else None,
                    "source_event_log_hash": event_log_hash,
                    "acceptance_hash": canonical_hash(
                        {
                            "source_ref": source_ref,
                            "critique_status": source.get("critique_status"),
                            "event_hash": event_hash,
                        }
                    ),
                    "classification_hash": canonical_hash(source.get("classification")),
                }
            )
        return snapshots
