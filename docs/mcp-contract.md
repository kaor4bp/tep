# MCP Contract

> Historical 0.9/0.10 contract draft. The active 0.12 agent loop is described
> in `docs/0.12-plan.md` and should prefer `prepare_work_context`,
> `learn_fact`, `relate_facts`, `prepare_reasoning_chain`, `check_chain`,
> `challenge_claim`, `decompose_claims`, and `prepare_finish`. ACT/ledger
> endpoints below are not the center of the current workflow.
> `prepare_work_context` is specified in `docs/work-context.md`: it is a
> read-only intent-specific context pack with compact fact/source/note cards,
> counterfacts, gaps, retrieval-quality warnings, candidate chains, and valid
> moves.

TEP exposes a small public MCP surface. Tools return:

- `ok`
- `data`
- `ledger_pressure`
- `source_pressure`
- `claim_pressure`
- `act_pressure`
- `valid_moves`
- `repair_options`

`valid_moves` are valid options, not a single forced next move. The agent still
chooses the move that fits the task.

## Public Tools

`generate_agent_identity`
: Generate an in-memory identity. Returns `agent_private_key`; it must not be
  written to disk.

`start_agent_thread`
: Bind an identity to a thread and optionally a task.

Required:

```json
{"thread_ref": "...", "identity": {"agent_ref": "...", "agent_private_key": "..."}}
```

Optional: `task_ref`, `project_refs`.

`brief`
: Return task, agent, session, settings, active work frame, compact fact cards,
  working argument chain, ledger pressure, and valid moves.

Optional: `task_ref`, `agent_ref`, `thread_ref`, `project_refs`.

`task`
: Create/attach/decompose/defer tasks and compile/list/revoke context.

Actions:

- `create`
- `attach_project`
- `attach_agent`
- `decompose`
- `defer`
- `compile_context`
- `list_context`
- `revoke_context`

`capture`
: Capture evidence.

Kinds:

- `input`
- `text`
- `file`
- `bash`
- `run_output`
- `source_excerpt`
- `source_fragments`
- `extract_claim_candidates`
- `confirm_source`

`claim`
: Create an atomic or aggregate `clm_*`.

Required:

```json
{"task_ref": "task_*", "statement": "...", "based_on": ["src_*|clm_*"]}
```

`run_*` must first be converted to `src_*` with `capture(run_output)`.

Optional retrieval fields: `context`, `tags`, `trigger_phrases`.

`learn`
: Save one reusable fact from exact `src_*` or `run_*` evidence. If the input
  is `run_*`, TEP captures output as `src_*` first. Returns the created CLM
  fact card and nearby related cards.

Required:

```json
{"task_ref": "task_*", "learned_statement": "...", "evidence_ref": "src_*|run_*"}
```

Optional: `context`, `tags`, `trigger_phrases`, `claim_form`, `claim_kind`,
`project_refs`.

`relate`
: Create a relation CLM.

Required:

```json
{
  "task_ref": "task_*",
  "relation_type": "supports|contradicts|depends_on|possible_relation_between|...",
  "subject_ref": "clm_*",
  "object_ref": "clm_*"
}
```

The relation project set must be a subset of the task project set.

`reason`
: Append a selected CLM snapshot to the task/agent reasoning ledger.

Required:

```json
{
  "task_ref": "task_*",
  "agent_ref": "agent_*",
  "agent_private_key": "...",
  "claim_ref": "clm_*",
  "why": "..."
}
```

Optional: `argument_role`, `branch_note`, `supersedes`, `rejects_refs`.

`act`
: Open, preflight, capture, or close a bounded probe.

Actions:

- `open`
- `preflight`
- `capture`
- `close`

`act(open)` writes a ledger row directly and can snapshot the claim without a
separate prior `reason` call. Hooks only check that a fresh ACT exists in the
task/agent ledger.

`lookup`
: Search reusable facts. Aggregate CLM records are prioritized and results
include compact fact cards. Use `record_detail` to drill into children.

`discover_bridges`
: Search latest code snapshots for cross-project bridge candidates such as
  shared routes, identifiers, symbols, config keys, or literals. Results are
  navigation-only pressure. They cannot support a final answer until the agent
  captures exact `src_*` excerpts, creates local `clm_*` facts for both sides,
  and records an explicit positive or negative `rel_*`.

`record_detail`
: Inspect one record, including trust posture, source events, aggregate
children, and links.

`prepare_finish`
: Read-only proof review before task closure. It checks selected `clm_*`
  support, unresolved child tasks, open jobs, source extraction pressure, user
  questions, stale code evidence, and stale document-backed evidence. It also prepares a final-mode
  `candidate_chain` from the selected support refs and returns `chain_review`
  from `check_chain`, including shape/coverage/counter/staleness scores, gaps,
  warnings, and repair pressure. Weak chains lower `recommended` but do not
  hard-block by default.

`finish`
: Mutating task closure. It calls the same proof review as `prepare_finish`,
  stores a compact `finish_chain_review` on a successfully closed task, and
  records a `finish_attempted` event. It should not be used as a raw status
  setter.

Final and task-done support accepts only ledgered `clm_*` refs. `src_*` and
`run_*` must first be interpreted into claims.

`check_argument`
: Validate selected CLM support before ACT/final/action. Returns fact cards,
  quality score, gaps, and questions. It is advisory pressure, not proof.

`prepare_reasoning_chain`
: Prepare a compact candidate chain from selected or retrieved CLM without
  persisting `chain_*` by default. The response includes compact CLM cards,
  candidate steps, premises, conclusion, counterfacts, gaps, score components,
  validation status, and repair moves. Aggregate CLM children are referenced but
  not expanded as full cards unless the agent opens them explicitly.

`decompose_task`
: Read-only planning helper for broad tasks, plan artifacts, Jira issue inputs,
  or draft text. It returns proposed executable child task records with
  `parent_task_ref`, inherited `plan_refs`/`project_refs`/`code_refs`,
  priorities, acceptance criteria, expected evidence, blockers, and
  `create_task` arguments. It does not write child tasks; the agent must choose
  which candidates to persist.

`chain_rule_registry`
: Return the typed rule registry for `chain_*` step validation. The registry
  explains accepted premise/conclusion families and required bindings.

`check_chain`
: Validate a candidate chain shape without writing it. It checks referenced
  records, rule names, premise/conclusion types, required bindings, gaps, and
  warnings. Natural-language explanations remain commentary; proof is the tuple
  of rule, premises, conclusion, bindings, constraints, counterfacts, and gaps.
  Unsupported hypothesis-on-hypothesis, missing relation premise, runtime-only
  support, stale facts, and counterfact pressure lower the chain label/score and
  are returned as explicit repair pressure.

`settings`
: Read or update global/task settings.

`register_project`
: Register `prj_*`.

`project_registry_search`
: Search `prj_*`.

## Hidden Compatibility Tools

These remain callable by name for hooks/debugging but are not part of the
normal public tool list:

`action_pressure`
: Low-level/debug action classification against settings and open ACT state.

`refresh_indexes` / `index_status`
: Low-level/debug runtime navigation index management.

## Mutation Rules

- No raw JSON write API.
- Failed mutation writes nothing.
- Multi-record mutations use transactions where needed.
- Ledger append performs signature and weak PoW.
- MCP journals redact `agent_private_key`.
- Duplicate claims are rejected by dedup key.
- Cross-project relations require both project scopes in `TASK.project_refs`.
- Map/index/backend output remains navigation until captured as `src_*` and
  turned into `clm_*`.
