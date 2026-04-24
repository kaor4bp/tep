# Data Model

This document defines the minimal v1 record shapes. Field sets are intentionally
small; implementation can add optional fields if they preserve these semantics.

## Source Record

```json
{
  "id": "SRC-*",
  "record_type": "source",
  "source_kind": "user_message|file_quote|command_output|artifact_snapshot|url_snapshot|mcp_capture",
  "critique_status": "accepted|audited|rejected|unknown",
  "classification": {
    "input_class": "instruction|preference|domain_assertion|working_assumption|user_confirmation|correction|question|secret_or_credential|irrelevant|null",
    "source_class": "user|first_party_project|runtime_observation|test_or_check|official_doc|standard_or_paper|third_party_doc|issue_discussion|generated_backend|agent_synthesis|unknown",
    "document_kind": "message|source_code|test|config|log|trace|spec|api_reference|manual|paper|dataset|issue|pull_request|web_page|release_notes|binary_artifact|unknown",
    "evidence_role": "intent|assertion|quote|observation|policy|theory|implementation|approval|correction",
    "authority_scope": "task_intent|workspace_policy|project_behavior|external_fact|implementation_detail|none|unknown",
    "independence_key": "user:owner|repo:/path|domain:example.com|publisher:vendor|run:RUN-*|unknown"
  },
  "origin": {
    "kind": "user|file|command|artifact|url|mcp",
    "ref": "..."
  },
  "provenance": {
    "entity_ref": "file|url|message|artifact|run|unknown",
    "activity_ref": "capture operation or RUN-*",
    "responsible_agent": "user|AGENT-*|tool|publisher|unknown",
    "content_hash": "sha256:...|null",
    "locator": "path/url/message/range",
    "quote_span": "line/page/time range|null",
    "retrieved_at": "iso8601|null",
    "published_at": "iso8601|null"
  },
  "quote": "...",
  "artifact_ref": "ART-*|null",
  "project_refs": ["PRJ-*"],
  "workspace_ref": "WSP-*",
  "workspace_refs": ["WSP-*"],
  "captured_at": "iso8601"
}
```

Only accepted source records can provide material support for commitment paths.
For gates, acceptance is derived from valid `source_events.jsonl` audit events
and ledger source snapshots. `critique_status` on `SRC-*` is a cached current
view for lookup, not sufficient proof by itself.

Source acceptance is a runtime policy decision. The agent may capture and
classify a source, but capture alone does not make it accepted. In v1,
acceptance must be derived from classification, validation, user confirmation,
authority scope, source trust posture, and task scope.

Classification is canonical provenance, not truth. Source trust score is
runtime/index output and must not be stored as mutable truth on `SRC-*`.

## Source Acceptance Policy

`critique_status` records cached source acceptance state:

- `unknown`: captured but not evaluated.
- `audited`: structurally checked, but not commitment-ready.
- `accepted`: may contribute material support.
- `rejected`: must not support commitment.

Minimum v1 defaults:

| Source kind | Default | Accepted when |
| --- | --- | --- |
| `user_message` | `accepted` only for user intent, instructions, preferences, corrections, and explicit hypothesis confirmation | captured from current user message and classified by `input_class`/`evidence_role` |
| `file_quote` | `audited` | quote/range matches local file, content hash is stable, and applicability is in scope |
| `command_output` | `audited` | linked `RUN-*` belongs to current open ACT and output excerpt is captured |
| `artifact_snapshot` | `audited` | artifact hash/path is stable and source meaning is explicit |
| `url_snapshot` | `unknown` | content is snapshotted/quoted and source policy or user confirmation accepts it |
| `mcp_capture` | `unknown` | underlying source is classified, inspectable, and policy accepts the capture route |

Runtime, not the agent, applies these transitions. MCP may expose
`accept_source`/`reject_source` only as typed runtime operations that record
reason, actor, timestamp, and policy basis.

Acceptance/classification changes append an event to
`records/src/source_events.jsonl`:

