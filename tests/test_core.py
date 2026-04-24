from __future__ import annotations

import json
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
from tep.errors import CanonicalJSONError, OwnershipError, ValidationError
from tep.jsoncanon import bytes_hash, canonical_dumps


class CoreTests(unittest.TestCase):
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

    def test_ingest_file_rejects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(TEPHome(tmp))
            workspace = runtime.create_workspace("workspace").data["workspace"]

            response = runtime.ingest_file(workspace["id"], str(Path(tmp) / "missing.md"))

            self.assertFalse(response.ok)
            self.assertEqual(response.error["code"], "validation_failed")
            self.assertIn("file_not_found", response.error["message"])

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
            self.assertIn("capture_input", tool_names)
            self.assertIn("capture_bash_command", tool_names)
            self.assertIn("capture_run_output_source", tool_names)
            self.assertIn("decrypt_sensitive_field", tool_names)

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


if __name__ == "__main__":
    unittest.main()
