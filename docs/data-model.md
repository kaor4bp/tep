# Data Model

These are minimal shapes, not exhaustive schemas.

## Project

```json
{
  "id": "prj_*",
  "record_type": "project",
  "project_type": "repo|domain|service|aggregate|example|reference",
  "name": "...",
  "roots": ["/path"],
  "parent_project_refs": ["prj_*"],
  "status": "active"
}
```

## Task

```json
{
  "id": "task_*",
  "record_type": "task",
  "goal": "...",
  "project_refs": ["prj_*"],
  "parent_task_ref": null,
  "child_task_refs": [],
  "claim_refs": [],
  "agent_refs": [],
  "status": "active|deferred|done"
}
```

## Source

```json
{
  "id": "src_*",
  "record_type": "source",
  "source_kind": "user_message|file_quote|source_excerpt|command_output|command_summary",
  "critique_status": "accepted|audited|unknown|rejected",
  "classification": {
    "input_class": "instruction|provided_context|observation|user_confirmation|working_assumption|unknown",
    "source_class": "user|official_doc|standard_or_paper|first_party_project|runtime_observation|test_or_check|unknown",
    "document_kind": "message|markdown|source_code|command_output|unknown",
    "evidence_role": "intent|assertion|contract|observation",
    "authority_scope": "task_intent|project_behavior|external_fact|implementation_detail|unknown",
    "independence_key": "..."
  },
  "origin": {"kind": "...", "ref": "..."},
  "provenance": {"content_hash": "sha256:...", "locator": "...", "quote_span": null},
  "quote": "...",
  "project_refs": ["prj_*"],
  "task_refs": ["task_*"]
}
```

Accepted source transitions are recorded in global `source_events.jsonl`.

## Document

```json
{
  "id": "doc_*",
  "record_type": "document",
  "doc_kind": "jira_issue|gitlab_merge_request|rancher_workload_snapshot|confluence_page|markdown|config|cluster_inventory|unknown",
  "title": "...",
  "remote_object": {"provider": "jira", "site_url": "...", "key": "..."},
  "latest_version": 2,
  "latest_content_hash": "sha256:...",
  "versions": [
    {
      "version": 1,
      "content_hash": "sha256:...",
      "raw_path": "documents/doc_*/v0001/raw.json",
      "normalized_path": "documents/doc_*/v0001/normalized.json",
      "readable_path": "documents/doc_*/v0001/readable.md"
    }
  ],
  "refresh_policy": {"mode": "manual|daily|weekly", "stale_after_days": 14}
}
```

`doc_*` is navigation and versioned context, not proof. A claim may not cite a
`doc_*` directly. It must cite a `src_*` excerpt extracted from a concrete
document version, or an `inp_*` user input. This keeps long mutable documents
available for review and diffing without letting broad documents masquerade as
evidence.

Document-backed `src_*` records should include:

```json
{
  "doc_ref": "doc_*",
  "doc_version": 2,
  "doc_path": "documents/doc_*/v0002/readable.md",
  "span": {"start_line": 10, "end_line": 18},
  "document_content_hash": "sha256:..."
}
```

If `doc.latest_version` is newer than `src.doc_version`, runtime should mark
the source as stale, show a warning during proof review, and apply a trust score
penalty until the source is refreshed.

Document storage may contain orphan snapshot files if a process dies after file
write but before record commit. `cleanup_document_snapshots` may delete only
paths under `documents/doc_*` that are not referenced by any `doc_*` record or
listed document version. It must never delete valid document versions.

## Claim

```json
{
  "id": "clm_*",
  "record_type": "claim",
  "claim_form": "assertion|relation|aggregate",
  "claim_kind": "other",
  "statement": "...",
  "source_refs": ["src_*|inp_*"],
  "support_refs": ["clm_*"],
  "contradiction_refs": ["clm_*"],
  "relation": null,
  "aggregation": null,
  "context": "short retrieval context",
  "tags": ["testing", "coding-guidelines"],
  "trigger_phrases": ["writing tests"],
  "scope": {
    "project_refs": ["prj_*"],
    "task_refs": ["task_*"]
  },
  "semantic_hash": "sha256:..."
}
```

No trust status is stored. Runtime derives labels and scores from sources and
relations.

`source_refs` may point to `src_*` evidence or captured `inp_*` user input.
Use `inp_*` only for what the user said, approved, corrected, requested, or
accepted as a working assumption. A design-decision CLM that claims "the user
confirmed X" must reference the captured `inp_*`; otherwise runtime should
treat it as unsupported agent memory.

`context`, `tags`, and `trigger_phrases` are retrieval hints for brief/lookup
and indexes. They do not increase trust by themselves.

## Relation Claim

Historical note: older docs represented relations as `claim_form="relation"`.
In 0.12, relations should be `rel_*` graph records. Relation-like CLM text can
exist as a human-readable fact, but graph traversal and proof checks should use
`rel_*` edges.

