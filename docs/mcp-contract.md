# MCP Contract

MCP is the normal agent interface for TEP v1. It is read/write, but all writes
are typed protocol mutations. There is no raw JSON write tool.

## RISC Shape

The public contract should stay RISC-style: a small set of predictable
operations with typed `operation_kind` values. An implementation may expose
friendly aliases such as `create_source` or `open_probe`, but they must route
through these primitives:

- `brief`: orient the agent.
- `lookup`: retrieve facts, maps, and index candidates.
- `detail`: inspect one record or route.
- `status`: inspect task, ledger, map, or index posture.
- `validate`: replay or check protocol state.
- `mutate_record`: create/update/link non-ledger records.
- `append_ledger`: append sealed reasoning rows.
- `probe_step`: open/preflight/capture/close ACT work.
- `refresh_runtime`: refresh maps, TAP summaries, claim/source trust indexes,
  dedup indexes, or backend indexes.

This keeps the runtime predictable while still allowing clear typed operations
such as `operation_kind=compile_claim`.

## Guided Choice

MCP should guide the agent without turning the protocol into a single forced
script. Every meaningful response returns valid moves the agent may choose
from. The runtime decides which operations are valid; the agent chooses which
valid operation best fits the task.

Rules:

- Successful responses include `valid_moves` when there is useful follow-up
  work, not only when something is blocked.
- Failed responses include `repair_options`, a list of valid recovery moves.
- Pressure blocks explain why a move is useful or why a commitment is blocked.
- Moves are ordered by runtime priority, but priority is guidance, not a
  command.
- A blocked commitment may still expose non-commitment moves such as lookup,
  source capture, task defer, or user question.
- The agent must not invent raw filesystem writes or unsupported protocol
  shortcuts when a valid move is available.

Move shape:

```json
{
  "priority": 10,
  "tool": "mutate_record|append_ledger|probe_step|refresh_runtime|lookup|detail|validate|status",
  "operation_kind": "...",
  "why": "...",
  "writes": false,
  "requires_user": false,
  "expected_output": "..."
}
```

## Common Response Envelope

Every serious tool response includes:

```json
{
  "ok": true,
  "data": {},
  "ledger_pressure": {
    "level": "none|low|medium|high|blocked",
    "current_agent": "AGENT-*|null",
    "ledger_valid": true,
    "current_head": "L-*|null",
    "open_act": "L-*|null",
    "level_reason": "...",
    "valid_moves": []
  },
  "index_pressure": [],
  "source_pressure": [],
  "claim_pressure": [],
  "dedup_pressure": [],
  "valid_moves": [
    {
      "priority": 10,
      "tool": "mutate_record|append_ledger|probe_step|refresh_runtime|lookup|detail|validate",
      "operation_kind": "...",
      "why": "...",
      "writes": false,
      "requires_user": false,
      "expected_output": "..."
    }
  ],
  "repair_options": []
}
```

Failed mutation response:

```json
{
  "ok": false,
  "error": {
    "code": "validation_failed|ownership_mismatch|ledger_invalid|needs_source|source_unclassified|source_not_accepted|needs_source_diversity|needs_relation|navigation_as_proof|duplicate_claim|dedup_conflict|open_act_exists",
    "message": "...",
    "details": {}
  },
  "ledger_pressure": {},
  "index_pressure": [],
  "source_pressure": [],
  "claim_pressure": [],
  "dedup_pressure": [],
  "valid_moves": [],
  "repair_options": [
    {
      "priority": 10,
      "tool": "lookup|detail|mutate_record|append_ledger|probe_step|refresh_runtime|validate",
      "operation_kind": "...",
      "why": "valid repair operation",
      "writes": false,
      "requires_user": false,
      "expected_output": "..."
    }
  ]
}
```

Failed mutations write nothing.

## Read Tools

The names below are typed aliases/operation kinds. They are not independent
protocol primitives.

