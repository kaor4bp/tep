# Concepts

TEP 0.12 keeps the canonical vocabulary small and pushes agents through compact
fact cards instead of raw record dumps.

| Prefix | Meaning | Proof role |
| --- | --- | --- |
| `prj_*` | Project, domain, repo, service, or aggregate project registry entry. Projects may have parent projects. | Scope/provenance only. |
| `task_*` | Current work unit. Tasks can be recursively decomposed and carry `project_refs`. | Scope and work coordination. |
| `agent_*` | One live agent thread/session identity. | Session attribution and adoption telemetry. |
| `inp_*` | Captured user input. | Source precursor. |
| `src_*` | Captured source/evidence: file quote, user message, command output, excerpt, document fragment. | Evidence once accepted/audited. |
| `run_*` | Captured command/action observation. | Evidence precursor; convert relevant output to `src_*`. |
| `clm_*` | Reusable knowledge record. Status is not stored; trust is derived at runtime from sources, relations, chains, feedback, and freshness. | Proof-capable when selected into a checked `chain_*`. |
| `rel_*` | Typed relation between records. | Graph edge; can support, contradict, scope, aggregate, duplicate, or challenge. |
| `chain_*` | Selected proof route over CLM/REL/SRC/INP/RUN records. | Inspectable reasoning support for finish/action/conclusion. |
| `ctx_*` | Generated work-context or briefing compilation. | Guidance/cache only. |
| `idx_*` | Runtime index/cache manifest. | Navigation only. |
| `map_*` | Curiosity map/navigation structure. | Navigation only. |
| `snap_*` | Immutable observed code snapshot. | Code-state evidence precursor; proof needs exact `src_*` excerpts from it. |

Removed from the active model:

- `WSP-*`
- old workspace memberships
- public `STEP-*` / `GRANT-*`
- `.codex_context`
- old sealed per-agent ledger rows as the active proof primitive
- hook-first ACT enforcement as the center of the workflow
- raw JSON writes as a supported mutation path

## Claims

`clm_*` records do not store `hypothesis`, `trusted`, or `disputed` status.
Those labels are runtime posture derived from:

- accepted/audited source classes
- source diversity
- user confirmations
- relation graph
- contradictions
- aggregation leaves
- checked chain use

A runtime-only CLM can have many repeated observations and still remain
hypothesis-like until supported by theory/docs or explicit user confirmation.

Ordinary `clm_*` records may carry `context`, `tags`, and `trigger_phrases`.
Those fields are retrieval hints, not proof. They let `brief` surface facts
like coding guidelines or domain theory before the agent knows the exact lookup
query.

## Relations

Claim relations are `rel_*` graph records. They are created by agents through
`relate_facts` when one fact supports, contradicts, depends on, applies to,
supersedes, duplicates, aggregates, or challenges another fact.

Relations are needed because TEP should store not only isolated facts, but why
one fact can be used with another in this task. Cross-project facts require a
relation when the link is not local to the current task's `project_refs`.

## Aggregates

Aggregate `clm_*` records summarize groups of child CLM records to reduce lookup
and token load. They must include:

- `aggregation.underlying_refs`
- `aggregation.limits`
- `support_refs` containing the child refs

Aggregate trust is computed from child trust. An aggregate cannot make weak
children trusted by using confident wording.

Lookup and brief prefer aggregate CLM records when they match the active task,
but `get_fact` and graph-walk detail must expose child refs, weakest refs, and
contested refs so the agent can drill down before final reliance.