```json
{
  "event_id": "SE-*",
  "event_prev": "SE-*|null",
  "source_ref": "SRC-*",
  "event_kind": "created|classified|accepted|rejected|superseded",
  "policy_basis": "user_intent|user_authority|quote_verified|run_capture|configured_source_policy|manual_reject",
  "actor_ref": "user|AGENT-*|runtime",
  "source_hash": "sha256:...",
  "classification_hash": "sha256:...",
  "event_prev_hash": "sha256:...|null",
  "event_log_hash": "sha256:...",
  "event_hash": "sha256:...",
  "reason": "...",
  "created_at": "iso8601"
}
```

Commitment validation must verify that an accepted source posture is supported
by a valid event chain for that `SRC-*`. A raw edit from `unknown` to
`accepted` without a matching audit event is untrusted.

`source_events.jsonl` is append-only and hash-chained. Manual deletion,
reordering, or rewriting of source events must be detected by replay. Source
events do not replace ledger seals; when a source supports a committed claim,
the ledger row snapshots the accepted event hash and source event log hash.

User input is accepted as provenance for what the user said. It does not become
theory/document support for an external fact unless the user is the configured
source of truth for that scope or explicitly confirms a hypothesis as usable.

Minimum user-input classification rules:

- `instruction` and `preference` support task intent, done criteria, and
  workspace policy claims.
- `domain_assertion` supports external facts only when the user is configured as
  authority for that scope; otherwise it is hypothesis/input evidence.
- `working_assumption` and `user_confirmation` can produce
  `user_confirmed_hypothesis` posture, not theory-proven truth.
- `correction` raises contradiction pressure and should trigger claim revision
  or relation creation.
- `secret_or_credential` must not store the raw secret in `quote`; runtime must
  redact or reject capture.

See [Source Classification And Dedup](source-classification.md) for the
classification axes and source-trust rules.

## Run Record

`RUN-*` records preserve command/test/tool execution evidence. They are audit
records, not proof by themselves.

```json
{
  "id": "RUN-*",
  "record_type": "run",
  "workspace_ref": "WSP-*",
  "project_refs": ["PRJ-*"],
  "agent_ref": "AGENT-*",
  "act_ref": "L-*|null",
  "action_kind": "inspect|test|protected_mutation|other",
  "command": "...",
  "command_hash": "sha256:...",
  "cwd": "...",
  "exit_code": 0,
  "output_artifact_ref": "ART-*|null",
  "captured_at": "iso8601"
}
```

A command result can support a claim only after a `SRC-*` cites the relevant
`RUN-*` output or artifact.

## Claim Record

```json
{
  "id": "CLM-*",
  "record_type": "claim",
  "claim_form": "assertion|relation|aggregate|policy",
  "claim_kind": "behavior|design|implementation|runtime_observation|applicability|policy|other",
  "statement": "...",
  "dedup_key": "sha256:...",
  "source_refs": ["SRC-*"],
  "support_refs": ["CLM-*"],
  "contradiction_refs": ["CLM-*"],
  "relation": null,
  "scope": {
    "workspace_ref": "WSP-*",
    "workspace_refs": ["WSP-*"],
    "project_refs": ["PRJ-*"],
    "task_refs": ["TASK-*"]
  },
  "semantic_hash": "sha256:...",
  "created_at": "iso8601",
  "updated_at": "iso8601"
}
```

The schema does not store truth status. Do not store `hypothesis`, `supported`,
`trusted`, or `contested` as CLM status. Runtime computes public labels and
trust posture from graph links, source types, source independence, contradiction
pressure, freshness, applicability, and current task context.

A claim with many runtime observations but no theory/document source and no
explicit user confirmation remains hypothesis-level in public posture. Runtime
evidence can make it useful for exploration or probes, but not automatically a
trusted fact.

`dedup_key` is a deterministic normalized key for exact duplicate blocking. It
is not a proof of semantic equivalence. Near-duplicate matches are index
candidates and require explicit reuse, merge, split, or `distinction_reason`.

## Relation Claim

Relation claims are normal `CLM-*` records with `claim_form=relation`.

