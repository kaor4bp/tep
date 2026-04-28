from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tep import (
    Ledger,
    MCPAdapter,
    Runtime,
    TEPHTTPApp,
    TEPHome,
    TEPStdioApp,
    canonical_hash,
    generate_agent_identity,
    init_project_pointer,
    read_project_pointer,
)
from tep.crypto import public_key_from_private
from tep.errors import CanonicalJSONError, OwnershipError, StorageError, ValidationError
from tep.jsoncanon import bytes_hash, canonical_dumps
from tep.mcp_stdio_server import TEPMCPStdioServer
from tep.mcp_stdio_server import run_loop_binary as run_mcp_loop_binary
from tep.mcp_stdio_server import run_loop as run_mcp_loop


class CoreTests(unittest.TestCase):
    def _compile_task_briefing(self, runtime: Runtime, workspace_ref: str, task_ref: str, support_ref: str) -> None:
        compiled = runtime.compile_context_pack(
            workspace_ref,
            task_ref=task_ref,
            kind="task_briefing",
            text="# Task Briefing\nUse the ledgered support for this task.\n",
            support_refs=[support_ref],
        )
        self.assertTrue(compiled.ok, compiled.error)

    def _operation_kinds_from(self, value) -> set[str]:
        kinds: set[str] = set()
        if isinstance(value, dict):
            operation_kind = value.get("operation_kind")
            if isinstance(operation_kind, str):
                kinds.add(operation_kind)
            for child in value.values():
                kinds.update(self._operation_kinds_from(child))
        elif isinstance(value, list):
            for child in value:
                kinds.update(self._operation_kinds_from(child))
        elif hasattr(value, "as_dict"):
            kinds.update(self._operation_kinds_from(value.as_dict()))
        return kinds

    def test_canonical_json_rejects_floats(self) -> None:
        with self.assertRaises(CanonicalJSONError):
            canonical_dumps({"score": 0.5})

    def test_agent_private_key_is_not_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("test")
            identity = generate_agent_identity("worker")
            agent = store.create_agent(workspace["id"], identity, thread_ref="thread-1")

            agent_path = Path(tmp) / "workspaces" / workspace["id"] / "agents" / identity.agent_ref / "agent.json"
            raw = agent_path.read_text(encoding="utf-8")
            self.assertNotIn(identity.private_key, raw)
            self.assertEqual(agent["public_key"], public_key_from_private(identity.private_key))

    def test_settings_merge_and_action_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]

            defaults = runtime.read_settings(workspace["id"])
            self.assertTrue(defaults.ok, defaults.error)
            self.assertEqual(defaults.data["settings"]["enforcement"]["mode"], "balanced")
            self.assertEqual(defaults.data["settings"]["enforcement"]["act_timeout_seconds"], 300)

            updated = runtime.update_settings(
                {"enforcement": {"mode": "strict", "bash_policy": "act_for_all"}},
                workspace_ref=workspace["id"],
            )
            self.assertTrue(updated.ok, updated.error)
            self.assertEqual(updated.data["settings"]["enforcement"]["mode"], "strict")
            self.assertEqual(updated.data["settings"]["enforcement"]["bash_policy"], "act_for_all")

            pressure = runtime.action_pressure(
                workspace["id"],
                action_kind="bash",
                action={"command": "rg -n settings src"},
            )
            self.assertTrue(pressure.ok, pressure.error)
            self.assertTrue(pressure.data["action_pressure"]["blocked"])
            self.assertEqual(pressure.data["action_pressure"]["classification"], "read_only_context")
            pressure_moves = {move["operation_kind"] for move in pressure.data["action_pressure"]["valid_moves"]}
            self.assertIn("open_probe", pressure_moves)
            self.assertNotIn("protected_action_preflight", pressure_moves)

            bad = runtime.update_settings({"enforcement": {"mode": "chaos"}}, workspace_ref=workspace["id"])
            self.assertFalse(bad.ok)
            self.assertIn("unsupported_enforcement_mode", bad.error["message"])

    def test_create_workspace_reuses_existing_workspace_for_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            project = runtime.register_project("primary").data["project"]
            first = runtime.create_workspace("primary-workspace", project_ref=project["id"])
            second = runtime.create_workspace("another-agent-workspace", project_ref=project["id"])

            self.assertTrue(first.ok, first.error)
            self.assertTrue(second.ok, second.error)
            self.assertEqual(first.data["workspace"]["id"], second.data["workspace"]["id"])
            self.assertTrue(second.data["reused"])

    def test_context_packs_are_task_scoped_text_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            task = runtime.create_task(workspace["id"], "Implement feature").data["task"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Use compact code and keep tests focused.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "Keep tests focused.", source_refs=[source["id"]]).data["claim"]

            compiled = runtime.compile_context_pack(
                workspace["id"],
                task_ref=task["id"],
                kind="coding_guidelines",
                text="# Coding Guidelines\nKeep tests focused.\n",
                support_refs=[claim["id"]],
            )

            self.assertTrue(compiled.ok, compiled.error)
            pack = compiled.data["context_pack"]
            self.assertTrue(pack["id"].startswith("CTX-"))
            self.assertEqual(pack["kind"], "coding_guidelines")
            self.assertEqual(Path(tmp, "workspaces", workspace["id"], pack["artifact_path"]).read_text(encoding="utf-8"), "# Coding Guidelines\nKeep tests focused.\n")

            listed = runtime.list_context_packs(workspace["id"], task_ref=task["id"])
            self.assertTrue(listed.ok, listed.error)
            self.assertEqual([item["id"] for item in listed.data["context_packs"]], [pack["id"]])

            revoked = runtime.revoke_context_pack(workspace["id"], pack["id"], reason="superseded")
            self.assertTrue(revoked.ok, revoked.error)
            self.assertEqual(revoked.data["context_pack"]["status"], "revoked")

    def test_project_and_global_context_packs_satisfy_non_task_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            project = runtime.register_project("primary").data["project"]
            runtime.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="test")
            runtime.update_settings({"enforcement": {"mode": "strict"}}, workspace_ref=workspace["id"])
            task = runtime.create_task(workspace["id"], "Implement with cached context", project_refs=[project["id"]]).data["task"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Use shared guidelines.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "Use shared guidelines.", source_refs=[source["id"]], project_refs=[project["id"]]).data["claim"]

            runtime.compile_context_pack(workspace["id"], task_ref=task["id"], kind="task_briefing", text="# Task\nDo the task.\n", support_refs=[claim["id"]])
            runtime.compile_context_pack(workspace["id"], project_ref=project["id"], kind="coding_guidelines", text="# Coding\nUse project style.\n", support_refs=[claim["id"]])
            runtime.compile_context_pack(workspace["id"], project_ref=project["id"], kind="project_conventions", text="# Conventions\nUse project conventions.\n", support_refs=[claim["id"]])
            runtime.compile_context_pack(workspace["id"], kind="domain_theory", text="# Theory\nUse global theory.\n", support_refs=[claim["id"]])

            identity = generate_agent_identity("context-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            runtime.attach_agent_to_task(workspace["id"], agent["id"], task["id"])
            brief = runtime.brief_current_context(workspace["id"], agent["id"])

            self.assertTrue(brief.ok, brief.error)
            self.assertEqual(brief.data["compiled_context"]["execution_state"], "ready")
            self.assertEqual(
                {pack["scope_type"] for pack in brief.data["compiled_context"]["active"]},
                {"task", "project", "global"},
            )

    def test_on_demand_guidelines_do_not_block_missing_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            task = runtime.create_task(workspace["id"], "Task with default balanced context").data["task"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Task briefing only.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "Task briefing exists.", source_refs=[source["id"]]).data["claim"]
            runtime.compile_context_pack(workspace["id"], task_ref=task["id"], kind="task_briefing", text="# Task\nBrief.\n", support_refs=[claim["id"]])
            identity = generate_agent_identity("balanced-context-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            runtime.attach_agent_to_task(workspace["id"], agent["id"], task["id"])

            brief = runtime.brief_current_context(workspace["id"], agent["id"])

            self.assertEqual(brief.data["compiled_context"]["missing_required"], [])
            self.assertEqual(brief.data["compiled_context"]["requirements"]["coding_guidelines"], "on_demand")

    def test_new_claim_invalidates_overlapping_context_packs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            project = runtime.register_project("primary").data["project"]
            runtime.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="test")
            task = runtime.create_task(workspace["id"], "Task with cached context", project_refs=[project["id"]]).data["task"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Context support.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            support = runtime.create_claim(workspace["id"], "Context support exists.", source_refs=[source["id"]], project_refs=[project["id"]]).data["claim"]
            task_pack = runtime.compile_context_pack(workspace["id"], task_ref=task["id"], kind="task_briefing", text="# Task\nCached task view.\n", support_refs=[support["id"]]).data["context_pack"]
            project_pack = runtime.compile_context_pack(workspace["id"], project_ref=project["id"], kind="coding_guidelines", text="# Coding\nCached project view.\n", support_refs=[support["id"]]).data["context_pack"]
            global_pack = runtime.compile_context_pack(workspace["id"], kind="domain_theory", text="# Theory\nCached global view.\n", support_refs=[support["id"]]).data["context_pack"]

            project_claim = runtime.create_claim(workspace["id"], "Project cache inputs changed.", source_refs=[source["id"]], project_refs=[project["id"]])

            self.assertTrue(project_claim.ok, project_claim.error)
            self.assertEqual(set(project_claim.data["invalidated_context_refs"]), {task_pack["id"], project_pack["id"]})
            self.assertEqual(runtime.store.read_context_pack(workspace["id"], task_pack["id"])["status"], "stale")
            self.assertEqual(runtime.store.read_context_pack(workspace["id"], project_pack["id"])["status"], "stale")
            self.assertEqual(runtime.store.read_context_pack(workspace["id"], global_pack["id"])["status"], "active")
            self.assertIn("compile_context_pack", {move["operation_kind"] for move in project_claim.valid_moves})

            global_claim = runtime.create_claim(workspace["id"], "Workspace-wide cache inputs changed.", source_refs=[source["id"]])

            self.assertTrue(global_claim.ok, global_claim.error)
            self.assertEqual(global_claim.data["invalidated_context_refs"], [global_pack["id"]])
            self.assertEqual(runtime.store.read_context_pack(workspace["id"], global_pack["id"])["status"], "stale")

    def test_append_and_validate_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("test")
            identity = generate_agent_identity("worker")
            store.create_agent(workspace["id"], identity, thread_ref="thread-1")
            source = store.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Use the project settings as the retry policy source.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            )
            claim = store.create_claim(
                workspace["id"],
                "The retry policy is configured in project settings.",
                source_refs=[source["id"]],
            )

            ledger = Ledger(store, workspace["id"], identity.agent_ref)
            result = ledger.append_claim(
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Initial source-backed claim skeleton.",
                difficulty_bits=8,
            )

            validation = ledger.validate()
            self.assertTrue(validation.ok, validation.errors)
            self.assertEqual(validation.head, result.row["id"])
            self.assertEqual(result.row["claim_snapshot_hash"], canonical_hash(claim))
            self.assertEqual(result.row["source_snapshots"][0]["ref"], source["id"])

    def test_wrong_private_key_cannot_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("test")
            owner = generate_agent_identity("owner")
            attacker = generate_agent_identity("attacker")
            store.create_agent(workspace["id"], owner, thread_ref="thread-1")
            claim = store.create_claim(workspace["id"], "A protected claim.")

            ledger = Ledger(store, workspace["id"], owner.agent_ref)
            with self.assertRaises(OwnershipError):
                ledger.append_claim(
                    private_key=attacker.private_key,
                    claim_ref=claim["id"],
                    why="Should fail.",
                    difficulty_bits=4,
                )

    def test_tampered_row_fails_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("test")
            identity = generate_agent_identity("worker")
            store.create_agent(workspace["id"], identity, thread_ref="thread-1")
            claim = store.create_claim(workspace["id"], "A tamper-sensitive claim.")
            ledger = Ledger(store, workspace["id"], identity.agent_ref)
            ledger.append_claim(
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Original reason.",
                difficulty_bits=8,
            )

            ledger_path = store.ledger_path(workspace["id"], identity.agent_ref)
            row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])
            row["why"] = "Tampered reason."
            ledger_path.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

            validation = ledger.validate()
            self.assertFalse(validation.ok)
            self.assertTrue(any("payload_hash mismatch" in error or "seal validation failed" in error for error in validation.errors))

    def test_tampered_source_fails_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("test")
            identity = generate_agent_identity("worker")
            store.create_agent(workspace["id"], identity, thread_ref="thread-1")
            source = store.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Confirmed working assumption.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:test",
                },
            )
            claim = store.create_claim(workspace["id"], "The user confirmed the working assumption.", source_refs=[source["id"]])
            ledger = Ledger(store, workspace["id"], identity.agent_ref)
            ledger.append_claim(
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Snapshot claim with source.",
                difficulty_bits=8,
            )

            source_path = store.source_path(workspace["id"], source["id"])
            source_record = json.loads(source_path.read_text(encoding="utf-8"))
            source_record["quote"] = "Tampered quote."
            source_path.write_text(json.dumps(source_record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

            validation = ledger.validate()
            self.assertFalse(validation.ok)
            self.assertTrue(any("source_hash mismatch" in error for error in validation.errors))

    def test_tampered_source_event_fails_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("test")
            identity = generate_agent_identity("worker")
            store.create_agent(workspace["id"], identity, thread_ref="thread-1")
            source = store.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Confirmed event.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:test",
                },
            )
            claim = store.create_claim(workspace["id"], "The event is confirmed.", source_refs=[source["id"]])
            ledger = Ledger(store, workspace["id"], identity.agent_ref)
            ledger.append_claim(
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Snapshot claim with source event.",
                difficulty_bits=8,
            )

            event_path = store.source_events_path(workspace["id"])
            event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
            event["reason"] = "Tampered event reason."
            event_path.write_text(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

            validation = ledger.validate()
            self.assertFalse(validation.ok)
            self.assertTrue(any("source event self-hash mismatch" in error for error in validation.errors))

    def test_source_event_replay_detects_reorder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("test")
            store.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="First source.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            )
            store.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Second source.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            )
            self.assertTrue(store.validate_source_events(workspace["id"]).ok)

            event_path = store.source_events_path(workspace["id"])
            lines = event_path.read_text(encoding="utf-8").splitlines()
            event_path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")

            validation = store.validate_source_events(workspace["id"])
            self.assertFalse(validation.ok)
            self.assertTrue(any("event_prev" in error or "event_log_hash mismatch" in error for error in validation.errors))

    def test_record_detail_reports_invalid_source_event_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Accepted source.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            event_path = store.source_events_path(workspace["id"])
            event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
            event["reason"] = "Tampered reason."
            event_path.write_text(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

            detail = runtime.record_detail(workspace["id"], source["id"])
            self.assertTrue(detail.ok)
            self.assertFalse(detail.data["detail"]["source_event_validation"]["ok"])
            self.assertTrue(any(pressure["level"] == "blocked" for pressure in detail.source_pressure))

    def test_duplicate_claim_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("test")
            store.create_claim(workspace["id"], "Duplicate claim.")
            with self.assertRaises(ValidationError):
                store.create_claim(workspace["id"], "  duplicate   CLAIM. ")

    def test_noop_resnapshot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("test")
            identity = generate_agent_identity("worker")
            store.create_agent(workspace["id"], identity, thread_ref="thread-1")
            claim = store.create_claim(workspace["id"], "Same snapshot.")
            ledger = Ledger(store, workspace["id"], identity.agent_ref)
            ledger.append_claim(
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="First.",
                difficulty_bits=4,
            )
            with self.assertRaises(ValidationError):
                ledger.append_claim(
                    private_key=identity.private_key,
                    claim_ref=claim["id"],
                    why="No-op.",
                    difficulty_bits=4,
                )

    def test_runtime_briefing_tracks_project_task_and_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            project = runtime.register_project("service-api", roots=["/repo/service-api"]).data["project"]
            attach = runtime.attach_project_to_workspace(
                workspace["id"],
                project["id"],
                role="primary",
                reason="main implementation target",
            )
            self.assertTrue(attach.ok)
            task = runtime.create_task(workspace["id"], "Implement sealed ledger core", project_refs=[project["id"]]).data["task"]
            child_response = runtime.decompose_task(workspace["id"], task["id"], ["Add runtime facade", "Add tests"])
            self.assertTrue(child_response.ok)
            identity = generate_agent_identity("runtime-agent")
            start = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity)
            self.assertTrue(start.ok)
            agent = start.data["agent"]
            attach_agent = runtime.attach_agent_to_task(workspace["id"], agent["id"], task["id"])
            self.assertTrue(attach_agent.ok)

            brief = runtime.brief_current_context(workspace["id"], agent["id"])
            self.assertTrue(brief.ok)
            self.assertEqual(brief.data["workspace"]["ref"], workspace["id"])
            self.assertEqual(brief.data["projects"][0]["project_ref"], project["id"])
            self.assertEqual(brief.data["task"]["active_task_path"], [task["id"]])
            self.assertIn("decompose_task", {move["operation_kind"] for move in brief.valid_moves})

    def test_runtime_duplicate_claim_returns_repair_choices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            first = runtime.create_claim(workspace["id"], "Duplicate through runtime.")
            self.assertTrue(first.ok)
            duplicate = runtime.create_claim(workspace["id"], " duplicate THROUGH runtime. ")
            self.assertFalse(duplicate.ok)
            self.assertEqual(duplicate.error["code"], "duplicate_claim")
            self.assertEqual(duplicate.error["details"]["existing_ref"], first.data["claim"]["id"])
            self.assertTrue(duplicate.dedup_pressure)
            self.assertIn("select_existing_claim", {move["operation_kind"] for move in duplicate.repair_options})

    def test_broad_claim_returns_decomposition_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]

            response = runtime.create_claim(
                workspace["id"],
                (
                    "The pytest run shows that the API returns 500 instead of 200, "
                    "the login flow has a bad token error, and the agent should inspect "
                    "the auth middleware before changing the response handler."
                ),
            )

            self.assertTrue(response.ok, response.error)
            self.assertTrue(response.claim_pressure)
            pressure = response.claim_pressure[0]
            self.assertEqual(pressure["claim_refs"], [response.data["claim"]["id"]])
            self.assertIn("What exactly did the agent learn?", pressure["questions"])
            self.assertIn("create_claim", {move["operation_kind"] for move in pressure["valid_moves"]})
            self.assertIn("link_claims", {move["operation_kind"] for move in response.valid_moves})

            detail = runtime.record_detail(workspace["id"], response.data["claim"]["id"])
            self.assertTrue(detail.claim_pressure)
            self.assertIn("create_claim", {move["operation_kind"] for move in detail.valid_moves})

    def test_runtime_append_ledger_returns_pressure_and_moves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            identity = generate_agent_identity("runtime-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Please treat this as task intent.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "User provided task intent.", source_refs=[source["id"]]).data["claim"]

            append = runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Record task intent claim.",
                difficulty_bits=8,
            )

            self.assertTrue(append.ok, append.error)
            self.assertTrue(append.ledger_pressure["ledger_valid"])
            self.assertEqual(append.ledger_pressure["current_head"], append.data["ledger_row"]["id"])
            self.assertIn("validate_ledger", {move["operation_kind"] for move in append.valid_moves})

    def test_probe_lifecycle_requires_ledgered_claim_and_closes_act(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            identity = generate_agent_identity("probe-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Probe this claim.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "Probe target claim.", source_refs=[source["id"]]).data["claim"]

            blocked = runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Check target claim.",
                allowed_action_kind="inspect",
                expected_evidence="captured source",
                difficulty_bits=8,
            )
            self.assertFalse(blocked.ok)
            self.assertEqual(blocked.error["code"], "validation_failed")
            self.assertIn("needs_claim_snapshot", blocked.error["message"])

            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Snapshot before probe.",
                difficulty_bits=8,
            )
            opened = runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Check target claim.",
                allowed_action_kind="inspect",
                expected_evidence="captured source",
                difficulty_bits=8,
            )
            self.assertTrue(opened.ok, opened.error)
            self.assertEqual(opened.data["ledger_row"]["kind"], "act")
            self.assertEqual(opened.ledger_pressure["open_act"], opened.data["ledger_row"]["id"])

            second_open = runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Open second probe.",
                allowed_action_kind="inspect",
                expected_evidence="captured source",
                difficulty_bits=8,
            )
            self.assertFalse(second_open.ok)
            self.assertIn("open_act_exists", second_open.error["message"])

            captured = runtime.capture_probe_result(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                evidence_ref=source["id"],
                summary="Captured source supports probe.",
                difficulty_bits=8,
            )
            self.assertTrue(captured.ok, captured.error)
            self.assertEqual(captured.data["ledger_row"]["kind"], "capture")
            self.assertEqual(captured.ledger_pressure["open_act"], opened.data["ledger_row"]["id"])

            closed = runtime.close_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                outcome="no_relevant_evidence",
                reason="Probe closed without claim update.",
                difficulty_bits=8,
            )
            self.assertTrue(closed.ok, closed.error)
            self.assertEqual(closed.data["ledger_row"]["kind"], "close_act")
            self.assertIsNone(closed.ledger_pressure["open_act"])
            self.assertTrue(closed.ledger_pressure["ledger_valid"])

    def test_open_probe_rejects_broad_or_observation_only_claim_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            identity = generate_agent_identity("probe-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]

            broad = runtime.create_claim(
                workspace["id"],
                (
                    "The previous pytest run completed with many failures, several setup errors, "
                    "multiple passing backend checks, and a dominant UI start-session cluster, "
                    "so it summarizes historical run state rather than a narrow next probe intent."
                ),
            ).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=broad["id"],
                why="Snapshot broad historical run summary.",
                difficulty_bits=8,
            )

            broad_act = runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=broad["id"],
                intent="Run tests from broad summary.",
                allowed_action_kind="bash",
                expected_evidence="command output",
                difficulty_bits=8,
            )
            self.assertFalse(broad_act.ok)
            self.assertIn("act_target_too_broad", broad_act.error["message"])

            run = runtime.capture_bash_command(workspace["id"], command="pytest -q", cwd=tmp, exit_code=1, stdout="1 failed\n").data["run"]
            source = runtime.capture_run_output_source(workspace["id"], run_ref=run["id"], stream="stdout").data["source"]
            observation = runtime.create_claim(workspace["id"], "Pytest observed one failing test.", source_refs=[source["id"]]).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=observation["id"],
                why="Snapshot runtime observation.",
                difficulty_bits=8,
            )

            observation_act = runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=observation["id"],
                intent="Use observation as next ACT target.",
                allowed_action_kind="bash",
                expected_evidence="command output",
                difficulty_bits=8,
            )
            self.assertFalse(observation_act.ok)
            self.assertIn("act_target_observation_only", observation_act.error["message"])

    def test_open_probe_allows_hostname_probe_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            identity = generate_agent_identity("probe-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            claim = runtime.create_claim(
                workspace["id"],
                "bridge.qa.trgdev.local resolves in the Codex execution environment.",
            ).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Snapshot narrow DNS probe hypothesis.",
                difficulty_bits=8,
            )

            opened = runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Check DNS resolution for bridge.qa.trgdev.local.",
                allowed_action_kind="bash",
                expected_evidence="DNS lookup command output",
                difficulty_bits=8,
            )

            self.assertTrue(opened.ok, opened.error)
            self.assertEqual(opened.data["ledger_row"]["kind"], "act")

    def test_protected_action_preflight_rejects_expired_act(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            runtime.update_settings({"enforcement": {"act_timeout_seconds": 0}}, workspace_ref=workspace["id"])
            identity = generate_agent_identity("timeout-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            claim = runtime.create_claim(workspace["id"], "Run tests to inspect current behavior.").data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Snapshot action intent.",
                difficulty_bits=8,
            )
            opened = runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Run pytest to inspect current behavior.",
                allowed_action_kind="bash",
                expected_evidence="command output",
                difficulty_bits=8,
            )
            self.assertTrue(opened.ok, opened.error)

            preflight = runtime.protected_action_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                action_kind="bash",
                action={"command": "pytest -q"},
            )
            self.assertFalse(preflight.ok)
            self.assertIn("open_act_expired", preflight.error["message"])

    def test_strict_task_context_gate_blocks_act_until_all_required_packs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            runtime.update_settings({"enforcement": {"mode": "strict"}}, workspace_ref=workspace["id"])
            task = runtime.create_task(workspace["id"], "Implement with context").data["task"]
            identity = generate_agent_identity("context-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            runtime.attach_agent_to_task(workspace["id"], agent["id"], task["id"])
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="This task has required guidance.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "Task guidance exists.", source_refs=[source["id"]]).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Snapshot before context-gated ACT.",
                difficulty_bits=8,
            )

            blocked = runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Try protected work before context.",
                allowed_action_kind="bash",
                expected_evidence="command output",
                difficulty_bits=8,
            )

            self.assertFalse(blocked.ok)
            self.assertIn("missing_task_context", blocked.error["message"])

            for kind in ("task_briefing", "coding_guidelines", "domain_theory", "project_conventions"):
                compiled = runtime.compile_context_pack(
                    workspace["id"],
                    task_ref=task["id"],
                    kind=kind,
                    text=f"# {kind}\nUse this context.\n",
                    support_refs=[claim["id"]],
                    agent_ref=agent["id"],
                )
                self.assertTrue(compiled.ok, compiled.error)

            brief = runtime.brief_current_context(workspace["id"], agent["id"])
            self.assertTrue(brief.ok, brief.error)
            self.assertEqual(brief.data["compiled_context"]["execution_state"], "ready")
            self.assertEqual(len(brief.data["compiled_context"]["active"]), 4)

            opened = runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Protected work after context.",
                allowed_action_kind="bash",
                expected_evidence="command output",
                difficulty_bits=8,
            )
            self.assertTrue(opened.ok, opened.error)

    def test_protected_action_preflight_requires_open_matching_act(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            identity = generate_agent_identity("preflight-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Inspect the filesystem for this claim.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "Filesystem inspection is needed.", source_refs=[source["id"]]).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Snapshot before protected action.",
                difficulty_bits=8,
            )

            no_act = runtime.protected_action_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                action_kind="inspect",
                action={"tool": "read_file", "path": "pyproject.toml"},
            )
            self.assertFalse(no_act.ok)
            self.assertIn("open_act_required", no_act.error["message"])

            runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Inspect project metadata.",
                allowed_action_kind="inspect",
                expected_evidence="file quote",
                difficulty_bits=8,
            )
            wrong_kind = runtime.protected_action_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                action_kind="mutate",
                action={"tool": "write_file", "path": "pyproject.toml"},
            )
            self.assertFalse(wrong_kind.ok)
            self.assertIn("action_kind_not_allowed", wrong_kind.error["message"])

            preflight = runtime.protected_action_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                action_kind="inspect",
                action={"tool": "read_file", "path": "pyproject.toml"},
            )
            self.assertTrue(preflight.ok, preflight.error)
            run = preflight.data["run"]
            self.assertEqual(run["record_type"], "run")
            self.assertEqual(run["status"], "preflight_issued")
            self.assertEqual(run["action_kind"], "inspect")
            self.assertEqual(run["open_act_ref"], preflight.ledger_pressure["open_act"])
            self.assertIn("preflight_token", preflight.data)
            self.assertNotIn(preflight.data["preflight_token"], store.run_path(workspace["id"], run["id"]).read_text(encoding="utf-8"))
            self.assertIn("capture_probe_result", {move["operation_kind"] for move in preflight.valid_moves})

    def test_final_answer_preflight_blocks_open_act_and_unledgered_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            identity = generate_agent_identity("final-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="This fact is confirmed.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "The fact is confirmed.", source_refs=[source["id"]]).data["claim"]

            unledgered = runtime.final_answer_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                support_refs=[claim["id"]],
            )
            self.assertTrue(unledgered.ok)
            self.assertFalse(unledgered.data["final_answer_preflight"]["allowed"])
            self.assertIn("support_blocked", {blocker["code"] for blocker in unledgered.data["final_answer_preflight"]["blockers"]})

            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Ledger confirmed fact.",
                difficulty_bits=8,
            )
            runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Open final-blocking ACT.",
                allowed_action_kind="inspect",
                expected_evidence="none",
                difficulty_bits=8,
            )

            blocked = runtime.final_answer_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                support_refs=[claim["id"]],
            )
            self.assertTrue(blocked.ok)
            self.assertFalse(blocked.data["final_answer_preflight"]["allowed"])
            self.assertIn("open_act", {blocker["code"] for blocker in blocked.data["final_answer_preflight"]["blockers"]})

    def test_final_answer_preflight_passes_with_ledgered_answer_usable_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            identity = generate_agent_identity("final-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="This assumption is acceptable.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "The user confirmed the assumption.", source_refs=[source["id"]]).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Ledger final support.",
                difficulty_bits=8,
            )

            preflight = runtime.final_answer_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                support_refs=[claim["id"]],
            )

            self.assertTrue(preflight.ok)
            self.assertTrue(preflight.data["final_answer_preflight"]["allowed"])
            self.assertEqual(preflight.ledger_pressure["level"], "none")
            self.assertIn("final_answer", {move["operation_kind"] for move in preflight.valid_moves})

    def test_final_answer_preflight_blocks_ledgered_unsupported_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            identity = generate_agent_identity("hypothesis-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            claim = runtime.create_claim(workspace["id"], "Unsupported but ledgered hypothesis.").data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Ledger exploratory hypothesis.",
                difficulty_bits=8,
            )

            preflight = runtime.final_answer_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                support_refs=[claim["id"]],
            )

            self.assertTrue(preflight.ok)
            self.assertFalse(preflight.data["final_answer_preflight"]["allowed"])
            support = preflight.data["final_answer_preflight"]["support"][0]
            self.assertIn("claim_not_usable_for_answer", support["blockers"])

    def test_task_done_preflight_blocks_task_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            identity = generate_agent_identity("task-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            task = store.create_task(workspace["id"], "Finish task", blocker_refs=["CLM-blocker"])
            runtime.attach_agent_to_task(workspace["id"], agent["id"], task["id"])
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Task result is confirmed.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "Task result is confirmed.", source_refs=[source["id"]], task_refs=[task["id"]]).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Ledger task support.",
                difficulty_bits=8,
            )

            preflight = runtime.task_done_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                task_ref=task["id"],
                support_refs=[claim["id"]],
            )

            self.assertTrue(preflight.ok)
            self.assertFalse(preflight.data["task_done_preflight"]["allowed"])
            self.assertIn("task_has_blockers", {blocker["code"] for blocker in preflight.data["task_done_preflight"]["blockers"]})

    def test_example_project_fact_requires_ledgered_scope_bridge_for_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            primary = runtime.register_project("primary").data["project"]
            example = runtime.register_project("example").data["project"]
            runtime.attach_project_to_workspace(workspace["id"], primary["id"], role="primary", reason="target")
            runtime.attach_project_to_workspace(workspace["id"], example["id"], role="example", reason="reference")
            task = runtime.create_task(workspace["id"], "Use scoped fact", project_refs=[primary["id"]]).data["task"]
            identity = generate_agent_identity("scope-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            runtime.attach_agent_to_task(workspace["id"], agent["id"], task["id"])
            example_source = runtime.create_source(
                workspace["id"],
                source_kind="file_quote",
                quote="Example project uses retries.",
                critique_status="accepted",
                classification={
                    "source_class": "first_party_project",
                    "document_kind": "source_code",
                    "evidence_role": "implementation",
                    "authority_scope": "implementation_detail",
                    "independence_key": "repo:example",
                },
                project_refs=[example["id"]],
            ).data["source"]
            primary_source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="This example is applicable to the primary project.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:test",
                },
            ).data["source"]
            example_claim = runtime.create_claim(
                workspace["id"],
                "Example project uses retries.",
                source_refs=[example_source["id"]],
                project_refs=[example["id"]],
            ).data["claim"]
            primary_claim = runtime.create_claim(
                workspace["id"],
                "The example retry pattern applies here.",
                source_refs=[primary_source["id"]],
                project_refs=[primary["id"]],
                task_refs=[task["id"]],
            ).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=example_claim["id"],
                why="Ledger example fact.",
                difficulty_bits=8,
            )

            blocked = runtime.final_answer_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                task_ref=task["id"],
                support_refs=[example_claim["id"]],
            )
            self.assertFalse(blocked.data["final_answer_preflight"]["allowed"])
            self.assertIn("support_blocked", {blocker["code"] for blocker in blocked.data["final_answer_preflight"]["blockers"]})

            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=primary_claim["id"],
                why="Ledger primary applicability basis.",
                difficulty_bits=8,
            )
            bridge = runtime.link_claims(
                workspace["id"],
                relation_type="applies_to_scope",
                subject_ref=example_claim["id"],
                object_ref=primary_claim["id"],
                reason="User confirmed applicability.",
            ).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=bridge["id"],
                why="Ledger scope bridge.",
                difficulty_bits=8,
            )
            self._compile_task_briefing(runtime, workspace["id"], task["id"], primary_claim["id"])

            allowed = runtime.final_answer_preflight(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                task_ref=task["id"],
                support_refs=[example_claim["id"]],
            )
            self.assertTrue(allowed.data["final_answer_preflight"]["allowed"], allowed.data["final_answer_preflight"]["blockers"])
            self.assertEqual(allowed.data["final_answer_preflight"]["support"][0]["bridge_ref"], bridge["id"])

    def test_lookup_returns_trust_and_scope_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            primary = runtime.register_project("primary").data["project"]
            example = runtime.register_project("example").data["project"]
            runtime.attach_project_to_workspace(workspace["id"], primary["id"], role="primary", reason="target")
            runtime.attach_project_to_workspace(workspace["id"], example["id"], role="example", reason="example only")
            task = runtime.create_task(workspace["id"], "Use local retry policy", project_refs=[primary["id"]]).data["task"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="file_quote",
                quote="Retry policy is defined in settings.py.",
                critique_status="accepted",
                classification={
                    "source_class": "first_party_project",
                    "document_kind": "source_code",
                    "evidence_role": "implementation",
                    "authority_scope": "implementation_detail",
                    "independence_key": "repo:primary",
                },
                project_refs=[primary["id"]],
            ).data["source"]
            local_claim = runtime.create_claim(
                workspace["id"],
                "Retry policy is defined in settings.py.",
                source_refs=[source["id"]],
                project_refs=[primary["id"]],
                task_refs=[task["id"]],
            ).data["claim"]
            runtime.create_claim(
                workspace["id"],
                "Example project uses exponential backoff.",
                project_refs=[example["id"]],
            )

            lookup = runtime.lookup_facts(workspace["id"], query="retry", task_ref=task["id"])
            self.assertTrue(lookup.ok)
            result = next(item for item in lookup.data["results"] if item["record_ref"] == local_claim["id"])
            self.assertEqual(result["scope_origin"], "primary_project")
            self.assertFalse(result["requires_bridge"])
            self.assertEqual(result["trust_posture"]["derived_label"], "trusted_fact")
            self.assertTrue(result["proof_usable_now"])

            example_lookup = runtime.lookup_facts(workspace["id"], query="example")
            example_result = example_lookup.data["results"][0]
            self.assertEqual(example_result["scope_origin"], "example")
            self.assertTrue(example_result["requires_bridge"])
            self.assertFalse(example_result["proof_usable_now"])

    def test_project_scoped_claim_is_visible_across_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            project = runtime.register_project("shared-service").data["project"]
            first_workspace = runtime.create_workspace("first").data["workspace"]
            second_workspace = runtime.create_workspace("second").data["workspace"]
            runtime.attach_project_to_workspace(first_workspace["id"], project["id"], role="primary", reason="capture")
            runtime.attach_project_to_workspace(second_workspace["id"], project["id"], role="primary", reason="reuse")

            source = runtime.create_source(
                first_workspace["id"],
                source_kind="file_quote",
                quote="Shared service uses settings.py for retry policy.",
                critique_status="accepted",
                classification={
                    "source_class": "first_party_project",
                    "document_kind": "source_code",
                    "evidence_role": "implementation",
                    "authority_scope": "implementation_detail",
                    "independence_key": "repo:shared",
                },
                project_refs=[project["id"]],
            ).data["source"]
            claim = runtime.create_claim(
                first_workspace["id"],
                "Shared service uses settings.py for retry policy.",
                source_refs=[source["id"]],
                project_refs=[project["id"]],
            ).data["claim"]

            lookup = runtime.lookup_facts(second_workspace["id"], query="retry")
            self.assertTrue(lookup.ok, lookup.error)
            self.assertIn(claim["id"], {item["record_ref"] for item in lookup.data["results"]})
            self.assertTrue(str(store.claim_path(first_workspace["id"], claim["id"])).startswith(str(Path(tmp) / "records" / "claims")))

    def test_legacy_workspace_claim_and_source_paths_still_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            workspace = store.create_workspace("legacy")
            identity = generate_agent_identity("legacy-agent")
            store.create_agent(workspace["id"], identity, thread_ref="thread-1")
            source = store.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Legacy source remains valid.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:legacy",
                },
            )
            claim = store.create_claim(workspace["id"], "Legacy source remains valid.", source_refs=[source["id"]])
            ledger = Ledger(store, workspace["id"], identity.agent_ref)
            ledger.append_claim(private_key=identity.private_key, claim_ref=claim["id"], why="Snapshot before path migration.", difficulty_bits=8)

            legacy_source = store._legacy_global_source_path(source["id"])
            legacy_claim = store._legacy_global_claim_path(claim["id"])
            legacy_events = store.records_dir() / "src" / "source_events.jsonl"
            legacy_source.parent.mkdir(parents=True, exist_ok=True)
            legacy_claim.parent.mkdir(parents=True, exist_ok=True)
            legacy_events.parent.mkdir(parents=True, exist_ok=True)
            store.source_path(workspace["id"], source["id"]).rename(legacy_source)
            store.claim_path(workspace["id"], claim["id"]).rename(legacy_claim)
            store.records_dir().joinpath("sources", "source_events.jsonl").rename(legacy_events)

            validation = ledger.validate()
            self.assertTrue(validation.ok, validation.errors)

            workspace_source = store._workspace_source_path(workspace["id"], source["id"])
            workspace_claim = store._workspace_claim_path(workspace["id"], claim["id"])
            workspace_events = store.workspace_dir(workspace["id"]) / "records" / "sources" / "source_events.jsonl"
            workspace_source.parent.mkdir(parents=True, exist_ok=True)
            workspace_claim.parent.mkdir(parents=True, exist_ok=True)
            workspace_events.parent.mkdir(parents=True, exist_ok=True)
            legacy_source.rename(workspace_source)
            legacy_claim.rename(workspace_claim)
            legacy_events.rename(workspace_events)

            validation = ledger.validate()
            self.assertTrue(validation.ok, validation.errors)

    def test_relation_between_projects_requires_workspace_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            primary = runtime.register_project("primary").data["project"]
            foreign = runtime.register_project("foreign").data["project"]
            runtime.attach_project_to_workspace(workspace["id"], primary["id"], role="primary", reason="target")
            primary_claim = runtime.create_claim(workspace["id"], "Primary behavior.", project_refs=[primary["id"]]).data["claim"]
            foreign_claim = runtime.create_claim(workspace["id"], "Foreign behavior.", project_refs=[foreign["id"]]).data["claim"]

            link = runtime.link_claims(
                workspace["id"],
                relation_type="possible_relation_between",
                subject_ref=primary_claim["id"],
                object_ref=foreign_claim["id"],
                reason="Maybe related.",
            )

            self.assertFalse(link.ok)
            self.assertEqual(link.error["code"], "validation_failed")
            self.assertIn("relation_project_not_in_workspace", link.error["message"])

    def test_task_specific_bridge_only_applies_to_that_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            primary = runtime.register_project("primary").data["project"]
            example = runtime.register_project("example").data["project"]
            runtime.attach_project_to_workspace(workspace["id"], primary["id"], role="primary", reason="target")
            runtime.attach_project_to_workspace(workspace["id"], example["id"], role="example", reason="reference")
            task = runtime.create_task(workspace["id"], "Use retry example", project_refs=[primary["id"]]).data["task"]
            other_task = runtime.create_task(workspace["id"], "Use timeout example", project_refs=[primary["id"]]).data["task"]
            identity = generate_agent_identity("bridge-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="The example applies to this retry task.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:test",
                },
            ).data["source"]
            example_claim = runtime.create_claim(
                workspace["id"],
                "Example uses retry middleware.",
                source_refs=[source["id"]],
                project_refs=[example["id"]],
            ).data["claim"]
            primary_claim = runtime.create_claim(
                workspace["id"],
                "Retry middleware is applicable to the primary task.",
                source_refs=[source["id"]],
                project_refs=[primary["id"]],
                task_refs=[task["id"]],
            ).data["claim"]
            for claim in [example_claim, primary_claim]:
                runtime.append_ledger(
                    workspace_ref=workspace["id"],
                    agent_ref=agent["id"],
                    private_key=identity.private_key,
                    claim_ref=claim["id"],
                    why="Ledger support claim.",
                    difficulty_bits=8,
                )
            bridge = runtime.link_claims(
                workspace["id"],
                relation_type="applies_to_scope",
                subject_ref=example_claim["id"],
                object_ref=primary_claim["id"],
                task_refs=[task["id"]],
                bridge_scope="task",
                reason="User scoped the bridge to this task.",
            ).data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=bridge["id"],
                why="Ledger task bridge.",
                difficulty_bits=8,
            )
            self._compile_task_briefing(runtime, workspace["id"], task["id"], primary_claim["id"])

            allowed = runtime.final_answer_preflight(workspace_ref=workspace["id"], agent_ref=agent["id"], task_ref=task["id"], support_refs=[example_claim["id"]])
            blocked = runtime.final_answer_preflight(workspace_ref=workspace["id"], agent_ref=agent["id"], task_ref=other_task["id"], support_refs=[example_claim["id"]])

            self.assertTrue(allowed.data["final_answer_preflight"]["allowed"], allowed.data["final_answer_preflight"]["blockers"])
            self.assertTrue(allowed.data["final_answer_preflight"]["support"][0]["bridge_context"]["task_specific"])
            self.assertFalse(blocked.data["final_answer_preflight"]["allowed"])

    def test_object_sync_bridge_is_exposed_in_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            primary = runtime.register_project("primary").data["project"]
            example = runtime.register_project("example").data["project"]
            runtime.attach_project_to_workspace(workspace["id"], primary["id"], role="primary", reason="target")
            runtime.attach_project_to_workspace(workspace["id"], example["id"], role="example", reason="reference")
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="These DTO fields are synchronized.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:test",
                },
            ).data["source"]
            example_claim = runtime.create_claim(workspace["id"], "Example DTO has customer_id.", source_refs=[source["id"]], project_refs=[example["id"]]).data["claim"]
            primary_claim = runtime.create_claim(workspace["id"], "Primary DTO has customer_id.", source_refs=[source["id"]], project_refs=[primary["id"]]).data["claim"]
            runtime.link_claims(
                workspace["id"],
                relation_type="applies_to_scope",
                subject_ref=example_claim["id"],
                object_ref=primary_claim["id"],
                bridge_scope="object_sync",
                synced_object={"kind": "field", "from": "ExampleDTO.customer_id", "to": "PrimaryDTO.customer_id"},
                reason="Same synchronized field.",
            )

            lookup = runtime.lookup_facts(workspace["id"], query="Example DTO")
            result = next(item for item in lookup.data["results"] if item["record_ref"] == example_claim["id"])
            self.assertEqual(result["bridge_context"]["bridge_scope"], "object_sync")
            self.assertTrue(result["bridge_context"]["object_sync"])
            self.assertEqual(result["bridge_context"]["synced_object"]["to"], "PrimaryDTO.customer_id")

    def test_link_claims_blocks_hypothesis_on_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            first = runtime.create_claim(workspace["id"], "Maybe cache invalidation is wrong.").data["claim"]
            second = runtime.create_claim(workspace["id"], "Maybe retry policy is involved.").data["claim"]

            link = runtime.link_claims(
                workspace["id"],
                relation_type="possible_relation_between",
                subject_ref=first["id"],
                object_ref=second["id"],
                reason="Explore possible connection.",
            )

            self.assertFalse(link.ok)
            self.assertEqual(link.error["code"], "validation_failed")
            self.assertIn("hypothesis_on_hypothesis_blocked", link.error["message"])

    def test_link_claims_allows_freshness_challenge_against_trusted_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="file_quote",
                quote="The timeout is 30 seconds.",
                critique_status="accepted",
                classification={
                    "source_class": "first_party_project",
                    "document_kind": "source_code",
                    "evidence_role": "implementation",
                    "authority_scope": "implementation_detail",
                    "independence_key": "repo:primary",
                },
            ).data["source"]
            trusted = runtime.create_claim(workspace["id"], "The timeout is 30 seconds.", source_refs=[source["id"]]).data["claim"]
            challenger = runtime.create_claim(workspace["id"], "The timeout may have changed.").data["claim"]

            link = runtime.link_claims(
                workspace["id"],
                relation_type="challenges_freshness",
                subject_ref=challenger["id"],
                object_ref=trusted["id"],
                reason="Fresh code may have changed the old fact.",
            )

            self.assertTrue(link.ok, link.error)
            self.assertEqual(link.data["claim"]["claim_form"], "relation")
            self.assertEqual(link.data["claim"]["relation"]["type"], "challenges_freshness")
            self.assertIn("open_probe", {move["operation_kind"] for move in link.valid_moves})

    def test_record_detail_returns_source_and_claim_posture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="This sounds like a usable working assumption.",
                classification={
                    "input_class": "user_confirmation",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "User confirmed the assumption.", source_refs=[source["id"]]).data["claim"]

            source_detail = runtime.record_detail(workspace["id"], source["id"])
            self.assertTrue(source_detail.ok)
            self.assertEqual(source_detail.data["detail"]["proof_role"], "proof_capable_when_accepted")
            self.assertEqual(source_detail.data["detail"]["source_trust_posture"]["derived_label"], "high")

            claim_detail = runtime.record_detail(workspace["id"], claim["id"])
            self.assertTrue(claim_detail.ok)
            self.assertEqual(claim_detail.data["detail"]["proof_role"], "proof_capable_after_ledger_snapshot")
            self.assertEqual(claim_detail.data["detail"]["trust_posture"]["derived_label"], "user_confirmed_hypothesis")
            self.assertIn("append_ledger", {move["operation_kind"] for move in claim_detail.valid_moves})

    def test_record_detail_flags_unclassified_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            claim = runtime.create_claim(workspace["id"], "Unsupported claim.").data["claim"]

            detail = runtime.record_detail(workspace["id"], claim["id"])
            self.assertTrue(detail.ok)
            posture = detail.data["detail"]["trust_posture"]
            self.assertEqual(posture["derived_label"], "unclassified_hypothesis")
            self.assertEqual(posture["inference_posture"]["kind"], "unclassified")
            self.assertTrue(detail.source_pressure)

    def test_ingest_text_creates_typed_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]

            response = runtime.ingest_text(
                workspace["id"],
                "Please use this as task intent.",
                evidence_role="intent",
                authority_scope="task_intent",
            )

            self.assertTrue(response.ok, response.error)
            source = response.data["source"]
            self.assertEqual(source["source_kind"], "user_message")
            self.assertEqual(source["critique_status"], "accepted")
            self.assertEqual(source["classification"]["evidence_role"], "intent")
            self.assertEqual(source["provenance"]["content_hash"], bytes_hash("Please use this as task intent.".encode("utf-8")))

    def test_ingest_file_creates_audited_source_with_file_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            path = Path(tmp) / "notes.md"
            path.write_text("# Retry policy\nUse settings.py.\n", encoding="utf-8")

            response = runtime.ingest_file(
                workspace["id"],
                str(path),
                project_refs=["PRJ-example"],
                source_class="user_supplied_document",
            )

            self.assertTrue(response.ok, response.error)
            source = response.data["source"]
            self.assertEqual(source["source_kind"], "file_quote")
            self.assertEqual(source["critique_status"], "audited")
            self.assertEqual(source["classification"]["document_kind"], "markdown")
            self.assertEqual(source["origin"], {"kind": "file", "ref": str(path.resolve())})
            self.assertEqual(source["project_refs"], ["PRJ-example"])
            self.assertEqual(source["provenance"]["content_hash"], bytes_hash(path.read_bytes()))
            self.assertTrue(response.source_pressure)
            self.assertTrue(any(pressure["level"] == "high" for pressure in response.source_pressure))
            move_kinds = {move["operation_kind"] for move in response.valid_moves}
            self.assertIn("extract_claim_candidates", move_kinds)
            self.assertIn("capture_source_fragments", move_kinds)
            self.assertNotIn("create_claim", move_kinds)

    def test_ingest_file_rejects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]

            response = runtime.ingest_file(workspace["id"], str(Path(tmp) / "missing.md"))

            self.assertFalse(response.ok)
            self.assertEqual(response.error["code"], "validation_failed")
            self.assertIn("file_not_found", response.error["message"])

    def test_document_claim_requires_captured_excerpt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            path = Path(tmp) / "guide.md"
            path.write_text("# Retry policy\nThe retry limit is 3 attempts.\nUse backoff.\n", encoding="utf-8")

            document = runtime.ingest_file(workspace["id"], str(path), source_class="first_party_project").data["source"]
            blocked = runtime.create_claim(workspace["id"], "The retry limit is 3 attempts.", source_refs=[document["id"]])

            self.assertFalse(blocked.ok)
            self.assertIn("document_source_requires_excerpt", blocked.error["message"])

            excerpt = runtime.capture_source_excerpt(
                workspace["id"],
                source_ref=document["id"],
                quote="The retry limit is 3 attempts.",
                locator="guide.md#retry-policy",
            )
            self.assertTrue(excerpt.ok, excerpt.error)
            excerpt_source = excerpt.data["source"]
            self.assertEqual(excerpt_source["origin"], {"kind": "source_excerpt", "ref": document["id"]})
            self.assertEqual(excerpt_source["provenance"]["quote_span"], {"start": 15, "end": 45})

            claim = runtime.create_claim(workspace["id"], "The retry limit is 3 attempts.", source_refs=[excerpt_source["id"]])
            self.assertTrue(claim.ok, claim.error)

    def test_capture_source_fragments_keeps_claims_on_exact_excerpt_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            path = Path(tmp) / "guide.md"
            text = "A" * 900 + "\n\nThe retry limit is 3 attempts.\n" + "B" * 900
            path.write_text(text, encoding="utf-8")

            document = runtime.ingest_file(workspace["id"], str(path), source_class="first_party_project").data["source"]
            fragments_response = runtime.capture_source_fragments(workspace["id"], source_ref=document["id"], max_chars=600)

            self.assertTrue(fragments_response.ok, fragments_response.error)
            fragments = fragments_response.data["fragments"]
            self.assertGreater(len(fragments), 1)
            self.assertEqual(fragments[0]["origin"], {"kind": "source_fragment", "ref": document["id"]})
            self.assertIn("extract_claim_candidates", {move["operation_kind"] for move in fragments_response.valid_moves})

            fragment_with_fact = next(fragment for fragment in fragments if "The retry limit" in fragment["quote"])
            blocked = runtime.create_claim(workspace["id"], "The retry limit is 3 attempts.", source_refs=[fragment_with_fact["id"]])
            self.assertFalse(blocked.ok)
            self.assertIn("document_source_requires_excerpt", blocked.error["message"])

            candidates = runtime.extract_claim_candidates(
                workspace["id"],
                source_ref=fragment_with_fact["id"],
                candidates=[{"quote": "The retry limit is 3 attempts.", "statement": "The retry limit is 3 attempts."}],
            )
            self.assertTrue(candidates.ok, candidates.error)
            claim = runtime.create_claim_from_evidence(
                workspace["id"],
                statement="The retry limit is 3 attempts.",
                evidence_refs=[candidates.data["claim_candidates"][0]["excerpt_source_ref"]],
            )
            self.assertTrue(claim.ok, claim.error)

    def test_confirm_source_for_scope_uses_user_confirmation_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            path = Path(tmp) / "guide.md"
            path.write_text("# Guide\nThe retry limit is 3 attempts.\n", encoding="utf-8")
            source = runtime.ingest_file(workspace["id"], str(path)).data["source"]
            confirmation = runtime.capture_input(
                workspace["id"],
                text="This uploaded guide is first-party project documentation for this task.",
                input_class="user_confirmation",
            ).data["input"]

            confirmed = runtime.confirm_source_for_scope(
                workspace["id"],
                source_ref=source["id"],
                confirmation_ref=confirmation["id"],
                source_class="first_party_project",
                authority_scope="project_documentation",
                reason="User confirmed the uploaded guide's project authority.",
            )

            self.assertTrue(confirmed.ok, confirmed.error)
            confirmed_source = confirmed.data["source"]
            self.assertEqual(confirmed_source["critique_status"], "accepted")
            self.assertEqual(confirmed_source["classification"]["source_class"], "first_party_project")
            self.assertEqual(confirmed_source["classification"]["authority_scope"], "project_documentation")
            self.assertEqual(confirmed.data["source_trust_posture"]["derived_label"], "high")
            event = confirmed.data["source_event"]
            self.assertEqual(event["event_kind"], "accepted")
            self.assertEqual(event["confirmation_ref"], confirmation["id"])
            validation = store.validate_source_events(workspace["id"])
            self.assertTrue(validation.ok, validation.errors)
            self.assertEqual(validation.accepted_sources[source["id"]], event["event_id"])

    def test_confirm_source_for_scope_requires_user_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            source = runtime.create_source(workspace["id"], source_kind="agent_observation", quote="Observation.").data["source"]
            agent_input = runtime.capture_input(
                workspace["id"],
                text="Agent thinks this is official.",
                input_class="user_confirmation",
                actor_ref="agent",
            ).data["input"]

            response = runtime.confirm_source_for_scope(
                workspace["id"],
                source_ref=source["id"],
                confirmation_ref=agent_input["id"],
                source_class="official_doc",
                authority_scope="project_documentation",
                reason="Agent attempted to confirm source authority.",
            )

            self.assertFalse(response.ok)
            self.assertIn("confirm_source_requires_user_confirmation", response.error["message"])

    def test_extract_claim_candidates_and_create_claim_from_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            path = Path(tmp) / "guide.md"
            path.write_text("# Retry policy\nThe retry limit is 3 attempts.\nUse exponential backoff.\n", encoding="utf-8")

            document = runtime.ingest_file(workspace["id"], str(path), source_class="first_party_project").data["source"]
            source_count_before_failed_extract = len(list(Path(tmp).rglob("SRC-*.json")))
            failed_candidates = runtime.extract_claim_candidates(
                workspace["id"],
                source_ref=document["id"],
                candidates=[
                    {"quote": "Use exponential backoff.", "statement": "Retry policy uses exponential backoff."},
                    {"quote": "Missing quote.", "statement": "Missing quote should not write a partial excerpt."},
                ],
            )
            self.assertFalse(failed_candidates.ok)
            self.assertIn("quote_not_found_in_source:1", failed_candidates.error["message"])
            self.assertEqual(len(list(Path(tmp).rglob("SRC-*.json"))), source_count_before_failed_extract)

            candidates = runtime.extract_claim_candidates(
                workspace["id"],
                source_ref=document["id"],
                candidates=[
                    {
                        "quote": "Use exponential backoff.",
                        "statement": "Retry policy uses exponential backoff.",
                        "claim_kind": "implementation_fact",
                        "confidence_bps": 9000,
                        "why_this_follows": "The source states the retry policy instruction directly.",
                    }
                ],
            )

            self.assertTrue(candidates.ok, candidates.error)
            candidate = candidates.data["claim_candidates"][0]
            self.assertEqual(candidate["statement"], "Retry policy uses exponential backoff.")
            self.assertEqual(candidate["quote_span"], {"start": 46, "end": 70})
            self.assertIn("create_claim_from_evidence", {move["operation_kind"] for move in candidates.valid_moves})

            claim = runtime.create_claim_from_evidence(
                workspace["id"],
                statement=candidate["statement"],
                evidence_refs=[candidate["excerpt_source_ref"]],
                claim_kind=candidate["claim_kind"],
            )
            self.assertTrue(claim.ok, claim.error)
            self.assertEqual(claim.data["claim"]["source_refs"], [candidate["excerpt_source_ref"]])

    def test_create_claim_from_evidence_requires_excerpt_and_atomic_statement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]
            path = Path(tmp) / "guide.md"
            path.write_text("# Retry policy\nThe retry limit is 3 attempts.\nUse backoff.\n", encoding="utf-8")

            document = runtime.ingest_file(workspace["id"], str(path), source_class="first_party_project").data["source"]
            whole_document = runtime.create_claim_from_evidence(
                workspace["id"],
                statement="The retry limit is 3 attempts.",
                evidence_refs=[document["id"]],
            )
            self.assertFalse(whole_document.ok)
            self.assertIn("claim_evidence_requires_excerpt_or_command_output", whole_document.error["message"])

            excerpt = runtime.capture_source_excerpt(
                workspace["id"],
                source_ref=document["id"],
                quote="The retry limit is 3 attempts.",
            ).data["source"]
            broad = runtime.create_claim_from_evidence(
                workspace["id"],
                statement="The retry limit is 3 attempts and the policy uses backoff because the guide says so.",
                evidence_refs=[excerpt["id"]],
            )
            self.assertFalse(broad.ok)
            self.assertIn("claim_from_evidence_not_atomic", broad.error["message"])

    def test_capture_input_creates_inp_and_source_hook_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]

            response = runtime.capture_input(
                workspace["id"],
                text="Please prefer the smaller API.",
                input_class="preference",
                thread_ref="thread-1",
                evidence_role="intent",
                authority_scope="task_intent",
            )

            self.assertTrue(response.ok, response.error)
            inp = response.data["input"]
            source = response.data["source"]
            self.assertTrue(inp["id"].startswith("INP-"))
            self.assertEqual(source["origin"], {"kind": "input", "ref": inp["id"]})
            self.assertEqual(source["provenance"]["activity_ref"], inp["id"])
            self.assertEqual(source["classification"]["input_class"], "preference")
            self.assertEqual(source["critique_status"], "accepted")
            self.assertEqual(store.read_input(workspace["id"], inp["id"])["content_hash"], inp["content_hash"])

    def test_codex_hook_captures_user_prompt_with_stdio_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env.pop("TEP_WORKSPACE_REF", None)
            env["TEP_REPO_ROOT"] = str(Path(__file__).resolve().parents[1])
            payload = {"cwd": str(project_root), "prompt": "Remember that prompt hooks should create INP records."}

            completed = subprocess.run(
                [sys.executable, str(script), "user-prompt"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            inputs = sorted((tep_home / "workspaces" / workspace["id"] / "records" / "inp").glob("INP-*.json"))
            self.assertEqual(len(inputs), 1)
            inp = json.loads(inputs[0].read_text(encoding="utf-8"))
            self.assertEqual(inp["text"], payload["prompt"])
            self.assertEqual(inp["input_class"], "instruction")

    def test_codex_hook_resolves_workspace_from_project_root_when_pointer_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            (project_root / ".tep").write_text(
                json.dumps({"tep_home": str(tep_home), "project_ref": "PRJ-stale", "mcp_server": "stdio"}),
                encoding="utf-8",
            )

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env.pop("TEP_WORKSPACE_REF", None)
            env["TEP_REPO_ROOT"] = str(Path(__file__).resolve().parents[1])

            completed = subprocess.run(
                [sys.executable, str(script), "user-prompt"],
                input=json.dumps({"cwd": str(project_root), "prompt": "Stale .tep project refs should not block hook capture."}),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            inputs = sorted((tep_home / "workspaces" / workspace["id"] / "records" / "inp").glob("INP-*.json"))
            self.assertEqual(len(inputs), 1)

    def test_codex_hook_session_start_reminds_agent_to_record_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            completed = subprocess.run(
                [sys.executable, str(script), "session-start"],
                input=json.dumps({"cwd": str(project_root)}),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("record durable system facts as CLM-*", completed.stdout)

    def test_codex_hook_captures_post_bash_with_stdio_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env.pop("TEP_WORKSPACE_REF", None)
            env["TEP_REPO_ROOT"] = str(Path(__file__).resolve().parents[1])
            payload = {
                "cwd": str(project_root),
                "tool_input": {"command": "echo ok"},
                "tool_response": {"exit_code": 0},
            }

            completed = subprocess.run(
                [sys.executable, str(script), "post-bash"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            runs = sorted((tep_home / "workspaces" / workspace["id"] / "records" / "run").glob("RUN-*.json"))
            self.assertEqual(len(runs), 1)
            run = json.loads(runs[0].read_text(encoding="utf-8"))
            self.assertEqual(run["command"], "echo ok")
            self.assertEqual(run["exit_code"], 0)
            claims = sorted((tep_home / "records" / "claims").glob("**/CLM-*.json"))
            self.assertEqual(len(claims), 0)
            sources = sorted((tep_home / "records" / "sources").glob("**/SRC-*.json"))
            self.assertEqual(len(sources), 1)
            self.assertIn("Captured RUN/SRC only", completed.stdout)

    def test_codex_hook_pushes_run_extraction_after_evidence_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env.pop("TEP_WORKSPACE_REF", None)
            env["TEP_REPO_ROOT"] = str(Path(__file__).resolve().parents[1])
            payload = {
                "cwd": str(project_root),
                "tool_input": {"command": "pytest -q"},
                "tool_response": {"exit_code": 0, "stdout": "1 passed\n"},
            }

            completed = subprocess.run(
                [sys.executable, str(script), "post-bash"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("extract_run_claim_candidates", completed.stdout)
            self.assertIn("what did this test output teach", completed.stdout)

    def test_codex_hook_resolves_latest_workspace_when_project_has_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("project", roots=[str(project_root)])
            first = store.create_workspace("workspace")
            store.attach_project_to_workspace(first["id"], project["id"], role="primary", reason="old")
            second = store.create_workspace("workspace-2")
            store.attach_project_to_workspace(second["id"], project["id"], role="primary", reason="new")
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env.pop("TEP_WORKSPACE_REF", None)
            env["TEP_REPO_ROOT"] = str(Path(__file__).resolve().parents[1])
            payload = {
                "cwd": str(project_root),
                "tool_input": {"command": "pytest -q"},
                "tool_response": {"exit_code": 0, "stdout": "1 passed\n"},
            }

            completed = subprocess.run(
                [sys.executable, str(script), "post-bash"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(len(list((tep_home / "workspaces" / first["id"] / "records" / "run").glob("RUN-*.json"))), 0)
            self.assertEqual(len(list((tep_home / "workspaces" / second["id"] / "records" / "run").glob("RUN-*.json"))), 1)
            claims = sorted((tep_home / "records" / "claims").glob("**/CLM-*.json"))
            self.assertEqual(len(claims), 0)

    def test_codex_hook_creates_semantic_pytest_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env.pop("TEP_WORKSPACE_REF", None)
            env["TEP_REPO_ROOT"] = str(Path(__file__).resolve().parents[1])
            stdout = "\n".join(
                [
                    "FAILED tests/test_api.py::test_returns_200 - AssertionError: 500 != 200",
                    "FAILED tests/test_auth.py::test_login - RuntimeError: bad token",
                    "=================== 2 failed, 3 passed, 1 skipped in 12.34s ===================",
                ]
            )

            completed = subprocess.run(
                [sys.executable, str(script), "post-bash"],
                input=json.dumps(
                    {
                        "cwd": str(project_root),
                        "tool_input": {"command": "pytest tests -q"},
                        "tool_response": {"exit_code": 1, "stdout": stdout},
                    }
                ),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            claims = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((tep_home / "records" / "claims").glob("**/CLM-*.json"))]
            self.assertEqual(len(claims), 3)
            statements = {claim["statement"] for claim in claims}
            summary_statement = next(statement for statement in statements if statement.startswith("Pytest command"))
            self.assertIn("2 failed, 3 passed, 1 skipped", summary_statement)
            self.assertIn("tests/test_api.py::test_returns_200", summary_statement)
            self.assertNotEqual(summary_statement, "Command `pytest tests -q` exited with code 1.")
            self.assertIn(
                "Pytest test `tests/test_api.py::test_returns_200` failed during `pytest tests -q`: AssertionError: 500 != 200.",
                statements,
            )
            self.assertIn(
                "Pytest test `tests/test_auth.py::test_login` failed during `pytest tests -q`: RuntimeError: bad token.",
                statements,
            )

    def test_codex_hook_blocks_bash_when_strict_settings_require_act(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            store.update_settings({"enforcement": {"mode": "strict", "bash_policy": "act_for_all"}}, workspace_ref=workspace["id"])
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env.pop("TEP_WORKSPACE_REF", None)
            payload = {"cwd": str(project_root), "tool_input": {"command": "rg -n settings src"}}

            completed = subprocess.run(
                [sys.executable, str(script), "pre-bash"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("Open an ACT", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_codex_hook_blocks_default_pytest_without_open_act(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            completed = subprocess.run(
                [sys.executable, str(script), "pre-bash"],
                input=json.dumps({"cwd": str(project_root), "tool_input": {"command": "pytest -q"}}),
                text=True,
                capture_output=True,
                env=dict(os.environ),
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("classification=evidence_producing", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_codex_hook_blocks_task_bash_when_required_context_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            runtime = Runtime(store)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            store.update_settings({"enforcement": {"mode": "strict", "bash_policy": "classify"}}, workspace_ref=workspace["id"])
            task = store.create_task(workspace["id"], "Do task-bound work")
            identity = generate_agent_identity("hook-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            runtime.attach_agent_to_task(workspace["id"], agent["id"], task["id"])
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env["TEP_AGENT_REF"] = agent["id"]
            completed = subprocess.run(
                [sys.executable, str(script), "pre-bash"],
                input=json.dumps({"cwd": str(project_root), "tool_input": {"command": "rg -n settings src"}}),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("missing_context", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_codex_hook_accepts_project_and_global_context_packs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            runtime = Runtime(store)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            store.update_settings({"enforcement": {"mode": "strict", "bash_policy": "classify"}}, workspace_ref=workspace["id"])
            task = runtime.create_task(workspace["id"], "Do task-bound work", project_refs=[project["id"]]).data["task"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="user_message",
                quote="Use shared context.",
                classification={
                    "input_class": "instruction",
                    "source_class": "user",
                    "document_kind": "message",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                    "independence_key": "user:test",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "Shared context exists.", source_refs=[source["id"]], project_refs=[project["id"]]).data["claim"]
            runtime.compile_context_pack(workspace["id"], task_ref=task["id"], kind="task_briefing", text="# Task\nBrief.\n", support_refs=[claim["id"]])
            runtime.compile_context_pack(workspace["id"], project_ref=project["id"], kind="coding_guidelines", text="# Coding\nGuidelines.\n", support_refs=[claim["id"]])
            runtime.compile_context_pack(workspace["id"], project_ref=project["id"], kind="project_conventions", text="# Conventions\nProject conventions.\n", support_refs=[claim["id"]])
            runtime.compile_context_pack(workspace["id"], kind="domain_theory", text="# Theory\nGlobal theory.\n", support_refs=[claim["id"]])
            identity = generate_agent_identity("hook-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            runtime.attach_agent_to_task(workspace["id"], agent["id"], task["id"])
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env["TEP_AGENT_REF"] = agent["id"]
            completed = subprocess.run(
                [sys.executable, str(script), "pre-bash"],
                input=json.dumps({"cwd": str(project_root), "tool_input": {"command": "rg -n settings src"}}),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "")

    def test_codex_hook_allows_strict_bash_when_single_open_act_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            runtime = Runtime(store)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            store.update_settings({"enforcement": {"mode": "strict", "bash_policy": "act_for_all"}}, workspace_ref=workspace["id"])
            identity = generate_agent_identity("hook-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            claim = runtime.create_claim(workspace["id"], "Strict Bash needs an ACT.").data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Snapshot before strict hook probe.",
                difficulty_bits=8,
            )
            runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Allow strict Bash hook smoke.",
                allowed_action_kind="bash",
                expected_evidence="command output",
                difficulty_bits=8,
            )
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            completed = subprocess.run(
                [sys.executable, str(script), "pre-bash"],
                input=json.dumps({"cwd": str(project_root), "tool_input": {"command": "rg -n settings src"}}),
                text=True,
                capture_output=True,
                env={**dict(os.environ), "TEP_AGENT_REF": agent["id"]},
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertNotIn("permissionDecision", output["hookSpecificOutput"])
            self.assertIn("ACT-bound", output["hookSpecificOutput"]["additionalContext"])

    def test_codex_hook_uses_unique_open_act_without_agent_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            runtime = Runtime(store)
            project = store.register_project("project", roots=[str(project_root)])
            workspace = store.create_workspace("workspace")
            store.attach_project_to_workspace(workspace["id"], project["id"], role="primary", reason="hook test")
            store.update_settings({"enforcement": {"mode": "strict", "bash_policy": "act_for_all"}}, workspace_ref=workspace["id"])
            identity = generate_agent_identity("hook-agent")
            agent = runtime.start_agent_thread(workspace_ref=workspace["id"], thread_ref="thread-1", identity=identity).data["agent"]
            claim = runtime.create_claim(workspace["id"], "Resolve bridge.qa.trgdev.local.").data["claim"]
            runtime.append_ledger(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                why="Snapshot before strict hook probe.",
                difficulty_bits=8,
            )
            runtime.open_probe(
                workspace_ref=workspace["id"],
                agent_ref=agent["id"],
                private_key=identity.private_key,
                claim_ref=claim["id"],
                intent="Allow DNS smoke command.",
                allowed_action_kind="bash",
                expected_evidence="command output",
                difficulty_bits=8,
            )
            init_project_pointer(project_root, tep_home=tep_home, project_ref=project["id"], mcp_server="stdio")

            script = Path(__file__).resolve().parents[1] / "plugins" / "tep" / "scripts" / "tep-codex-hook.py"
            env = dict(os.environ)
            env.pop("TEP_AGENT_REF", None)
            completed = subprocess.run(
                [sys.executable, str(script), "pre-bash"],
                input=json.dumps({"cwd": str(project_root), "tool_input": {"command": "python -c 'print(1)'"}},),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertNotIn("permissionDecision", output["hookSpecificOutput"])
            self.assertIn("ACT-bound", output["hookSpecificOutput"]["additionalContext"])

    def test_secret_input_is_encrypted_not_redacted_or_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            secret_text = "token=supersecretvalue12345"

            response = runtime.capture_input(
                workspace["id"],
                text=secret_text,
                input_class="instruction",
                thread_ref="thread-1",
            )

            self.assertTrue(response.ok, response.error)
            inp = response.data["input"]
            source = response.data["source"]
            self.assertIsInstance(inp["text"], dict)
            self.assertTrue(inp["text"]["encrypted"])
            self.assertNotIn(secret_text, json.dumps(inp, sort_keys=True))
            self.assertNotIn(secret_text, json.dumps(source, sort_keys=True))
            self.assertEqual(inp["input_class"], "secret_or_credential")
            self.assertEqual(source["classification"]["input_class"], "secret_or_credential")
            self.assertEqual(source["quote"]["plaintext_hash"], bytes_hash(secret_text.encode("utf-8")))
            self.assertTrue((Path(tmp) / "runtime" / "host_keys" / "default.json").exists())

            decrypted = runtime.decrypt_sensitive_field(workspace["id"], inp["id"], "text")
            self.assertTrue(decrypted.ok, decrypted.error)
            self.assertEqual(decrypted.data["plaintext"], secret_text)

    def test_capture_bash_command_records_run_then_source_excerpt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]

            captured = runtime.capture_bash_command(
                workspace["id"],
                command="pytest -q",
                cwd=tmp,
                exit_code=0,
                stdout="1 passed\n",
                stderr="",
            )
            self.assertTrue(captured.ok, captured.error)
            run = captured.data["run"]
            self.assertTrue(run["id"].startswith("RUN-"))
            self.assertEqual(run["run_kind"], "bash")
            self.assertEqual(run["status"], "captured")
            self.assertEqual(run["stdout_hash"], bytes_hash("1 passed\n".encode("utf-8")))

            source_response = runtime.capture_run_output_source(
                workspace["id"],
                run_ref=run["id"],
                stream="stdout",
                quote="1 passed\n",
            )
            self.assertTrue(source_response.ok, source_response.error)
            source = source_response.data["source"]
            self.assertEqual(source["source_kind"], "command_output")
            self.assertEqual(source["origin"], {"kind": "command", "ref": run["id"]})
            self.assertEqual(source["classification"]["source_class"], "runtime_observation")
            self.assertEqual(source["critique_status"], "audited")
            self.assertTrue(source_response.source_pressure)

            bad_quote = runtime.capture_run_output_source(workspace["id"], run_ref=run["id"], quote="2 failed")
            self.assertFalse(bad_quote.ok)
            self.assertIn("quote_not_found_in_run_output", bad_quote.error["message"])

    def test_extract_run_claim_candidates_and_create_claim_from_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            run = runtime.capture_bash_command(
                workspace["id"],
                command="pytest tests/test_api.py -q",
                cwd=tmp,
                exit_code=1,
                stdout="FAILED tests/test_api.py::test_returns_200 - AssertionError: 500 != 200\n",
            ).data["run"]

            source_count_before_failed_extract = len(list(Path(tmp).rglob("SRC-*.json")))
            failed = runtime.extract_run_claim_candidates(
                workspace["id"],
                run_ref=run["id"],
                candidates=[
                    {
                        "stream": "stdout",
                        "quote": "FAILED tests/test_api.py::test_returns_200 - AssertionError: 500 != 200",
                        "statement": "API test observes a 500 response where 200 is expected.",
                    },
                    {"stream": "stdout", "quote": "missing", "statement": "Missing quote should not write a partial source."},
                ],
            )
            self.assertFalse(failed.ok)
            self.assertIn("quote_not_found_in_run_output:1", failed.error["message"])
            self.assertEqual(len(list(Path(tmp).rglob("SRC-*.json"))), source_count_before_failed_extract)

            candidates = runtime.extract_run_claim_candidates(
                workspace["id"],
                run_ref=run["id"],
                candidates=[
                    {
                        "stream": "stdout",
                        "quote": "FAILED tests/test_api.py::test_returns_200 - AssertionError: 500 != 200",
                        "statement": "API test observes a 500 response where 200 is expected.",
                        "claim_kind": "runtime_observation",
                        "why_this_follows": "The pytest failure line reports the actual and expected status codes.",
                    }
                ],
            )
            self.assertTrue(candidates.ok, candidates.error)
            candidate = candidates.data["claim_candidates"][0]
            self.assertIn("create_claim_from_evidence", {move["operation_kind"] for move in candidates.valid_moves})

            claim = runtime.create_claim_from_evidence(
                workspace["id"],
                statement=candidate["statement"],
                evidence_refs=[candidate["evidence_source_ref"]],
                claim_kind=candidate["claim_kind"],
            )
            self.assertTrue(claim.ok, claim.error)
            self.assertEqual(claim.data["claim"]["source_refs"], [candidate["evidence_source_ref"]])

    def test_secret_bash_output_is_encrypted_and_can_be_captured_as_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            secret_output = "password=supersecretvalue12345\n"

            captured = runtime.capture_bash_command(
                workspace["id"],
                command="print-secret",
                cwd=tmp,
                exit_code=0,
                stdout=secret_output,
            )
            self.assertTrue(captured.ok, captured.error)
            run = captured.data["run"]
            self.assertIsInstance(run["stdout"], dict)
            self.assertTrue(run["stdout"]["encrypted"])
            self.assertNotIn(secret_output, json.dumps(run, sort_keys=True))

            source_response = runtime.capture_run_output_source(workspace["id"], run_ref=run["id"], quote=secret_output)
            self.assertTrue(source_response.ok, source_response.error)
            source = source_response.data["source"]
            self.assertIsInstance(source["quote"], dict)
            self.assertTrue(source["quote"]["encrypted"])
            self.assertEqual(source["classification"]["input_class"], "secret_or_credential")

            decrypted = runtime.decrypt_sensitive_field(workspace["id"], source["id"], "quote")
            self.assertTrue(decrypted.ok, decrypted.error)
            self.assertEqual(decrypted.data["plaintext"], secret_output)

    def test_refresh_indexes_writes_runtime_navigation_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TEPHome(tmp)
            runtime = Runtime(store)
            workspace = runtime.create_workspace("workspace").data["workspace"]
            source = runtime.create_source(
                workspace["id"],
                source_kind="file_quote",
                quote="Retry policy is in settings.py.",
                critique_status="accepted",
                classification={
                    "source_class": "first_party_project",
                    "document_kind": "source_code",
                    "evidence_role": "implementation",
                    "authority_scope": "implementation_detail",
                    "independence_key": "repo:primary",
                },
            ).data["source"]
            claim = runtime.create_claim(workspace["id"], "Retry policy is in settings.py.", source_refs=[source["id"]]).data["claim"]

            before = runtime.index_status(workspace["id"])
            self.assertTrue(before.ok)
            self.assertTrue(before.index_pressure)

            refresh = runtime.refresh_indexes(workspace["id"])
            self.assertTrue(refresh.ok, refresh.error)
            self.assertEqual(refresh.data["index_refresh"]["indexes"]["trust_score"]["row_count"], 1)

            status = runtime.index_status(workspace["id"])
            self.assertTrue(status.ok)
            self.assertFalse(status.index_pressure)
            trust_rows = status.data["index_status"]["indexes"]["trust_score"]["rows"]
            self.assertEqual(trust_rows[0]["claim_ref"], claim["id"])
            self.assertEqual(trust_rows[0]["derived_label"], "trusted_fact")
            self.assertEqual(store.read_index_manifest(workspace["id"], "source_class")["rows"][0]["source_ref"], source["id"])
            self.assertTrue(str(store.index_manifest_path(workspace["id"], "source_class")).startswith(str(Path(tmp) / "records" / "indexes")))
            self.assertFalse((Path(tmp) / "workspaces" / workspace["id"] / "indexes" / "manifests" / "source_class.json").exists())

    def test_mcp_adapter_lists_and_dispatches_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = MCPAdapter(Runtime(TEPHome(tmp)))
            tool_names = {tool["name"] for tool in adapter.list_tools()}
            self.assertIn("start_agent_thread", tool_names)
            self.assertIn("append_ledger", tool_names)
            self.assertIn("protected_action_preflight", tool_names)
            self.assertIn("final_answer_preflight", tool_names)
            self.assertIn("task_done_preflight", tool_names)
            self.assertIn("ingest_file", tool_names)
            self.assertIn("capture_source_excerpt", tool_names)
            self.assertIn("capture_source_fragments", tool_names)
            self.assertIn("extract_claim_candidates", tool_names)
            self.assertIn("confirm_source_for_scope", tool_names)
            self.assertIn("create_claim_from_evidence", tool_names)
            self.assertIn("capture_input", tool_names)
            self.assertIn("capture_bash_command", tool_names)
            self.assertIn("capture_run_output_source", tool_names)
            self.assertIn("extract_run_claim_candidates", tool_names)
            self.assertIn("decrypt_sensitive_field", tool_names)
            self.assertIn("read_settings", tool_names)
            self.assertIn("update_settings", tool_names)
            self.assertIn("action_pressure", tool_names)
            self.assertIn("compile_context_pack", tool_names)
            self.assertIn("list_context_packs", tool_names)
            self.assertIn("revoke_context_pack", tool_names)
            compile_tool = next(tool for tool in adapter.list_tools() if tool["name"] == "compile_context_pack")
            self.assertIn("task_ref", compile_tool["optional"])

            missing = adapter.call_tool("create_workspace", {})
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["error"]["code"], "missing_required_arguments")

            invalid_identity = adapter.call_tool(
                "start_agent_thread",
                {"workspace_ref": "WSP-missing", "thread_ref": "thread-1", "identity": {}},
            )
            self.assertFalse(invalid_identity["ok"])
            self.assertEqual(invalid_identity["error"]["code"], "invalid_arguments")

            identity = adapter.call_tool("generate_agent_identity", {"agent_name": "mcp-agent"})
            self.assertTrue(identity["ok"], identity.get("error"))
            workspace = adapter.call_tool("create_workspace", {"name": "workspace"})
            self.assertTrue(workspace["ok"], workspace.get("error"))
            settings = adapter.call_tool(
                "update_settings",
                {
                    "workspace_ref": workspace["data"]["workspace"]["id"],
                    "settings": {"enforcement": {"mode": "advisory", "bash_policy": "classify"}},
                },
            )
            self.assertTrue(settings["ok"], settings.get("error"))
            pressure = adapter.call_tool(
                "action_pressure",
                {
                    "workspace_ref": workspace["data"]["workspace"]["id"],
                    "action_kind": "bash",
                    "action": {"command": "pytest -q"},
                },
            )
            self.assertTrue(pressure["ok"], pressure.get("error"))
            self.assertEqual(pressure["data"]["action_pressure"]["level"], "medium")
            agent = adapter.call_tool(
                "start_agent_thread",
                {
                    "workspace_ref": workspace["data"]["workspace"]["id"],
                    "thread_ref": "thread-1",
                    "identity": identity["data"],
                },
            )
            self.assertTrue(agent["ok"], agent.get("error"))
            self.assertEqual(agent["data"]["agent"]["key_fingerprint"], identity["data"]["key_fingerprint"])
            self.assertNotIn(identity["data"]["agent_private_key"], json.dumps(agent["data"]["agent"], sort_keys=True))

            source = adapter.call_tool(
                "ingest_text",
                {
                    "workspace_ref": workspace["data"]["workspace"]["id"],
                    "text": "Use this source through MCP adapter.",
                    "evidence_role": "intent",
                    "authority_scope": "task_intent",
                },
            )
            self.assertTrue(source["ok"], source.get("error"))
            claim = adapter.call_tool(
                "create_claim",
                {
                    "workspace_ref": workspace["data"]["workspace"]["id"],
                    "statement": "The MCP adapter can create facts.",
                    "source_refs": [source["data"]["source"]["id"]],
                },
            )
            self.assertTrue(claim["ok"], claim.get("error"))
            append = adapter.call_tool(
                "append_ledger",
                {
                    "workspace_ref": workspace["data"]["workspace"]["id"],
                    "agent_ref": agent["data"]["agent"]["id"],
                    "agent_private_key": identity["data"]["agent_private_key"],
                    "claim_ref": claim["data"]["claim"]["id"],
                    "why": "Adapter dispatch should seal a ledger row.",
                    "difficulty_bits": 8,
                },
            )
            self.assertTrue(append["ok"], append.get("error"))
            self.assertTrue(append["ledger_pressure"]["ledger_valid"])

            unknown = adapter.call_tool("raw_json_write", {})
            self.assertFalse(unknown["ok"])
            self.assertEqual(unknown["error"]["code"], "unknown_tool")

    def test_runtime_moves_do_not_reference_deferred_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            adapter = MCPAdapter(runtime)
            tool_names = {tool["name"] for tool in adapter.list_tools()}
            virtual_operation_kinds = {"final_answer", "project_registry_search", "select_existing_claim"}
            allowed = tool_names | virtual_operation_kinds
            workspace = runtime.create_workspace("workspace").data["workspace"]
            path = Path(tmp) / "guide.md"
            path.write_text("# Guide\nUse settings.py.\n", encoding="utf-8")
            document = runtime.ingest_file(workspace["id"], str(path)).data["source"]

            responses = [
                runtime.create_source(
                    workspace["id"],
                    source_kind="agent_observation",
                    quote="Runtime source pressure must only suggest executable moves.",
                    classification={"source_class": "runtime_observation", "document_kind": "implementation_note"},
                    critique_status="audited",
                ),
                runtime.ingest_file(workspace["id"], str(path)),
                runtime.record_detail(workspace["id"], document["id"]),
                runtime.action_pressure(workspace["id"], action_kind="bash", action={"command": "pytest -q"}),
            ]

            for response in responses:
                kinds = self._operation_kinds_from(response)
                self.assertFalse({"classify_source", "accept_source", "reject_source"} & kinds)
                self.assertTrue(kinds <= allowed, f"unsupported operation kinds: {sorted(kinds - allowed)}")

    def test_http_app_exposes_standalone_tool_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = TEPHTTPApp(MCPAdapter(Runtime(TEPHome(tmp))))

            status, headers, body = app.handle("GET", "/health")
            self.assertEqual(status, 200)
            self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
            self.assertTrue(json.loads(body)["ok"])

            status, _headers, body = app.handle("GET", "/tools")
            self.assertEqual(status, 200)
            self.assertIn("create_workspace", {tool["name"] for tool in json.loads(body)["tools"]})

            status, _headers, body = app.handle(
                "POST",
                "/call",
                json.dumps({"name": "create_workspace", "arguments": {"name": "http-workspace"}}).encode("utf-8"),
            )
            self.assertEqual(status, 200)
            response = json.loads(body)
            self.assertTrue(response["ok"])
            self.assertEqual(response["data"]["workspace"]["name"], "http-workspace")

            status, _headers, body = app.handle("POST", "/call", b"{")
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["error"]["code"], "invalid_json")

            status, _headers, body = app.handle("POST", "/call", json.dumps({"arguments": {}}).encode("utf-8"))
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["error"]["code"], "missing_tool_name")

    def test_http_vertical_agent_flow_reaches_final_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = TEPHTTPApp(MCPAdapter(Runtime(TEPHome(tmp))))

            def call(name: str, arguments: dict[str, object]) -> dict[str, object]:
                status, _headers, body = app.handle(
                    "POST",
                    "/call",
                    json.dumps({"name": name, "arguments": arguments}).encode("utf-8"),
                )
                response = json.loads(body)
                self.assertEqual(status, 200, response)
                self.assertTrue(response["ok"], response.get("error"))
                return response

            identity = call("generate_agent_identity", {"agent_name": "vertical-agent"})["data"]
            workspace = call("create_workspace", {"name": "vertical"})["data"]["workspace"]
            project = call("register_project", {"name": "primary"})["data"]["project"]
            call(
                "attach_project_to_workspace",
                {"workspace_ref": workspace["id"], "project_ref": project["id"], "role": "primary", "reason": "vertical test"},
            )
            task = call("create_task", {"workspace_ref": workspace["id"], "goal": "Answer with ledger support", "project_refs": [project["id"]]})["data"]["task"]
            agent = call("start_agent_thread", {"workspace_ref": workspace["id"], "thread_ref": "thread-1", "identity": identity})["data"]["agent"]
            call("attach_agent_to_task", {"workspace_ref": workspace["id"], "agent_ref": agent["id"], "task_ref": task["id"]})
            source = call(
                "capture_input",
                {
                    "workspace_ref": workspace["id"],
                    "text": "This result is acceptable.",
                    "input_class": "user_confirmation",
                    "evidence_role": "approval",
                    "authority_scope": "workspace_policy",
                },
            )["data"]["source"]
            run = call(
                "capture_bash_command",
                {
                    "workspace_ref": workspace["id"],
                    "command": "echo ok",
                    "cwd": tmp,
                    "exit_code": 0,
                    "stdout": "ok\n",
                },
            )["data"]["run"]
            run_source = call("capture_run_output_source", {"workspace_ref": workspace["id"], "run_ref": run["id"], "quote": "ok\n"})["data"]["source"]
            self.assertEqual(run_source["origin"], {"kind": "command", "ref": run["id"]})
            claim = call(
                "create_claim",
                {
                    "workspace_ref": workspace["id"],
                    "statement": "The user confirmed this result is acceptable.",
                    "source_refs": [source["id"]],
                    "project_refs": [project["id"]],
                    "task_refs": [task["id"]],
                },
            )["data"]["claim"]
            call(
                "append_ledger",
                {
                    "workspace_ref": workspace["id"],
                    "agent_ref": agent["id"],
                    "agent_private_key": identity["agent_private_key"],
                    "claim_ref": claim["id"],
                    "why": "Final support.",
                    "difficulty_bits": 8,
                },
            )
            call(
                "compile_context_pack",
                {
                    "workspace_ref": workspace["id"],
                    "task_ref": task["id"],
                    "kind": "task_briefing",
                    "text": "# Task Briefing\nUse the ledgered final support.\n",
                    "support_refs": [claim["id"]],
                    "agent_ref": agent["id"],
                },
            )
            final = call(
                "final_answer_preflight",
                {
                    "workspace_ref": workspace["id"],
                    "agent_ref": agent["id"],
                    "task_ref": task["id"],
                    "support_refs": [claim["id"]],
                },
            )
            self.assertTrue(final["data"]["final_answer_preflight"]["allowed"])

    def test_stdio_app_exposes_local_jsonl_tool_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = TEPStdioApp(MCPAdapter(Runtime(TEPHome(tmp))))

            tools = app.handle_line(json.dumps({"method": "tools/list"}))
            self.assertTrue(tools["ok"])
            self.assertIn("create_workspace", {tool["name"] for tool in tools["tools"]})

            created = app.handle_line(
                json.dumps(
                    {
                        "method": "tools/call",
                        "params": {"name": "create_workspace", "arguments": {"name": "stdio-workspace"}},
                    }
                )
            )
            self.assertTrue(created["ok"], created.get("error"))
            self.assertEqual(created["data"]["workspace"]["name"], "stdio-workspace")

            invalid_json = app.handle_line("{")
            self.assertFalse(invalid_json["ok"])
            self.assertEqual(invalid_json["error"]["code"], "invalid_json")

            unknown = app.handle_line(json.dumps({"method": "raw_json_write"}))
            self.assertFalse(unknown["ok"])
            self.assertEqual(unknown["error"]["code"], "unknown_method")

    def test_mcp_stdio_server_exposes_jsonrpc_tool_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = TEPMCPStdioServer(MCPAdapter(Runtime(TEPHome(tmp))))

            initialized = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                }
            )
            self.assertEqual(initialized["result"]["serverInfo"]["name"], "tep")
            self.assertEqual(initialized["result"]["serverInfo"]["version"], "0.6.25")

            tools = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            tool_names = {tool["name"] for tool in tools["result"]["tools"]}
            self.assertIn("generate_agent_identity", tool_names)
            self.assertIn("append_ledger", tool_names)
            compile_tool = next(tool for tool in tools["result"]["tools"] if tool["name"] == "compile_context_pack")
            self.assertIn("task_ref", compile_tool["inputSchema"]["properties"])

            called = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "generate_agent_identity", "arguments": {"agent_name": "mcp-check"}},
                }
            )
            self.assertFalse(called["result"]["isError"])
            payload = json.loads(called["result"]["content"][0]["text"])
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["data"]["agent_ref"].startswith("AGENT-"))

            unknown = server.handle_message(
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "raw_json_write"}}
            )
            self.assertTrue(unknown["result"]["isError"])

            bad_briefing = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "compile_context_pack",
                        "arguments": {
                            "workspace_ref": "WSP-missing",
                            "kind": "task_briefing",
                            "text": "# Brief\n",
                            "support_refs": ["CLM-missing"],
                        },
                    },
                }
            )
            self.assertTrue(bad_briefing["result"]["isError"])
            self.assertIn("task_ref", bad_briefing["result"]["content"][0]["text"])

    def test_mcp_stdio_server_supports_content_length_framing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = TEPMCPStdioServer(MCPAdapter(Runtime(TEPHome(tmp))))
            message = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
            stdin = io.StringIO(f"Content-Length: {len(message.encode('utf-8'))}\r\n\r\n{message}")
            stdout = io.StringIO()

            run_mcp_loop(server, stdin=stdin, stdout=stdout)

            raw = stdout.getvalue()
            self.assertTrue(raw.startswith("Content-Length: "), raw)
            body = raw.split("\r\n\r\n", 1)[1]
            response = json.loads(body)
            self.assertEqual(response["result"]["serverInfo"]["version"], "0.6.25")

    def test_mcp_stdio_binary_loop_handles_utf8_content_length(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = TEPMCPStdioServer(MCPAdapter(Runtime(TEPHome(tmp))))
            message = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "create_workspace", "arguments": {"name": "проект"}},
                },
                ensure_ascii=False,
            )
            body = message.encode("utf-8")
            stdin = io.BytesIO(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
            stdout = io.BytesIO()

            run_mcp_loop_binary(server, stdin=stdin, stdout=stdout)

            raw = stdout.getvalue()
            self.assertTrue(raw.startswith(b"Content-Length: "), raw)
            response = json.loads(raw.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
            payload = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(payload["ok"], payload.get("error"))
            self.assertEqual(payload["data"]["workspace"]["name"], "проект")

    def test_init_project_pointer_registers_project_and_writes_dot_tep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()

            result = init_project_pointer(
                project_root,
                tep_home=tep_home,
                name="service-api",
                mcp_server="http://127.0.0.1:8765",
            )

            pointer = read_project_pointer(project_root)
            self.assertEqual(pointer.tep_home, str(tep_home))
            self.assertEqual(pointer.project_ref, result["project"]["id"])
            self.assertEqual(pointer.mcp_server, "http://127.0.0.1:8765")
            self.assertTrue(pointer.project_ref.startswith("PRJ-"))
            self.assertNotIn("workspace_ref", json.loads((project_root / ".tep").read_text(encoding="utf-8")))
            self.assertEqual(TEPHome.from_project_pointer(project_root).root, tep_home)
            self.assertEqual(TEPHome(tep_home).read_project(pointer.project_ref)["roots"], [str(project_root.resolve())])

            with self.assertRaises(ValidationError):
                init_project_pointer(project_root, tep_home=tep_home, name="duplicate")

            rebound = init_project_pointer(project_root, tep_home=tep_home, name="duplicate", force=True)
            self.assertEqual(rebound["project"]["id"], pointer.project_ref)
            self.assertEqual(len(TEPHome(tep_home).projects()), 1)

            with self.assertRaises(ValidationError):
                TEPHome(tep_home).register_project("duplicate-root", roots=[str(project_root)])

            archived_project = TEPHome(tep_home).archive_project(pointer.project_ref, reason="cleanup duplicate registration test")
            self.assertEqual(archived_project["status"], "archived")
            self.assertEqual(archived_project["archive_reason"], "cleanup duplicate registration test")
            replacement = TEPHome(tep_home).register_project("replacement", roots=[str(project_root)])
            self.assertNotEqual(replacement["id"], pointer.project_ref)
            self.assertEqual(TEPHome(tep_home).find_project_by_root(project_root)["id"], replacement["id"])

            workspace = TEPHome(tep_home).create_workspace("scratch")
            archived_workspace = TEPHome(tep_home).archive_workspace(workspace["id"], reason="cleanup empty workspace")
            self.assertEqual(archived_workspace["status"], "archived")
            self.assertEqual(archived_workspace["archive_reason"], "cleanup empty workspace")

    def test_init_project_pointer_can_bind_existing_project_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            store = TEPHome(tep_home)
            project = store.register_project("existing", roots=[str(project_root)])

            result = init_project_pointer(
                project_root,
                tep_home=tep_home,
                project_ref=project["id"],
                mcp_server="stdio",
            )

            pointer = read_project_pointer(project_root)
            self.assertEqual(pointer.project_ref, project["id"])
            self.assertEqual(result["project"]["name"], "existing")

    def test_init_project_pointer_rolls_back_new_project_when_pointer_commit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            (project_root / ".tep").mkdir()

            with self.assertRaises(StorageError):
                init_project_pointer(project_root, tep_home=tep_home, name="broken", force=True)

            store = TEPHome(tep_home)
            self.assertEqual(store.projects(), [])
            self.assertFalse((tep_home / "runtime" / "tx").exists() and any((tep_home / "runtime" / "tx").iterdir()))

    def test_project_registry_mutations_are_journaled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tep_home = Path(tmp) / "tep-home"
            store = TEPHome(tep_home)

            project = store.register_project("journaled", roots=[str(Path(tmp) / "project")])
            workspace = store.create_workspace("journaled workspace")
            store.archive_project(project["id"], reason="test archive")
            store.archive_workspace(workspace["id"], reason="test archive")

            journal_files = sorted((tep_home / "journals" / "operations").glob("*.jsonl"))
            self.assertEqual(len(journal_files), 1)
            operations = [json.loads(line)["operation"] for line in journal_files[0].read_text(encoding="utf-8").splitlines()]
            self.assertEqual(operations, ["register_project", "create_workspace", "archive_project", "archive_workspace"])


if __name__ == "__main__":
    unittest.main()
