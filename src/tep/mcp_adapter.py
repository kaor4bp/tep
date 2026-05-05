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
    optional: tuple[str, ...] = ()
    public: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "writes": self.writes,
            "description": self.description,
            "required": list(self.required),
            "optional": list(self.optional),
            "public": self.public,
        }


class MCPAdapter:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._tools: dict[str, tuple[MCPToolSpec, Callable[[dict[str, Any]], RuntimeResponse]]] = {
            "brief": (
                MCPToolSpec("brief", "brief", False, "Return the current task, context, ledger chain, gaps, and next public moves.", ("workspace_ref",), ("agent_ref",), True),
                self._brief_current_context,
            ),
            "capture": (
                MCPToolSpec(
                    "capture",
                    "capture",
                    True,
                    "Capture input, documents, command observations, excerpts, fragments, or extraction candidates.",
                    ("workspace_ref", "capture_kind"),
                    ("text", "path", "input_class", "actor_ref", "thread_ref", "evidence_role", "authority_scope", "source_ref", "confirmation_ref", "source_class", "reason", "quote", "locator", "candidates", "run_ref", "stream", "command", "cwd", "exit_code", "stdout", "stderr", "agent_ref", "open_act_ref", "max_chars"),
                    True,
                ),
                self._capture,
            ),
            "task": (
                MCPToolSpec(
                    "task",
                    "task",
                    True,
                    "Create, attach, decompose, defer, or compile task context.",
                    ("workspace_ref", "task_action"),
                    ("goal", "task_ref", "parent_task_ref", "goals", "agent_ref", "project_ref", "project_refs", "done_criteria", "kind", "text", "support_refs", "resume_condition", "reason", "scope_type", "context_ref"),
                    True,
                ),
                self._task,
            ),
            "claim": (
                MCPToolSpec(
                    "claim",
                    "claim",
                    True,
                    "Create an atomic or aggregate CLM-* fact/hypothesis from explicit support refs.",
                    ("workspace_ref", "statement", "based_on"),
                    ("claim_form", "claim_kind", "project_refs", "task_refs", "support_refs", "contradiction_refs", "aggregation"),
                    True,
                ),
                self._claim,
            ),
            "relate": (
                MCPToolSpec(
                    "relate",
                    "claim",
                    True,
                    "Create a relation CLM-* explaining how two claims connect.",
                    ("workspace_ref", "relation_type", "subject_ref", "object_ref"),
                    ("statement", "project_refs", "task_refs", "source_refs", "reason", "bridge_scope", "synced_object", "bridge_limits"),
                    True,
                ),
                self._link_claims,
            ),
            "reason": (
                MCPToolSpec(
                    "reason",
                    "ledger",
                    True,
                    "Append a selected CLM-* snapshot to the current agent reasoning ledger.",
                    ("workspace_ref", "agent_ref", "agent_private_key", "claim_ref", "why"),
                    ("difficulty_bits",),
                    True,
                ),
                self._append_ledger,
            ),
            "act": (
                MCPToolSpec(
                    "act",
                    "ledger",
                    True,
                    "Open, capture, close, or preflight a bounded ACT probe.",
                    ("workspace_ref", "agent_ref", "agent_private_key", "act_action"),
                    ("claim_ref", "intent", "allowed_action_kind", "expected_evidence", "scope", "evidence_ref", "summary", "outcome", "reason", "result_ref", "action_kind", "action", "difficulty_bits"),
                    True,
                ),
                self._act,
            ),
            "lookup": (
                MCPToolSpec("lookup", "lookup", False, "Lookup reusable CLM-* facts and trust posture.", ("workspace_ref",), ("query", "task_ref", "limit"), True),
                self._lookup_facts,
            ),
            "finish": (
                MCPToolSpec(
                    "finish",
                    "gate",
                    False,
                    "Check final answer, task done, or deferral against the selected CLM support path.",
                    ("workspace_ref", "finish_kind"),
                    ("agent_ref", "task_ref", "support_refs", "reason", "resume_condition"),
                    True,
                ),
                self._finish,
            ),
            "generate_agent_identity": (
                MCPToolSpec("generate_agent_identity", "identity", False, "Generate an in-memory agent identity.", (), public=True),
                self._generate_agent_identity,
            ),
            "start_agent_thread": (
                MCPToolSpec("start_agent_thread", "identity", True, "Bind current thread to an AGENT-* ledger.", ("workspace_ref", "thread_ref", "identity"), public=True),
                self._start_agent_thread,
            ),
            "register_project": (
                MCPToolSpec("register_project", "scope", True, "Register a global PRJ-*.", ("name",)),
                self._register_project,
            ),
            "create_workspace": (
                MCPToolSpec("create_workspace", "scope", True, "Create or reuse a local WSP-* context.", ("name",), ("project_ref", "role", "reason")),
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
                MCPToolSpec(
                    "compile_context_pack",
                    "context",
                    True,
                    "Compile scoped CTX-* text guidance. Pass task_ref when kind is task_briefing.",
                    ("workspace_ref", "kind", "text", "support_refs"),
                    ("task_ref", "project_ref", "agent_ref"),
                ),
                self._compile_context_pack,
            ),
            "list_context_packs": (
                MCPToolSpec("list_context_packs", "context", False, "List scoped CTX-* guidance packs.", ("workspace_ref",), ("task_ref", "project_ref", "scope_type")),
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
            "capture_source_excerpt": (
                MCPToolSpec("capture_source_excerpt", "source", True, "Capture an exact excerpt/span from an existing SRC-*.", ("workspace_ref", "source_ref", "quote"), ("locator",)),
                self._capture_source_excerpt,
            ),
            "capture_source_fragments": (
                MCPToolSpec("capture_source_fragments", "source", True, "Split a long document SRC-* into navigable fragment SRC-* records.", ("workspace_ref", "source_ref"), ("max_chars",)),
                self._capture_source_fragments,
            ),
            "extract_claim_candidates": (
                MCPToolSpec("extract_claim_candidates", "source", True, "Validate quote-backed claim candidates and capture excerpt SRC-* records.", ("workspace_ref", "source_ref", "candidates")),
                self._extract_claim_candidates,
            ),
            "confirm_source_for_scope": (
                MCPToolSpec("confirm_source_for_scope", "source", True, "Confirm a source's class and authority scope using user-provided confirmation evidence.", ("workspace_ref", "source_ref", "confirmation_ref", "source_class", "authority_scope", "reason"), ("actor_ref",)),
                self._confirm_source_for_scope,
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
            "extract_run_claim_candidates": (
                MCPToolSpec("extract_run_claim_candidates", "run", True, "Validate quote-backed claim candidates from RUN-* output and capture SRC-* evidence.", ("workspace_ref", "run_ref", "candidates")),
                self._extract_run_claim_candidates,
            ),
            "decrypt_sensitive_field": (
                MCPToolSpec("decrypt_sensitive_field", "secret", False, "Decrypt an encrypted top-level record field with the host key.", ("workspace_ref", "record_ref", "field")),
                self._decrypt_sensitive_field,
            ),
            "create_claim": (
                MCPToolSpec("create_claim", "claim", True, "Create CLM-* through typed claim API.", ("workspace_ref", "statement")),
                self._create_claim,
            ),
            "create_claim_from_evidence": (
                MCPToolSpec(
                    "create_claim_from_evidence",
                    "claim",
                    True,
                    "Create one atomic CLM-* from captured excerpt evidence.",
                    ("workspace_ref", "statement", "evidence_refs"),
                    ("claim_kind", "project_refs", "task_refs", "support_refs", "contradiction_refs"),
                ),
                self._create_claim_from_evidence,
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
        return [spec.as_dict() for spec, _handler in self._tools.values() if spec.public]

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
                    "details": {"required": list(spec.required), "optional": list(spec.optional)},
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
                    "details": {"tool": name, "required": list(spec.required), "optional": list(spec.optional)},
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
        return self.runtime.create_workspace(args["name"], project_ref=args.get("project_ref"), role=args.get("role", "primary"), reason=args.get("reason", "workspace resolved by MCP"))

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

    def _capture_source_excerpt(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.capture_source_excerpt(workspace_ref, **payload)

    def _capture_source_fragments(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.capture_source_fragments(workspace_ref, **payload)

    def _extract_claim_candidates(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.extract_claim_candidates(workspace_ref, **payload)

    def _confirm_source_for_scope(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.confirm_source_for_scope(workspace_ref, **payload)

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

    def _extract_run_claim_candidates(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.extract_run_claim_candidates(workspace_ref, **payload)

    def _decrypt_sensitive_field(self, args: dict[str, Any]) -> RuntimeResponse:
        return self.runtime.decrypt_sensitive_field(args["workspace_ref"], args["record_ref"], args["field"])

    def _capture(self, args: dict[str, Any]) -> RuntimeResponse:
        kind = str(args["capture_kind"])
        if kind in {"input", "user_input"}:
            return self.runtime.capture_input(
                args["workspace_ref"],
                text=args["text"],
                input_class=args.get("input_class", "task_instruction"),
                actor_ref=args.get("actor_ref", "user"),
                thread_ref=args.get("thread_ref"),
                evidence_role=args.get("evidence_role", "assertion"),
                authority_scope=args.get("authority_scope", "user_supplied_context"),
            )
        if kind == "text":
            return self.runtime.ingest_text(args["workspace_ref"], args["text"], **{key: value for key, value in args.items() if key not in {"workspace_ref", "capture_kind", "text"}})
        if kind == "file":
            return self.runtime.ingest_file(args["workspace_ref"], args["path"], **{key: value for key, value in args.items() if key not in {"workspace_ref", "capture_kind", "path"}})
        if kind in {"bash", "command"}:
            return self.runtime.capture_bash_command(
                args["workspace_ref"],
                command=args["command"],
                cwd=args["cwd"],
                exit_code=args["exit_code"],
                stdout=args.get("stdout", ""),
                stderr=args.get("stderr", ""),
                agent_ref=args.get("agent_ref"),
                open_act_ref=args.get("open_act_ref"),
            )
        if kind == "run_output":
            return self.runtime.capture_run_output_source(args["workspace_ref"], run_ref=args["run_ref"], stream=args.get("stream", "stdout"), quote=args.get("quote"))
        if kind == "source_excerpt":
            return self.runtime.capture_source_excerpt(args["workspace_ref"], source_ref=args["source_ref"], quote=args["quote"], locator=args.get("locator"))
        if kind == "source_fragments":
            return self.runtime.capture_source_fragments(args["workspace_ref"], source_ref=args["source_ref"], max_chars=args.get("max_chars", 4000))
        if kind == "extract_claim_candidates":
            return self.runtime.extract_claim_candidates(args["workspace_ref"], source_ref=args["source_ref"], candidates=args["candidates"])
        if kind == "extract_run_claim_candidates":
            return self.runtime.extract_run_claim_candidates(args["workspace_ref"], run_ref=args["run_ref"], candidates=args["candidates"])
        if kind == "confirm_source":
            return self.runtime.confirm_source_for_scope(
                args["workspace_ref"],
                source_ref=args["source_ref"],
                confirmation_ref=args["confirmation_ref"],
                source_class=args["source_class"],
                authority_scope=args["authority_scope"],
                reason=args["reason"],
                actor_ref=args.get("actor_ref", "runtime"),
            )
        raise ValueError(f"unsupported capture_kind: {kind}")

    def _task(self, args: dict[str, Any]) -> RuntimeResponse:
        action = str(args["task_action"])
        if action == "create":
            return self.runtime.create_task(
                args["workspace_ref"],
                args["goal"],
                parent_task_ref=args.get("parent_task_ref"),
                project_refs=args.get("project_refs"),
                done_criteria=args.get("done_criteria"),
            )
        if action == "attach_agent":
            return self.runtime.attach_agent_to_task(args["workspace_ref"], args["agent_ref"], args["task_ref"])
        if action == "decompose":
            return self.runtime.decompose_task(args["workspace_ref"], args["parent_task_ref"], args["goals"])
        if action == "defer":
            return self.runtime.defer_task(args["workspace_ref"], args["task_ref"], reason=args["reason"], resume_condition=args.get("resume_condition"))
        if action == "compile_context":
            return self.runtime.compile_context_pack(
                args["workspace_ref"],
                task_ref=args.get("task_ref"),
                project_ref=args.get("project_ref"),
                kind=args["kind"],
                text=args["text"],
                support_refs=args["support_refs"],
                agent_ref=args.get("agent_ref"),
            )
        if action == "list_context":
            return self.runtime.list_context_packs(
                args["workspace_ref"],
                task_ref=args.get("task_ref"),
                project_ref=args.get("project_ref"),
                scope_type=args.get("scope_type"),
            )
        if action == "revoke_context":
            return self.runtime.revoke_context_pack(args["workspace_ref"], args["context_ref"], reason=args["reason"])
        raise ValueError(f"unsupported task_action: {action}")

    def _claim(self, args: dict[str, Any]) -> RuntimeResponse:
        based_on = args["based_on"]
        if not isinstance(based_on, list) or not based_on:
            raise ValueError("claim.based_on must be a non-empty array of SRC/INP/CLM refs")
        source_refs = list(args.get("source_refs") or [])
        support_refs = list(args.get("support_refs") or [])
        for ref in based_on:
            if not isinstance(ref, str):
                raise ValueError("claim.based_on entries must be refs")
            if ref.startswith(("SRC-", "INP-")):
                source_refs.append(ref)
            elif ref.startswith("CLM-"):
                support_refs.append(ref)
            elif ref.startswith("RUN-"):
                raise ValueError("RUN-* must be converted to SRC-* with capture before creating CLM-*")
            else:
                raise ValueError(f"unsupported based_on ref: {ref}")
        return self.runtime.create_claim(
            args["workspace_ref"],
            args["statement"],
            claim_form=args.get("claim_form", "assertion"),
            claim_kind=args.get("claim_kind", "other"),
            project_refs=args.get("project_refs"),
            task_refs=args.get("task_refs"),
            source_refs=sorted(set(source_refs)),
            support_refs=sorted(set(support_refs)),
            contradiction_refs=args.get("contradiction_refs"),
            aggregation=args.get("aggregation"),
        )

    def _create_claim(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        statement = payload.pop("statement")
        return self.runtime.create_claim(workspace_ref, statement, **payload)

    def _create_claim_from_evidence(self, args: dict[str, Any]) -> RuntimeResponse:
        payload = dict(args)
        workspace_ref = payload.pop("workspace_ref")
        return self.runtime.create_claim_from_evidence(workspace_ref, **payload)

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

    def _act(self, args: dict[str, Any]) -> RuntimeResponse:
        action = str(args["act_action"])
        if action == "open":
            return self._open_probe(args)
        if action == "capture":
            return self._capture_probe_result(args)
        if action == "close":
            return self._close_probe(args)
        if action == "preflight":
            return self._protected_action_preflight(args)
        raise ValueError(f"unsupported act_action: {action}")

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

    def _finish(self, args: dict[str, Any]) -> RuntimeResponse:
        kind = str(args["finish_kind"])
        if kind in {"final", "final_answer"}:
            return self.runtime.final_answer_preflight(
                workspace_ref=args["workspace_ref"],
                agent_ref=args["agent_ref"],
                support_refs=args.get("support_refs", []),
                task_ref=args.get("task_ref"),
            )
        if kind in {"task_done", "done"}:
            return self.runtime.task_done_preflight(
                workspace_ref=args["workspace_ref"],
                agent_ref=args["agent_ref"],
                task_ref=args["task_ref"],
                support_refs=args.get("support_refs", []),
            )
        if kind == "defer":
            return self.runtime.defer_task(args["workspace_ref"], args["task_ref"], reason=args["reason"], resume_condition=args.get("resume_condition"))
        raise ValueError(f"unsupported finish_kind: {kind}")

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