```json
{
  "id": "CLM-*",
  "record_type": "claim",
  "claim_form": "relation",
  "statement": "PRJ-B retry strategy applies to PRJ-A queue worker.",
  "relation": {
    "type": "supports|contradicts|refines|applies_to_scope|analogous_to|differs_from|implements_pattern|depends_on|deduced_from|induced_from|abduced_from|assumed_from|possible_relation_between|analogized_from|challenges_freshness",
    "subject": "CLM-*",
    "object": "CLM-*",
    "bridge_scope": "general|task|object_sync|null",
    "task_refs": ["TASK-*"],
    "synced_object": {
      "kind": "field|api_route|schema|artifact|contract|object|unknown",
      "from": "...",
      "to": "..."
    },
    "bridge_limits": {"max_depth": 1}
  },
  "source_refs": ["SRC-*"],
  "semantic_hash": "sha256:..."
}
```

Any semantic edge between claims must be represented as a relation claim. Ledger
paths cannot jump from one claim to another unrelated claim without a relation.

For exact dedup, relation claims use a canonical key over relation type,
subject, object, directionality, and effective scope. Repeated bridge relations
should reuse the existing relation unless the agent supplies a real
`distinction_reason`.

Bridge relation scope:

- `general`: applicability exists, but project domains are not merged.
- `task`: applicability is limited to listed `TASK-*` records.
- `object_sync`: applicability is limited to a concrete synchronized object,
  field, route, schema, artifact, or contract.

Runtime must expose this bridge context in lookup and gate output so the agent
can see whether it has a broad analogy, a task-specific bridge, or a concrete
sync edge.

Relation claims are created by typed runtime operations such as `link_claims`,
usually at agent or user request. Runtime may suggest candidate relations from
curiosity/index signals, but a suggestion is not a relation claim until the
agent creates or selects the `CLM-*` relation and it passes normal source/trust
rules. Relations exist to make support, contradiction, applicability,
refinement, dependency, and analogy explicit instead of hiding those moves in
private agent reasoning.

Relation claims must not use a hypothesis as the basis for another hypothesis.
A relation may mention a hypothesis as a probe target, rejected route, or
freshness challenge record, but it cannot turn one unsupported claim into a new
unsupported claim. To continue, the agent must open a verification branch, add
accepted source material, ask the user, or ground the next step in a trusted or
user-confirmed claim.

## Hypothesis Inference Paths

Hypothesis is not stored as a CLM status, but it must be predictable in API
output. Runtime derives hypothesis posture from source support and relation
claims.

Minimum v1 inference kinds:

| Inference kind | Stored graph shape | Meaning | Commitment posture |
| --- | --- | --- | --- |
| `deduction` | relation `deduced_from` plus premise/rule claims | conclusion is claimed to follow from explicit premises/rules | only as trusted as the weakest required premise/rule; no formal solver implied |
| `induction` | relation `induced_from` plus sample/source refs | generalization from observed cases | scope-limited; needs independent/theory support before trusted use |
| `abduction` | relation `abduced_from` plus observation/anomaly refs | candidate explanation for observations | exploration/probe unless later supported |
| `fact_based_assumption` | relation `assumed_from` plus factual/user basis | working assumption based on known facts | must carry scope/risk; not proof by itself |
| `possible_relation` | relation `possible_relation_between` | candidate edge between facts | navigation/probe until converted to supported relation |
| `analogy` | relation `analogized_from` or `analogous_to` | inference from similar case/example | cross-scope use still needs applicability bridge |
| `freshness_challenge` | relation `challenges_freshness` from challenge claim to trusted target claim | trusted fact may be stale for current time/scope/version | exploration/probe; does not invalidate target until supported |
| `user_working_assumption` | accepted user source confirms hypothesis usability | user accepts it as usable assumption | usable only in the configured scope |
| `unclassified` | no sufficient source/relation path | runtime cannot explain the hypothesis type | blocked for final/protected commitment |

Rules:

- Runtime may expose `hypothesis`, `user_confirmed_hypothesis`, or
  `unclassified_hypothesis` as API labels, but these labels are derived.
- Creating or updating an under-supported claim should either include accepted
  source material or be followed by a relation that classifies its inference
  path.
- Hypothesis-on-hypothesis is forbidden. An under-supported claim cannot appear
  as the basis for creating another under-supported claim. Runtime must block
  the mutation or route it to an alternative verification branch.
- A hypothesis may trigger lookup, curiosity drilldown, source capture, user
  question, or ACT probe. Those operations may produce new evidence; the
  hypothesis itself is not evidence for the next hypothesis.
