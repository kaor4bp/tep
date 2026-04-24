# Runtime Indexes

TEP computes a lot at runtime: claim trust posture, source trust posture, graph
reachability, source acceptance, dedup candidates, map pressure, ledger heads,
and backend candidates. V1 therefore needs indexes, but indexes are never proof.

An index is a rebuildable projection over canonical records. If an index and
canonical records disagree, canonical records win and the index is stale.

## Required Index Classes

Minimum v1 indexes:

- `trust_score`: derived trust posture and `usable_for` by `CLM-*` and scope.
- `source_trust`: derived source posture by `SRC-*`, scope, and source policy.
- `claim_graph`: adjacency over support, contradiction, relation, aggregate,
  compiled model, and compiled flow claims.
- `source_acceptance`: accepted/audited/rejected source lookup derived from
  `SRC-*` plus source event replay.
- `dedup`: exact `dedup_key` lookup and near-duplicate candidate retrieval.
- `ledger_heads`: current valid heads, open ACT, and invalid rows by `AGENT-*`.
- `map_coverage`: which `CLM/SRC/RUN/CIX/TASK` records are covered by `MAP-*`.
- `tap_heat`: decayed TAP summaries by record, task, project, and agent.
- `backend`: generated search/index projections such as `CIX-*`.

## Index Manifest

Every index family has an `IDX-*` manifest:

```json
{
  "id": "IDX-*",
  "record_type": "index_manifest",
  "index_kind": "trust_score|source_trust|claim_graph|source_acceptance|dedup|ledger_heads|map_coverage|tap_heat|backend",
  "workspace_ref": "WSP-*",
  "project_refs": ["PRJ-*"],
  "source_refs": ["CLM-*|SRC-*|RUN-*|MAP-*|TAP-*|L-*|CIX-*"],
  "source_set_hash": "sha256:...",
  "build_hash": "sha256:...",
  "freshness": "fresh|stale|partial|invalid",
  "generated_at": "iso8601",
  "expires_at": "iso8601|null"
}
```

`IDX-*` is navigation/runtime acceleration only. It must not appear in claim
support, source refs, contradiction refs, or ledger proof paths.

## Trust Score Index

The `trust_score` index exists because computing trust posture from scratch on
every lookup will be too expensive.

It may store:

```json
{
  "claim_ref": "CLM-*",
  "workspace_ref": "WSP-*",
  "project_refs": ["PRJ-*"],
  "task_refs": ["TASK-*"],
  "trust_score": 0.0,
  "derived_label": "hypothesis|unclassified_hypothesis|trusted_fact|trusted_but_challenged|user_confirmed_hypothesis|contested|needs_theory_support",
  "inference_posture": {
    "kind": "deduction|induction|abduction|fact_based_assumption|possible_relation|analogy|freshness_challenge|user_working_assumption|unclassified|null",
    "predictability": "classified|ambiguous|missing_basis|not_applicable",
    "relation_refs": ["CLM-*"]
  },
  "source_diversity": {
    "accepted_source_count": 0,
    "independent_source_class_count": 0,
    "missing": ["official_doc|standard_or_paper|user_confirmation|test_or_check"]
  },
  "freshness_pressure": {
    "level": "none|low|medium|high|blocked",
    "challenge_refs": ["CLM-*"]
  },
  "usable_for": ["exploration", "probe"],
  "input_hash": "sha256:...",
  "computed_at": "iso8601"
}
```

Rules:

- `trust_score` is derived from canonical `SRC-*`, `CLM-*`, relation graph,
  source acceptance, source trust posture, source diversity, ledger snapshots,
  contradiction pressure, freshness, and applicability.
- Runtime-only observations can raise runtime confidence but cannot by
  themselves produce `trusted_fact`.
- Hypothesis labels must include derived inference posture. `unclassified`
  hypotheses are allowed for exploration, but not final/protected commitment.
- Freshness challenges against trusted facts produce `freshness_pressure` and
  may derive `trusted_but_challenged`; they do not erase the target fact's
  existing support.
- Repeated support with the same source independence key saturates as repeated
  observation; it does not count as independent confirmation.
- A stale trust index cannot satisfy final/protected/task-done gates.
- `validate` or `status` must report stale/partial indexes before commitment.

## Source Trust Index

The `source_trust` index computes source posture without mutating `SRC-*`.

