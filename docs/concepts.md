# Concepts

This document defines the public vocabulary for TEP v1.

## Core Objects

| Object | Role | Proof posture |
| --- | --- | --- |
| `WSP-*` | Workspace working scope. Holds tasks, agents, artifacts, and project memberships; views shared facts, maps, and indexes through scope policy. | Scope only. |
| `PRJ-*` | Global project/repository/service registry entry. Independent from workspaces. | Scope and provenance context only. |
| `AGENT-*` | One live agent thread/session with owner public key, selected focus, working context, task attachments, curiosity position, and ledger path. | Runtime authority for appends. |
| `TASK-*` | Durable recursive work item with goal, scope, blockers, done criteria, and optional child tasks. Any task can be split into subtasks. | Coordination only. |
| `SRC-*` | Captured source/provenance with classification: user message, file quote, command output, artifact snapshot, URL snapshot, or MCP capture. | Proof-capable only when runtime source acceptance policy accepts it. Source trust is computed, not stored. |
| `RUN-*` | Execution audit record for a command/test/tool run. | Evidence source only after captured by `SRC-*`. |
| `CLM-*` | Claim graph node. It does not store truth status and is referenced without revision outside ledger. Runtime computes trust posture from links, sources, and context. | Proof-capable only when ledger snapshots it as `CLM@rev` and computes trust posture. |
| `LEDGER` | Append-only per-agent JSONL reasoning graph over `CLM@rev`. | Validates reasoning structure and ownership, not global truth. |
| `ACT` | Ledger row for an open probe or intended check. | Commitment gate, not proof. |
| `MAP-*` | Durable curiosity/navigation cell. A larger map is a graph of `MAP-*` cells linked to broader, smaller, adjacent, refined, or superseded maps. | Navigation only. |
| `IDX-*` | Runtime index manifest for generated projections such as trust score, claim graph, source acceptance, ledger heads, map coverage, TAP heat, or backend indexes. | Runtime acceleration only; never proof. |
| `CIX-*` | CocoIndex-produced projection, extraction batch, or candidate bundle. It is a specialized `IDX-*`-class record. | Navigation only until inspected and captured as `SRC-*`. |

## Terms

`CLM@rev`
: A ledger-local claim snapshot reference such as
`CLM-20260424-ab12cd34@3`. Revisions exist only inside the reasoning ledger.
Outside ledger APIs and schemas, claims are referenced as bare `CLM-*`.

`semantic_hash`
: Hash of claim fields that can change reasoning meaning. Formatting,
timestamps, generated metadata, and workspace/task assignment are not semantic.

`ledger seal`
: Algorithm-neutral public-key seal over the canonical ledger row payload and
predecessor material. It binds the row to the ledger context hash, branch
predecessor, physical append-log predecessor, ledger claim snapshot material,
and weak PoW. The concrete algorithm is a separate implementation decision.

`briefing`
: Runtime summary that reminds the agent what it is working on now: current
workspace, current/related projects, active task/subtask, done criteria,
blockers, agent focus, selected facts, ledger posture, and curiosity pressure.

`trust posture`
: Runtime-computed view over a `CLM-*` or ledger snapshot `CLM@rev` in context.
The schema does not store `hypothesis`, `trusted`, `supported`, or `contested`
as claim status. Public API may return those labels as derived output.

`inference posture`
: Runtime-computed explanation of why an under-supported claim is being treated
as a hypothesis: deduction, induction, abduction/explanation, fact-based
assumption, possible relation, analogy, user working assumption, or
unclassified. This is derived from source and relation paths, not stored as a
claim status.

`source trust posture`
: Runtime-computed view over `SRC-*` classification, provenance, validation,
freshness, scope fit, and contradictions. It is index/API output, not a stored
`trusted=true` flag.

`source diversity`
: Runtime measure of independent confirmation across source classes and
independence keys. Repeated runtime observations with the same independence key
can raise confidence but do not become theory/document support.

`dedup key`
: Deterministic normalized key for exact duplicate `CLM-*` blocking. It is not
a logical-equivalence proof.

`near-duplicate candidate`
: Runtime/index hint that two claims may be semantically close. It is
navigation-only and must be resolved by reuse, distinction, relation, split, or
merge.

`ledger pressure`
: MCP response block that explains ledger posture and returns valid protocol
moves the agent may choose from: lookup, source capture, claim creation,
relation, ledger append, probe open, capture, close, validation, or deferral.

`commitment boundary`
: A point where private reasoning is not enough. TEP gates protected mutation,
final answers, and task completion.

`runtime-only hypothesis`
: A derived label for a claim with runtime observations but no theory/document
support and no explicit user confirmation. Even 1000 runtime observations do
not make it a trusted fact by themselves.

`TAP`
: Append-only usage pressure over records or map entries. TAP affects retrieval,
heat, decay, and fixation/cold-zone signals. It is never popularity-as-truth.

`compiled CLM`
: A `CLM-*` with `claim_form=aggregate` and `compilation.compiled_kind` of
`summary`, `model`, or `flow`. V1 does not expose separate public `MODEL-*` or
`FLOW-*` record types.

`retrospective map`
: A `MAP-*` that captures what was learned from a completed or failed attempt:
useful routes, failure modes, open questions, and future probes. It is
navigation-only unless converted into source-backed `CLM-*` claims.

`hypothesis`
: A public API label for an under-supported `CLM-*` in context. It is not a
stored claim status. A hypothesis must be explainable through an inference
posture. A hypothesis must not be used as the basis for another hypothesis.
It can open an alternative verification branch, ACT, lookup, source capture, or
user question. If runtime cannot classify the inference, it should return
`unclassified_hypothesis` pressure and valid moves to add sources, relations, or
user confirmation.

`freshness challenge`
: A hypothesis that a currently trusted fact may be stale for the current time,
scope, dependency version, project state, or task. It does not invalidate the
trusted fact by itself. It raises freshness pressure and routes the agent to
lookup, source capture, ACT probe, or claim update. The trusted fact remains on
the commitment path until the alternative branch is verified.

## Keep From Old TEP

- Source-backed claims as the truth-bearing layer.
- Curiosity maps as navigation, never proof.
- Relation claims for semantic edges between facts.
- Classified sources and source-backed claim trust.
- Agent-owned ledgers and branch validation.
- `ACT` as an open probe rather than a permission token.
- Weak PoW and seals as tamper friction.
- Agent adoption pressure through briefing, valid moves, and commitment gates.

## Drop From The v1 Baseline

- `WCTX-*` as public live context.
- Public `STEP-*` and `GRANT-*` concepts.
- `.codex_context` storage.
- Hook-first enforcement as the architecture.
- Raw record writes as supported mutation path.
- Code smell/index/backend output as proof.
- Stored claim truth status.
- Public `MODEL-*` and `FLOW-*` record types; v1 uses compiled `CLM-*`.
- Curator-created aggregate records; v1 aggregate/compiled claims are
  runtime-created.