- A declared deduction is not a theorem proof. It is a typed reasoning claim
  whose premises, rule claim, and sources must be trusted before the conclusion
  can be trusted.
- Induction must preserve sample scope and source diversity. Repeated runtime
  observations from one independence key do not become independent induction.
- A possible relation is not an established relation. It must not bridge
  projects or support final/protected gates until supported and ledgered as an
  applicable relation claim.
- A freshness challenge against a trusted fact raises freshness pressure, not
  contradiction pressure by default. The challenged fact remains usable under
  its existing scope until the challenge is supported by accepted source
  material, a probe result, user confirmation, or a new claim update path.
- A freshness challenge forms an alternative verification branch from the
  trusted target fact. It is not permission to discard the trusted fact on the
  active commitment path.
- If a freshness challenge is confirmed, runtime should create a new supported
  claim path: update the `CLM-*` for future snapshots, create a replacement
  claim, or add a `contradicts`/`refines` relation as appropriate. Old
  `CLM@rev` ledger snapshots remain replayable.

## Claim Snapshot Rules

- `CLM-*` records are referenced without revisions outside ledger.
- Revisions exist only as ledger snapshots: `CLM@rev`.
- Ledger branches extend selected ledger predecessors, not the current mutable
  "latest CLM" file by implication.
- A ledger branch may snapshot the same `CLM-*` again as a later `rev` when the
  fact changed and the reasoning chain must be reconsidered.
- `semantic_hash` covers reasoning-material fields: statement, claim form,
  claim kind, relation payload, source refs, support refs, contradiction refs,
  and scope material when scope changes claim meaning.
- Formatting, timestamps, generated metadata, and task assignment metadata are
  not semantic.
- Ledger rows store the snapshot hash they used. That is what makes old
  reasoning replayable after the current `CLM-*` changes.
- Ledger rows store canonical snapshot material inline. V1 validation cannot
  rely on a hash alone.
- Ledger rows that commit a claim path store source snapshot hashes for the
  accepted `SRC-*` records used by that claim. If a cited source, acceptance
  event, or classification is manually rewritten later, ledger replay fails.
- No-op re-snapshotting does not unlock another `ACT`.

## Trust Posture

Trust posture is computed, not stored:

```json
{
  "claim_ref": "CLM-*",
  "ledger_snapshot": "CLM-*@rev|null",
  "trust_score": 0.0,
  "derived_label": "hypothesis|unclassified_hypothesis|trusted_fact|trusted_but_challenged|user_confirmed_hypothesis|contested|needs_theory_support",
  "inference_posture": {
    "kind": "deduction|induction|abduction|fact_based_assumption|possible_relation|analogy|freshness_challenge|user_working_assumption|unclassified|null",
    "basis_refs": ["CLM-*|SRC-*"],
    "relation_refs": ["CLM-*"],
    "predictability": "classified|ambiguous|missing_basis|not_applicable",
    "why": "..."
  },
  "runtime_support_count": 0,
  "theory_support_count": 0,
  "user_confirmation": "none|confirmed|confirmed_hypothesis",
  "source_diversity": {
    "accepted_source_count": 0,
    "independent_source_class_count": 0,
    "independence_keys": ["..."],
    "missing": ["official_doc|standard_or_paper|user_confirmation|test_or_check"]
  },
  "freshness_pressure": {
    "level": "none|low|medium|high|blocked",
    "challenge_refs": ["CLM-*"],
    "why": "..."
  },
  "contradiction_pressure": 0.0,
  "usable_for": ["exploration", "probe"]
}
```

These fields are API output, not persisted CLM fields.

Minimum v1 trust policy:

- Runtime support increases runtime confidence but does not by itself produce
  `trusted_fact`.
- `unclassified_hypothesis` means runtime has not found a sufficient source or
  inference path. It is exploration-only until repaired.
- `trusted_fact` requires theory/document support or accepted user
  confirmation, plus adequate source diversity for the configured scope, plus
  contradiction pressure below the configured threshold.
- `trusted_but_challenged` means the fact still has trusted support, but a
  freshness challenge is material for the current scope. This should route to
  revalidation before final/protected commitment when freshness matters.
- `user_confirmed_hypothesis` means the user accepted a hypothesis as a usable
  working assumption; it is not theory-proven.