`start_agent_thread`
: Resolve or create the current `AGENT-*`, bind it to a key fingerprint and
thread reference, and return initial task, scope, and ledger posture.

`brief_current_context`
: Return the current briefing: workspace, related projects, active task/subtask,
done criteria, blockers, agent working context, selected facts, trust posture,
ledger posture, and curiosity pressure.

Briefing is also an adoption mechanism. It should make using TEP cheaper than
rediscovering context manually by surfacing the current task, selected facts,
open blockers, source gaps, valid moves, and reusable compiled flows.

Required response shape:

```json
{
  "workspace": {"ref": "WSP-*", "name": "..."},
  "projects": [
    {"ref": "PRJ-*", "role": "primary|dependency|example|reference|comparison"}
  ],
  "task": {
    "active_task_path": ["TASK-*"],
    "state": "none|active|deferred|blocked|done",
    "goal": "...",
    "done_criteria": ["..."],
    "blocker_refs": ["CLM-*"],
    "deferred_work": ["TASK-*"]
  },
  "agent": {
    "ref": "AGENT-*",
    "selected_ledger_head": "L-*|null",
    "open_act": "L-*|null",
    "selected_claim_refs": ["CLM-*"],
    "curiosity": {
      "current_map_ref": "MAP-*|null",
      "breadcrumbs": ["MAP-*"],
      "active_lens": "topology|topic|scope|code|activity|inquiry|task|mixed|null",
      "deferred_candidate_refs": ["MAP-*/entry/*"]
    },
    "current_assumptions": []
  },
  "facts": [
    {"ref": "CLM-*", "trust_posture": {}, "scope_origin": "primary_project"}
  ],
  "curiosity_pressure": [],
  "compilation_pressure": [
    {
      "level": "none|low|medium|high|blocked",
      "compiled_kind": "summary|model|flow",
      "cluster_refs": ["CLM-*"],
      "why": "...",
      "valid_moves": [
        {
          "priority": 20,
          "tool": "mutate_record",
          "operation_kind": "compile_claim",
          "why": "Create a compact reusable aggregate from a stable trusted cluster.",
          "writes": true,
          "requires_user": false,
          "expected_output": "CLM-* with claim_form=aggregate"
        }
      ]
    }
  ],
  "index_pressure": [
    {
      "level": "none|low|medium|high|blocked",
      "stale_indexes": ["trust_score|source_trust|claim_graph|source_acceptance|dedup|ledger_heads|map_coverage|tap_heat|backend"],
      "why": "...",
      "valid_moves": [
        {
          "priority": 10,
          "tool": "refresh_runtime",
          "operation_kind": "refresh_index",
          "why": "Recompute stale runtime projections before commitment.",
          "writes": true,
          "requires_user": false,
          "expected_output": "fresh IDX-* projection"
        }
      ]
    }
  ],
  "source_pressure": [
    {
      "level": "none|low|medium|high|blocked",
      "source_refs": ["SRC-*"],
      "why": "source needs classification, acceptance, trust refresh, or independent confirmation",
      "valid_moves": [
        {
          "priority": 10,
          "tool": "mutate_record",
          "operation_kind": "capture_source_excerpt",
          "why": "Document facts require exact quote/span evidence.",
          "writes": true,
          "requires_user": false,
          "expected_output": "excerpt SRC-*"
        },
        {
          "priority": 20,
          "tool": "lookup",
          "operation_kind": "lookup_facts",
          "why": "Find corroborating or conflicting claims.",
          "writes": false,
          "requires_user": false,
          "expected_output": "related CLM-* candidates"
        },
        {
          "priority": 30,
          "tool": "refresh_runtime",
          "operation_kind": "refresh_source_trust",
          "why": "Recompute derived source posture.",
          "writes": true,
          "requires_user": false,
          "expected_output": "fresh source_trust index entry"
        }
      ]
    }
  ],
  "dedup_pressure": [
    {
      "level": "none|low|medium|high|blocked",
      "claim_refs": ["CLM-*"],
      "why": "exact duplicate or near-duplicate candidate found",
      "valid_moves": [
        {
          "priority": 10,
          "tool": "mutate_record",
          "operation_kind": "select_existing_claim",
          "why": "Reuse an exact or sufficient existing claim.",
          "writes": false,
          "requires_user": false,
          "expected_output": "existing CLM-* selected"
        },
        {
          "priority": 20,
          "tool": "mutate_record",
          "operation_kind": "merge_claims",
          "why": "Confirm duplicates and keep a canonical claim.",
          "writes": true,
          "requires_user": false,
          "expected_output": "canonical CLM-* and refreshed dedup index"
        },
        {
          "priority": 30,
          "tool": "mutate_record",
          "operation_kind": "link_claims",
          "why": "Represent semantic difference or relationship explicitly.",
          "writes": true,
          "requires_user": false,
          "expected_output": "relation CLM-*"
        },
        {
          "priority": 40,
          "tool": "mutate_record",
          "operation_kind": "update_claim",
          "why": "Revise the current claim instead of creating a duplicate.",
          "writes": true,
          "requires_user": false,
          "expected_output": "updated CLM-*"
        }
      ]
    }
  ],
  "ledger_pressure": {},
  "valid_moves": [
    {
      "priority": 10,
      "tool": "lookup|detail|mutate_record|probe_step|refresh_runtime",
      "operation_kind": "...",
      "why": "...",
      "writes": false,
      "requires_user": false,
      "expected_output": "..."
    }
  ]
}
```