It may store:

```json
{
  "source_ref": "SRC-*",
  "workspace_ref": "WSP-*",
  "project_refs": ["PRJ-*"],
  "source_trust_score": 0.0,
  "derived_label": "unrated|low|medium|high|blocked",
  "classification": {
    "input_class": "instruction|preference|domain_assertion|working_assumption|user_confirmation|correction|question|secret_or_credential|irrelevant|null",
    "source_class": "user|first_party_project|runtime_observation|test_or_check|official_doc|standard_or_paper|third_party_doc|issue_discussion|generated_backend|agent_synthesis|unknown",
    "document_kind": "message|source_code|test|config|log|trace|spec|api_reference|manual|paper|dataset|issue|pull_request|web_page|release_notes|binary_artifact|unknown",
    "authority_scope": "task_intent|workspace_policy|project_behavior|external_fact|implementation_detail|none|unknown",
    "independence_key": "..."
  },
  "factors": {
    "critique_status": "accepted|audited|rejected|unknown",
    "content_hash_present": true,
    "quote_or_span_verified": true,
    "freshness": "fresh|stale|unknown",
    "scope_fit": "local|bridged|foreign|unknown",
    "known_contradictions": 0
  },
  "usable_for": ["exploration", "probe"],
  "input_hash": "sha256:...",
  "computed_at": "iso8601"
}
```

Rules:

- Canonical `SRC-*` stores classification and provenance; `source_trust_score`
  is rebuildable index output.
- `source_trust` is an input to claim `trust_score`, not a proof object.
- `generated_backend`, `agent_synthesis`, maps, and embeddings stay
  navigation-only until the underlying material is captured as `SRC-*`.
- Stale, contradicted, unverified, or scope-foreign sources lower posture and
  should produce `valid_moves` for recapture, bridge relation, or user
  confirmation.

## Dedup Index

The `dedup` index prevents obvious duplicate `CLM-*` growth and retrieves
possible near duplicates.

It may store:

```json
{
  "claim_ref": "CLM-*",
  "dedup_key": "sha256:...",
  "claim_form": "assertion|relation|aggregate|policy",
  "scope_hash": "sha256:...",
  "sketch_hash": "sha256:...",
  "near_duplicate_refs": [
    {
      "claim_ref": "CLM-*",
      "score": 0.0,
      "basis": ["normalized_text|source_overlap|relation_overlap|embedding|shingle_sketch"]
    }
  ],
  "input_hash": "sha256:...",
  "computed_at": "iso8601"
}
```

Rules:

- Exact `dedup_key` matches block duplicate creation in the same effective
  scope.
- Near-duplicate entries are candidates only. They cannot justify a claim,
  relation, final answer, protected action, or ledger row.
- No solver-based equivalence is implied. Runtime must ask for reuse,
  `distinction_reason`, relation creation, split, or `merge_claims`.
- Ledger snapshots remain historical facts even after a duplicate merge.

## Invalidation

Indexes become stale when:

- a referenced `SRC-*`, `CLM-*`, `RUN-*`, `MAP-*`, `TAP-*`, `CIX-*`, or ledger
  row changes
- a source audit event is appended or fails replay
- source acceptance changes
- source event log hash changes
- source classification, source trust factors, or source policy changes
- claim relation graph changes
- claim `dedup_key` or near-duplicate inputs change
- a compiled claim is created/refreshed/staled
- project membership changes
- backend source hashes change
- configured freshness window expires

`refresh_index` may rebuild all indexes or a bounded family/scope. Failed
refresh writes nothing.

## RISC Integration

Runtime responses should use `index_pressure` and `valid_moves` to keep the
agent from thinking through mechanical validity while preserving strategic
choice. Examples:

```json
{
  "index_pressure": {
    "level": "low|medium|high|blocked",
    "stale_indexes": ["trust_score"],
    "why": "CLM graph changed after trust_score build."
  },
  "valid_moves": [
    {
      "priority": 10,
      "tool": "refresh_runtime",
      "operation_kind": "refresh_index",
      "why": "Recompute trust_score before protected mutation.",
      "writes": true,
      "requires_user": false,
      "expected_output": "fresh trust_score IDX-*"
    }
  ]
}
```

The agent should not decide how to recompute trust. The runtime owns the
mechanics and exposes valid refresh/repair choices.
