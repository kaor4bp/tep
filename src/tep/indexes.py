"""Runtime-built index manifests.

These indexes are derived state. They speed up lookup and briefing, but they
are never proof by themselves.
"""

from __future__ import annotations

from typing import Any

from .ids import new_id
from .posture import PostureService
from .storage import TEPHome, utc_now


class IndexService:
    def __init__(self, store: TEPHome) -> None:
        self.store = store
        self.posture = PostureService(store)

    def refresh_workspace_indexes(self, workspace_ref: str) -> dict[str, Any]:
        manifests = {
            "trust_score": self._trust_score_index(workspace_ref),
            "source_class": self._source_class_index(workspace_ref),
            "relation_graph": self._relation_graph_index(workspace_ref),
        }
        for name, manifest in manifests.items():
            self.store.write_index_manifest(workspace_ref, name, manifest)
        return {
            "workspace_ref": workspace_ref,
            "generated_at": utc_now(),
            "indexes": manifests,
        }

    def index_status(self, workspace_ref: str) -> dict[str, Any]:
        return {
            "workspace_ref": workspace_ref,
            "indexes": {
                name: self.store.read_index_manifest(workspace_ref, name)
                for name in ["trust_score", "source_class", "relation_graph"]
                if self.store.index_manifest_path(workspace_ref, name).exists()
            },
        }

    def _trust_score_index(self, workspace_ref: str) -> dict[str, Any]:
        rows = []
        for claim in self.store.claims(workspace_ref):
            posture = self.posture.trust_posture(workspace_ref, claim)
            rows.append(
                {
                    "claim_ref": claim["id"],
                    "trust_score_bps": posture["trust_score_bps"],
                    "derived_label": posture["derived_label"],
                    "usable_for": posture["usable_for"],
                    "source_refs": claim.get("source_refs", []),
                }
            )
        rows.sort(key=lambda row: (row["trust_score_bps"], row["claim_ref"]), reverse=True)
        return self._manifest(workspace_ref, "trust_score", rows)

    def _source_class_index(self, workspace_ref: str) -> dict[str, Any]:
        rows = []
        for source in self.store.sources(workspace_ref):
            classification = source.get("classification", {})
            rows.append(
                {
                    "source_ref": source["id"],
                    "critique_status": source.get("critique_status"),
                    "source_class": classification.get("source_class"),
                    "document_kind": classification.get("document_kind"),
                    "evidence_role": classification.get("evidence_role"),
                    "authority_scope": classification.get("authority_scope"),
                    "independence_key": classification.get("independence_key"),
                }
            )
        rows.sort(key=lambda row: row["source_ref"])
        return self._manifest(workspace_ref, "source_class", rows)

    def _relation_graph_index(self, workspace_ref: str) -> dict[str, Any]:
        edges = []
        for claim in self.store.claims(workspace_ref):
            relation = claim.get("relation") or {}
            if relation:
                edges.append(
                    {
                        "relation_claim_ref": claim["id"],
                        "type": relation.get("type"),
                        "subject": relation.get("subject"),
                        "object": relation.get("object"),
                    }
                )
        edges.sort(key=lambda row: row["relation_claim_ref"])
        return self._manifest(workspace_ref, "relation_graph", edges)

    @staticmethod
    def _manifest(workspace_ref: str, index_kind: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": new_id("IDX"),
            "record_type": "index_manifest",
            "workspace_ref": workspace_ref,
            "index_kind": index_kind,
            "algorithm": "runtime-derived-v1",
            "proof_role": "navigation_only",
            "generated_at": utc_now(),
            "row_count": len(rows),
            "rows": rows,
        }