- `contested` is returned when unresolved contradiction pressure is material for
  the current task.
- `needs_theory_support` is returned when runtime evidence is strong but no
  theory/document/user support exists.
- Repeated sources with the same `independence_key` saturate as repeated
  observation; they do not count as independent confirmation.

`usable_for` minimum rules:

| Derived condition | Usable for |
| --- | --- |
| runtime-only support | `exploration`, `probe` |
| user-confirmed hypothesis | `exploration`, `probe`, context-dependent `answer` |
| trusted fact | `exploration`, `probe`, `answer`, possible `protected_action` |
| contested | `exploration`, `probe`; not final/protected until resolved |

## CLM Dedup Rules

TEP v1 deduplicates claims without logical solvers.

Exact duplicate blocking uses `dedup_key`:

- assertion/policy key: normalized statement, claim form, claim kind, and
  effective semantic scope;
- relation key: relation type, subject, object, directionality, and effective
  semantic scope;
- aggregate/compiled key: compiled kind, query/intent, source set hash,
  underlying refs, and input policy.

Near-duplicate discovery is runtime/index output. It may use normalized text,
source overlap, relation overlap, embeddings, or shingle/MinHash-style sketches
to find candidates. It must not decide entailment. Ambiguous candidates require
one of:

- select and reuse existing `CLM-*`;
- create a relation claim explaining the difference;
- provide `distinction_reason`;
- split or merge claims with an explicit typed mutation.

Dedup candidates are navigation only. They cannot support a claim or ledger row.

## Aggregated And Compiled Claims

Aggregated and compiled records are still `CLM-*` records with
`claim_form=aggregate`. V1 does not introduce public `MODEL-*` or `FLOW-*`
record types. A model or flow is a compiled claim over trusted lower-level
claims.

They are created only by runtime compilation operations, not by a curator role
and not as free-form agent thoughts.

An aggregate or compiled claim must include reproducible metadata:

```json
{
  "aggregation": {
    "query": "...",
    "source_set_hash": "sha256:...",
    "sample_refs": ["CLM-*"],
    "underlying_refs": ["CLM-*"],
    "ledger_snapshot_refs": ["CLM-*@rev"],
    "generated_by": "runtime",
    "generated_at": "iso8601"
  },
  "compilation": {
    "compiled_kind": "summary|model|flow",
    "input_policy": "trusted_or_user_confirmed_only",
    "underlying_trust_set_hash": "sha256:...",
    "stale_when": ["underlying_changed", "trust_score_changed", "contradiction_added"],
    "refresh_operation": "compile_claim"
  }
}
```

Compiled model/flow claims are useful because they give the agent a compact
working picture, but they do not replace underlying object-level `CLM/SRC` in
proof paths. A compiled claim becomes stale when the source set, underlying
claims, trust posture, contradiction pressure, or ledger snapshots change.

Compilation rules:

- `compiled_kind=model` summarizes a mechanism, invariant, policy, or design
  theory from trusted/user-confirmed claims.
- `compiled_kind=flow` summarizes an ordered process, lifecycle, dependency
  path, or decision route from trusted/user-confirmed claims.
- Runtime-only hypotheses cannot be compiled into trusted model/flow claims.
- The runtime should suggest compilation when repeated lookup/TAP/ledger use
  shows a stable cluster that agents keep rediscovering.
- Compilation is a typed mutation (`compile_claim`) and should be offered as a
  mechanical valid move; the agent should not need to invent it.

## Map Record

`MAP-*` records are durable navigation cells. They are not proof.