`lookup_facts`
: Search facts under workspace scope, including current project, workspace
domain stock, dependencies, examples, and references. Returns source drilldown
routes and bridge requirements.
Lookup should prefer relevant aggregate `CLM-*` records over their children so
agents receive a compact working handle first. Aggregates remain expandable:
results include `aggregate_drilldown.underlying_refs`, and agents can call
`record_detail` on the aggregate or any child `CLM-*` when they need the exact
leaf evidence.

`curiosity_view`
: Return TAP, cold zones, bridge candidates, contradiction candidates, backend
navigation candidates, and suggested probes.

Required response shape:

```json
{
  "proof_role": "navigation_only",
  "partial_view": true,
  "current_map_ref": "MAP-*|null",
  "maps": [
    {
      "ref": "MAP-*",
      "level": "L1|L2|L3",
      "map_kind": "...",
      "lens": "topology|topic|scope|code|activity|inquiry|task|mixed",
      "summary": "...",
      "up_map_refs": ["MAP-*"],
      "down_map_refs": ["MAP-*"],
      "route_hints": []
    }
  ],
  "candidates": [
    {
      "candidate_ref": "MAP-*/entry/*",
      "state": "suggested|inspected|deferred|converted_to_source|converted_to_relation|opened_act|rejected",
      "outcome_refs": ["SRC-*|CLM-*|L-*|TASK-*"],
      "proof_usable_now": false,
      "valid_tools": ["map_drilldown|record_detail|create_source|link_claims|open_probe"]
    }
  ],
  "frontier": {
    "collapsed_map_refs": ["MAP-*"],
    "expected_missing": [],
    "tested_absent": [],
    "expansion_points": ["MAP-*|MAP-*/entry/*"]
  },
  "ledger_pressure": {}
}
```

`map_view`
: Read a bounded `MAP-*` view by map ref, level, lens, or task scope. It returns
allowed moves and never proof.

`map_drilldown`
: Expand `MAP-L3`/`MAP-L2` through bounded child maps and route hints toward
`CLM-*`, accepted `SRC-*`, `RUN-*`, or file/command/url capture routes. The
drilldown is still navigation until proof-capable records are inspected and
ledgered.

`record_detail`
: Read one canonical record with proof/navigation classification and direct
links.

