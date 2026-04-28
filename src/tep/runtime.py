"""Protocol runtime facade used by a future MCP transport."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Callable

from .crypto import AgentIdentity, assert_private_key_matches, generate_agent_identity
from .enforcement import action_pressure as compute_action_pressure, context_requirements, required_context_kinds
from .errors import OwnershipError, TEPError, ValidationError
from .indexes import IndexService
from .ingest import ingest_file_payload, ingest_text_payload
from .ledger import Ledger
from .posture import PostureService
from .responses import RuntimeResponse, error_response, move, ok_response
from .secrets import decrypt_text, has_secrets, maybe_encrypt_text
from .storage import TEPHome


class Runtime:
    """Small RISC-style facade.

    This is deliberately transport-free. MCP should call this layer rather than
    duplicating protocol decisions inside tool handlers.
    """

    def __init__(self, store: TEPHome) -> None:
        self.store = store
        self.posture = PostureService(store)
        self.indexes = IndexService(store)

    def generate_identity(self, agent_name: str | None = None) -> RuntimeResponse:
        identity = generate_agent_identity(agent_name)
        return ok_response(
            {
                "agent_ref": identity.agent_ref,
                "agent_name": identity.agent_name,
                "agent_private_key": identity.private_key,
                "public_key": identity.public_key,
                "key_fingerprint": identity.key_fingerprint,
                "seal_suite": identity.seal_suite,
            },
            valid_moves=[
                move("mutate_record", "start_agent_thread", "Bind this identity to an AGENT-* in a workspace.", writes=True)
            ],
        )

    def start_agent_thread(
        self,
        *,
        workspace_ref: str,
        thread_ref: str,
        identity: AgentIdentity,
        allow_create: bool = True,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            existing = self.store.find_agent_by_thread(workspace_ref, thread_ref)
            if existing is not None:
                if existing.get("key_fingerprint") != identity.key_fingerprint:
                    raise OwnershipError("thread_ref is already bound to a different key fingerprint")
                return ok_response({"agent": existing}, valid_moves=[move("brief", "brief_current_context", "Load current task and ledger posture.")])
            if not allow_create:
                raise ValidationError("agent_not_found")
            agent = self.store.create_agent(workspace_ref, identity, thread_ref=thread_ref)
            return ok_response({"agent": agent}, valid_moves=[move("brief", "brief_current_context", "Load initial task and ledger posture.")])

        return self._guard(op)

    def read_settings(self, workspace_ref: str | None = None) -> RuntimeResponse:
        return self._guard(lambda: ok_response({"settings": self.store.read_settings(workspace_ref)}))

    def update_settings(self, settings: dict[str, Any], *, workspace_ref: str | None = None) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"settings": self.store.update_settings(settings, workspace_ref=workspace_ref)},
                valid_moves=[move("brief", "brief_current_context", "Refresh briefing with updated enforcement settings.")],
            )
        )

    def action_pressure(
        self,
        workspace_ref: str,
        *,
        action_kind: str,
        action: dict[str, Any],
        agent_ref: str | None = None,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            pressure = compute_action_pressure(
                self.store.read_settings(workspace_ref),
                action_kind,
                action,
                open_act=self._ledger_pressure(workspace_ref, agent_ref)["open_act"] if agent_ref else None,
            )
            return ok_response({"action_pressure": pressure}, valid_moves=pressure["valid_moves"])

        return self._guard(op)

    def register_project(
        self,
        name: str,
        *,
        roots: list[str] | None = None,
        aliases: list[str] | None = None,
        project_type: str = "repo",
        parent_project_refs: list[str] | None = None,
    ) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"project": self.store.register_project(name, roots=roots, aliases=aliases, project_type=project_type, parent_project_refs=parent_project_refs)},
                valid_moves=[move("mutate_record", "attach_project_to_workspace", "Attach project to a workspace scope.", writes=True)],
            )
        )

    def create_workspace(self, name: str, *, project_ref: str | None = None, role: str = "primary", reason: str = "workspace resolved by create_workspace") -> RuntimeResponse:
        def op() -> RuntimeResponse:
            if project_ref:
                existing = self.store.active_workspaces_for_project(project_ref)
                if existing:
                    return ok_response(
                        {"workspace": existing[0], "reused": True, "project_ref": project_ref},
                        valid_moves=[move("mutate_record", "create_task", "Create or resume a task in this workspace.", writes=True)],
                    )
            existing_by_name = self.store.active_workspace_by_name(name)
            workspace = self.store.create_workspace(name)
            reused = existing_by_name is not None and existing_by_name.get("id") == workspace.get("id")
            if project_ref and project_ref not in self.store.visible_project_refs(workspace["id"]):
                self.store.attach_project_to_workspace(workspace["id"], project_ref, role=role, reason=reason)
            return ok_response(
                {"workspace": workspace, "reused": reused, "project_ref": project_ref},
                valid_moves=[move("mutate_record", "attach_project_to_workspace", "Attach one or more projects.", writes=True)],
            )

        return self._guard(op)

    def archive_workspace(self, workspace_ref: str, *, reason: str) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"workspace": self.store.archive_workspace(workspace_ref, reason=reason)},
                valid_moves=[move("detail", "record_detail", "Inspect archived workspace metadata.")],
            )
        )

    def archive_project(self, project_ref: str, *, reason: str) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"project": self.store.archive_project(project_ref, reason=reason)},
                valid_moves=[move("lookup", "project_registry_search", "Confirm active project registry state.")],
            )
        )

    def attach_project_to_workspace(
        self,
        workspace_ref: str,
        project_ref: str,
        *,
        role: str,
        reason: str,
        include_children: bool = False,
    ) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"membership": self.store.attach_project_to_workspace(workspace_ref, project_ref, role=role, reason=reason, include_children=include_children)},
                valid_moves=[move("mutate_record", "create_task", "Create or resume a task in this workspace.", writes=True)],
            )
        )

    def create_task(
        self,
        workspace_ref: str,
        goal: str,
        *,
        parent_task_ref: str | None = None,
        project_refs: list[str] | None = None,
        done_criteria: list[str] | None = None,
    ) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"task": self.store.create_task(workspace_ref, goal, parent_task_ref=parent_task_ref, project_refs=project_refs, done_criteria=done_criteria)},
                valid_moves=[
                    move("mutate_record", "attach_agent_to_task", "Attach current agent to the task.", writes=True),
                    move("mutate_record", "decompose_task", "Split broad work into subtasks.", writes=True),
                    move("lookup", "lookup_facts", "Find existing facts relevant to the task."),
                ],
            )
        )

    def decompose_task(self, workspace_ref: str, parent_task_ref: str, goals: list[str]) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"tasks": self.store.decompose_task(workspace_ref, parent_task_ref, goals)},
                valid_moves=[
                    move("mutate_record", "attach_agent_to_task", "Attach current agent to a child task.", writes=True),
                    move("brief", "brief_current_context", "Refresh briefing after decomposition."),
                ],
            )
        )

    def defer_task(self, workspace_ref: str, task_ref: str, *, reason: str, resume_condition: str | None = None) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"task": self.store.defer_task(workspace_ref, task_ref, reason=reason, resume_condition=resume_condition)},
                valid_moves=[move("brief", "brief_current_context", "Return to current briefing.")],
            )
        )

    def attach_agent_to_task(self, workspace_ref: str, agent_ref: str, task_ref: str) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"agent": self.store.attach_agent_to_task(workspace_ref, agent_ref, task_ref)},
                valid_moves=[
                    move("brief", "brief_current_context", "Brief current task context."),
                    move("lookup", "lookup_facts", "Find facts relevant to this task."),
                ],
            )
        )

    def compile_context_pack(
        self,
        workspace_ref: str,
        *,
        task_ref: str | None = None,
        project_ref: str | None = None,
        kind: str,
        text: str,
        support_refs: list[str],
        agent_ref: str | None = None,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            pack = self.store.create_context_pack(
                workspace_ref,
                task_ref=task_ref,
                project_ref=project_ref,
                kind=kind,
                text=text,
                support_refs=support_refs,
                agent_ref=agent_ref,
            )
            task_context = self._task_context_state(workspace_ref, task_ref) if task_ref else None
            return ok_response(
                {"context_pack": pack, "task_context": task_context},
                valid_moves=[
                    move("brief", "brief_current_context", "Refresh briefing with active context packs."),
                    move("detail", "record_detail", "Inspect compiled context pack."),
                ],
            )

        return self._guard(op)

    def list_context_packs(self, workspace_ref: str, *, task_ref: str | None = None, project_ref: str | None = None, scope_type: str | None = None) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"context_packs": self.store.context_packs(workspace_ref, task_ref=task_ref, project_ref=project_ref, scope_type=scope_type)},
                valid_moves=[move("brief", "brief_current_context", "Use active context packs for task guidance.")],
            )
        )

    def revoke_context_pack(self, workspace_ref: str, context_ref: str, *, reason: str) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            pack = self.store.revoke_context_pack(workspace_ref, context_ref, reason=reason)
            task_context = self._task_context_state(workspace_ref, pack["task_ref"]) if pack.get("task_ref") else None
            return ok_response(
                {"context_pack": pack, "task_context": task_context},
                valid_moves=[move("mutate_record", "compile_context_pack", "Compile replacement context if still required.", writes=True)],
            )

        return self._guard(op)

    def create_source(self, workspace_ref: str, **kwargs: Any) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            source = self.store.create_source(workspace_ref, **kwargs)
            moves = self._source_valid_moves(source)
            source_pressure = []
            if self.store._source_requires_excerpt(source):
                source_pressure.append(
                    {
                        "level": "high",
                        "source_refs": [source["id"]],
                        "why": "document source requires excerpt-based extraction before CLM creation",
                        "valid_moves": [
                            move("mutate_record", "extract_claim_candidates", "Extract quote-backed candidate CLM-* facts.", writes=True),
                            move("mutate_record", "capture_source_fragments", "Split long document into navigable SRC-* fragments.", writes=True),
                            move("mutate_record", "capture_source_excerpt", "Capture exact quote/span for one atomic fact.", writes=True),
                            move("lookup", "lookup_facts", "Check whether the extracted fact already exists."),
                        ],
                    }
                )
            if source.get("critique_status") != "accepted":
                source_pressure.append(
                    {
                        "level": "medium",
                        "source_refs": [source["id"]],
                        "why": "source is captured but not accepted for commitment",
                        "valid_moves": self._source_valid_moves(source),
                    }
                )
            return ok_response({"source": source}, source_pressure=source_pressure, valid_moves=moves)

        return self._guard(op)

    def capture_source_fragments(
        self,
        workspace_ref: str,
        *,
        source_ref: str,
        max_chars: int = 4000,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            if max_chars < 500 or max_chars > 20000:
                raise ValidationError("source_fragment_max_chars_out_of_range")
            parent = self.store.read_source(workspace_ref, source_ref)
            parent_quote = parent.get("quote")
            if not isinstance(parent_quote, str):
                raise ValidationError("source_fragment_requires_plaintext_parent")
            spans = self._source_fragment_spans(parent_quote, max_chars=max_chars)
            fragments = []
            for index, span in enumerate(spans, start=1):
                text = parent_quote[span["start"] : span["end"]]
                classification = dict(parent.get("classification", {}))
                classification["independence_key"] = f"{source_ref}:{span['start']}:{span['end']}"
                fragment = self.store.create_source(
                    workspace_ref,
                    source_kind=parent.get("source_kind", "file_quote"),
                    quote=text,
                    classification=classification,
                    origin={"kind": "source_fragment", "ref": source_ref},
                    provenance={
                        "entity_ref": parent.get("provenance", {}).get("entity_ref") or source_ref,
                        "activity_ref": "capture_source_fragments",
                        "responsible_agent": "runtime",
                        "content_hash": self.store._captured_text_hash(text),
                        "locator": f"{parent.get('provenance', {}).get('locator') or source_ref}#fragment-{index}",
                        "quote_span": span,
                        "retrieved_at": parent.get("provenance", {}).get("retrieved_at"),
                        "published_at": parent.get("provenance", {}).get("published_at"),
                    },
                    project_refs=parent.get("project_refs", []),
                    critique_status=parent.get("critique_status"),
                    reason=f"fragment {index} captured from {source_ref}",
                )
                fragments.append(fragment)
            return ok_response(
                {"fragments": fragments, "parent_source_ref": source_ref},
                source_pressure=[
                    {
                        "level": "medium",
                        "source_refs": [fragment["id"] for fragment in fragments],
                        "why": "fragments are navigation units; create CLM-* only from exact extracted quotes",
                        "valid_moves": [
                            move("mutate_record", "extract_claim_candidates", "Extract quote-backed claims from a fragment.", writes=True),
                            move("lookup", "lookup_facts", "Check for duplicate or related facts."),
                        ],
                    }
                ],
                valid_moves=[
                    move("mutate_record", "extract_claim_candidates", "Extract quote-backed claims from selected fragments.", writes=True),
                    move("lookup", "lookup_facts", "Check for duplicate or related facts."),
                ],
            )

        return self._guard(op)

    def capture_source_excerpt(
        self,
        workspace_ref: str,
        *,
        source_ref: str,
        quote: str,
        locator: str | None = None,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            source = self._capture_excerpt_source(workspace_ref, source_ref=source_ref, quote=quote, locator=locator)
            return ok_response(
                {"source": source, "parent_source_ref": source_ref},
                valid_moves=[
                    move("mutate_record", "create_claim_from_evidence", "Create one atomic CLM-* from this excerpt.", writes=True),
                    move("lookup", "lookup_facts", "Check for duplicate or related claims."),
                ],
            )

        return self._guard(op)

    def extract_claim_candidates(
        self,
        workspace_ref: str,
        *,
        source_ref: str,
        candidates: list[dict[str, Any]],
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            if not candidates:
                raise ValidationError("extract_claim_candidates_requires_candidates")
            parent = self.store.read_source(workspace_ref, source_ref)
            parent_quote = parent.get("quote")
            if not isinstance(parent_quote, str):
                raise ValidationError("source_excerpt_requires_plaintext_parent")
            prepared = []
            for index, candidate in enumerate(candidates):
                if not isinstance(candidate, dict):
                    raise ValidationError(f"claim_candidate_invalid:{index}")
                quote = str(candidate.get("quote") or "").strip()
                statement = str(candidate.get("statement") or "").strip()
                if not quote:
                    raise ValidationError(f"claim_candidate_quote_required:{index}")
                if not statement:
                    raise ValidationError(f"claim_candidate_statement_required:{index}")
                claim_kind = str(candidate.get("claim_kind") or "other")
                confidence_bps = candidate.get("confidence_bps")
                if confidence_bps is not None and (not isinstance(confidence_bps, int) or confidence_bps < 0 or confidence_bps > 10000):
                    raise ValidationError(f"claim_candidate_confidence_bps_invalid:{index}")
                start = parent_quote.find(quote)
                if start < 0:
                    raise ValidationError(f"quote_not_found_in_source:{index}")
                prepared.append(
                    {
                        "index": index,
                        "quote": quote,
                        "statement": statement,
                        "claim_kind": claim_kind,
                        "confidence_bps": confidence_bps,
                        "why_this_follows": str(candidate.get("why_this_follows") or ""),
                        "locator": candidate.get("locator"),
                        "quote_span": {"start": start, "end": start + len(quote)},
                    }
                )
            extracted = []
            for candidate in prepared:
                source = self._capture_excerpt_source(
                    workspace_ref,
                    source_ref=source_ref,
                    quote=candidate["quote"],
                    locator=candidate.get("locator"),
                )
                extracted.append(
                    {
                        "index": candidate["index"],
                        "source_ref": source_ref,
                        "excerpt_source_ref": source["id"],
                        "statement": candidate["statement"],
                        "claim_kind": candidate["claim_kind"],
                        "confidence_bps": candidate["confidence_bps"],
                        "why_this_follows": candidate["why_this_follows"],
                        "quote_span": source.get("provenance", {}).get("quote_span"),
                    }
                )
            return ok_response(
                {"claim_candidates": extracted},
                source_pressure=[
                    {
                        "level": "medium",
                        "source_refs": [source_ref],
                        "why": "candidate excerpts are captured but not yet committed as CLM-* facts",
                        "valid_moves": [
                            move("mutate_record", "create_claim_from_evidence", "Create one atomic CLM-* per useful candidate.", writes=True),
                            move("lookup", "lookup_facts", "Check for duplicate or related claims before committing."),
                        ],
                    }
                ],
                valid_moves=[
                    move("mutate_record", "create_claim_from_evidence", "Create one atomic CLM-* from an excerpt candidate.", writes=True),
                    move("lookup", "lookup_facts", "Check for duplicate or related claims."),
                ],
            )

        return self._guard(op)

    def create_claim_from_evidence(
        self,
        workspace_ref: str,
        *,
        statement: str,
        evidence_refs: list[str],
        claim_kind: str = "other",
        project_refs: list[str] | None = None,
        task_refs: list[str] | None = None,
        support_refs: list[str] | None = None,
        contradiction_refs: list[str] | None = None,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            if not evidence_refs:
                raise ValidationError("create_claim_from_evidence_requires_evidence_refs")
            for source_ref in evidence_refs:
                source = self.store.read_source(workspace_ref, source_ref)
                if source.get("origin", {}).get("kind") != "source_excerpt" and source.get("source_kind") != "command_output":
                    raise ValidationError(f"claim_evidence_requires_excerpt_or_command_output:{source_ref}")
            candidate_pressure = self._claim_analysis_pressure({"id": "CLM-candidate", "statement": statement, "relation": None})
            if candidate_pressure:
                raise ValidationError("claim_from_evidence_not_atomic")
            return self.create_claim(
                workspace_ref,
                statement,
                claim_kind=claim_kind,
                source_refs=evidence_refs,
                project_refs=project_refs,
                task_refs=task_refs,
                support_refs=support_refs,
                contradiction_refs=contradiction_refs,
            )

        return self._guard(op)

    def _capture_excerpt_source(self, workspace_ref: str, *, source_ref: str, quote: str, locator: str | None = None) -> dict[str, Any]:
        parent = self.store.read_source(workspace_ref, source_ref)
        parent_quote = parent.get("quote")
        if not isinstance(parent_quote, str):
            raise ValidationError("source_excerpt_requires_plaintext_parent")
        if not quote:
            raise ValidationError("source_excerpt_requires_non_empty_quote")
        start = parent_quote.find(quote)
        if start < 0:
            raise ValidationError("quote_not_found_in_source")
        end = start + len(quote)
        classification = dict(parent.get("classification", {}))
        classification["independence_key"] = f"{source_ref}:{start}:{end}"
        return self.store.create_source(
            workspace_ref,
            source_kind=parent.get("source_kind", "file_quote"),
            quote=quote,
            classification=classification,
            origin={"kind": "source_excerpt", "ref": source_ref},
            provenance={
                "entity_ref": parent.get("provenance", {}).get("entity_ref") or source_ref,
                "activity_ref": "capture_source_excerpt",
                "responsible_agent": "runtime",
                "content_hash": self.store._captured_text_hash(quote),
                "locator": locator or parent.get("provenance", {}).get("locator") or source_ref,
                "quote_span": {"start": start, "end": end},
                "retrieved_at": parent.get("provenance", {}).get("retrieved_at"),
                "published_at": parent.get("provenance", {}).get("published_at"),
            },
            project_refs=parent.get("project_refs", []),
            critique_status=parent.get("critique_status"),
            reason=f"excerpt captured from {source_ref}",
        )

    def _source_valid_moves(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        if self.store._source_requires_excerpt(source):
            return [
                move("mutate_record", "extract_claim_candidates", "Extract quote-backed candidate CLM-* facts.", writes=True),
                move("mutate_record", "capture_source_fragments", "Split long document into navigable SRC-* fragments.", writes=True),
                move("mutate_record", "capture_source_excerpt", "Capture exact quote/span for one atomic fact.", writes=True),
                move("lookup", "lookup_facts", "Check for existing related claims."),
            ]
        return [
            move("mutate_record", "create_claim", "Create or select a CLM-* from captured source.", writes=True),
            move("lookup", "lookup_facts", "Check for existing related claims."),
        ]

    @staticmethod
    def _source_fragment_spans(text: str, *, max_chars: int) -> list[dict[str, int]]:
        spans = []
        start = 0
        length = len(text)
        while start < length:
            end = min(start + max_chars, length)
            if end < length:
                paragraph_break = text.rfind("\n\n", start, end)
                newline = text.rfind("\n", start, end)
                space = text.rfind(" ", start, end)
                split_at = max(paragraph_break + 2 if paragraph_break >= start else -1, newline + 1 if newline >= start else -1, space + 1 if space >= start else -1)
                if split_at > start:
                    end = split_at
            if end <= start:
                end = min(start + max_chars, length)
            spans.append({"start": start, "end": end})
            start = end
        return spans

    def ingest_text(self, workspace_ref: str, text: str, **kwargs: Any) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            payload = ingest_text_payload(text, **kwargs)
            if has_secrets(text):
                payload["quote"] = maybe_encrypt_text(self.store.root, text)
                payload["classification"]["input_class"] = "secret_or_credential"
                payload["critique_status"] = "encrypted_sensitive"
            return self.create_source(workspace_ref, **payload)

        return self._guard(op)

    def capture_input(
        self,
        workspace_ref: str,
        *,
        text: str,
        input_class: str,
        actor_ref: str = "user",
        thread_ref: str | None = None,
        evidence_role: str = "assertion",
        authority_scope: str = "user_supplied_context",
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            stored_text = maybe_encrypt_text(self.store.root, text)
            effective_input_class = "secret_or_credential" if not isinstance(stored_text, str) else input_class
            inp = self.store.create_input(
                workspace_ref,
                text=stored_text,
                input_class=effective_input_class,
                actor_ref=actor_ref,
                thread_ref=thread_ref,
            )
            source_response = self.create_source(
                workspace_ref,
                source_kind="user_message",
                quote=stored_text,
                classification={
                    "input_class": effective_input_class,
                    "source_class": "user" if actor_ref == "user" else "unknown",
                    "document_kind": "message",
                    "evidence_role": evidence_role,
                    "authority_scope": authority_scope,
                    "independence_key": f"{actor_ref}:{thread_ref or 'input'}",
                },
                origin={"kind": "input", "ref": inp["id"]},
                provenance={
                    "entity_ref": actor_ref,
                    "activity_ref": inp["id"],
                    "responsible_agent": "runtime",
                    "content_hash": inp["content_hash"],
                    "locator": "conversation",
                    "quote_span": {"start": 0, "end": len(text)},
                    "retrieved_at": None,
                    "published_at": None,
                },
                reason="input hook captured user message",
            )
            return ok_response(
                {"input": inp, "source": source_response.data["source"]},
                source_pressure=source_response.source_pressure,
                valid_moves=[
                    move("mutate_record", "create_claim", "Create/select a CLM-* from captured input.", writes=True),
                    move("lookup", "lookup_facts", "Check existing facts before committing input."),
                ],
            )

        return self._guard(op)

    def ingest_file(self, workspace_ref: str, path: str, **kwargs: Any) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            payload = ingest_file_payload(path, **kwargs)
            quote = payload["quote"]
            if has_secrets(quote):
                payload["quote"] = maybe_encrypt_text(self.store.root, quote)
                payload["classification"]["input_class"] = "secret_or_credential"
                payload["critique_status"] = "encrypted_sensitive"
            return self.create_source(workspace_ref, **payload)

        return self._guard(op)

    def capture_bash_command(
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
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            stored_stdout = maybe_encrypt_text(self.store.root, stdout)
            stored_stderr = maybe_encrypt_text(self.store.root, stderr)
            run = self.store.create_bash_run_capture(
                workspace_ref,
                command=command,
                cwd=cwd,
                exit_code=exit_code,
                stdout=stored_stdout,
                stderr=stored_stderr,
                agent_ref=agent_ref,
                preflight_run_ref=preflight_run_ref,
            )
            return ok_response(
                {"run": run},
                valid_moves=[
                    move("mutate_record", "capture_run_output_source", "Capture relevant RUN-* output as SRC-*.", writes=True),
                    move("probe_step", "capture_probe_result", "Bind RUN-* evidence to open ACT.", writes=True),
                ],
            )

        return self._guard(op)

    def capture_run_output_source(
        self,
        workspace_ref: str,
        *,
        run_ref: str,
        stream: str = "stdout",
        quote: str | None = None,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            source, run = self._capture_run_output_source(workspace_ref, run_ref=run_ref, stream=stream, quote=quote)
            return ok_response(
                {"source": source, "run": run},
                source_pressure=[
                    {
                        "level": "medium",
                        "source_refs": [source["id"]],
                        "why": "command output is audited runtime evidence; it needs theory/user support for final trust",
                        "valid_moves": [
                            move("mutate_record", "create_claim", "Create observation claim from RUN output.", writes=True),
                            move("mutate_record", "link_claims", "Connect observation to theory/user-supported claim.", writes=True),
                        ],
                    }
                ],
                valid_moves=[
                    move("mutate_record", "create_claim", "Create observation claim from RUN output.", writes=True),
                    move("probe_step", "capture_probe_result", "Bind source to open ACT.", writes=True),
                ],
            )

        return self._guard(op)

    def extract_run_claim_candidates(
        self,
        workspace_ref: str,
        *,
        run_ref: str,
        candidates: list[dict[str, Any]],
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            if not candidates:
                raise ValidationError("extract_run_claim_candidates_requires_candidates")
            run = self.store.read_run(workspace_ref, run_ref)
            prepared = []
            for index, candidate in enumerate(candidates):
                if not isinstance(candidate, dict):
                    raise ValidationError(f"run_claim_candidate_invalid:{index}")
                stream = str(candidate.get("stream") or "stdout")
                if stream not in {"stdout", "stderr"}:
                    raise ValidationError(f"run_claim_candidate_stream_invalid:{index}")
                output = run.get(stream, "")
                if isinstance(output, dict) and output.get("encrypted") is True:
                    output = decrypt_text(self.store.root, output)
                quote = str(candidate.get("quote") or "").strip()
                statement = str(candidate.get("statement") or "").strip()
                if not quote:
                    raise ValidationError(f"run_claim_candidate_quote_required:{index}")
                if not statement:
                    raise ValidationError(f"run_claim_candidate_statement_required:{index}")
                if quote not in output:
                    raise ValidationError(f"quote_not_found_in_run_output:{index}")
                prepared.append(
                    {
                        "index": index,
                        "stream": stream,
                        "quote": quote,
                        "statement": statement,
                        "claim_kind": str(candidate.get("claim_kind") or "runtime_observation"),
                        "why_this_follows": str(candidate.get("why_this_follows") or ""),
                    }
                )
            extracted = []
            for candidate in prepared:
                source, _run = self._capture_run_output_source(
                    workspace_ref,
                    run_ref=run_ref,
                    stream=candidate["stream"],
                    quote=candidate["quote"],
                )
                extracted.append(
                    {
                        "index": candidate["index"],
                        "run_ref": run_ref,
                        "stream": candidate["stream"],
                        "evidence_source_ref": source["id"],
                        "statement": candidate["statement"],
                        "claim_kind": candidate["claim_kind"],
                        "why_this_follows": candidate["why_this_follows"],
                    }
                )
            return ok_response(
                {"claim_candidates": extracted, "run": run},
                source_pressure=[
                    {
                        "level": "medium",
                        "source_refs": [candidate["evidence_source_ref"] for candidate in extracted],
                        "why": "RUN evidence candidates are captured but not yet committed as CLM-* facts",
                        "valid_moves": [
                            move("mutate_record", "create_claim_from_evidence", "Create one atomic CLM-* per useful RUN observation.", writes=True),
                            move("mutate_record", "link_claims", "Relate runtime observations to system behavior claims.", writes=True),
                        ],
                    }
                ],
                valid_moves=[
                    move("mutate_record", "create_claim_from_evidence", "Create one atomic CLM-* from captured RUN evidence.", writes=True),
                    move("mutate_record", "link_claims", "Connect observation to existing system facts or hypotheses.", writes=True),
                ],
            )

        return self._guard(op)

    def _capture_run_output_source(
        self,
        workspace_ref: str,
        *,
        run_ref: str,
        stream: str = "stdout",
        quote: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        run = self.store.read_run(workspace_ref, run_ref)
        if stream not in {"stdout", "stderr"}:
            raise ValidationError("stream must be stdout or stderr")
        output = run.get(stream, "")
        if isinstance(output, dict) and output.get("encrypted") is True:
            output = decrypt_text(self.store.root, output)
        selected = output if quote is None else quote
        if selected and selected not in output:
            raise ValidationError("quote_not_found_in_run_output")
        stored_quote = maybe_encrypt_text(self.store.root, selected)
        source = self.store.create_source(
            workspace_ref,
            source_kind="command_output",
            quote=stored_quote,
            classification={
                "input_class": "secret_or_credential" if not isinstance(stored_quote, str) else None,
                "source_class": "runtime_observation",
                "document_kind": "command_output",
                "evidence_role": "observation",
                "authority_scope": "local_runtime",
                "independence_key": f"run:{run_ref}:{stream}",
            },
            origin={"kind": "command", "ref": run_ref},
            provenance={
                "entity_ref": run_ref,
                "activity_ref": run_ref,
                "responsible_agent": run.get("agent_ref") or "runtime",
                "content_hash": run.get(f"{stream}_hash") if quote is None else self.store._captured_text_hash(stored_quote),
                "locator": f"{run_ref}:{stream}",
                "quote_span": None,
                "retrieved_at": None,
                "published_at": None,
            },
            critique_status="audited",
            reason="RUN output captured as source",
        )
        return source, run

    def decrypt_sensitive_field(self, workspace_ref: str, record_ref: str, field: str) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            record = self._read_record(workspace_ref, record_ref)
            value = record.get(field)
            if not isinstance(value, dict) or value.get("encrypted") is not True:
                raise ValidationError("field_is_not_encrypted")
            plaintext = decrypt_text(self.store.root, value)
            return ok_response(
                {
                    "record_ref": record_ref,
                    "field": field,
                    "plaintext": plaintext,
                    "plaintext_hash": value.get("plaintext_hash"),
                    "finding_kinds": value.get("finding_kinds", []),
                },
                valid_moves=[move("detail", "record_detail", "Return to encrypted record detail.")],
            )

        return self._guard(op)

    def create_claim(self, workspace_ref: str, statement: str, **kwargs: Any) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            claim = self.store.create_claim(workspace_ref, statement, **kwargs)
            invalidated_context_refs = self._context_invalidated_by_claim(workspace_ref, claim["id"])
            source_pressure = []
            if not claim.get("source_refs"):
                source_pressure.append(
                    {
                        "level": "medium",
                        "claim_refs": [claim["id"]],
                        "why": "claim has no source refs; it can guide exploration but not commitment",
                        "valid_moves": [
                            move("mutate_record", "create_source", "Capture source material.", writes=True),
                            move("mutate_record", "link_claims", "Classify inference through relation.", writes=True),
                        ],
                    }
                )
            claim_pressure = self._claim_analysis_pressure(claim)
            valid_moves = [
                move("append_ledger", "append_ledger", "Snapshot claim into current agent ledger.", writes=True),
                move("lookup", "lookup_facts", "Look for duplicates, supports, or contradictions."),
            ]
            if claim_pressure:
                valid_moves.insert(0, move("mutate_record", "create_claim", "Split broad claim into narrower CLM-* records.", writes=True))
                valid_moves.insert(1, move("mutate_record", "link_claims", "Relate split facts to the original claim.", writes=True))
            if invalidated_context_refs:
                valid_moves.append(move("mutate_record", "compile_context_pack", "Recompile stale CTX-* context packs affected by this claim.", writes=True))
            return ok_response(
                {"claim": claim, "invalidated_context_refs": invalidated_context_refs},
                source_pressure=source_pressure,
                claim_pressure=claim_pressure,
                valid_moves=valid_moves,
            )

        return self._guard(op)

    def link_claims(
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
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            self._validate_relation_bases(workspace_ref, relation_type, subject_ref, object_ref, task_refs=task_refs, bridge_scope=bridge_scope, synced_object=synced_object)
            relation_claim = self.store.create_relation_claim(
                workspace_ref,
                relation_type=relation_type,
                subject_ref=subject_ref,
                object_ref=object_ref,
                statement=statement,
                project_refs=project_refs,
                task_refs=task_refs,
                source_refs=source_refs,
                reason=reason,
                bridge_scope=bridge_scope,
                synced_object=synced_object,
                bridge_limits=bridge_limits,
            )
            valid_moves = [
                move("append_ledger", "append_ledger", "Snapshot relation claim into current ledger.", writes=True),
                move("detail", "record_detail", "Inspect relation posture."),
            ]
            invalidated_context_refs = self._context_invalidated_by_claim(workspace_ref, relation_claim["id"])
            if invalidated_context_refs:
                valid_moves.append(move("mutate_record", "compile_context_pack", "Recompile stale CTX-* context packs affected by this relation.", writes=True))
            if relation_type == "challenges_freshness":
                valid_moves.append(move("probe_step", "open_probe", "Verify the freshness challenge before replacing trusted fact.", writes=True))
            else:
                valid_moves.append(move("lookup", "lookup_facts", "Look for supporting or conflicting relation facts."))
            return ok_response({"claim": relation_claim, "invalidated_context_refs": invalidated_context_refs}, valid_moves=valid_moves)

        return self._guard(op)

    def append_ledger(
        self,
        *,
        workspace_ref: str,
        agent_ref: str,
        private_key: str,
        claim_ref: str,
        why: str,
        difficulty_bits: int = 18,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            ledger = Ledger(self.store, workspace_ref, agent_ref)
            result = ledger.append_claim(private_key=private_key, claim_ref=claim_ref, why=why, difficulty_bits=difficulty_bits)
            validation = ledger.validate()
            return ok_response(
                {"ledger_row": result.row, "validation": validation.__dict__},
                ledger_pressure=self._ledger_pressure(workspace_ref, agent_ref),
                valid_moves=[
                    move("validate", "validate_ledger", "Replay ledger after append."),
                    move("brief", "brief_current_context", "Refresh current briefing."),
                ],
            )

        return self._guard(op)

    def validate_ledger(self, workspace_ref: str, agent_ref: str) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            validation = Ledger(self.store, workspace_ref, agent_ref).validate()
            moves = [move("brief", "brief_current_context", "Return to briefing.")] if validation.ok else [
                move("validate", "validate_ledger", "Inspect failing ledger rows."),
                move("mutate_record", "start_agent_thread", "Start a clean agent thread if needed.", writes=True),
            ]
            return ok_response({"validation": validation.__dict__}, ledger_pressure=self._ledger_pressure(workspace_ref, agent_ref), valid_moves=moves)

        return self._guard(op)

    def open_probe(
        self,
        *,
        workspace_ref: str,
        agent_ref: str,
        private_key: str,
        claim_ref: str,
        intent: str,
        allowed_action_kind: str,
        expected_evidence: str,
        scope: dict[str, Any] | None = None,
        difficulty_bits: int = 18,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            self._require_task_context_ready(workspace_ref, agent_ref)
            self._validate_act_target_claim(workspace_ref, claim_ref)
            ledger = Ledger(self.store, workspace_ref, agent_ref)
            result = ledger.open_probe(
                private_key=private_key,
                claim_ref=claim_ref,
                why=intent,
                intent=intent,
                allowed_action_kind=allowed_action_kind,
                expected_evidence=expected_evidence,
                scope=scope,
                difficulty_bits=difficulty_bits,
            )
            return ok_response(
                {"ledger_row": result.row, "validation": ledger.validate().__dict__},
                ledger_pressure=self._ledger_pressure(workspace_ref, agent_ref),
                valid_moves=[
                    move("probe_step", "capture_probe_result", "Capture observed evidence for the open ACT.", writes=True),
                    move("probe_step", "close_probe", "Close the ACT with a result or no-update reason.", writes=True),
                ],
            )

        return self._guard(op)

    def capture_probe_result(
        self,
        *,
        workspace_ref: str,
        agent_ref: str,
        private_key: str,
        claim_ref: str,
        evidence_ref: str,
        summary: str,
        difficulty_bits: int = 18,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            self._require_task_context_ready(workspace_ref, agent_ref)
            ledger = Ledger(self.store, workspace_ref, agent_ref)
            result = ledger.capture_probe_result(
                private_key=private_key,
                claim_ref=claim_ref,
                why=summary,
                evidence_ref=evidence_ref,
                summary=summary,
                difficulty_bits=difficulty_bits,
            )
            return ok_response(
                {"ledger_row": result.row, "validation": ledger.validate().__dict__},
                ledger_pressure=self._ledger_pressure(workspace_ref, agent_ref),
                valid_moves=[
                    move("mutate_record", "create_claim", "Integrate captured evidence into a claim.", writes=True),
                    move("probe_step", "close_probe", "Close the open ACT.", writes=True),
                ],
            )

        return self._guard(op)

    def close_probe(
        self,
        *,
        workspace_ref: str,
        agent_ref: str,
        private_key: str,
        claim_ref: str,
        outcome: str,
        reason: str,
        result_ref: str | None = None,
        difficulty_bits: int = 18,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            ledger = Ledger(self.store, workspace_ref, agent_ref)
            result = ledger.close_probe(
                private_key=private_key,
                claim_ref=claim_ref,
                why=reason,
                outcome=outcome,
                result_ref=result_ref,
                difficulty_bits=difficulty_bits,
            )
            return ok_response(
                {"ledger_row": result.row, "validation": ledger.validate().__dict__},
                ledger_pressure=self._ledger_pressure(workspace_ref, agent_ref),
                valid_moves=[
                    move("validate", "validate_ledger", "Replay ledger after closing ACT."),
                    move("brief", "brief_current_context", "Refresh current context."),
                ],
            )

        return self._guard(op)

    def protected_action_preflight(
        self,
        *,
        workspace_ref: str,
        agent_ref: str,
        private_key: str,
        action_kind: str,
        action: dict[str, Any],
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            self._require_task_context_ready(workspace_ref, agent_ref)
            agent = self.store.read_agent(workspace_ref, agent_ref)
            assert_private_key_matches(agent["public_key"], agent["key_fingerprint"], private_key)
            ledger = Ledger(self.store, workspace_ref, agent_ref)
            validation = ledger.validate()
            if not validation.ok:
                raise ValidationError("ledger_invalid: " + "; ".join(validation.errors))
            open_act = ledger.current_open_act_row()
            if open_act is None:
                raise ValidationError("open_act_required")
            self._require_open_act_fresh(workspace_ref, open_act)
            allowed_action_kind = open_act.get("act", {}).get("allowed_action_kind")
            if allowed_action_kind not in {action_kind, "*"}:
                raise ValidationError(f"action_kind_not_allowed:{action_kind}")
            run, token = self.store.create_run_preflight(
                workspace_ref,
                agent_ref=agent_ref,
                ledger_head=validation.head or open_act["id"],
                open_act_ref=open_act["id"],
                open_act_hash=open_act["payload_hash"],
                action_kind=action_kind,
                action=action,
            )
            return ok_response(
                {
                    "run": run,
                    "preflight_token": token,
                    "capture_contract": {
                        "open_act_ref": open_act["id"],
                        "expected_evidence": open_act.get("act", {}).get("expected_evidence"),
                        "required_next": "execute_action_then_capture_probe_result",
                    },
                },
                ledger_pressure=self._ledger_pressure(workspace_ref, agent_ref),
                valid_moves=[
                    move("probe_step", "capture_probe_result", "Capture action result as evidence for the open ACT.", writes=True),
                    move("probe_step", "close_probe", "Close ACT if action cannot produce useful evidence.", writes=True),
                ],
            )

        return self._guard(op)

    def final_answer_preflight(
        self,
        *,
        workspace_ref: str,
        agent_ref: str,
        support_refs: list[str],
        task_ref: str | None = None,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            gate = self._final_gate(workspace_ref, agent_ref, support_refs, task_ref)
            return ok_response(
                {"final_answer_preflight": gate},
                ledger_pressure=gate["ledger_pressure"],
                valid_moves=self._gate_moves(gate),
            )

        return self._guard(op)

    def task_done_preflight(
        self,
        *,
        workspace_ref: str,
        agent_ref: str,
        task_ref: str,
        support_refs: list[str],
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            task = self.store.read_task(workspace_ref, task_ref)
            gate = self._final_gate(workspace_ref, agent_ref, support_refs, task_ref)
            blockers = list(task.get("blocker_refs", []))
            if blockers:
                gate["allowed"] = False
                gate["blockers"].append(
                    {
                        "code": "task_has_blockers",
                        "refs": blockers,
                        "why": "task has unresolved blocker refs",
                    }
                )
            if agent_ref not in task.get("agent_refs", []):
                gate["allowed"] = False
                gate["blockers"].append(
                    {
                        "code": "agent_not_attached_to_task",
                        "refs": [agent_ref, task_ref],
                        "why": "current agent is not attached to the task",
                    }
                )
            gate["ledger_pressure"] = self._gate_ledger_pressure(agent_ref, gate)
            return ok_response(
                {"task_done_preflight": gate},
                ledger_pressure=gate["ledger_pressure"],
                valid_moves=self._gate_moves(gate),
            )

        return self._guard(op)

    def lookup_facts(
        self,
        workspace_ref: str,
        *,
        query: str | None = None,
        task_ref: str | None = None,
        limit: int = 20,
    ) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            claims = self.store.claims(workspace_ref)
            if query:
                needle = query.casefold()
                claims = [claim for claim in claims if needle in claim.get("statement", "").casefold()]
            if task_ref:
                task = self.store.read_task(workspace_ref, task_ref)
                task_projects = set(task.get("project_refs", []))
                claims = [
                    claim for claim in claims
                    if not task_projects or task_projects.intersection(claim.get("scope", {}).get("project_refs", []))
                ]
            ranked = sorted(claims, key=lambda claim: self._claim_rank(workspace_ref, claim, task_ref), reverse=True)[:limit]
            results = [self._lookup_result(workspace_ref, claim, task_ref) for claim in ranked]
            return ok_response(
                {"results": results},
                valid_moves=[
                    move("detail", "record_detail", "Inspect a returned record."),
                    move("mutate_record", "create_source", "Capture missing source material.", writes=True),
                    move("mutate_record", "link_claims", "Create bridge/support/contradiction relation when needed.", writes=True),
                ],
            )

        return self._guard(op)

    def refresh_indexes(self, workspace_ref: str) -> RuntimeResponse:
        return self._guard(
            lambda: ok_response(
                {"index_refresh": self.indexes.refresh_workspace_indexes(workspace_ref)},
                index_pressure=[],
                valid_moves=[
                    move("lookup", "lookup_facts", "Use refreshed indexes for navigation."),
                    move("brief", "brief_current_context", "Refresh briefing with current fact posture."),
                ],
            )
        )

    def index_status(self, workspace_ref: str) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            status = self.indexes.index_status(workspace_ref)
            index_pressure = []
            if not status["indexes"]:
                index_pressure.append(
                    {
                        "level": "medium",
                        "why": "no runtime indexes have been generated for this workspace",
                        "valid_moves": [move("index", "refresh_indexes", "Build runtime navigation indexes.", writes=True)],
                    }
                )
            return ok_response(
                {"index_status": status},
                index_pressure=index_pressure,
                valid_moves=[move("index", "refresh_indexes", "Rebuild runtime navigation indexes.", writes=True)],
            )

        return self._guard(op)

    def record_detail(self, workspace_ref: str, record_ref: str) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            record = self._read_record(workspace_ref, record_ref)
            detail = {
                "record": record,
                "proof_role": self.posture.proof_role(record),
                "links": self.posture.record_links(record),
            }
            source_pressure: list[dict[str, Any]] = []
            claim_pressure: list[dict[str, Any]] = []
            valid_moves = [move("brief", "brief_current_context", "Return to briefing.")]
            if record_ref.startswith("CLM-"):
                detail["trust_posture"] = self.posture.trust_posture(workspace_ref, record)
                detail["scope"] = self.posture.scope_metadata(workspace_ref, record, None)
                claim_pressure = self._claim_analysis_pressure(record)
                if not record.get("source_refs"):
                    source_pressure.append(
                        {
                            "level": "medium",
                            "claim_refs": [record_ref],
                            "why": "claim has no captured source support",
                            "valid_moves": [move("mutate_record", "create_source", "Capture support source.", writes=True)],
                        }
                    )
                valid_moves = [
                    move("append_ledger", "append_ledger", "Snapshot this claim into the current ledger.", writes=True),
                    move("lookup", "lookup_facts", "Find related facts."),
                    move("mutate_record", "link_claims", "Create explicit relation if needed.", writes=True),
                ]
                if claim_pressure:
                    valid_moves.insert(0, move("mutate_record", "create_claim", "Split broad claim into narrower CLM-* records.", writes=True))
            elif record_ref.startswith("SRC-"):
                detail["source_trust_posture"] = self.posture.source_trust_posture(record)
                source_events = self.store.validate_source_events(workspace_ref)
                latest_event = self.store.latest_source_event(workspace_ref, record_ref)
                detail["source_event_validation"] = {
                    "ok": source_events.ok,
                    "event_count": source_events.event_count,
                    "head": source_events.head,
                    "head_hash": source_events.head_hash,
                    "latest_event_ref": latest_event.get("event_id") if latest_event else None,
                    "latest_event_hash": latest_event.get("event_hash") if latest_event else None,
                    "accepted_event_ref": source_events.accepted_sources.get(record_ref),
                    "errors": source_events.errors,
                }
                if not source_events.ok:
                    source_pressure.append(
                        {
                            "level": "blocked",
                            "source_refs": [record_ref],
                            "why": "source event chain is invalid; source acceptance cannot be trusted",
                            "valid_moves": [
                                move("validate", "record_detail", "Inspect source event replay errors."),
                                move("mutate_record", "create_source", "Recapture source material through MCP.", writes=True),
                            ],
                        }
                    )
                if record.get("critique_status") != "accepted":
                    source_pressure.append(
                        {
                            "level": "medium",
                            "source_refs": [record_ref],
                            "why": "source is not accepted for commitment",
                            "valid_moves": [
                                move("mutate_record", "capture_source_excerpt", "Capture precise document evidence before claim creation.", writes=True),
                                move("lookup", "lookup_facts", "Find corroborating or conflicting claims."),
                            ],
                        }
                    )
                valid_moves = self._source_valid_moves(record)
            elif record_ref.startswith("TASK-"):
                valid_moves = [
                    move("mutate_record", "decompose_task", "Split this task into subtasks.", writes=True),
                    move("mutate_record", "attach_agent_to_task", "Attach current agent to this task.", writes=True),
                    move("lookup", "lookup_facts", "Find facts for this task."),
                ]
            return ok_response({"detail": detail}, source_pressure=source_pressure, claim_pressure=claim_pressure, valid_moves=valid_moves)

        return self._guard(op)

    def brief_current_context(self, workspace_ref: str, agent_ref: str | None = None) -> RuntimeResponse:
        def op() -> RuntimeResponse:
            workspace = self.store.read_workspace(workspace_ref)
            memberships = self.store.project_memberships(workspace_ref)
            agent = self.store.read_agent(workspace_ref, agent_ref) if agent_ref else None
            task_path = agent["working_context"]["active_task_path"] if agent else []
            active_task = self.store.read_task(workspace_ref, task_path[-1]) if task_path else None
            task_context = self._task_context_state(workspace_ref, active_task["id"]) if active_task else None
            deferred = [task["id"] for task in self.store.tasks(workspace_ref) if task.get("status") == "deferred"]
            facts = [
                {
                    "ref": claim["id"],
                    "source_refs": claim.get("source_refs", []),
                    "trust_posture": self.posture.trust_posture(workspace_ref, claim),
                    "scope_origin": self.posture.scope_metadata(workspace_ref, claim, active_task).get("scope_origin"),
                }
                for claim in self.store.claims(workspace_ref)[:20]
            ]
            selected_claim_refs = []
            if agent:
                for refs in agent["working_context"].get("selected_claim_refs_by_task", {}).values():
                    selected_claim_refs.extend(refs)
            return ok_response(
                {
                    "workspace": {"ref": workspace_ref, "name": workspace.get("name")},
                    "settings": self.store.read_settings(workspace_ref),
                    "projects": memberships,
                    "task": {
                        "active_task_path": task_path,
                        "state": active_task.get("status") if active_task else "none",
                        "execution_state": task_context["execution_state"] if task_context else "no_active_task",
                        "goal": active_task.get("goal") if active_task else None,
                        "done_criteria": active_task.get("done_criteria", []) if active_task else [],
                        "blocker_refs": active_task.get("blocker_refs", []) if active_task else [],
                        "deferred_work": deferred,
                    },
                    "compiled_context": task_context,
                    "agent": {
                        "ref": agent_ref,
                        "selected_ledger_head": self._ledger_pressure(workspace_ref, agent_ref)["current_head"] if agent_ref else None,
                        "open_act": self._ledger_pressure(workspace_ref, agent_ref)["open_act"] if agent_ref else None,
                        "selected_claim_refs": selected_claim_refs,
                    },
                    "facts": facts,
                },
                ledger_pressure=self._ledger_pressure(workspace_ref, agent_ref),
                valid_moves=self._brief_moves(active_task is None),
            )

        return self._guard(op)

    def _guard(self, fn: Callable[[], RuntimeResponse]) -> RuntimeResponse:
        try:
            return fn()
        except OwnershipError as exc:
            return error_response("ownership_mismatch", str(exc), repair_options=[move("mutate_record", "start_agent_thread", "Start or select the correct agent thread.", writes=True)])
        except ValidationError as exc:
            message = str(exc)
            if message.startswith("duplicate_claim:"):
                existing_ref = message.split(":", 1)[1]
                return error_response(
                    "duplicate_claim",
                    "duplicate claim exists",
                    details={"existing_ref": existing_ref},
                    dedup_pressure=[
                        {
                            "level": "blocked",
                            "claim_refs": [existing_ref],
                            "why": "exact dedup key already exists",
                            "valid_moves": [
                                move("mutate_record", "select_existing_claim", "Reuse the existing CLM-* instead of creating a duplicate."),
                                move("mutate_record", "link_claims", "Represent a real semantic distinction as a relation.", writes=True),
                            ],
                        }
                    ],
                    repair_options=[move("mutate_record", "select_existing_claim", "Reuse existing claim.")],
                )
            if message == "task_briefing_requires_task_ref":
                return error_response(
                    "task_briefing_requires_task_ref",
                    "compile_context_pack kind=task_briefing requires task_ref",
                    repair_options=[
                        move("brief", "brief_current_context", "Find the active TASK-* before compiling task briefing."),
                        move("mutate_record", "compile_context_pack", "Retry with task_ref set to the target TASK-*.", writes=True),
                    ],
                )
            return error_response("validation_failed", message, repair_options=[move("brief", "brief_current_context", "Refresh protocol context.")])
        except TEPError as exc:
            return error_response("protocol_error", str(exc), repair_options=[move("validate", "validate_ledger", "Validate current protocol state.")])

    def _validate_act_target_claim(self, workspace_ref: str, claim_ref: str) -> None:
        claim = self.store.read_claim(workspace_ref, claim_ref)
        if self._claim_analysis_pressure(claim):
            raise ValidationError("act_target_too_broad")
        source_refs = claim.get("source_refs", [])
        if not source_refs:
            return
        sources = [self.store.read_source(workspace_ref, source_ref) for source_ref in source_refs]
        source_classes = {source.get("classification", {}).get("source_class") for source in sources}
        source_kinds = {source.get("source_kind") for source in sources}
        observation_only = source_classes.issubset({"runtime_observation", "test_or_check"}) or source_kinds.issubset({"command_output", "command_summary"})
        if observation_only and not claim.get("relation") and not claim.get("support_refs"):
            raise ValidationError("act_target_observation_only")

    def _require_open_act_fresh(self, workspace_ref: str, open_act: dict[str, Any]) -> None:
        timeout = int(self.store.read_settings(workspace_ref)["enforcement"].get("act_timeout_seconds", 3600))
        created_at = open_act.get("created_at")
        if not isinstance(created_at, str):
            raise ValidationError("open_act_expired:missing_created_at")
        try:
            opened = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError("open_act_expired:invalid_created_at") from exc
        age_seconds = int((datetime.now(UTC) - opened).total_seconds())
        if age_seconds >= timeout:
            raise ValidationError(f"open_act_expired:{age_seconds}s>{timeout}s")

    def _claim_analysis_pressure(self, claim: dict[str, Any]) -> list[dict[str, Any]]:
        statement = str(claim.get("statement") or "")
        if not statement.strip() or claim.get("relation"):
            return []
        normalized = " ".join(statement.split())
        words = normalized.split()
        sentence_count = sum(1 for part in re.split(r"[.!?]+", normalized) if part.strip())
        separators = normalized.count(";") + normalized.count(":") + normalized.count(",")
        connectors = sum(
            1
            for pattern in [
                r"\band\b",
                r"\bor\b",
                r"\bbecause\b",
                r"\btherefore\b",
                r"\bso that\b",
                r"\bwhich\b",
                r"\bthat\b",
            ]
            if re.search(pattern, normalized, flags=re.IGNORECASE)
        )
        heavy = len(words) >= 24 or sentence_count > 1 or separators >= 3 or connectors >= 2
        if not heavy:
            return []
        return [
            {
                "level": "medium",
                "claim_refs": [claim["id"]],
                "why": "claim appears broad or compound; it may hide several atomic facts or mix observation with inference",
                "questions": [
                    "What exactly did the agent learn?",
                    "Can this CLM-* be split into separate point facts?",
                    "Which parts are observed evidence, inference, applicability, or uncertainty?",
                ],
                "valid_moves": [
                    move("mutate_record", "create_claim", "Create one CLM-* per separable point fact.", writes=True),
                    move("mutate_record", "link_claims", "Link split facts with support/dependency/applicability/equivalence relations.", writes=True),
                    move("lookup", "lookup_facts", "Check whether atomic parts already exist."),
                ],
            }
        ]

    def _read_record(self, workspace_ref: str, record_ref: str) -> dict[str, Any]:
        if record_ref.startswith("CLM-"):
            return self.store.read_claim(workspace_ref, record_ref)
        if record_ref.startswith("SRC-"):
            return self.store.read_source(workspace_ref, record_ref)
        if record_ref.startswith("INP-"):
            return self.store.read_input(workspace_ref, record_ref)
        if record_ref.startswith("TASK-"):
            return self.store.read_task(workspace_ref, record_ref)
        if record_ref.startswith("RUN-"):
            return self.store.read_run(workspace_ref, record_ref)
        if record_ref.startswith("CTX-"):
            record = self.store.read_context_pack(workspace_ref, record_ref)
            record["text"] = self.store.context_pack_text(workspace_ref, record_ref)
            return record
        if record_ref.startswith("AGENT-"):
            return self.store.read_agent(workspace_ref, record_ref)
        if record_ref.startswith("PRJ-"):
            return self.store.read_project(record_ref)
        raise ValidationError(f"unsupported record ref: {record_ref}")

    def _lookup_result(self, workspace_ref: str, claim: dict[str, Any], task_ref: str | None) -> dict[str, Any]:
        task = self.store.read_task(workspace_ref, task_ref) if task_ref else None
        scope = self.posture.scope_metadata(workspace_ref, claim, task)
        trust_posture = self.posture.trust_posture(workspace_ref, claim)
        bridge_context = self._scope_bridge_context(workspace_ref, claim["id"], task)
        return {
            "record_ref": claim["id"],
            "statement": claim["statement"],
            "scope_origin": scope["scope_origin"],
            "workspace_ref": workspace_ref,
            "project_refs": claim.get("scope", {}).get("project_refs", []),
            "proof_usable_now": scope["proof_usable_now"] and "answer" in trust_posture["usable_for"],
            "requires_bridge": scope["requires_bridge"],
            "bridge_context": bridge_context,
            "trust_posture": trust_posture,
            "drilldown": claim.get("source_refs", []),
            "valid_moves": [
                move("detail", "record_detail", "Inspect claim details."),
                move("append_ledger", "append_ledger", "Snapshot claim if current agent can commit it.", writes=True),
            ],
        }

    def _claim_rank(self, workspace_ref: str, claim: dict[str, Any], task_ref: str | None) -> int:
        posture = self.posture.trust_posture(workspace_ref, claim)
        scope = self.posture.scope_metadata(workspace_ref, claim, self.store.read_task(workspace_ref, task_ref) if task_ref else None)
        score = posture["trust_score_bps"]
        if scope["scope_origin"] == "primary_project":
            score += 5000
        elif scope["scope_origin"] == "dependency":
            score += 3000
        elif scope["requires_bridge"]:
            score -= 2000
        if claim.get("source_refs"):
            score += 1000
        return score

    def _final_gate(
        self,
        workspace_ref: str,
        agent_ref: str,
        support_refs: list[str],
        task_ref: str | None,
    ) -> dict[str, Any]:
        validation = Ledger(self.store, workspace_ref, agent_ref).validate()
        task = self.store.read_task(workspace_ref, task_ref) if task_ref else None
        ledgered_claim_refs = self._ledger_claim_refs(workspace_ref, agent_ref) if validation.ok else set()
        blockers: list[dict[str, Any]] = []
        support = []

        if not support_refs:
            blockers.append({"code": "missing_support_refs", "refs": [], "why": "final answer needs explicit CLM-* support refs"})
        if not validation.ok:
            blockers.append({"code": "ledger_invalid", "refs": [agent_ref], "why": "; ".join(validation.errors)})
        if validation.open_act is not None:
            blockers.append({"code": "open_act", "refs": [validation.open_act], "why": "final answer requires no open ACT"})
        if task is not None:
            task_context = self._task_context_state(workspace_ref, task["id"])
            if task_context["missing_required"]:
                blockers.append(
                    {
                        "code": "missing_task_context",
                        "refs": [task["id"]],
                        "why": ",".join(task_context["missing_required"]),
                    }
                )

        for claim_ref in support_refs:
            claim = self.store.read_claim(workspace_ref, claim_ref)
            posture = self.posture.trust_posture(workspace_ref, claim)
            scope = self.posture.scope_metadata(workspace_ref, claim, task)
            claim_blockers = []
            if claim_ref not in ledgered_claim_refs:
                claim_blockers.append("claim_not_ledgered")
            if "answer" not in posture["usable_for"]:
                claim_blockers.append("claim_not_usable_for_answer")
            bridge_ref = None
            bridge_context = None
            if scope["requires_bridge"]:
                bridge_context = self._scope_bridge_context(workspace_ref, claim_ref, task, ledgered_claim_refs)
                bridge_ref = bridge_context.get("bridge_ref") if bridge_context else None
                if bridge_context is None:
                    claim_blockers.append("missing_scope_bridge")
            if claim_blockers:
                blockers.append(
                    {
                        "code": "support_blocked",
                        "refs": [claim_ref],
                        "why": ",".join(claim_blockers),
                    }
                )
            support.append(
                {
                    "claim_ref": claim_ref,
                    "trust_posture": posture,
                    "scope": scope,
                    "bridge_ref": bridge_ref,
                    "bridge_context": bridge_context,
                    "ledgered": claim_ref in ledgered_claim_refs,
                    "blockers": claim_blockers,
                }
            )

        gate = {
            "allowed": not blockers,
            "workspace_ref": workspace_ref,
            "agent_ref": agent_ref,
            "task_ref": task_ref,
            "support_refs": support_refs,
            "support": support,
            "blockers": blockers,
            "ledger_validation": validation.__dict__,
        }
        if task is not None:
            gate["task_context"] = self._task_context_state(workspace_ref, task["id"])
        gate["ledger_pressure"] = self._gate_ledger_pressure(agent_ref, gate)
        return gate

    def _ledger_claim_refs(self, workspace_ref: str, agent_ref: str) -> set[str]:
        rows = self.store.read_jsonl(self.store.ledger_path(workspace_ref, agent_ref))
        return {row["ref"] for row in rows if isinstance(row.get("ref"), str) and row.get("kind") in {"claim", "relation", "act", "capture", "close_act"}}

    def _scope_bridge_context(
        self,
        workspace_ref: str,
        claim_ref: str,
        task: dict[str, Any] | None,
        ledgered_claim_refs: set[str] | None = None,
    ) -> dict[str, Any] | None:
        for claim in self.store.claims(workspace_ref):
            if ledgered_claim_refs is not None and claim["id"] not in ledgered_claim_refs:
                continue
            relation = claim.get("relation") or {}
            if relation.get("type") != "applies_to_scope":
                continue
            if claim_ref in {relation.get("subject"), relation.get("object")}:
                bridge_scope = relation.get("bridge_scope") or "general"
                task_refs = set(relation.get("task_refs") or claim.get("scope", {}).get("task_refs", []))
                task_ref = task.get("id") if task else None
                task_specific = bridge_scope == "task" and task_ref in task_refs
                object_sync = bridge_scope == "object_sync" and relation.get("synced_object") is not None
                if bridge_scope == "task" and not task_specific:
                    continue
                return {
                    "bridge_ref": claim["id"],
                    "bridge_scope": bridge_scope,
                    "task_specific": task_specific,
                    "task_refs": sorted(task_refs),
                    "object_sync": object_sync,
                    "synced_object": relation.get("synced_object"),
                    "bridge_limits": relation.get("bridge_limits") or {},
                    "ledgered": ledgered_claim_refs is not None,
                }
        return None

    def _gate_ledger_pressure(self, agent_ref: str, gate: dict[str, Any]) -> dict[str, Any]:
        return {
            "level": "none" if gate["allowed"] else "blocked",
            "current_agent": agent_ref,
            "ledger_valid": gate["ledger_validation"]["ok"],
            "current_head": gate["ledger_validation"]["head"],
            "open_act": gate["ledger_validation"]["open_act"],
            "level_reason": "gate allowed" if gate["allowed"] else "; ".join(blocker["code"] for blocker in gate["blockers"]),
            "valid_moves": self._gate_moves(gate),
        }

    @staticmethod
    def _gate_moves(gate: dict[str, Any]) -> list[dict[str, Any]]:
        if gate["allowed"]:
            return [move("final", "final_answer", "Return final answer using the approved support path.")]
        codes = {blocker["code"] for blocker in gate["blockers"]}
        moves = []
        if "open_act" in codes:
            moves.append(move("probe_step", "close_probe", "Close the open ACT before finalizing.", writes=True))
        if "ledger_invalid" in codes:
            moves.append(move("validate", "validate_ledger", "Inspect ledger replay errors."))
        if "missing_support_refs" in codes or "support_blocked" in codes:
            moves.append(move("lookup", "lookup_facts", "Find answer-usable support facts."))
            moves.append(move("append_ledger", "append_ledger", "Snapshot required support facts into current ledger.", writes=True))
            moves.append(move("mutate_record", "link_claims", "Create required bridge/support relation.", writes=True))
        if "task_has_blockers" in codes:
            moves.append(move("brief", "brief_current_context", "Inspect task blockers."))
        if "agent_not_attached_to_task" in codes:
            moves.append(move("mutate_record", "attach_agent_to_task", "Attach current agent to task.", writes=True))
        if "missing_task_context" in codes:
            moves.append(move("lookup", "lookup_facts", "Collect CLM-* support for missing context packs."))
            moves.append(move("mutate_record", "compile_context_pack", "Compile required CTX-* task context.", writes=True))
        return moves

    def _task_context_state(self, workspace_ref: str, task_ref: str) -> dict[str, Any]:
        settings = self.store.read_settings(workspace_ref)
        requirements = context_requirements(settings)
        required = required_context_kinds(settings)
        task = self.store.read_task(workspace_ref, task_ref)
        task_project_refs = task.get("project_refs", [])
        packs = self._context_packs_for_task(workspace_ref, task_ref, task_project_refs)
        active_by_kind = {pack["kind"]: pack for pack in packs}
        missing = [kind for kind in required if not self._context_kind_satisfied(kind, active_by_kind)]
        return {
            "task_ref": task_ref,
            "project_refs": task_project_refs,
            "requirements": requirements,
            "required_kinds": required,
            "active": [
                {
                    "ref": pack["id"],
                    "kind": pack["kind"],
                    "scope_type": pack.get("scope_type", "task"),
                    "scope_ref": pack.get("scope_ref"),
                    "status": pack["status"],
                    "path": str(self.store.workspace_dir(workspace_ref) / pack["artifact_path"]),
                    "support_refs": pack.get("support_refs", []),
                    "support_hash": pack.get("support_hash"),
                }
                for pack in sorted(packs, key=lambda item: (item["kind"], item["id"]))
            ],
            "missing_required": missing,
            "execution_state": "ready" if not missing else "blocked_missing_context",
            "valid_moves": [
                move("lookup", "lookup_facts", "Collect facts for missing context packs."),
                move("mutate_record", "compile_context_pack", "Compile required task context pack.", writes=True),
            ]
            if missing
            else [move("brief", "brief_current_context", "Use active task context.")],
        }

    def _context_packs_for_task(self, workspace_ref: str, task_ref: str, project_refs: list[str]) -> list[dict[str, Any]]:
        packs = self.store.context_packs(workspace_ref, task_ref=task_ref, status="active")
        packs.extend(self.store.context_packs(workspace_ref, scope_type="global", status="active"))
        for project_ref in project_refs:
            packs.extend(self.store.context_packs(workspace_ref, project_ref=project_ref, status="active"))
        return self._dedupe_context_packs(packs)

    def _context_invalidated_by_claim(self, workspace_ref: str, claim_ref: str) -> list[str]:
        return [
            pack["id"]
            for pack in self.store.context_packs(workspace_ref, status="stale")
            if pack.get("stale_trigger_ref") == claim_ref
        ]

    @staticmethod
    def _context_kind_satisfied(kind: str, active_by_kind: dict[str, dict[str, Any]]) -> bool:
        pack = active_by_kind.get(kind)
        if pack is None:
            return False
        return kind != "task_briefing" or pack.get("scope_type") == "task"

    @staticmethod
    def _dedupe_context_packs(packs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result = []
        for pack in packs:
            pack_id = pack.get("id")
            if isinstance(pack_id, str) and pack_id not in seen:
                seen.add(pack_id)
                result.append(pack)
        return result

    def _require_task_context_ready(self, workspace_ref: str, agent_ref: str) -> None:
        agent = self.store.read_agent(workspace_ref, agent_ref)
        task_path = agent.get("working_context", {}).get("active_task_path", [])
        if not task_path:
            return
        state = self._task_context_state(workspace_ref, task_path[-1])
        if state["missing_required"]:
            raise ValidationError("missing_task_context:" + ",".join(state["missing_required"]))

    def _validate_relation_bases(
        self,
        workspace_ref: str,
        relation_type: str,
        subject_ref: str,
        object_ref: str,
        *,
        task_refs: list[str] | None = None,
        bridge_scope: str | None = None,
        synced_object: dict[str, Any] | None = None,
    ) -> None:
        allowed = {
            "supports",
            "contradicts",
            "applies_to_scope",
            "deduced_from",
            "induced_from",
            "abduced_from",
            "assumed_from",
            "possible_relation_between",
            "challenges_freshness",
        }
        if relation_type not in allowed:
            raise ValidationError(f"unsupported_relation_type:{relation_type}")

        subject = self.store.read_claim(workspace_ref, subject_ref)
        obj = self.store.read_claim(workspace_ref, object_ref)
        invisible = [
            claim["id"]
            for claim in [subject, obj]
            if not self.store.claim_visible_in_workspace(workspace_ref, claim)
        ]
        if invisible:
            raise ValidationError("relation_scope_not_visible:" + ",".join(invisible))
        relation_projects = set(subject.get("scope", {}).get("project_refs", [])) | set(obj.get("scope", {}).get("project_refs", []))
        if relation_projects and not relation_projects.issubset(self.store.visible_project_refs(workspace_ref)):
            raise ValidationError("relation_project_not_in_workspace:" + ",".join(sorted(relation_projects)))
        if relation_type == "applies_to_scope":
            selected_scope = bridge_scope or "general"
            if selected_scope not in {"general", "task", "object_sync"}:
                raise ValidationError(f"unsupported_bridge_scope:{selected_scope}")
            if selected_scope == "task" and not task_refs:
                raise ValidationError("task_bridge_requires_task_refs")
            if selected_scope == "object_sync" and not synced_object:
                raise ValidationError("object_sync_bridge_requires_synced_object")
        hypothesis_builders = {
            "deduced_from",
            "induced_from",
            "abduced_from",
            "assumed_from",
            "possible_relation_between",
            "applies_to_scope",
        }
        if relation_type in hypothesis_builders:
            weak = [
                claim["id"]
                for claim in [subject, obj]
                if self.posture.trust_posture(workspace_ref, claim)["derived_label"]
                not in {"trusted_fact", "user_confirmed_hypothesis"}
            ]
            if weak:
                raise ValidationError("hypothesis_on_hypothesis_blocked:" + ",".join(weak))
        if relation_type == "challenges_freshness":
            target_posture = self.posture.trust_posture(workspace_ref, obj)
            if target_posture["derived_label"] not in {"trusted_fact", "user_confirmed_hypothesis"}:
                raise ValidationError("freshness_challenge_requires_trusted_target")

    def _ledger_pressure(self, workspace_ref: str, agent_ref: str | None) -> dict[str, Any]:
        if agent_ref is None:
            return {
                "level": "medium",
                "current_agent": None,
                "ledger_valid": False,
                "current_head": None,
                "open_act": None,
                "level_reason": "no current agent selected",
                "valid_moves": [move("mutate_record", "start_agent_thread", "Start or select an AGENT-*.", writes=True)],
            }
        validation = Ledger(self.store, workspace_ref, agent_ref).validate()
        return {
            "level": "none" if validation.ok else "blocked",
            "current_agent": agent_ref,
            "ledger_valid": validation.ok,
            "current_head": validation.head,
            "open_act": validation.open_act,
            "level_reason": "ledger valid" if validation.ok else "; ".join(validation.errors),
            "valid_moves": [move("append_ledger", "append_ledger", "Append a claim snapshot.", writes=True)] if validation.ok else [move("validate", "validate_ledger", "Inspect ledger errors.")],
        }

    def _brief_moves(self, no_active_task: bool) -> list[dict[str, Any]]:
        moves = [
            move("lookup", "lookup_facts", "Search existing facts."),
            move("mutate_record", "create_source", "Capture new source material.", writes=True),
        ]
        if no_active_task:
            moves.insert(0, move("mutate_record", "create_task", "Create a durable task scope.", writes=True))
        else:
            moves.append(move("mutate_record", "decompose_task", "Split task into subtasks.", writes=True))
            moves.append(move("mutate_record", "defer_task", "Defer task with resume condition.", writes=True))
        return moves
