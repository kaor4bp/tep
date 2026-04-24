# Curiosity Map

The curiosity map is the agent's navigation surface over the fact space. It is
not proof.

It gives the agent a bounded spatial/topological picture: dense islands,
bridges, cold zones, contested zones, stale areas, likely drill-down routes, and
frontier questions. This is how TEP supports "visual thinking" for agents
without letting map output become evidence.

## MAP Records

`MAP-*` is a durable navigation cell, not a generated full-project graph. One
`MAP-*` has exactly one abstraction level and one primary lens. Larger maps are
graphs of many `MAP-*` cells connected by typed map links.

Levels:

- `L1`: evidence patch near `CLM-*`, `SRC-*`, `RUN-*`, `ART-*`, or `CIX-*`.
- `L2`: pattern, mechanism, risk, policy, workflow, code-area, or open-frontier
  cell over L1 cells and aggregate/relation claims.
- `L3`: task situation, strategy, or retrospective cell over L2 cells,
  `TASK-*`, and `AGENT-*` working context.

Minimal shape:

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

`MAP-*` may point to proof-capable records, but it never becomes proof itself.
Every route from a map to commitment must drill down through `CLM-*`, accepted
`SRC-*`, and, when needed, a sealed ledger path.

`entries[].entry_kind=submap` with `ref=MAP-*` is containment/navigation, not a
semantic relation. Parent maps do not inherit proof or trust from child maps,
and child maps do not prove parent summaries. Traversal between maps never
replaces a relation `CLM-*`.

## Map-Of-Maps

Map hierarchy is explicit:

- `up_map_refs`: lower level to higher abstraction.
- `down_map_refs`: higher level to supporting map cells.
- `adjacent_map_refs`: neighboring cells at the same level.
- `refines_map_refs`: narrower or clearer replacement that preserves useful
  older context.
- `supersedes_map_refs`: newer cell replaces an older stale cell.
- `contradicts_map_refs`: map summaries or route implications are in tension.

Validation rules:

- `L1.up_map_refs` should point to `L2` or bounded `L3`.
- `L2.down_map_refs` should point to `L1`.
- `L2.up_map_refs` should point to `L3`.
- `L3.down_map_refs` should point to `L2` or a bounded set of `L1`.
- Same-level adjacency is preferred for `adjacent_map_refs`; cross-level
  adjacency requires a reason.
- Candidate links do not form topology clusters.

The agent should normally move through maps instead of asking for a full graph
dump:

```text
map_open -> map_view -> map_move -> map_drilldown -> map_checkpoint
```

`map_open`, `map_move`, and `map_checkpoint` update only the current
`AGENT-*` working context. Shared `MAP-*` cells remain shared navigation memory.
Another agent may inspect a foreign map trail, but it continues through its own
`AGENT-*` position and ledger.

## Visual Thinking Contract

The runtime may intentionally show a partial map. Partial maps are allowed only
when the response makes the frontier explicit:

- collapsed nearby clusters
- cold-but-near clusters
- expected but unestablished links
- bridge candidates
- known rejected/tested-absent links
- suggested expansion points

Gap semantics:

- no visible link means "not shown or not established", not "no link exists";
- expected missing links are inquiry candidates, not facts;
- `tested_absent` requires recorded scope, method, and source-backed claim;
- absence of a generated edge is never evidence of absence.

This lets TEP induce useful curiosity by controlling representation while
keeping the proof boundary intact.

## Signals

Curiosity views may expose:

- TAP usage frequency and decay
- cold relevant records
- bridge pressure between clusters, projects, domains, or map levels
- contradiction and tension candidates
- missing relation candidates
- hypothesis/probe candidates
- runtime-heavy but theory-weak claims
- user-confirmation candidates
- stale or superseded map cells
- compilation pressure for repeated trusted clusters that need a compact
  summary/model/flow `CLM-*`
- CocoIndex (`CIX-*`), Serena, embeddings, and other backend candidates

TAP is not popularity-as-truth. High TAP can mean a useful anchor or unhealthy
fixation. Smell rises when repeated access looks like circular reasoning,
missing abstraction, or reuse without ledger/state extension. TAP should decay
over time and be scoped by workspace, project, task, and agent where useful.

Curiosity ranking is conceptual in v1, not a hard numeric contract:

```text
curiosity_value =
  uncertainty
  * impact_on_current_task
  * downstream_chain_value
  * testability
  * source_independence_gain
  - observation_cost
  - interruption_cost
  - safety_risk
```

The runtime should prefer cheap safe checks, focused user questions when the
user is the only practical source, and source drill-down when evidence is
available locally.

## Candidates

Every candidate must include:

```json
{
  "candidate_ref": "...",
  "candidate_kind": "tap|cold_zone|bridge|contradiction|missing_relation|backend|stale_map|zoom",
  "state": "suggested|inspected|deferred|converted_to_source|converted_to_relation|opened_act|rejected",
  "source_map_refs": ["MAP-*"],
  "workspace_ref": "WSP-*",
  "project_refs": ["PRJ-*"],
  "proof_role": "navigation_only",
  "proof_usable_now": false,
  "why_suggested": "...",
  "trust_posture_impact": "raises|lowers|clarifies|unknown",
  "expected_value": "low|medium|high",
  "outcome_refs": [],
  "required_drilldown": ["MAP-*|SRC-*|CLM-*|file|command|url"],
  "valid_tools": ["map_view|map_drilldown|record_detail|create_source|link_claims|open_probe|defer_task"]
}
```

