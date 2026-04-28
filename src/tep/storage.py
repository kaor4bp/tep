"""Filesystem storage primitives for the local TEP context store."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .crypto import AgentIdentity
from .enforcement import CONTEXT_KINDS, DEFAULT_SETTINGS, merged_settings
from .errors import NotFoundError, ValidationError
from .ids import new_id
from .jsoncanon import bytes_hash, canonical_dumps, canonical_hash, loads_no_duplicates, read_json
from .transactions import FileTransaction


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
            self.root / "records" / "sources",
            self.root / "records" / "claims",
            self.root / "records" / "maps",
            self.root / "records" / "indexes" / "manifests",
        ]:
            path.mkdir(parents=True, exist_ok=True)
        (self.root / "records" / "sources" / "source_events.jsonl").touch(exist_ok=True)
        if not self.settings_path().exists():
            self._write_json(self.settings_path(), DEFAULT_SETTINGS)

    def begin_transaction(self, operation: str) -> FileTransaction:
        self.ensure()
        return FileTransaction(self.root, operation)

    def ensure_workspace(self, workspace_ref: str) -> Path:
        self.ensure()
        workspace = self.workspace_dir(workspace_ref)
        for path in [
            workspace / "memberships",
            workspace / "records" / "inp",
            workspace / "records" / "run",
            workspace / "tasks",
            workspace / "agents",
            workspace / "artifacts" / "context_packs",
        ]:
            path.mkdir(parents=True, exist_ok=True)
        return workspace

    def workspace_dir(self, workspace_ref: str) -> Path:
        return self.root / "workspaces" / workspace_ref

    def records_dir(self) -> Path:
        return self.root / "records"

    def settings_path(self, workspace_ref: str | None = None) -> Path:
        if workspace_ref is None:
            return self.root / "settings.json"
        return self.workspace_dir(workspace_ref) / "settings.json"

    def read_settings(self, workspace_ref: str | None = None) -> dict[str, Any]:
        self.ensure()
        global_settings = read_json(self.settings_path()) if self.settings_path().exists() else {}
        workspace_settings = {}
        if workspace_ref is not None and self.settings_path(workspace_ref).exists():
            workspace_settings = read_json(self.settings_path(workspace_ref))
        return merged_settings(global_settings, workspace_settings)

    def update_settings(self, settings: dict[str, Any], *, workspace_ref: str | None = None) -> dict[str, Any]:
        self.ensure_workspace(workspace_ref) if workspace_ref is not None else self.ensure()
        current = self.read_settings(workspace_ref)
        merged = merged_settings(current, settings)
        self._write_json(self.settings_path(workspace_ref), merged)
        return merged

    def _record_path(self, directory: str, record_ref: str) -> Path:
        parts = record_ref.split("-")
        day = parts[1] if len(parts) >= 3 and len(parts[1]) == 8 else "undated"
        year = day[:4] if day != "undated" else "undated"
        month = day[4:6] if day != "undated" else "00"
        return self.records_dir() / directory / year / month / f"{record_ref}.json"

    def create_workspace(self, name: str, *, tx: FileTransaction | None = None, allow_existing: bool = True) -> dict[str, Any]:
        if allow_existing:
            existing = self.active_workspace_by_name(name)
            if existing is not None:
                return existing
        workspace_ref = new_id("WSP")
        record = {
            "id": workspace_ref,
            "record_type": "workspace",
            "name": name,
            "status": "active",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.ensure_workspace(workspace_ref)
        owns_tx = tx is None
        tx = tx or self.begin_transaction("create_workspace")
        self._write_json(self.root / "registry" / "workspaces" / f"{workspace_ref}.json", record, tx=tx)
        if owns_tx:
            self._commit_transaction(tx, "create_workspace", refs={"workspace_ref": workspace_ref})
        return record

    def read_workspace(self, workspace_ref: str) -> dict[str, Any]:
        return read_json(self.root / "registry" / "workspaces" / f"{workspace_ref}.json")

    def active_workspace_by_name(self, name: str) -> dict[str, Any] | None:
        self.ensure()
        for path in sorted((self.root / "registry" / "workspaces").glob("WSP-*.json")):
            workspace = read_json(path)
            if workspace.get("status") == "active" and workspace.get("name") == name:
                return workspace
        return None

    def active_workspaces_for_project(self, project_ref: str) -> list[dict[str, Any]]:
        self.ensure()
        matches: list[tuple[str, int, dict[str, Any]]] = []
        for path in sorted((self.root / "registry" / "workspaces").glob("WSP-*.json")):
            workspace = read_json(path)
            if workspace.get("status") == "archived":
                continue
            workspace_ref = workspace.get("id")
            if not isinstance(workspace_ref, str) or not workspace_ref.startswith("WSP-"):
                continue
            memberships = self.read_jsonl(self.memberships_path(workspace_ref))
            active_rows = [row for row in memberships if row.get("active") is True and row.get("project_ref") == project_ref]
            if active_rows:
                latest = max(str(row.get("added_at", "")) for row in active_rows)
                try:
                    mtime_ns = self.memberships_path(workspace_ref).stat().st_mtime_ns
                except OSError:
                    mtime_ns = 0
                matches.append((latest, mtime_ns, workspace))
        return [
            workspace
            for _latest, _mtime_ns, workspace in sorted(
                matches,
                key=lambda item: (item[0], item[1], item[2].get("created_at", ""), item[2].get("id", "")),
                reverse=True,
            )
        ]

    def update_workspace(self, workspace_ref: str, record: dict[str, Any], *, tx: FileTransaction | None = None) -> dict[str, Any]:
        record["updated_at"] = utc_now()
        owns_tx = tx is None
        tx = tx or self.begin_transaction("update_workspace")
        self._write_json(self.root / "registry" / "workspaces" / f"{workspace_ref}.json", record, tx=tx)
        if owns_tx:
            self._commit_transaction(tx, "update_workspace", refs={"workspace_ref": workspace_ref})
        return record

    def archive_workspace(self, workspace_ref: str, *, reason: str) -> dict[str, Any]:
        workspace = self.read_workspace(workspace_ref)
        workspace["status"] = "archived"
        workspace["archive_reason"] = reason
        tx = self.begin_transaction("archive_workspace")
        result = self.update_workspace(workspace_ref, workspace, tx=tx)
        self._commit_transaction(tx, "archive_workspace", refs={"workspace_ref": workspace_ref})
        return result

    def register_project(
        self,
        name: str,
        *,
        roots: list[str] | None = None,
        aliases: list[str] | None = None,
        status: str = "active",
        project_type: str = "repo",
        parent_project_refs: list[str] | None = None,
        tx: FileTransaction | None = None,
    ) -> dict[str, Any]:
        self.ensure()
        normalized_roots = [str(Path(root).expanduser().resolve()) for root in roots or []]
        for root in normalized_roots:
            existing = self.find_project_by_root(root)
            if existing is not None and existing.get("status") != "archived":
                raise ValidationError(f"duplicate_project:{existing['id']}")
        for parent_ref in parent_project_refs or []:
            self.read_project(parent_ref)
        project_ref = new_id("PRJ")
        record = {
            "id": project_ref,
            "record_type": "project",
            "project_type": project_type,
            "name": name,
            "roots": normalized_roots,
            "aliases": aliases or [],
            "parent_project_refs": parent_project_refs or [],
            "status": status,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        owns_tx = tx is None
        tx = tx or self.begin_transaction("register_project")
        self._write_json(self.project_path(project_ref), record, tx=tx)
        if owns_tx:
            self._commit_transaction(tx, "register_project", refs={"project_ref": project_ref})
        return record

    def projects(self) -> list[dict[str, Any]]:
        self.ensure()
        return [read_json(path) for path in sorted((self.root / "registry" / "projects").glob("PRJ-*.json"))]

    def find_project_by_root(self, root: str | os.PathLike[str]) -> dict[str, Any] | None:
        normalized = str(Path(root).expanduser().resolve())
        archived_match: dict[str, Any] | None = None
        for project in self.projects():
            project_roots = [str(Path(item).expanduser().resolve()) for item in project.get("roots", [])]
            if normalized in project_roots:
                if project.get("status") != "archived":
                    return project
                if archived_match is None:
                    archived_match = project
        return archived_match

    def read_project(self, project_ref: str) -> dict[str, Any]:
        return read_json(self.project_path(project_ref))

    def project_path(self, project_ref: str) -> Path:
        return self.root / "registry" / "projects" / f"{project_ref}.json"

    def update_project(self, project_ref: str, record: dict[str, Any], *, tx: FileTransaction | None = None) -> dict[str, Any]:
        record["updated_at"] = utc_now()
        owns_tx = tx is None
        tx = tx or self.begin_transaction("update_project")
        self._write_json(self.project_path(project_ref), record, tx=tx)
        if owns_tx:
            self._commit_transaction(tx, "update_project", refs={"project_ref": project_ref})
        return record

    def archive_project(self, project_ref: str, *, reason: str) -> dict[str, Any]:
        project = self.read_project(project_ref)
        project["status"] = "archived"
        project["archive_reason"] = reason
        tx = self.begin_transaction("archive_project")
        result = self.update_project(project_ref, project, tx=tx)
        self._commit_transaction(tx, "archive_project", refs={"project_ref": project_ref})
        return result

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
        include_children: bool = False,
    ) -> dict[str, Any]:
        self.read_project(project_ref)
        self.ensure_workspace(workspace_ref)
        row = {
            "project_ref": project_ref,
            "role": role,
            "reason": reason,
            "active": active,
            "include_children": include_children,
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

    def child_project_refs(self, project_ref: str) -> list[str]:
        return [project["id"] for project in self.projects() if project_ref in project.get("parent_project_refs", [])]

    def visible_project_refs(self, workspace_ref: str) -> set[str]:
        return set(self.project_roles_for_workspace(workspace_ref))

    def project_roles_for_workspace(self, workspace_ref: str) -> dict[str, str]:
        visible: set[str] = set()
        roles: dict[str, str] = {}
        queue: list[str] = []
        for row in self.project_memberships(workspace_ref):
            project_ref = row["project_ref"]
            visible.add(project_ref)
            roles[project_ref] = row["role"]
            if row.get("include_children") is True:
                queue.append(project_ref)
        while queue:
            current = queue.pop(0)
            for child_ref in self.child_project_refs(current):
                if child_ref not in visible:
                    visible.add(child_ref)
                    roles[child_ref] = roles[current]
                    queue.append(child_ref)
        return roles

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

    def create_context_pack(
        self,
        workspace_ref: str,
        *,
        task_ref: str | None = None,
        project_ref: str | None = None,
        kind: str,
        text: str,
        support_refs: list[str],
        agent_ref: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_ref)
        if kind not in CONTEXT_KINDS:
            raise ValidationError(f"unsupported_context_kind:{kind}")
        if task_ref is not None:
            self.read_task(workspace_ref, task_ref)
        if project_ref is not None and project_ref not in self.visible_project_refs(workspace_ref):
            raise ValidationError(f"context_project_not_visible:{project_ref}")
        if kind == "task_briefing" and task_ref is None:
            raise ValidationError("task_briefing_requires_task_ref")
        if not text.strip():
            raise ValidationError("context pack text must be non-empty")
        if not support_refs:
            raise ValidationError("context pack requires support_refs")
        support = [self._context_support_snapshot(workspace_ref, ref) for ref in support_refs]
        context_ref = new_id("CTX")
        scope_type, scope_ref, scope_dir = self._context_scope(task_ref=task_ref, project_ref=project_ref)
        relative_md = f"artifacts/context_packs/{scope_dir}/{context_ref}-{kind}.md"
        relative_json = f"artifacts/context_packs/{scope_dir}/{context_ref}.json"
        artifact_path = self.workspace_dir(workspace_ref) / relative_md
        metadata_path = self.workspace_dir(workspace_ref) / relative_json
        record = {
            "id": context_ref,
            "record_type": "context_pack",
            "workspace_ref": workspace_ref,
            "task_ref": task_ref,
            "project_ref": project_ref,
            "scope_type": scope_type,
            "scope_ref": scope_ref,
            "kind": kind,
            "format": "markdown",
            "artifact_path": relative_md,
            "metadata_path": relative_json,
            "support_refs": support_refs,
            "support_hash": canonical_hash(support),
            "status": "active",
            "created_by_agent": agent_ref,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        for existing in self.context_packs(workspace_ref, task_ref=task_ref, project_ref=project_ref, scope_type=scope_type, kind=kind, status="active"):
            existing["status"] = "stale"
            existing["stale_reason"] = "replaced_by_new_context_pack"
            existing["updated_at"] = utc_now()
            self._write_json(self.workspace_dir(workspace_ref) / existing["metadata_path"], existing)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(text, encoding="utf-8")
        self._write_json(metadata_path, record)
        return record

    def read_context_pack(self, workspace_ref: str, context_ref: str) -> dict[str, Any]:
        for path in sorted((self.workspace_dir(workspace_ref) / "artifacts" / "context_packs").glob(f"**/{context_ref}.json")):
            return read_json(path)
        raise NotFoundError(f"context pack not found: {context_ref}")

    def context_packs(
        self,
        workspace_ref: str,
        *,
        task_ref: str | None = None,
        project_ref: str | None = None,
        scope_type: str | None = None,
        kind: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        base = self.workspace_dir(workspace_ref) / "artifacts" / "context_packs"
        records = [read_json(path) for path in sorted(base.glob("**/CTX-*.json"))]
        if task_ref is not None:
            records = [record for record in records if record.get("task_ref") == task_ref]
        if project_ref is not None:
            records = [record for record in records if record.get("project_ref") == project_ref]
        if scope_type is not None:
            records = [record for record in records if record.get("scope_type") == scope_type]
        if kind is not None:
            records = [record for record in records if record.get("kind") == kind]
        if status is not None:
            records = [record for record in records if record.get("status") == status]
        return records

    def revoke_context_pack(self, workspace_ref: str, context_ref: str, *, reason: str) -> dict[str, Any]:
        record = self.read_context_pack(workspace_ref, context_ref)
        record["status"] = "revoked"
        record["revoke_reason"] = reason
        record["updated_at"] = utc_now()
        self._write_json(self.workspace_dir(workspace_ref) / record["metadata_path"], record)
        return record

    def context_pack_text(self, workspace_ref: str, context_ref: str) -> str:
        record = self.read_context_pack(workspace_ref, context_ref)
        return (self.workspace_dir(workspace_ref) / record["artifact_path"]).read_text(encoding="utf-8")

    @staticmethod
    def _context_scope(*, task_ref: str | None, project_ref: str | None) -> tuple[str, str, str]:
        if task_ref is not None:
            return "task", task_ref, f"tasks/{task_ref}"
        if project_ref is not None:
            return "project", project_ref, f"projects/{project_ref}"
        return "global", "global", "global"

    def _context_support_snapshot(self, workspace_ref: str, ref: str) -> dict[str, Any]:
        if ref.startswith("CLM-"):
            claim = self.read_claim(workspace_ref, ref)
            if not self.claim_visible_in_workspace(workspace_ref, claim):
                raise ValidationError(f"context_support_not_visible:{ref}")
            return {"ref": ref, "hash": canonical_hash(claim), "record_type": "claim"}
        if ref.startswith("SRC-"):
            source = self.read_source(workspace_ref, ref)
            if not self.source_visible_in_workspace(workspace_ref, source):
                raise ValidationError(f"context_support_not_visible:{ref}")
            return {"ref": ref, "hash": canonical_hash(source), "record_type": "source"}
        raise ValidationError(f"unsupported_context_support_ref:{ref}")

    def _invalidate_context_packs_for_claim(self, workspace_ref: str, claim: dict[str, Any]) -> list[dict[str, Any]]:
        return self._invalidate_context_packs_for_claim_in_tx(workspace_ref, claim, tx=None)

    def _invalidate_context_packs_for_claim_in_tx(self, workspace_ref: str, claim: dict[str, Any], *, tx: FileTransaction | None) -> list[dict[str, Any]]:
        scope = claim.get("scope", {})
        project_refs = set(scope.get("project_refs", []))
        task_refs = set(scope.get("task_refs", []))
        affected: list[dict[str, Any]] = []
        for pack in self.context_packs(workspace_ref, status="active"):
            scope_type = pack.get("scope_type")
            should_stale = False
            if scope_type == "task":
                pack_task = pack.get("task_ref")
                if pack_task in task_refs:
                    should_stale = True
                elif project_refs and pack_task:
                    task = self.read_task(workspace_ref, pack_task)
                    should_stale = bool(project_refs.intersection(task.get("project_refs", [])))
            elif scope_type == "project":
                should_stale = pack.get("project_ref") in project_refs
            elif scope_type == "global":
                should_stale = not project_refs and not task_refs
            if not should_stale:
                continue
            pack["status"] = "stale"
            pack["stale_reason"] = "new_claim_in_scope"
            pack["stale_trigger_ref"] = claim["id"]
            pack["updated_at"] = utc_now()
            self._write_json(self.workspace_dir(workspace_ref) / pack["metadata_path"], pack, tx=tx)
            affected.append(pack)
        return affected

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
            "workspace_refs": [workspace_ref],
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
        path = self.source_path(workspace_ref, source_ref)
        if path.exists():
            return read_json(path)
        legacy_global = self._legacy_global_source_path(source_ref)
        if legacy_global.exists():
            return read_json(legacy_global)
        workspace_named = self._workspace_source_path(workspace_ref, source_ref)
        if workspace_named.exists():
            return read_json(workspace_named)
        legacy = self._legacy_source_path(workspace_ref, source_ref)
        if legacy.exists():
            return read_json(legacy)
        return read_json(path)

    def source_path(self, workspace_ref: str, source_ref: str) -> Path:
        return self._record_path("sources", source_ref)

    def _legacy_global_source_path(self, source_ref: str) -> Path:
        return self._record_path("src", source_ref)

    def _legacy_source_path(self, workspace_ref: str, source_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "records" / "src" / f"{source_ref}.json"

    def _workspace_source_path(self, workspace_ref: str, source_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "records" / "sources" / f"{source_ref}.json"

    def source_events_path(self, workspace_ref: str) -> Path:
        workspace_named = self.workspace_dir(workspace_ref) / "records" / "sources" / "source_events.jsonl"
        if workspace_named.exists() and workspace_named.stat().st_size > 0:
            return workspace_named
        legacy = self.workspace_dir(workspace_ref) / "records" / "src" / "source_events.jsonl"
        if legacy.exists() and legacy.stat().st_size > 0:
            return legacy
        legacy_global = self.records_dir() / "src" / "source_events.jsonl"
        if legacy_global.exists() and legacy_global.stat().st_size > 0:
            return legacy_global
        return self.records_dir() / "sources" / "source_events.jsonl"

    def source_events(self, workspace_ref: str) -> list[dict[str, Any]]:
        return self.read_jsonl(self.source_events_path(workspace_ref))

    def latest_source_event(self, workspace_ref: str, source_ref: str) -> dict[str, Any] | None:
        for event in reversed(self.source_events(workspace_ref)):
            if event.get("source_ref") == source_ref:
                return event
        return None

    def sources(self, workspace_ref: str) -> list[dict[str, Any]]:
        records = [read_json(path) for path in sorted((self.records_dir() / "sources").glob("**/SRC-*.json"))]
        legacy_global = self.records_dir() / "src"
        if legacy_global.exists():
            records.extend(read_json(path) for path in sorted(legacy_global.glob("**/SRC-*.json")))
        workspace_named = self.workspace_dir(workspace_ref) / "records" / "sources"
        if workspace_named.exists():
            records.extend(read_json(path) for path in sorted(workspace_named.glob("SRC-*.json")))
        legacy_dir = self.workspace_dir(workspace_ref) / "records" / "src"
        if legacy_dir.exists():
            records.extend(read_json(path) for path in sorted(legacy_dir.glob("SRC-*.json")))
        return [source for source in self._dedupe_records(records) if self.source_visible_in_workspace(workspace_ref, source)]

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
        tx: FileTransaction | None = None,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_ref)
        self._validate_claim_source_refs(workspace_ref, source_refs or [])
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
                "workspace_refs": [workspace_ref],
                "project_refs": project_refs or [],
                "task_refs": task_refs or [],
            },
            "semantic_hash": "",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        record["semantic_hash"] = canonical_hash(self._claim_semantic_payload(record))
        owns_tx = tx is None
        tx = tx or self.begin_transaction("create_claim")
        self._write_json(self.claim_path(workspace_ref, claim_ref), record, tx=tx)
        affected = self._invalidate_context_packs_for_claim_in_tx(workspace_ref, record, tx=tx)
        if owns_tx:
            self._commit_transaction(
                tx,
                "create_claim",
                refs={"workspace_ref": workspace_ref, "claim_ref": claim_ref, "invalidated_context_refs": [pack["id"] for pack in affected]},
            )
        return record

    def _validate_claim_source_refs(self, workspace_ref: str, source_refs: list[str]) -> None:
        for source_ref in source_refs:
            source = self.read_source(workspace_ref, source_ref)
            if self._source_requires_excerpt(source):
                raise ValidationError(f"document_source_requires_excerpt:{source_ref}")

    @staticmethod
    def _source_requires_excerpt(source: dict[str, Any]) -> bool:
        if source.get("source_kind") != "file_quote":
            return False
        if source.get("origin", {}).get("kind") != "file":
            return False
        document_kind = source.get("classification", {}).get("document_kind")
        if document_kind not in {"markdown", "text", "manual", "spec", "api_reference", "paper"}:
            return False
        quote = source.get("quote")
        if not isinstance(quote, str):
            return False
        span = source.get("provenance", {}).get("quote_span")
        return span == {"start": 0, "end": len(quote)}

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
        bridge_scope: str | None = None,
        synced_object: dict[str, Any] | None = None,
        bridge_limits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.read_claim(workspace_ref, subject_ref)
        self.read_claim(workspace_ref, object_ref)
        relation = {
            "type": relation_type,
            "subject": subject_ref,
            "object": object_ref,
            "reason": reason,
        }
        if relation_type == "applies_to_scope":
            relation["bridge_scope"] = bridge_scope or "general"
            relation["task_refs"] = task_refs or []
            relation["synced_object"] = synced_object
            relation["bridge_limits"] = bridge_limits or {}
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
        for record in self.claims(workspace_ref):
            if record.get("dedup_key") == dedup_key:
                return record
        return None

    def read_claim(self, workspace_ref: str, claim_ref: str) -> dict[str, Any]:
        path = self.claim_path(workspace_ref, claim_ref)
        if path.exists():
            return read_json(path)
        legacy_global = self._legacy_global_claim_path(claim_ref)
        if legacy_global.exists():
            return read_json(legacy_global)
        workspace_named = self._workspace_claim_path(workspace_ref, claim_ref)
        if workspace_named.exists():
            return read_json(workspace_named)
        legacy = self._legacy_claim_path(workspace_ref, claim_ref)
        if legacy.exists():
            return read_json(legacy)
        return read_json(path)

    def claims(self, workspace_ref: str) -> list[dict[str, Any]]:
        records = [read_json(path) for path in sorted((self.records_dir() / "claims").glob("**/CLM-*.json"))]
        legacy_global = self.records_dir() / "clm"
        if legacy_global.exists():
            records.extend(read_json(path) for path in sorted(legacy_global.glob("**/CLM-*.json")))
        workspace_named = self.workspace_dir(workspace_ref) / "records" / "claims"
        if workspace_named.exists():
            records.extend(read_json(path) for path in sorted(workspace_named.glob("CLM-*.json")))
        legacy_dir = self.workspace_dir(workspace_ref) / "records" / "clm"
        if legacy_dir.exists():
            records.extend(read_json(path) for path in sorted(legacy_dir.glob("CLM-*.json")))
        return [claim for claim in self._dedupe_records(records) if self.claim_visible_in_workspace(workspace_ref, claim)]

    def claim_path(self, workspace_ref: str, claim_ref: str) -> Path:
        return self._record_path("claims", claim_ref)

    def _legacy_global_claim_path(self, claim_ref: str) -> Path:
        return self._record_path("clm", claim_ref)

    def _legacy_claim_path(self, workspace_ref: str, claim_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "records" / "clm" / f"{claim_ref}.json"

    def _workspace_claim_path(self, workspace_ref: str, claim_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "records" / "claims" / f"{claim_ref}.json"

    def claim_visible_in_workspace(self, workspace_ref: str, claim: dict[str, Any]) -> bool:
        scope = claim.get("scope", {})
        workspace_refs = set(scope.get("workspace_refs", []))
        if scope.get("workspace_ref"):
            workspace_refs.add(scope["workspace_ref"])
        if workspace_ref in workspace_refs:
            return True
        project_refs = set(scope.get("project_refs", []))
        return bool(project_refs and project_refs.intersection(self.visible_project_refs(workspace_ref)))

    def source_visible_in_workspace(self, workspace_ref: str, source: dict[str, Any]) -> bool:
        workspace_refs = set(source.get("workspace_refs", []))
        if source.get("workspace_ref"):
            workspace_refs.add(source["workspace_ref"])
        if workspace_ref in workspace_refs:
            return True
        project_refs = set(source.get("project_refs", []))
        return bool(project_refs and project_refs.intersection(self.visible_project_refs(workspace_ref)))

    @staticmethod
    def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result = []
        for record in records:
            record_id = record.get("id")
            if isinstance(record_id, str) and record_id not in seen:
                seen.add(record_id)
                result.append(record)
        return result

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
        path = self.index_manifest_path(workspace_ref, index_name)
        if path.exists():
            return read_json(path)
        legacy = self._legacy_index_manifest_path(workspace_ref, index_name)
        if legacy.exists():
            return read_json(legacy)
        return read_json(path)

    def index_manifest_path(self, workspace_ref: str, index_name: str) -> Path:
        return self.records_dir() / "indexes" / "manifests" / workspace_ref / f"{index_name}.json"

    def _legacy_index_manifest_path(self, workspace_ref: str, index_name: str) -> Path:
        return self.workspace_dir(workspace_ref) / "indexes" / "manifests" / f"{index_name}.json"

    def maps_dir(self, workspace_ref: str | None = None) -> Path:
        return self.records_dir() / "maps" if workspace_ref is None else self.records_dir() / "maps" / workspace_ref

    def legacy_maps_dir(self, workspace_ref: str) -> Path:
        return self.workspace_dir(workspace_ref) / "maps"

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

    def _write_json(self, path: Path, record: dict[str, Any], *, tx: FileTransaction | None = None) -> None:
        if tx is not None:
            tx.stage_json(path, record)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(canonical_dumps(record) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def _commit_transaction(self, tx: FileTransaction, operation: str, *, refs: dict[str, Any]) -> dict[str, Any]:
        data_writes = tx.writes
        journal_row = {
            "recorded_at": utc_now(),
            "tx_ref": tx.tx_ref,
            "operation": operation,
            "status": "committed",
            "refs": refs,
            "write_count": len(data_writes),
            "write_hashes": [item.content_hash for item in data_writes],
        }
        journal_path = self.root / "journals" / "operations" / f"{journal_row['recorded_at'][:7]}.jsonl"
        journal_content = journal_path.read_text(encoding="utf-8") if journal_path.exists() else ""
        tx.stage_text(journal_path, journal_content + canonical_dumps(journal_row) + "\n")
        try:
            return tx.commit()
        except Exception:
            tx.abort()
            raise

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