`ledger_status`
: Return current-agent ledger validation, heads, open ACT, and allowed append
choices.

`validate_ledger`
: Replay ledger rows against seals, PoW, branch transitions, append-log order,
ledger claim snapshots, and current store.

`validate_answer_support`
: Decompose a draft or final answer into atomic support requirements, map each
requirement to `CLM-*`, accepted `SRC-*`, and sealed ledger rows, and return
unsupported or overclaimed statements with `valid_moves` for repair. This is a
typed `validate` operation, not a new primitive.

`task_status`
: Return task tree, blockers, done criteria, current derived agents, and final
ledger requirements.

`index_status`
: Return claim trust, source trust, claim graph, source acceptance, dedup,
ledger, map, TAP, and backend index freshness.

`project_registry_search`
: Search global `PRJ-*` records and workspace memberships.

## Write Tools

The names below are typed aliases/operation kinds. They are not independent
protocol primitives.

`register_project`
: Create or update a global `PRJ-*`. `project_type` may classify the node as
domain, system, project group, repo, service, docs, external reference, or
example. Parent project refs model recursive project scopes.

`create_workspace`
: Create a `WSP-*`.

`attach_project_to_workspace`
: Append a project membership row with role, reason, and optional
`include_children`. If children are included, runtime visibility expands through
recursive child `PRJ-*` records, but lookup and gates still preserve role and
bridge policy.

`create_task`
: Create a scoped `TASK-*`.

`decompose_task`
: Split a task into subtasks. Subtasks may be decomposed recursively.

`defer_task`
: Mark a task or subtask as deferred with reason and optional resume condition.

`resume_task`
: Resume a deferred task or subtask.

`attach_agent_to_task`
: Record current agent task attachment in agent state.

`map_open`
: Set the current `MAP-*` focus in the current `AGENT-*` working context.

`map_move`
: Move the current `AGENT-*` map position through an allowed map link.

`map_checkpoint`
: Persist inspected, deferred, rejected, or converted candidate state in
`AGENT-*` working context. Converted states must include `outcome_refs`.

`create_source`
: Capture provenance as `SRC-*`. Source acceptance is computed by runtime policy
from source kind, validation, user confirmation, and trust rules; capture alone
does not make a source commitment-ready.

Required input includes source classification when known: `input_class`,
`source_class`, `document_kind`, `evidence_role`, `authority_scope`, and
`independence_key`. Runtime may fill safe defaults, but an ambiguous source must
return `source_pressure` and valid moves for supported recovery operations such
as excerpt capture, lookup, or recapture.

`capture_source_excerpt`
: Capture an exact quote/span from an existing `SRC-*` as a smaller excerpt
`SRC-*`. Document-backed CLM creation must cite excerpt sources rather than a
whole ingested document. If the quote is not found in the parent source, the
mutation writes nothing.

`capture_source_fragments`
: Split a large plaintext document `SRC-*` into smaller `SRC-*` records with
`origin.kind = "source_fragment"` and parent-relative `quote_span`. Fragments
are navigation/review units only: claims still cannot cite them directly and
must use exact excerpt evidence produced by `extract_claim_candidates` or
`capture_source_excerpt`.

`confirm_source_for_scope`
: Confirm a source's class and authority scope using explicit user-provided
confirmation evidence. Input includes `source_ref`, `confirmation_ref`,
`source_class`, `authority_scope`, and `reason`; `confirmation_ref` must point
to user-captured `INP-*` or user-classified `SRC-*`. Runtime updates the source
classification through the typed path, appends an accepted source event, and
keeps source-event replay valid. This is narrower than a generic
`accept_source`: it records who confirmed what scope and why.

`extract_claim_candidates`
: Validate agent-proposed document fact candidates. Input is a source plus
candidate objects containing at least `quote` and `statement`. Runtime verifies
each quote exists in the parent source, captures one excerpt `SRC-*` per
candidate, and returns candidate packages with `excerpt_source_ref` for the
next step. This tool does not decide truth by itself; it makes extraction
auditable and span-bound.

