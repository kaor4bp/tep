"""Filesystem storage primitives for the local TEP context store."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .crypto import AgentIdentity
from .errors import NotFoundError, ValidationError
from .ids import new_id
from .jsoncanon import bytes_hash, canonical_dumps, canonical_hash, loads_no_duplicates, read_json


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SourceEventValidation:
    ok: bool
    event_count: int
    head: str | None
    head_hash: str | None
    event_hashes: dict[str, str] = field(default_factory=dict)
    accepted_sources: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class TEPHome:
    """Small typed storage layer.

    This is internal architecture, not a raw JSON mutation API for agents.
    """

    def __init__(self, root: str | os.PathLike[str] = "~/.tep") -> None:
        self.root = Path(root).expanduser()

    @classmethod
    def from_project_pointer(cls, project_root: str | os.PathLike[str]) -> "TEPHome":
        pointer = read_json(Path(project_root).expanduser().resolve() / ".tep")
        return cls(pointer.get("tep_home", "~/.tep"))

    def ensure(self) -> None:
        for path in [
            self.root / "registry" / "projects",
            self.root / "registry" / "workspaces",
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def ensure_workspace(self, workspace_ref: str) -> Path:
        self.ensure()
        workspace = self.workspace_dir(workspace_ref)
        for path in [
            workspace / "memberships",
            workspace / "records" / "src",
            workspace / "records" / "clm",
            workspace / "records" / "inp",
            workspace / "records" / "run",
            workspace / "tasks",
            workspace / "agents",
            workspace / "maps",
            workspace / "indexes" / "manifests",
            workspace / "artifacts",
        ]:
            path.mkdir(parents=True, exist_ok=True)
        source_events = workspace / "records" / "src" / "source_events.jsonl"
        source_events.touch(exist_ok=True)
        return workspace

    def workspace_dir(self, workspace_ref: str) -> Path:
        return self.root / "workspaces" / workspace_ref

    def create_workspace(self, name: str) -> dict[str, Any]:
        workspace_ref = new_id("WSP")
        record = {
            "id": workspace_ref,
            "record_type": "workspace",
            "name": name,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.ensure_workspace(workspace_ref)
        self._write_json(self.root / "registry" / "workspaces" / f"{workspace_ref}.json", record)
        return record

    def read_workspace(self, workspace_ref: str) -> dict[str, Any]:
        return read_json(self.root / "registry" / "workspaces" / f"{workspace_ref}.json")

    def register_project(
        self,
        name: str,
        *,
        roots: list[str] | None = None,
        aliases: list[str] | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        self.ensure()
        project_ref = new_id("PRJ")
        record = {
            "id": project_ref,
            "record_type": "project",
            "name": name,
            "roots": roots or [],
            "aliases": aliases or [],
            "status": status,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self._write_json(self.project_path(project_ref), record)
        return record

    def read_project(self, project_ref: str) -> dict[str, Any]:
        return read_json(self.project_path(project_ref))

    def project_path(self, project_ref: str) -> Path:
        return self.root / "registry" / "projects" / f"{project_ref}.json"

    def project_registry_search(self, query: str | None = None) -> list[dict[str, Any]]:
        self.ensure()
        needle = (query or "").casefold().strip()
        results = []
        for path in sorted((self.root / "registry" / "projects").glob("PRJ-*.json")):
            record = read_json(path)
            haystack = " ".join([record.get("name", ""), *record.get("aliases", []), *record.get("roots", [])]).casefold()
            if not needle or needle in haystack:
                results.append(record)
        return results

    def attach_project_to_workspace(
        self,
        workspace_ref: str,
        project_ref: str,
        *,
        role: str,
        reason: str,
        active: bool = True,
    ) -> dict[str, Any]:
        self.read_project(project_ref)
        self.ensure_workspace(workspace_ref)
        row = {
            "project_ref": project_ref,
            "role": role,
            "reason": reason,
            "active": active,
            "added_at": utc_now(),
        }
        self.append_jsonl(self.memberships_path(workspace_ref), row)
        return row

    def memberships_path(self, workspace_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "memberships" / "projects.jsonl"

    def project_memberships(self, workspace_ref: str, *, active_only: bool = True) -> list[dict[str, Any]]:
        rows = self.read_jsonl(self.memberships_path(workspace_ref))
        if active_only:
            rows = [row for row in rows if row.get("active") is True]
        return rows

    def create_agent(self, workspace_ref: str, identity: AgentIdentity, *, thread_ref: str) -> dict[str, Any]:
        workspace = self.ensure_workspace(workspace_ref)
        agent_dir = workspace / "agents" / identity.agent_ref
        agent_dir.mkdir(parents=True, exist_ok=False)
        record = {
            "id": identity.agent_ref,
            "record_type": "agent",
            "workspace_ref": workspace_ref,
            "thread_ref": thread_ref,
            "agent_name": identity.agent_name,
            "public_key": identity.public_key,
            "seal_suite": identity.seal_suite,
            "key_fingerprint": identity.key_fingerprint,
            "ledger_path": f"agents/{identity.agent_ref}/ledger.jsonl",
            "canonicalization": "tep-json-v1",
            "pow_policy": {"policy_id": "test-or-runtime-selected", "difficulty_bits": 18},
            "working_context": {
                "active_task_path": [],
                "attached_task_refs": [],
                "selected_ledger_head": None,
                "selected_claim_refs_by_task": {},
                "current_assumptions": [],
                "open_act_ref": None,
                "curiosity": {
                    "current_map_ref": None,
                    "breadcrumbs": [],
                    "active_lens": None,
                    "inspected_candidate_refs": [],
                    "deferred_candidate_refs": [],
                    "candidate_states": [],
                },
                "deferred_probe_refs": [],
                "last_briefing_at": None,
            },
            "task_refs": [],
            "created_at": utc_now(),
        }
        self._write_json(agent_dir / "agent.json", record)
        (agent_dir / "ledger.jsonl").touch()
        return record

    def read_agent(self, workspace_ref: str, agent_ref: str) -> dict[str, Any]:
        return read_json(self.workspace_dir(workspace_ref) / "agents" / agent_ref / "agent.json")

    def update_agent(self, workspace_ref: str, agent_ref: str, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("id") != agent_ref:
            raise ValidationError("agent id mismatch")
        self._write_json(self.workspace_dir(workspace_ref) / "agents" / agent_ref / "agent.json", record)
        return record

    def agents(self, workspace_ref: str) -> list[dict[str, Any]]:
        agents_dir = self.workspace_dir(workspace_ref) / "agents"
        if not agents_dir.exists():
            return []
        return [read_json(path) for path in sorted(agents_dir.glob("AGENT-*/agent.json"))]

    def find_agent_by_thread(self, workspace_ref: str, thread_ref: str) -> dict[str, Any] | None:
        for agent in self.agents(workspace_ref):
            if agent.get("thread_ref") == thread_ref:
                return agent
        return None

    def create_input(
        self,
        workspace_ref: str,
        *,
        text: str | dict[str, Any],
        input_class: str,
        actor_ref: str = "user",
        thread_ref: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_ref)
        if not text:
            raise ValidationError("input text must be non-empty")
        content_hash = bytes_hash(text.encode("utf-8")) if isinstance(text, str) else text.get("plaintext_hash")
        input_ref = new_id("INP")
        record = {
            "id": input_ref,
            "record_type": "input",
            "workspace_ref": workspace_ref,
            "actor_ref": actor_ref,
            "thread_ref": thread_ref,
            "input_class": input_class,
            "text": text,
            "content_hash": content_hash,
            "captured_at": utc_now(),
        }
        self._write_json(self.input_path(workspace_ref, input_ref), record)
        return record

    def read_input(self, workspace_ref: str, input_ref: str) -> dict[str, Any]:
        return read_json(self.input_path(workspace_ref, input_ref))

    def input_path(self, workspace_ref: str, input_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "records" / "inp" / f"{input_ref}.json"

    def attach_agent_to_task(self, workspace_ref: str, agent_ref: str, task_ref: str) -> dict[str, Any]:
        agent = self.read_agent(workspace_ref, agent_ref)
        task = self.read_task(workspace_ref, task_ref)
        if task_ref not in agent["task_refs"]:
            agent["task_refs"].append(task_ref)
        if task_ref not in agent["working_context"]["attached_task_refs"]:
            agent["working_context"]["attached_task_refs"].append(task_ref)
        agent["working_context"]["active_task_path"] = self.task_path_refs(workspace_ref, task_ref)
        agent["working_context"]["last_briefing_at"] = utc_now()
        self.update_agent(workspace_ref, agent_ref, agent)
        if agent_ref not in task["agent_refs"]:
            task["agent_refs"].append(agent_ref)
            task["updated_at"] = utc_now()
            self.update_task(workspace_ref, task_ref, task)
        return agent

    def create_source(
        self,
        workspace_ref: str,
        *,
        source_kind: str,
        quote: str | dict[str, Any],
        classification: dict[str, Any] | None = None,
        origin: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        project_refs: list[str] | None = None,
        critique_status: str | None = None,
        reason: str = "source captured",
        actor_ref: str = "runtime",
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_ref)
        source_ref = new_id("SRC")
        classification = self._source_classification_defaults(classification)
        if critique_status is None:
            critique_status = self._default_source_status(source_kind, classification)
        provenance = self._source_provenance_defaults(provenance, quote)
        record = {
            "id": source_ref,
            "record_type": "source",
            "source_kind": source_kind,
            "critique_status": critique_status,
            "classification": classification,
            "origin": origin or {"kind": "unknown", "ref": "unknown"},
            "provenance": provenance,
            "quote": quote,
            "artifact_ref": None,
            "project_refs": project_refs or [],
            "workspace_ref": workspace_ref,
            "captured_at": utc_now(),
        }
        self._write_json(self.source_path(workspace_ref, source_ref), record)
        self._append_source_event(
            workspace_ref,
            source_ref=source_ref,
            event_kind="created" if critique_status != "accepted" else "accepted",
            policy_basis=self._source_policy_basis(source_kind, classification, critique_status),
            actor_ref=actor_ref,
            reason=reason,
        )
        return record

    def read_source(self, workspace_ref: str, source_ref: str) -> dict[str, Any]:
        return read_json(self.source_path(workspace_ref, source_ref))

    def source_path(self, workspace_ref: str, source_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "records" / "src" / f"{source_ref}.json"

    def source_events_path(self, workspace_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "records" / "src" / "source_events.jsonl"

    def source_events(self, workspace_ref: str) -> list[dict[str, Any]]:
        return self.read_jsonl(self.source_events_path(workspace_ref))

    def latest_source_event(self, workspace_ref: str, source_ref: str) -> dict[str, Any] | None:
        for event in reversed(self.source_events(workspace_ref)):
            if event.get("source_ref") == source_ref:
                return event
        return None

    def sources(self, workspace_ref: str) -> list[dict[str, Any]]:
        source_dir = self.workspace_dir(workspace_ref) / "records" / "src"
        if not source_dir.exists():
            return []
        return [read_json(path) for path in sorted(source_dir.glob("SRC-*.json"))]

    def source_event_by_id(self, workspace_ref: str, event_id: str) -> dict[str, Any] | None:
        for event in self.source_events(workspace_ref):
            if event.get("event_id") == event_id:
                return event
        return None

    def validate_source_events(self, workspace_ref: str) -> SourceEventValidation:
        events = self.source_events(workspace_ref)
        errors: list[str] = []
        event_hashes: dict[str, str] = {}
        accepted_sources: dict[str, str] = {}
        seen: set[str] = set()
        previous_id: str | None = None
        previous_hash: str | None = None
        previous_log_hash: str | None = None

        for index, event in enumerate(events, start=1):
            location = f"source_event[{index}]"
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or event_id in seen:
                errors.append(f"{location}: duplicate or invalid event_id")
                continue
            seen.add(event_id)

            if event.get("event_prev") != previous_id:
                errors.append(f"{event_id}: event_prev mismatch")
            if event.get("event_prev_hash") != previous_hash:
                errors.append(f"{event_id}: event_prev_hash mismatch")

            source_ref = event.get("source_ref")
            if not isinstance(source_ref, str):
                errors.append(f"{event_id}: invalid source_ref")
                source_hash = None
                classification_hash = None
            else:
                try:
                    source = self.read_source(workspace_ref, source_ref)
                    source_hash = canonical_hash(self.source_material_payload(source))
                    classification_hash = canonical_hash(source.get("classification"))
                except Exception as exc:  # noqa: BLE001 - replay should report all damage it can.
                    errors.append(f"{event_id}: source missing or unreadable: {source_ref}: {exc}")
                    source_hash = None
                    classification_hash = None

            if source_hash is not None and event.get("source_hash") != source_hash:
                errors.append(f"{event_id}: source_hash mismatch")
            if classification_hash is not None and event.get("classification_hash") != classification_hash:
                errors.append(f"{event_id}: classification_hash mismatch")

            expected_log_hash = canonical_hash(
                {
                    "event_prev_hash": previous_hash,
                    "event_prev_log_hash": previous_log_hash,
                    "source_ref": source_ref,
                    "event_kind": event.get("event_kind"),
                    "source_hash": event.get("source_hash"),
                    "classification_hash": event.get("classification_hash"),
                }
            )
            legacy_log_hash = canonical_hash(
                {
                    "event_prev_hash": previous_hash,
                    "source_ref": source_ref,
                    "event_kind": event.get("event_kind"),
                    "source_hash": event.get("source_hash"),
                    "classification_hash": event.get("classification_hash"),
                }
            )
            if event.get("event_log_hash") not in {expected_log_hash, legacy_log_hash}:
                errors.append(f"{event_id}: event_log_hash mismatch")

            expected_event_hash = canonical_hash({key: value for key, value in event.items() if key != "event_hash"})
            if event.get("event_hash") != expected_event_hash:
                errors.append(f"{event_id}: event_hash mismatch")
            else:
                event_hashes[event_id] = expected_event_hash
                if event.get("event_kind") == "accepted" and isinstance(source_ref, str):
                    accepted_sources[source_ref] = event_id

            previous_id = event_id
            previous_hash = event.get("event_hash") if isinstance(event.get("event_hash"), str) else None
            previous_log_hash = event.get("event_log_hash") if isinstance(event.get("event_log_hash"), str) else None

        return SourceEventValidation(
            ok=not errors,
            event_count=len(events),
            head=previous_id,
            head_hash=previous_hash,
            event_hashes=event_hashes,
            accepted_sources=accepted_sources,
            errors=errors,
        )

    def create_claim(
        self,
        workspace_ref: str,
        statement: str,
        *,
        claim_form: str = "assertion",
        claim_kind: str = "other",
        project_refs: list[str] | None = None,
        task_refs: list[str] | None = None,
        source_refs: list[str] | None = None,
        support_refs: list[str] | None = None,
        contradiction_refs: list[str] | None = None,
        relation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_ref)
        claim_ref = new_id("CLM")
        dedup_key = canonical_hash(
            {
                "claim_form": claim_form,
                "claim_kind": claim_kind,
                "relation": relation,
                "scope": {
                    "workspace_ref": workspace_ref,
                    "project_refs": project_refs or [],
                    "task_refs": task_refs or [],
                },
                "statement": " ".join(statement.casefold().split()),
            }
        )
        existing = self.find_claim_by_dedup_key(workspace_ref, dedup_key)
        if existing is not None:
            raise ValidationError(f"duplicate_claim:{existing['id']}")
        record = {
            "id": claim_ref,
            "record_type": "claim",
            "claim_form": claim_form,
            "claim_kind": claim_kind,
            "statement": statement,
            "dedup_key": dedup_key,
            "source_refs": source_refs or [],
            "support_refs": support_refs or [],
            "contradiction_refs": contradiction_refs or [],
            "relation": relation,
            "scope": {
                "workspace_ref": workspace_ref,
                "project_refs": project_refs or [],
                "task_refs": task_refs or [],
            },
            "semantic_hash": "",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        record["semantic_hash"] = canonical_hash(self._claim_semantic_payload(record))
        self._write_json(self.claim_path(workspace_ref, claim_ref), record)
        return record

    def create_relation_claim(
        self,
        workspace_ref: str,
        *,
        relation_type: str,
        subject_ref: str,
        object_ref: str,
        statement: str | None = None,
        project_refs: list[str] | None = None,
        task_refs: list[str] | None = None,
        source_refs: list[str] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        self.read_claim(workspace_ref, subject_ref)
        self.read_claim(workspace_ref, object_ref)
        relation = {
            "type": relation_type,
            "subject": subject_ref,
            "object": object_ref,
            "reason": reason,
        }
        if statement is None:
            statement = f"{subject_ref} {relation_type} {object_ref}"
        support_refs = [subject_ref] if relation_type == "supports" else []
        contradiction_refs = [subject_ref] if relation_type in {"contradicts", "challenges_freshness"} else []
        return self.create_claim(
            workspace_ref,
            statement,
            claim_form="relation",
            claim_kind=relation_type,
            project_refs=project_refs,
            task_refs=task_refs,
            source_refs=source_refs,
            support_refs=support_refs,
            contradiction_refs=contradiction_refs,
            relation=relation,
        )

    def find_claim_by_dedup_key(self, workspace_ref: str, dedup_key: str) -> dict[str, Any] | None:
        claims_dir = self.workspace_dir(workspace_ref) / "records" / "clm"
        if not claims_dir.exists():
            return None
        for path in sorted(claims_dir.glob("CLM-*.json")):
            record = read_json(path)
            if record.get("dedup_key") == dedup_key:
                return record
        return None

    def read_claim(self, workspace_ref: str, claim_ref: str) -> dict[str, Any]:
        return read_json(self.claim_path(workspace_ref, claim_ref))

    def claims(self, workspace_ref: str) -> list[dict[str, Any]]:
        claims_dir = self.workspace_dir(workspace_ref) / "records" / "clm"
        if not claims_dir.exists():
            return []
        return [read_json(path) for path in sorted(claims_dir.glob("CLM-*.json"))]

    def claim_path(self, workspace_ref: str, claim_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "records" / "clm" / f"{claim_ref}.json"

    def create_task(
        self,
        workspace_ref: str,
        goal: str,
        *,
        parent_task_ref: str | None = None,
        project_refs: list[str] | None = None,
        done_criteria: list[str] | None = None,
        blocker_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_ref)
        if parent_task_ref is not None:
            self.read_task(workspace_ref, parent_task_ref)
        task_ref = new_id("TASK")
        record = {
            "id": task_ref,
            "record_type": "task",
            "workspace_ref": workspace_ref,
            "parent_task_ref": parent_task_ref,
            "child_task_refs": [],
            "project_refs": project_refs or [],
            "goal": goal,
            "status": "active",
            "done_criteria": done_criteria or [],
            "blocker_refs": blocker_refs or [],
            "claim_refs": [],
            "agent_refs": [],
            "defer_reason": None,
            "resume_condition": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self._write_json(self.task_file_path(workspace_ref, task_ref), record)
        if parent_task_ref is not None:
            parent = self.read_task(workspace_ref, parent_task_ref)
            parent["child_task_refs"].append(task_ref)
            parent["updated_at"] = utc_now()
            self.update_task(workspace_ref, parent_task_ref, parent)
        return record

    def decompose_task(
        self,
        workspace_ref: str,
        parent_task_ref: str,
        goals: list[str],
        *,
        project_refs: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not goals:
            raise ValidationError("decompose_task requires at least one child goal")
        parent = self.read_task(workspace_ref, parent_task_ref)
        children = []
        for goal in goals:
            children.append(
                self.create_task(
                    workspace_ref,
                    goal,
                    parent_task_ref=parent_task_ref,
                    project_refs=project_refs if project_refs is not None else parent.get("project_refs", []),
                )
            )
        return children

    def defer_task(self, workspace_ref: str, task_ref: str, *, reason: str, resume_condition: str | None = None) -> dict[str, Any]:
        task = self.read_task(workspace_ref, task_ref)
        task["status"] = "deferred"
        task["defer_reason"] = reason
        task["resume_condition"] = resume_condition
        task["updated_at"] = utc_now()
        return self.update_task(workspace_ref, task_ref, task)

    def resume_task(self, workspace_ref: str, task_ref: str) -> dict[str, Any]:
        task = self.read_task(workspace_ref, task_ref)
        task["status"] = "active"
        task["defer_reason"] = None
        task["resume_condition"] = None
        task["updated_at"] = utc_now()
        return self.update_task(workspace_ref, task_ref, task)

    def update_task(self, workspace_ref: str, task_ref: str, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("id") != task_ref:
            raise ValidationError("task id mismatch")
        self._write_json(self.task_file_path(workspace_ref, task_ref), record)
        return record

    def read_task(self, workspace_ref: str, task_ref: str) -> dict[str, Any]:
        path = self.task_file_path(workspace_ref, task_ref)
        if not path.exists():
            raise NotFoundError(f"task not found: {task_ref}")
        return read_json(path)

    def tasks(self, workspace_ref: str) -> list[dict[str, Any]]:
        tasks_dir = self.workspace_dir(workspace_ref) / "tasks"
        if not tasks_dir.exists():
            return []
        return [read_json(path) for path in sorted(tasks_dir.glob("TASK-*.json"))]

    def task_file_path(self, workspace_ref: str, task_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "tasks" / f"{task_ref}.json"

    def create_run_preflight(
        self,
        workspace_ref: str,
        *,
        agent_ref: str,
        ledger_head: str,
        open_act_ref: str,
        open_act_hash: str,
        action_kind: str,
        action: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        self.ensure_workspace(workspace_ref)
        self.read_agent(workspace_ref, agent_ref)
        run_ref = new_id("RUN")
        preflight_token = "run-token:" + secrets.token_hex(32)
        action_hash = canonical_hash({"action_kind": action_kind, "action": action})
        record = {
            "id": run_ref,
            "record_type": "run",
            "workspace_ref": workspace_ref,
            "agent_ref": agent_ref,
            "ledger_head": ledger_head,
            "open_act_ref": open_act_ref,
            "open_act_hash": open_act_hash,
            "action_kind": action_kind,
            "action": action,
            "action_hash": action_hash,
            "preflight_token_hash": canonical_hash({"run_ref": run_ref, "preflight_token": preflight_token}),
            "status": "preflight_issued",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self._write_json(self.run_path(workspace_ref, run_ref), record)
        return record, preflight_token

    def create_bash_run_capture(
        self,
        workspace_ref: str,
        *,
        command: str,
        cwd: str,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
        agent_ref: str | None = None,
        preflight_run_ref: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_ref)
        if agent_ref is not None:
            self.read_agent(workspace_ref, agent_ref)
        if preflight_run_ref is not None:
            self.read_run(workspace_ref, preflight_run_ref)
        run_ref = new_id("RUN")
        command_payload = {"kind": "bash", "command": command, "cwd": str(Path(cwd).expanduser().resolve())}
        record = {
            "id": run_ref,
            "record_type": "run",
            "workspace_ref": workspace_ref,
            "agent_ref": agent_ref,
            "preflight_run_ref": preflight_run_ref,
            "status": "captured",
            "run_kind": "bash",
            "command": command,
            "cwd": command_payload["cwd"],
            "command_hash": canonical_hash(command_payload),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_hash": self._captured_text_hash(stdout),
            "stderr_hash": self._captured_text_hash(stderr),
            "captured_at": utc_now(),
        }
        self._write_json(self.run_path(workspace_ref, run_ref), record)
        return record

    def read_run(self, workspace_ref: str, run_ref: str) -> dict[str, Any]:
        return read_json(self.run_path(workspace_ref, run_ref))

    def run_path(self, workspace_ref: str, run_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "records" / "run" / f"{run_ref}.json"

    def write_index_manifest(self, workspace_ref: str, index_name: str, manifest: dict[str, Any]) -> dict[str, Any]:
        self.ensure_workspace(workspace_ref)
        self._write_json(self.index_manifest_path(workspace_ref, index_name), manifest)
        return manifest

    def read_index_manifest(self, workspace_ref: str, index_name: str) -> dict[str, Any]:
        return read_json(self.index_manifest_path(workspace_ref, index_name))

    def index_manifest_path(self, workspace_ref: str, index_name: str) -> Path:
        return self.workspace_dir(workspace_ref) / "indexes" / "manifests" / f"{index_name}.json"

    def task_path_refs(self, workspace_ref: str, task_ref: str) -> list[str]:
        refs = []
        current: str | None = task_ref
        while current is not None:
            task = self.read_task(workspace_ref, current)
            refs.append(current)
            current = task.get("parent_task_ref")
        return list(reversed(refs))

    def ledger_path(self, workspace_ref: str, agent_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "agents" / agent_ref / "ledger.jsonl"

    def read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(loads_no_duplicates(line))
        return rows

    def append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_dumps(row))
            handle.write("\n")

    def _write_json(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(canonical_dumps(record) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _captured_text_hash(value: str | dict[str, Any]) -> str:
        return bytes_hash(value.encode("utf-8")) if isinstance(value, str) else value["plaintext_hash"]

    def _append_source_event(
        self,
        workspace_ref: str,
        *,
        source_ref: str,
        event_kind: str,
        policy_basis: str,
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        source = self.read_source(workspace_ref, source_ref)
        previous = self.source_events(workspace_ref)[-1:] or [None]
        previous_event = previous[0]
        previous_hash = previous_event.get("event_hash") if previous_event else None
        previous_log_hash = previous_event.get("event_log_hash") if previous_event else None
        source_hash = canonical_hash(self.source_material_payload(source))
        classification_hash = canonical_hash(source["classification"])
        event_core = {
            "event_id": new_id("SE"),
            "event_prev": previous_event.get("event_id") if previous_event else None,
            "source_ref": source_ref,
            "event_kind": event_kind,
            "policy_basis": policy_basis,
            "actor_ref": actor_ref,
            "source_hash": source_hash,
            "classification_hash": classification_hash,
            "event_prev_hash": previous_hash,
            "event_log_hash": canonical_hash(
                {
                    "event_prev_hash": previous_hash,
                    "event_prev_log_hash": previous_log_hash,
                    "source_ref": source_ref,
                    "event_kind": event_kind,
                    "source_hash": source_hash,
                    "classification_hash": classification_hash,
                }
            ),
            "reason": reason,
            "created_at": utc_now(),
        }
        event = dict(event_core)
        event["event_hash"] = canonical_hash(event_core)
        self.append_jsonl(self.source_events_path(workspace_ref), event)
        return event

    @staticmethod
    def _claim_semantic_payload(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "claim_form": record["claim_form"],
            "claim_kind": record["claim_kind"],
            "statement": record["statement"],
            "source_refs": record["source_refs"],
            "support_refs": record["support_refs"],
            "contradiction_refs": record["contradiction_refs"],
            "relation": record["relation"],
            "scope": record["scope"],
        }

    @staticmethod
    def source_material_payload(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": record["id"],
            "record_type": record["record_type"],
            "source_kind": record["source_kind"],
            "origin": record["origin"],
            "provenance": record["provenance"],
            "quote": record["quote"],
            "artifact_ref": record["artifact_ref"],
            "project_refs": record["project_refs"],
            "workspace_ref": record["workspace_ref"],
            "captured_at": record["captured_at"],
        }

    @staticmethod
    def _source_classification_defaults(classification: dict[str, Any] | None) -> dict[str, Any]:
        base = {
            "input_class": None,
            "source_class": "unknown",
            "document_kind": "unknown",
            "evidence_role": "assertion",
            "authority_scope": "unknown",
            "independence_key": "unknown",
        }
        if classification:
            base.update(classification)
        return base

    @staticmethod
    def _source_provenance_defaults(provenance: dict[str, Any] | None, quote: str | dict[str, Any]) -> dict[str, Any]:
        content_hash = quote.get("plaintext_hash") if isinstance(quote, dict) else bytes_hash(quote.encode("utf-8"))
        base = {
            "entity_ref": "unknown",
            "activity_ref": "capture",
            "responsible_agent": "unknown",
            "content_hash": content_hash,
            "locator": "unknown",
            "quote_span": None,
            "retrieved_at": None,
            "published_at": None,
        }
        if provenance:
            base.update(provenance)
        return base

    @staticmethod
    def _default_source_status(source_kind: str, classification: dict[str, Any]) -> str:
        if source_kind == "user_message" and classification.get("input_class") in {
            "instruction",
            "preference",
            "user_confirmation",
            "correction",
        }:
            return "accepted"
        if source_kind in {"file_quote", "command_output", "artifact_snapshot"}:
            return "audited"
        return "unknown"

    @staticmethod
    def _source_policy_basis(source_kind: str, classification: dict[str, Any], critique_status: str) -> str:
        if critique_status == "accepted" and source_kind == "user_message":
            return "user_intent" if classification.get("input_class") in {"instruction", "preference"} else "user_authority"
        if source_kind == "file_quote":
            return "quote_verified"
        if source_kind == "command_output":
            return "run_capture"
        return "configured_source_policy" if critique_status == "accepted" else "captured"
