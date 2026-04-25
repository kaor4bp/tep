"""Transport-neutral MCP tool adapter.

The real MCP server should be a thin transport layer over this module. Keeping
the dispatch here makes tool behavior testable without binding core protocol
semantics to a particular Python MCP SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .crypto import AgentIdentity
from .responses import RuntimeResponse
from .runtime import Runtime


@dataclass(frozen=True)
class MCPToolSpec:
    name: str
    kind: str
    writes: bool
    description: str
    required: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "writes": self.writes,
            "description": self.description,
            "required": list(self.required),
        }


class MCPAdapter:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._tools: dict[str, tuple[MCPToolSpec, Callable[[dict[str, Any]], RuntimeResponse]]] = {
            "generate_agent_identity": (
                MCPToolSpec("generate_agent_identity", "identity", False, "Generate an in-memory agent identity.", ()),
                self._generate_agent_identity,
            ),
            "start_agent_thread": (
                MCPToolSpec("start_agent_thread", "identity", True, "Bind current thread to an AGENT-* ledger.", ("workspace_ref", "thread_ref", "identity")),
                self._start_agent_thread,
            ),
            "register_project": (
                MCPToolSpec("register_project", "scope", True, "Register a global PRJ-*.", ("name",)),
                self._register_project,
            ),
            "create_workspace": (
                MCPToolSpec("create_workspace", "scope", True, "Create a local WSP-* context.", ("name",)),
                self._create_workspace,
            ),
            "archive_workspace": (
                MCPToolSpec("archive_workspace", "scope", True, "Archive a WSP-* registry record.", ("workspace_ref", "reason")),
                self._archive_workspace,
            ),
            "attach_project_to_workspace": (
                MCPToolSpec("attach_project_to_workspace", "scope", True, "Attach PRJ-* to WSP-* by role.", ("workspace_ref", "project_ref", "role", "reason")),
                self._attach_project_to_workspace,
            ),
            "archive_project": (
                MCPToolSpec("archive_project", "scope", True, "Archive a PRJ-* registry record.", ("project_ref", "reason")),
                self._archive_project,
            ),
            "create_task": (
                MCPToolSpec("create_task", "task", True, "Create a TASK-*.", ("workspace_ref", "goal")),
                self._create_task,
            ),
            "decompose_task": (
                MCPToolSpec("decompose_task", "task", True, "Split TASK-* into child tasks.", ("workspace_ref", "parent_task_ref", "goals")),
                self._decompose_task,
            ),
            "defer_task": (
                MCPToolSpec("defer_task", "task", True, "Defer TASK-* with resume condition.", ("workspace_ref", "task_ref", "reason")),
                self._defer_task,
            ),
            "attach_agent_to_task": (
                MCPToolSpec("attach_agent_to_task", "task", True, "Attach AGENT-* to TASK-*.", ("workspace_ref", "agent_ref", "task_ref")),
                self._attach_agent_to_task,
            ),
            "brief_current_context": (
                MCPToolSpec("brief_current_context", "brief", False, "Return current workspace/task/agent briefing.", ("workspace_ref",)),
                self._brief_current_context,
            ),
            "read_settings": (
                MCPToolSpec("read_settings", "settings", False, "Read merged TEP enforcement settings.", ()),
                self._read_settings,
            ),
            "update_settings": (
                MCPToolSpec("update_settings", "settings", True, "Update TEP enforcement settings.", ("settings",)),
                self._update_settings,
            ),
            "action_pressure": (
                MCPToolSpec("action_pressure", "settings", False, "Classify an action against enforcement settings.", ("workspace_ref", "action_kind", "action")),
                self._action_pressure,
            ),
            "compile_context_pack": (
                MCPToolSpec("compile_context_pack", "context", True, "Compile scoped CTX-* text guidance.", ("workspace_ref", "kind", "text", "support_refs")),
                self._compile_context_pack,
            ),
            "list_context_packs": (
                MCPToolSpec("list_context_packs", "context", False, "List scoped CTX-* guidance packs.", ("workspace_ref",)),
                self._list_context_packs,
            ),
            "revoke_context_pack": (
                MCPToolSpec("revoke_context_pack", "context", True, "Revoke a CTX-* guidance pack.", ("workspace_ref", "context_ref", "reason")),
                self._revoke_context_pack,
            ),
            "create_source": (
                MCPToolSpec("create_source", "source", True, "Capture SRC-* through typed source API.", ("workspace_ref", "source_kind", "quote")),
                self._create_source,
            ),
            "ingest_text": (
                MCPToolSpec("ingest_text", "source", True, "Ingest user-supplied text as SRC-*.", ("workspace_ref", "text")),
                self._ingest_text,
            ),
            "ingest_file": (
                MCPToolSpec("ingest_file", "source", True, "Ingest a local UTF-8 file as SRC-*.", ("workspace_ref", "path")),
                self._ingest_file,
            ),
            "capture_input": (
                MCPToolSpec("capture_input", "input", True, "Capture an INP-* event and source.", ("workspace_ref", "text", "input_class")),
                self._capture_input,
            ),
            "capture_bash_command": (
                MCPToolSpec("capture_bash_command", "run", True, "Capture an observed bash command as RUN-*.", ("workspace_ref", "command", "cwd", "exit_code")),
                self._capture_bash_command,
            ),
            "capture_run_output_source": (
                MCPToolSpec("capture_run_output_source", "source", True, "Capture RUN-* output excerpt as audited SRC-*.", ("workspace_ref", "run_ref")),
                self._capture_run_output_source,
            ),
            "decrypt_sensitive_field": (
                MCPToolSpec("decrypt_sensitive_field", "secret", False, "Decrypt an encrypted top-level record field with the host key.", ("workspace_ref", "record_ref", "field")),
                self._decrypt_sensitive_field,
            ),
            "create_claim": (
                MCPToolSpec("create_claim", "claim", True, "Create CLM-* through typed claim API.", ("workspace_ref", "statement")),
                self._create_claim,
            ),
            "link_claims": (
                MCPToolSpec("link_claims", "claim", True, "Create relation CLM-* between claims.", ("workspace_ref", "relation_type", "subject_ref", "object_ref")),
                self._link_claims,
            ),
            "append_ledger": (
                MCPToolSpec("append_ledger", "ledger", True, "Append sealed claim snapshot to current AGENT-* ledger.", ("workspace_ref", "agent_ref", "agent_private_key", "claim_ref", "why")),
                self._append_ledger,
            ),
            "open_probe": (
                MCPToolSpec("open_probe", "ledger", True, "Open ACT in current ledger.", ("workspace_ref", "agent_ref", "agent_private_key", "claim_ref", "intent", "allowed_action_kind", "expected_evidence")),
                self._open_probe,
            ),
            "protected_action_preflight": (
                MCPToolSpec("protected_action_preflight", "run", True, "Issue RUN-* preflight for open ACT.", ("workspace_ref", "agent_ref", "agent_private_key", "action_kind", "action")),
                self._protected_action_preflight,
            ),
            "capture_probe_result": (
                MCPToolSpec("capture_probe_result", "ledger", True, "Capture evidence for open ACT.", ("workspace_ref", "agent_ref", "agent_private_key", "claim_ref", "evidence_ref", "summary")),
                self._capture_probe_result,
            ),
            "close_probe": (
                MCPToolSpec("close_probe", "ledger", True, "Close current ACT.", ("workspace_ref", "agent_ref", "agent_private_key", "claim_ref", "outcome", "reason")),
                self._close_probe,
            ),
            "validate_ledger": (
                MCPToolSpec("validate_ledger", "ledger", False, "Replay AGENT-* ledger.", ("workspace_ref", "agent_ref")),
                self._validate_ledger,
            ),
            "lookup_facts": (
                MCPToolSpec("lookup_facts", "lookup", False, "Lookup CLM-* facts with scope/trust posture.", ("workspace_ref",)),
                self._lookup_facts,
            ),
            "record_detail": (
                MCPToolSpec("record_detail", "detail", False, "Inspect a TEP record.", ("workspace_ref", "record_ref")),
                self._record_detail,
            ),
            "refresh_indexes": (
                MCPToolSpec("refresh_indexes", "index", True, "Rebuild runtime navigation indexes.", ("workspace_ref",)),
                self._refresh_indexes,
            ),
            "index_status": (
                MCPToolSpec("index_status", "index", False, "Inspect runtime navigation index manifests.", ("workspace_ref",)),
                self._index_status,
            ),
            "final_answer_preflight": (
                MCPToolSpec("final_answer_preflight", "gate", False, "Check whether final answer may use selected support refs.", ("workspace_ref", "agent_ref", "support_refs")),
                self._final_answer_preflight,
            ),
            "task_done_preflight": (
                MCPToolSpec("task_done_preflight", "gate", False, "Check whether TASK-* can be marked done.", ("workspace_ref", "agent_ref", "task_ref", "support_refs")),
                self._task_done_preflight,
            ),
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [spec.as_dict() for spec, _handler in self._tools.values()]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self._tools:
            return {
                "ok": False,
                "error": {"code": "unknown_tool", "message": f"unknown MCP tool: {name}", "details": {}},
                "repair_options": [{"operation_kind": "list_tools", "why": "Inspect supported TEP tools."}],
            }
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return {
                "ok": False,
                "error": {"code": "invalid_arguments", "message": "tool arguments must be a JSON object", "details": {}},
            }
        spec, handler = self._tools[name]
        missing = [key for key in spec.required if key not in arguments]
        if missing:
            return {
                "ok": False,
                "error": {
                    "code": "missing_required_arguments",
                    "message": ",".join(missing),
                    "details": {"required": list(spec.required)},
                },
                "repair_options": [{"operation_kind": name, "why": "Call tool with required arguments."}],
            }
        try:
            response = handler(arguments)
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_arguments",
                    "message": str(exc),
                    "details": {"tool": name, "required": list(spec.required)},
                },
                "repair_options": [{"operation_kind": name, "why": "Call tool with valid typed arguments."}],
            }
        result = response.as_dict()
        result["tool"] = spec.as_dict()
        return result

    def _generate_agent_identity(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.generate_identity(args.get("agent_name"))

    def _start_agent_thread(self, args: dict[str, Any]) -> RuntimeResponse:
        identity = self._identity(args["identity"])
        return self.runtime.start_agent_thread(
            workspace_ref=args["workspace_ref"],
            thread_ref=args["thread_ref"],
            identity=identity,
            allow_create=args.get("allow_create", True),
        )

    def _register_project(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.register_project(
            args["name"],
            roots=args.get("roots"),
            aliases=args.get("aliases"),
            project_type=args.get("project_type", "repo"),
            parent_project_refs=args.get("parent_project_refs"),
        )

    def _create_workspace(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.create_workspace(args["name"])

    def _archive_workspace(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.archive_workspace(args["workspace_ref"], reason=args["reason"])

    def _attach_project_to_workspace(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.attach_project_to_workspace(
            args["workspace_ref"],
            args["project_ref"],
            role=args["role"],
            reason=args["reason"],
            include_children=args.get("include_children", False),
        )

    def _archive_project(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.archive_project(args["project_ref"], reason=args["reason"])

    def _create_task(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.create_task(
            args["workspace_ref"],
            args["goal"],
            parent_task_ref=args.get("parent_task_ref"),
            project_refs=args.get("project_refs"),
            done_criteria=args.get("done_criteria"),
        )

    def _decompose_task(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.decompose_task(args["workspace_ref"], args["parent_task_ref"], args["goals"])

    def _defer_task(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.defer_task(args["workspace_ref"], args["task_ref"], reason=args["reason"], resume_condition=args.get("resume_condition"))

    def _attach_agent_to_task(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.attach_agent_to_task(args["workspace_ref"], args["agent_ref"], args["task_ref"])

    def _brief_current_context(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.brief_current_context(args["workspace_ref"], args.get("agent_ref"))

    def _read_settings(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.read_settings(args.get("workspace_ref"))

    def _update_settings(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.update_settings(args["settings"], workspace_ref=args.get("workspace_ref"))

    def _action_pressure(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.action_pressure(
            args["workspace_ref"],
            action_kind=args["action_kind"],
            action=args["action"],
            agent_ref=args.get("agent_ref"),
        )

    def _compile_context_pack(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.compile_context_pack(
            args["workspace_ref"],
            task_ref=args.get("task_ref"),
            project_ref=args.get("project_ref"),
            kind=args["kind"],
            text=args["text"],
            support_refs=args["support_refs"],
            agent_ref=args.get("agent_ref"),
        )

    def _list_context_packs(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.list_context_packs(
            args["workspace_ref"],
            task_ref=args.get("task_ref"),
            project_ref=args.get("project_ref"),
            scope_type=args.get("scope_type"),
        )

    def _revoke_context_pack(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.revoke_context_pack(args["workspace_ref"], args["context_ref"], reason=args["reason"])

    def _create_source(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.create_source(workspace_ref, **payload)

    def _ingest_text(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        text = payload.pop("text")
        return self.runtime.ingest_text(workspace_ref, text, **payload)

    def _ingest_file(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        path = payload.pop("path")
        return self.runtime.ingest_file(workspace_ref, path, **payload)

    def _capture_input(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.capture_input(workspace_ref, **payload)

    def _capture_bash_command(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.capture_bash_command(workspace_ref, **payload)

    def _capture_run_output_source(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.capture_run_output_source(workspace_ref, **payload)

    def _decrypt_sensitive_field(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.decrypt_sensitive_field(args["workspace_ref"], args["record_ref"], args["field"])

    def _create_claim(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        statement = payload.pop("statement")
        return self.runtime.create_claim(workspace_ref, statement, **payload)

    def _link_claims(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.link_claims(workspace_ref, **payload)

    def _append_ledger(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.append_ledger(
            workspace_ref=args["workspace_ref"],
            agent_ref=args["agent_ref"],
            private_key=args["agent_private_key"],
            claim_ref=args["claim_ref"],
            why=args["why"],
            difficulty_bits=args.get("difficulty_bits", 18),
        )

    def _open_probe(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.open_probe(
            workspace_ref=args["workspace_ref"],
            agent_ref=args["agent_ref"],
            private_key=args["agent_private_key"],
            claim_ref=args["claim_ref"],
            intent=args["intent"],
            allowed_action_kind=args["allowed_action_kind"],
            expected_evidence=args["expected_evidence"],
            scope=args.get("scope"),
            difficulty_bits=args.get("difficulty_bits", 18),
        )

    def _protected_action_preflight(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.protected_action_preflight(
            workspace_ref=args["workspace_ref"],
            agent_ref=args["agent_ref"],
            private_key=args["agent_private_key"],
            action_kind=args["action_kind"],
            action=args["action"],
        )

    def _capture_probe_result(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.capture_probe_result(
            workspace_ref=args["workspace_ref"],
            agent_ref=args["agent_ref"],
            private_key=args["agent_private_key"],
            claim_ref=args["claim_ref"],
            evidence_ref=args["evidence_ref"],
            summary=args["summary"],
            difficulty_bits=args.get("difficulty_bits", 18),
        )

    def _close_probe(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.close_probe(
            workspace_ref=args["workspace_ref"],
            agent_ref=args["agent_ref"],
            private_key=args["agent_private_key"],
            claim_ref=args["claim_ref"],
            outcome=args["outcome"],
            reason=args["reason"],
            result_ref=args.get("result_ref"),
            difficulty_bits=args.get("difficulty_bits", 18),
        )

    def _validate_ledger(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.validate_ledger(args["workspace_ref"], args["agent_ref"])

    def _lookup_facts(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.lookup_facts(
            args["workspace_ref"],
            query=args.get("query"),
            task_ref=args.get("task_ref"),
            limit=args.get("limit", 20),
        )

    def _record_detail(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.record_detail(args["workspace_ref"], args["record_ref"])

    def _refresh_indexes(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.refresh_indexes(args["workspace_ref"])

    def _index_status(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.index_status(args["workspace_ref"])

    def _final_answer_preflight(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.final_answer_preflight(
            workspace_ref=args["workspace_ref"],
            agent_ref=args["agent_ref"],
            support_refs=args["support_refs"],
            task_ref=args.get("task_ref"),
        )

    def _task_done_preflight(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.task_done_preflight(
            workspace_ref=args["workspace_ref"],
            agent_ref=args["agent_ref"],
            task_ref=args["task_ref"],
            support_refs=args["support_refs"],
        )

    @staticmethod
    def _identity(data: dict[str, Any]) -> AgentIdentity:
        return AgentIdentity(
            agent_ref=data["agent_ref"],
            agent_name=data["agent_name"],
            private_key=data["agent_private_key"],
            public_key=data["public_key"],
            key_fingerprint=data["key_fingerprint"],
            seal_suite=data.get("seal_suite", "cryptography-ed25519-v1"),
        )