`classify_source`, `accept_source`, `reject_source`
: Deferred source-audit operations. Runtime must not return these operation
kinds in `valid_moves` until the typed tools are implemented.

`create_claim`
: Create a `CLM-*`. Runtime computes exact `dedup_key` before write. Exact
duplicates fail with `duplicate_claim` and return the existing claim. Near
duplicates return `dedup_pressure`; creation requires selecting an existing
claim, linking claims, merging/splitting, or providing `distinction_reason`.
Broad or compound claims return `claim_pressure` with analysis questions such
as what exactly the agent learned, whether the claim should be split into point
facts, and which parts are observation, inference, applicability, or
uncertainty. This pressure does not store a claim status; it is runtime guidance
that pushes the agent toward narrower `CLM-*` records and explicit relations.
If the new claim is under-supported, runtime should return inference pressure:
the agent must either provide accepted source support, create/select an
inference relation such as `deduced_from`, `induced_from`, `abduced_from`,
`assumed_from`, `possible_relation_between`, or `challenges_freshness`, or
explicitly ask the user for a working-assumption confirmation.
If the requested basis is another under-supported hypothesis, the mutation must
fail or be converted into valid verification moves; MCP must not create a
hypothesis-on-hypothesis chain.
Claims citing whole document sources fail with
`document_source_requires_excerpt`; capture an exact excerpt first.

`create_claim_from_evidence`
: Create one atomic `CLM-*` from captured excerpt evidence. It accepts
`evidence_refs` that point to excerpt `SRC-*` records, rejects whole-document
sources, and rejects broad or compound statements before writing. This is the
preferred commit path after `extract_claim_candidates`.

`update_claim`
: Update a `CLM-*`. If the claim is later used in ledger, the ledger snapshots
the then-current claim state as a new `CLM@rev`.

`link_claims`
: Create a relation `CLM-*` between endpoint claims. Endpoint snapshots are
created when the relation enters a ledger branch.

Relation creation uses a canonical relation dedup key. A duplicate relation
must reuse the existing relation unless the request includes a real
`distinction_reason`.

Cross-project relation creation is valid only when both endpoint project scopes
are visible in the current workspace. This applies to possible relations and
hypotheses; the repair move is to attach the missing `PRJ-*` with an explicit
role/reason before linking.

`applies_to_scope` relations may include bridge context:

- `bridge_scope=general`: broad applicability, no domain merge.
- `bridge_scope=task`: applicability only for listed `TASK-*`.
- `bridge_scope=object_sync`: applicability only for a concrete synchronized
  object described by `synced_object`.

Inference relation creation must state the inference kind and basis. Deduction
requires explicit premise/rule refs, induction requires sample/scope refs,
abduction requires observation/anomaly refs, assumptions require scope/risk, and
possible relation claims must remain navigation/probe until supported.
Freshness challenges require target claim refs, freshness dimension
(`time|dependency_version|project_state|scope|external_policy|unknown`),
current scope, and the reason the trusted fact may be stale.
Inference relation bases must not be under-supported hypotheses unless the
operation is explicitly creating a verification branch rather than a new
supporting claim.

`compile_claim`
: Create or refresh a compiled `CLM-*` with `claim_form=aggregate` and
`compilation.compiled_kind=summary|model|flow`. Runtime should suggest this
when trusted facts form a stable repeated cluster that agents keep rediscovering.
Compiled claims use aggregate dedup keys over compiled kind, query/intent,
source set hash, underlying refs, and input policy.
Aggregate trust posture is computed from the underlying `CLM-*` posture. It
must expose weakest refs and limits, and it must not promote runtime-only or
contradicted leaves into trusted proof by summary wording alone.