Candidate lifecycle:

- `suggested`: runtime generated the candidate.
- `inspected`: agent viewed detail or drilled down.
- `deferred`: agent kept it in `AGENT-*` working context for later.
- `converted_to_source`: candidate led to `SRC-*` capture.
- `converted_to_relation`: candidate led to relation `CLM-*`.
- `opened_act`: candidate led to a probe.
- `rejected`: candidate was checked and is not useful under recorded scope.

Per-agent lifecycle overlay belongs to `AGENT-*` working context:

```json
{
  "candidate_ref": "MAP-*/entry/*",
  "map_ref": "MAP-*",
  "task_ref": "TASK-*|null",
  "state": "suggested|inspected|deferred|converted_to_source|converted_to_relation|opened_act|rejected",
  "outcome_refs": ["SRC-*|CLM-*|L-*|TASK-*"],
  "reason": "...",
  "updated_at": "iso8601"
}
```

`converted_to_source` must reference the created `SRC-*`.
`converted_to_relation` must reference the relation `CLM-*`. `opened_act` must
reference the ledger `L-*` ACT row. `rejected` without a source-backed `CLM-*`
does not prove absence.

Curiosity state does not mutate canonical truth unless the agent follows a typed
operation such as `create_source`, `link_claims`, or `open_probe`.

## Bridge Pressure

Bridge pressure appears when facts from different clusters, projects, domains,
or map levels look related. For cross-project examples, bridge pressure is only
navigation until an applicability relation claim is created and ledgered.

Valid bridge outcomes:

- `established`
- `candidate`
- `expected_missing`
- `tested_absent`
- `rejected`
- `unknown`

Evidence of absence requires a source-backed claim with recorded method/scope,
not an absent generated edge.

`expected_missing` means the map expected a relation but has not found one. It
is a prompt to inspect, not a claim. `tested_absent` means a bounded search was
performed under recorded scope/method; commitment still requires the resulting
absence claim to be represented as `CLM-*` with accepted source support.

## Backend Boundary

CocoIndex, Serena, embeddings, and static analysis tools are optional
navigation backends.

Backend output must be labeled as one of:

- `navigation_candidate`
- `extraction_candidate`
- `validation_candidate`
- `conflict_candidate`
- `derived_candidate`

Backend output cannot be direct claim support. The agent must inspect/capture
source material and create `SRC-*` before using it in `CLM-*` or ledger paths.

`CIX-*` records may cover one or more `PRJ-*` records. Each extracted candidate
must keep project/scope metadata so cross-project matches can be ranked and
bridged instead of silently treated as local proof.

## Map Refresh

`refresh_curiosity_map` is an explicit mutating operation. Read-only map views
must not silently create or rewrite `MAP-*`.

Refresh should:

1. read canonical records and generated index/backend signals;
2. propose bounded candidate `MAP-*` cells;
3. update in place only for activity/pressure/timestamp changes;
4. create a new cell when anchors, source set, route hints, level, kind, lens,
   or summary meaning changes;
5. link old/new cells through `refines_map_refs` or `supersedes_map_refs`;
6. mark old cells stale when they remain useful but should de-rank.

Refresh triggers:

- new or changed `CLM-*`/`SRC-*`/`RUN-*`
- source-set hash changes
- changed project membership
- stale TAP/cold-zone data
- stale or superseded map anchors
- explicit user or agent request

Stale maps remain navigation-only. They can orient the agent, but commitment
requires drill-down to current proof-capable records and ledgered claims.

## Retrospective Maps

After closing an ACT, finishing a task, abandoning a route, or hitting a
repeatable failure, runtime may offer a valid move to create or refresh a
`retrospective` `MAP-*`.

Retrospective maps can store:

- what route was tried
- which `RUN-*`, `SRC-*`, `CLM-*`, `MAP-*`, and ledger rows were involved
- why the route worked, failed, became stale, or was abandoned
- what a future agent should inspect first
- which claims still need source support, bridge relations, or user
  confirmation

Retrospective maps are an adoption mechanism: they make the protocol useful to
the next agent by preserving the shape of the investigation. They remain
navigation-only. A lesson from a retrospective map becomes proof-capable only
after conversion into accepted `SRC-*`, `CLM-*`, relation claims, and sealed
ledger rows.

## Hard Boundaries

- `MAP-*`, `IDX-*`, `CIX-*`, and `MAP-*/entry/*` are forbidden in `source_refs`,
  `support_refs`, `contradiction_refs`, and ledger proof paths.
- A claim that tries to use a map/index/backend candidate as support must fail
  with `needs_source` or `navigation_as_proof`.
- `refresh_curiosity_map` must not create `SRC-*`, `CLM-*`, or ledger rows.
- Spatial layout, analogy, imagined bridge, route, cluster distance, and map
  containment are always navigation-only.
- Final/protected/task-done gates must reject paths that contain only
  map/backend/spatial/imaginative candidates without accepted `SRC-*`, `CLM-*`
  graph support, and sealed ledger rows.
