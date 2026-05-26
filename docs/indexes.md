# Indexes

Indexes are runtime navigation aids. They are generated from canonical records
and never count as proof.

TEP 0.12 treats indexes as rebuildable server/cache projections. They may live
in Valkey, TerminusDB-derived projections, or generated artifacts, but their
location is not part of the proof contract.

Current index kinds:

- `trust_score`: derived CLM posture, aggregate priority, usability labels
- `source_class`: source classification and critique status
- `relation_graph`: relation CLM edges
- `tags_context`: CLM tags, context, and trigger phrases for ambient brief
  retrieval

Example:

```json
{
  "id": "IDX-*",
  "record_type": "index_manifest",
  "task_ref": "task_*",
  "project_refs": ["prj_*"],
  "index_kind": "trust_score",
  "algorithm": "runtime-derived-v2",
  "proof_role": "navigation_only",
  "rows": [
    {
      "claim_ref": "clm_*",
      "claim_form": "aggregate",
      "trust_score_bps": 7200,
      "derived_label": "trusted_aggregate",
      "usable_for": ["exploration", "probe", "answer"]
    }
  ]
}
```

Agents may use indexes to find likely useful facts. Before final support, they
must inspect the selected CLM/REL/SRC chain and run the chain checker.
