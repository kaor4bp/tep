"""Computed posture helpers for claims, sources, scope, and record details."""

from __future__ import annotations

from typing import Any

from .storage import TEPHome


class PostureService:
    def __init__(self, store: TEPHome) -> None:
        self.store = store

    def trust_posture(self, workspace_ref: str, claim: dict[str, Any]) -> dict[str, Any]:
        source_refs = claim.get("source_refs", [])
        sources = [self.store.read_source(workspace_ref, source_ref) for source_ref in source_refs]
        accepted = [source for source in sources if source.get("critique_status") == "accepted"]
        classifications = [source.get("classification", {}) for source in accepted]
        source_classes = {item.get("source_class") for item in classifications}
        input_classes = {item.get("input_class") for item in classifications}
        independence_keys = sorted({item.get("independence_key", "unknown") for item in classifications})
        contradiction_count = len(claim.get("contradiction_refs", []))

        if contradiction_count:
            label = "contested"
            trust_score_bps = 2500
            usable_for = ["exploration", "probe"]
        elif not source_refs:
            label = "unclassified_hypothesis"
            trust_score_bps = 500
            usable_for = ["exploration", "probe"]
        elif "user_confirmation" in input_classes or "working_assumption" in input_classes:
            label = "user_confirmed_hypothesis"
            trust_score_bps = 6500
            usable_for = ["exploration", "probe", "answer"]
        elif {"official_doc", "standard_or_paper", "first_party_project"}.intersection(source_classes):
            label = "trusted_fact"
            trust_score_bps = 8000
            usable_for = ["exploration", "probe", "answer", "protected_action"]
        elif "runtime_observation" in source_classes or "test_or_check" in source_classes:
            label = "needs_theory_support"
            trust_score_bps = 4500
            usable_for = ["exploration", "probe"]
        elif accepted:
            label = "hypothesis"
            trust_score_bps = 3500
            usable_for = ["exploration", "probe"]
        else:
            label = "unclassified_hypothesis"
            trust_score_bps = 1000
            usable_for = ["exploration", "probe"]

        return {
            "claim_ref": claim["id"],
            "ledger_snapshot": None,
            "trust_score_bps": trust_score_bps,
            "derived_label": label,
            "inference_posture": self.inference_posture(claim),
            "runtime_support_count": sum(
                1
                for source in accepted
                if source.get("classification", {}).get("source_class") in {"runtime_observation", "test_or_check"}
            ),
            "theory_support_count": sum(
                1
                for source in accepted
                if source.get("classification", {}).get("source_class") in {"official_doc", "standard_or_paper", "first_party_project"}
            ),
            "user_confirmation": "confirmed_hypothesis" if label == "user_confirmed_hypothesis" else "none",
            "source_diversity": {
                "accepted_source_count": len(accepted),
                "independent_source_class_count": len(source_classes),
                "independence_keys": independence_keys,
                "missing": self.missing_source_classes(source_classes, input_classes),
            },
            "freshness_pressure": {"level": "none", "challenge_refs": [], "why": ""},
            "contradiction_pressure_bps": 9000 if contradiction_count else 0,
            "usable_for": usable_for,
        }

    @staticmethod
    def source_trust_posture(source: dict[str, Any]) -> dict[str, Any]:
        classification = source.get("classification", {})
        source_class = classification.get("source_class")
        critique_status = source.get("critique_status")
        if critique_status == "rejected" or classification.get("input_class") == "secret_or_credential":
            label = "blocked"
            score = 0
            usable_for: list[str] = []
        elif critique_status == "accepted" and source_class in {"user", "official_doc", "standard_or_paper", "first_party_project"}:
            label = "high"
            score = 8000
            usable_for = ["exploration", "probe", "answer"]
        elif critique_status == "audited":
            label = "medium"
            score = 5000
            usable_for = ["exploration", "probe"]
        elif critique_status == "accepted":
            label = "medium"
            score = 5500
            usable_for = ["exploration", "probe", "answer"]
        else:
            label = "unrated"
            score = 1000
            usable_for = ["exploration"]
        return {
            "source_ref": source["id"],
            "source_trust_score_bps": score,
            "derived_label": label,
            "classification": classification,
            "factors": {
                "critique_status": critique_status,
                "content_hash_present": source.get("provenance", {}).get("content_hash") is not None,
                "quote_or_span_verified": source.get("source_kind") in {"file_quote", "user_message", "command_output"},
                "freshness": "unknown",
                "scope_fit": "unknown",
                "known_contradictions": 0,
            },
            "usable_for": usable_for,
        }

    @staticmethod
    def missing_source_classes(source_classes: set[Any], input_classes: set[Any]) -> list[str]:
        missing = []
        if not {"official_doc", "standard_or_paper", "first_party_project"}.intersection(source_classes):
            missing.append("official_doc|standard_or_paper|first_party_project")
        if "user_confirmation" not in input_classes and "working_assumption" not in input_classes:
            missing.append("user_confirmation")
        if not {"runtime_observation", "test_or_check"}.intersection(source_classes):
            missing.append("test_or_check")
        return missing

    @staticmethod
    def inference_posture(claim: dict[str, Any]) -> dict[str, Any]:
        relation = claim.get("relation") or {}
        relation_type = relation.get("type")
        mapping = {
            "deduced_from": "deduction",
            "induced_from": "induction",
            "abduced_from": "abduction",
            "assumed_from": "fact_based_assumption",
            "possible_relation_between": "possible_relation",
            "analogized_from": "analogy",
            "analogous_to": "analogy",
            "challenges_freshness": "freshness_challenge",
        }
        kind = mapping.get(relation_type)
        if kind is None and claim.get("source_refs"):
            kind = None
            predictability = "not_applicable"
        elif kind is None:
            kind = "unclassified"
            predictability = "missing_basis"
        else:
            predictability = "classified"
        return {
            "kind": kind,
            "basis_refs": [ref for ref in [relation.get("subject"), relation.get("object")] if ref],
            "relation_refs": [claim["id"]] if claim.get("claim_form") == "relation" else [],
            "predictability": predictability,
            "why": "derived from relation type" if relation_type else "no inference relation",
        }

    def scope_metadata(self, workspace_ref: str, claim: dict[str, Any], task: dict[str, Any] | None) -> dict[str, Any]:
        claim_projects = set(claim.get("scope", {}).get("project_refs", []))
        task_projects = set(task.get("project_refs", [])) if task else set()
        memberships = self.store.project_memberships(workspace_ref)
        roles = {row["project_ref"]: row["role"] for row in memberships}
        if not claim_projects:
            scope_origin = "workspace"
            requires_bridge = False
        elif task_projects and claim_projects.intersection(task_projects):
            scope_origin = "primary_project"
            requires_bridge = False
        else:
            role_set = {roles.get(project_ref, "unknown") for project_ref in claim_projects}
            if "primary" in role_set:
                scope_origin = "primary_project"
                requires_bridge = False
            elif "dependency" in role_set:
                scope_origin = "dependency"
                requires_bridge = False
            elif role_set.intersection({"example", "reference", "comparison"}):
                scope_origin = sorted(role_set.intersection({"example", "reference", "comparison"}))[0]
                requires_bridge = True
            else:
                scope_origin = "foreign"
                requires_bridge = True
        return {
            "scope_origin": scope_origin,
            "proof_usable_now": not requires_bridge,
            "requires_bridge": requires_bridge,
        }

    @staticmethod
    def proof_role(record: dict[str, Any]) -> str:
        record_type = record.get("record_type")
        if record_type == "claim":
            return "proof_capable_after_ledger_snapshot"
        if record_type == "source":
            return "proof_capable_when_accepted"
        if record_type == "run":
            return "protected_action_evidence_after_capture"
        if record_type in {"task", "agent", "project", "workspace"}:
            return "coordination_or_scope"
        return "navigation_only"

    @staticmethod
    def record_links(record: dict[str, Any]) -> dict[str, Any]:
        if record.get("record_type") == "claim":
            return {
                "source_refs": record.get("source_refs", []),
                "support_refs": record.get("support_refs", []),
                "contradiction_refs": record.get("contradiction_refs", []),
                "relation": record.get("relation"),
            }
        if record.get("record_type") == "source":
            return {"project_refs": record.get("project_refs", [])}
        if record.get("record_type") == "task":
            return {
                "parent_task_ref": record.get("parent_task_ref"),
                "child_task_refs": record.get("child_task_refs", []),
                "claim_refs": record.get("claim_refs", []),
                "agent_refs": record.get("agent_refs", []),
            }
        if record.get("record_type") == "run":
            return {
                "agent_ref": record.get("agent_ref"),
                "ledger_head": record.get("ledger_head"),
                "open_act_ref": record.get("open_act_ref"),
                "action_hash": record.get("action_hash"),
            }
        return {}
