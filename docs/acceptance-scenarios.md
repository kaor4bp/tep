# Acceptance Scenarios

TEP 0.12 implementation should support these tests. Older 0.9/0.10 ledger and
ACT scenarios are historical unless they are explicitly restated below as
current chain/task/server behavior.

## Storage

- Legacy `workspaces/` and `registry/workspaces/` are moved to quarantine on
  startup.
- Docker beta canonical records and events are written through TerminusDB, not
  the SQLite sidecar.
- SQLite may store control-plane/test state, but not canonical `clm_*`,
  `src_*`, `rel_*`, `task_*`, `job_*`, `snap_*`, or `chain_*` records.
- Mirage-backed `snap_*` records can restore a code snapshot with matching file
  hashes when Mirage is configured.

## Task Scope

- `task_*` can be linked to two or more `prj_*`.
- A project can represent a domain/system aggregate, concrete repo, service, or
  example/reference.
- A relation cannot connect facts from project scopes that are absent from the
  current task.
- Foreign/example facts are lookup/navigation until a task-scoped relation
  explains applicability.
- `decompose_task` is read-only by default and returns candidate executable
  child tasks with priorities, acceptance criteria, expected evidence, inherited
  plan/project/code refs, and `create_task` arguments.
- If a task already has children, `decompose_task` surfaces them before
  suggesting more decomposition.
- Priority plans distinguish executable active leaf tasks from blocked or
  deferred leaves. Blocked high-priority work remains visible, but the next
  executable leaf should be ranked first unless the agent chooses to unblock it.
- `prepare_work_context` includes compact task context and priority discipline
  so the agent can see when it is working on a lower-priority leaf.

## Chains

- `prepare_reasoning_chain` can prepare a compact candidate proof route from
  selected CLM refs, a target CLM, a task, or a query.
- `check_chain` / `check_argument` flags unsupported leaves, bookkeeping CLM,
  missing source evidence, contradictions, and hypothesis-on-hypothesis gaps.
- Important finishes cite selected `clm_*` support and may persist `chain_*`
  when the route should be inspected or reused.
- `prepare_finish` returns a final-mode `candidate_chain` plus `chain_review`;
  weak or invalid chains lower recommendation and produce repair moves without
  hard-blocking task closure by default.
- Final support rejects bare `src_*` and `run_*`; evidence must support
  reusable `clm_*` records or appear inside the selected chain as evidence.

## Claims

- Unsupported CLM receives pressure but is not hard-blocked.
- Bookkeeping-like CLM receives pressure and lowers argument quality.
- Runtime-only repeated observations do not become trusted without stronger
  sources or user confirmation.
- A hypothesis cannot support another hypothesis as final reasoning without
  added evidence or a relation that exposes the gap.
- A freshness challenge creates an alternate branch, not silent replacement.
- Aggregate CLM trust is derived from children and lookup ranks aggregates
  before children.
- `brief` surfaces tagged/contextual fact cards without requiring an explicit
  lookup query.
- `learn` creates one reusable fact from exact `src_*` or `run_*` evidence.
- `check_chain` / `check_argument` flags bookkeeping, unsupported leaves, and
  hypothesis-on-hypothesis links.

## Sources

- File/text ingestion creates a source, then extraction creates quote-backed
  excerpts/candidates.
- A CLM from a document is backed by exact quote SRC evidence, not only by a
  whole-file source.
- User confirmation can accept a source scope.
- Command output is captured as RUN/SRC; CLM creation happens only for useful
  durable facts or narrow failure observations.

## MCP And Hooks

- Public MCP tools do not expose WSP creation/attachment or raw provider
  access.
- `prepare_work_context` / `brief` returns fact cards with short quotes,
  context/tags, counterfacts, gaps, and candidate proof routes.
- `valid_moves` lists options, not a single forced next operation.
- Bash hook blocks direct `.tep` writes when configured.
- Bash hook can require `capture_run` for process execution when configured.
- Stop hook emits valid Stop metadata when it asks for a final support summary.