```json
{
  "id": "rel_*",
  "record_type": "relation",
  "type": "supports|contradicts|depends_on|possible_relation_between|challenges_freshness|...",
  "from_ref": "clm_*",
  "to_ref": "clm_*",
  "scope_refs": ["task_*", "prj_*"],
  "quote": "why this edge exists",
  "evidence_refs": ["src_*"]
}
```

Legacy shape:

```json
{
  "claim_form": "relation",
  "relation": {
    "type": "supports|contradicts|depends_on|possible_relation_between|challenges_freshness|...",
    "subject": "clm_*",
    "object": "clm_*",
    "bridge_scope": "task|object_sync|general",
    "synced_object": {},
    "bridge_limits": {}
  }
}
```

## Aggregate Claim

```json
{
  "claim_form": "aggregate",
  "aggregation": {
    "underlying_refs": ["clm_*", "clm_*"],
    "limits": "Only applies to parser validation errors.",
    "method": "agent_synthesis"
  }
}
```

The aggregate's `support_refs` should include all `underlying_refs`.

## Ledger Row

Historical note: sealed ledger rows were the 0.9/0.10 proof mechanism. In 0.12,
proof should be modeled as selected `chain_*` routes over CLM/REL/SRC/INP/RUN
records. Keep this shape only for reading legacy/quarantined material.

```json
{
  "id": "l_000001",
  "prev": null,
  "append_prev": null,
  "kind": "claim|relation|act|capture|close_act",
  "ref": "clm_*",
  "rev": 1,
  "act_ref": "l_000001",
  "ledger_context_hash": "sha256:...",
  "task_scope_hash": "sha256:...",
  "claim_snapshot": {"ref": "clm_*", "rev": 1, "canonical_payload": {}},
  "claim_snapshot_hash": "sha256:...",
  "source_snapshots": [],
  "source_set_hash": "sha256:...",
  "prev_state_hash": "sha256:...",
  "append_log_hash": "sha256:...",
  "payload_hash": "sha256:...",
  "pow": {"nonce": "...", "difficulty_bits": 18, "work_hash": "sha256:..."},
  "seal": "ed25519:..."
}
```

CLM revision is ledger-local. Outside ledger rows, use bare `clm_*`.
`act_ref` appears on `capture` and `close_act` rows to bind them to the ACT row
they are resolving.

## Chain

```json
{
  "id": "chain_*",
  "record_type": "chain",
  "target_ref": "clm_*|task_*|null",
  "purpose": "finish|action|answer|reuse|challenge",
  "steps": [
    {
      "rule": "source_attribution|observation_supports_claim|deduction|induction|applicability_bridge|contradiction|freshness_challenge|aggregation|decision_support",
      "premises": ["clm_*", "rel_*", "src_*", "inp_*", "task_*", "snap_*"],
      "conclusion": "clm_*|task_*|note_*",
      "bindings": {
        "quote_hash": "sha256:...",
        "span": {"start": 120, "end": 310}
      },
      "constraints": {},
      "warnings": []
    }
  ],
  "score_cache": {
    "shape": 0,
    "coverage": 0,
    "counter_pressure": 0,
    "staleness_risk": 0
  },
  "gaps": [],
  "counterfact_refs": ["clm_*"],
  "created_at": "iso8601"
}
```

`chain_*` is a selected route, not a replacement for the global relation graph.
Most chains can be prepared dynamically; persist them when they support finish,
user review, comparison, or reusable synthesized CLM.
`prepare_finish` may store a compact `finish_chain_review` on `task_*` after a
successful closure. That review is derived metadata (`status`, `label`, score
components, gap codes, warning codes), not a canonical proof record. Persist a
full `chain_*` only when the route itself needs later inspection or reuse.

The rule registry is typed and deterministic:

- `source_attribution`: `src_*|inp_* -> clm_*`, requires quote/span/source binding.
- `observation_supports_claim`: runtime/source observation -> `clm_*`, requires
  run/source binding.
- `deduction`: `clm_*|rel_* -> clm_*`.
- `induction`: two or more observations/CLM -> probabilistic `clm_*`.
- `applicability_bridge`: `clm_*|rel_*|task_* -> clm_*|task_*`, requires explicit
  scope/bridge/relation binding.
- `contradiction`: `clm_*|rel_* -> clm_*`, requires counter/relation binding.
- `freshness_challenge`: `clm_*|rel_*|src_*|snap_* -> clm_*`, requires newer
  source/snapshot/relation binding.
- `aggregation`: child `clm_* -> aggregate clm_*`, requires underlying refs.
- `decision_support`: `clm_*|src_*|inp_*|rel_* -> task_*|clm_*|note_*`.

`score_cache` is derived output. TEP may store it for UI/performance, but
validators must be able to recompute it from canonical graph records.

Chain validation is deliberately structural. A chain is weakened when it builds
an unsupported conclusion from unsupported CLM, skips a required relation
premise, relies only on runtime output, touches stale facts, or crosses
counterfact relations. These are warnings/gaps for repair, not hidden status
fields on CLM.