`select_existing_claim`
: Resolve duplicate pressure by selecting an existing `CLM-*` instead of
creating a new one.

`merge_claims`
: Confirm two or more claims are duplicates, choose a canonical `CLM-*`, record
merge reason, and refresh dedup/claim graph indexes. Historical ledger
snapshots remain replayable.

`append_ledger`
: Append a sealed ledger row over a valid `CLM-*`, creating or selecting a
ledger-local `CLM@rev` snapshot.

Requires an explicit in-memory signing parameter. The signing parameter
(`agent_private_key` or equivalent) is sensitive: never persist, log, return,
capture as `SRC-*`, or write to `RUN-*`.

`open_probe`
: Append an `ACT` row from the current valid ledger state.

Required input includes target claim/relation refs, intent, allowed action kind,
scope, expected evidence, and the same explicit in-memory signing parameter.
The target must be a narrow current action intent or probe hypothesis, not a
broad historical run summary or pure runtime/command observation. Broad targets
return `act_target_too_broad`; pure observation targets return
`act_target_observation_only`. A narrow retry claim may cite the previous
failed/unfinished attempt if it names the bounded next check to try again.

`protected_action_preflight`
: Optionally validate that a protected action matches the current open ACT in a
stricter/audited flow. Returns an action token/id bound to ACT, action kind,
command/action hash, cwd/scope, and expiry. Default hook admission does not
require this step; it checks that a matching ACT is open and still fresh under
`settings.enforcement.act_timeout_seconds` (default 300 seconds). Expired ACTs
return `open_act_expired` and should be closed or replaced with a fresh ACT.

`record_run`
: Record a `RUN-*` for an executed command/tool/action. It must link to the
current ACT or action token for protected work.

`extract_run_claim_candidates`
: Validate agent-proposed facts from `RUN-*` stdout/stderr. Input candidates
contain `stream`, exact `quote`, and atomic `statement`. Runtime verifies each
quote exists in the selected output stream, captures audited `SRC-*` command
evidence, and returns candidate packages for `create_claim_from_evidence`.
This keeps test-driven learning from collapsing into mechanical “command ran”
claims.

`capture_probe_result`
: Convert RUN/user/file/artifact evidence into `SRC-*` for the open probe.
If it appends a ledger `capture` row, it requires the explicit in-memory signing
parameter.

`close_probe`
: Close the current open ACT through claim update, relation update,
contradiction, cancellation, supersession, or explicit no-update reason.
Requires the explicit in-memory signing parameter because it appends a ledger
row.

`record_tap`
: Record bounded usage pressure for facts/maps. TAP is navigation only.

`refresh_curiosity_map`
: Refresh or create map cells from canonical facts and generated index signals.

`refresh_index`
: Rebuild or incrementally update runtime indexes such as trust score, claim
graph adjacency, source trust, source acceptance, dedup, ledger heads, TAP
heat, map coverage, and CIX/backend projections.

`refresh_source_trust`
: Refresh source trust posture for one source, task scope, project scope, or
workspace. This is a `refresh_runtime` operation, not a canonical source write.

## Mutation Rules

- Validate before write.
- Failed mutation writes nothing.
- No raw JSON write API.
- Ledger append performs seal and weak PoW.
- Ledger signing operations require an explicit in-memory private key parameter
  that is never persisted or echoed.
- Source acceptance for commitment requires valid source audit events; a mutable
  `SRC-*` status field alone is not enough.
- Duplicate claim creation requires `distinction_reason`.
- Exact duplicate claim creation is blocked before write and returns the
  existing `CLM-*`.
- Near-duplicate candidates are navigation-only and require reuse,
  `distinction_reason`, relation creation, split, or merge.
- Foreign/example project facts require a bridge relation before commitment.
- Backend/map/index candidates cannot be direct support for claims.
- Every response that blocks or warns must provide valid recovery choices in
  `valid_moves` or `repair_options`.