```json
{
  "id": "MAP-*",
  "record_type": "map",
  "proof_role": "navigation_only",
  "level": "L1|L2|L3",
  "map_kind": "evidence_patch|mechanism|pattern|risk|policy|code_area|task_situation|strategy|open_frontier|retrospective",
  "lens": "topology|topic|scope|code|activity|inquiry|task|mixed",
  "summary": "...",
  "scope": {
    "workspace_ref": "WSP-*",
    "project_refs": ["PRJ-*"],
    "task_refs": ["TASK-*"]
  },
  "anchor_refs": ["CLM-*|SRC-*|RUN-*|CIX-*|MAP-*|TASK-*"],
  "derived_from_refs": ["CLM-*|SRC-*|RUN-*|CIX-*|MAP-*"],
  "source_set_hash": "sha256:...",
  "up_map_refs": ["MAP-*"],
  "down_map_refs": ["MAP-*"],
  "adjacent_map_refs": ["MAP-*"],
  "refines_map_refs": ["MAP-*"],
  "supersedes_map_refs": ["MAP-*"],
  "contradicts_map_refs": ["MAP-*"],
  "entries": [
    {
      "entry_ref": "MAP-*/entry/*",
      "entry_kind": "candidate|submap|claim|source|index",
      "ref": "MAP-*|CLM-*|SRC-*|IDX-*|CIX-*|null",
      "signal_kind": "tap|cold_zone|bridge|contradiction|missing_relation|backend|analogy|spatial_gap|probe",
      "link_state": "established|candidate|expected_missing|tested_absent|rejected|unknown|null",
      "why_suggested": "...",
      "required_drilldown": [{"kind": "record|file|command|url", "ref": "..."}],
      "valid_tools": ["map_view|map_drilldown|record_detail|create_source|link_claims|open_probe|defer_task"]
    }
  ],
  "route_hints": [
    {
      "route_kind": "proof_drilldown|source_capture|relation_bridge|probe|zoom",
      "route_refs": ["MAP-*|CLM-*|SRC-*|RUN-*|CIX-*"],
      "required_tool": "map_drilldown|record_detail|create_source|link_claims|open_probe",
      "route_is_proof": false
    }
  ],
  "signals": {},
  "map_is_proof": false,
  "created_at": "iso8601",
  "updated_at": "iso8601"
}
```

Map entries can point at child maps or records, but the entry itself is still
navigation. `MAP-*`, `IDX-*`, `CIX-*`, and `MAP-*/entry/*` must not appear in
claim `source_refs`, `support_refs`, `contradiction_refs`, or ledger proof
paths.

Map semantic changes create a new cell linked through `refines_map_refs` or
`supersedes_map_refs`. Pressure/activity changes may update `signals` in place
when anchors, route hints, source set, level, kind, lens, and summary meaning
remain unchanged.

## TAP Event

TAP is usage pressure, not popularity-as-truth. It should be recorded as an
append-only event stream and summarized into map signals.

```json
{
  "id": "TAP-*",
  "record_type": "tap_event",
  "ref": "CLM-*|SRC-*|MAP-*|CIX-*",
  "event_kind": "retrieved|opened|cited|decisive|updated|challenged|contradicted",
  "workspace_ref": "WSP-*",
  "project_refs": ["PRJ-*"],
  "task_ref": "TASK-*|null",
  "agent_ref": "AGENT-*|null",
  "ledger_ref": "L-*|null",
  "weight": 1.0,
  "recorded_at": "iso8601"
}
```

Derived TAP summaries must include decay settings and scope. A hot fact is not
trusted because it is hot; heat only affects navigation pressure.

## Task Record

```json
{
  "id": "TASK-*",
  "record_type": "task",
  "workspace_ref": "WSP-*",
  "project_refs": ["PRJ-*"],
  "title": "...",
  "goal": "...",
  "done_criteria": ["..."],
  "blocker_refs": ["CLM-*"],
  "parent_task_ref": "TASK-*|null",
  "child_task_refs": ["TASK-*"],
  "deferred_until": "iso8601|null",
  "status": "active|deferred|blocked|done|archived",
  "created_at": "iso8601",
  "updated_at": "iso8601"
}
```

`TASK-*` does not store canonical agent participants. Participant views are
derived from `AGENT-*` attachments, ledger rows, and captures.

Any task can be decomposed into subtasks recursively. A task may also be
deferred and resumed later without losing its claim links, done criteria, or
ledger history.

Task lifecycle mutations:

- `create_task`: create active task with goal and done criteria.
- `decompose_task`: add child tasks and keep parent as coordination node.
- `defer_task`: set `status=deferred`, reason, and optional resume condition.
- `resume_task`: restore `status=active`.
- `block_task` / `unblock_task`: manage blocker refs.
- `complete_task`: allowed only when required children are done/deferred by
  explicit decision, blockers are resolved, and final support path is valid.
