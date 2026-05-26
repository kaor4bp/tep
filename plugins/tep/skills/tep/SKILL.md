---
name: tep
description: Use the Trust Evidence Protocol server as durable fact memory and a reasoning checker for Codex tasks.
---

# TEP Skill

TEP is not a ceremony to satisfy. It is a local fact-memory server that helps you stop relearning the same project, separate facts from guesses, and show the user what your conclusion rests on.

Use TEP through the `tep` MCP server tools. Do not read or write raw TEP storage files.

Before assuming an external retrieval layer exists, check `status.integration_status`
or `tep-client doctor`. In 0.12.x, PageIndex, Mirage, Valkey, TerminusDB, and
code-navigation adapters may appear in plans as direction/hints even when their
component status is not active. Code-navigation providers are internal TEP
details; you may read the provider list in TEP status, but use only TEP code
tools from the agent side and never call provider MCP/CLI tools directly.

TEP scoring and pressure rules are visible algorithm contracts. Use
`list_algorithm_contracts` or `get_algorithm_contract` when you need to explain
which scoring rule shaped a trust/rank/chain result. In 0.12.x these contracts
are seeded into the server store from default scripts and remain read-only
metadata around the current Python implementation unless TEP explicitly reports
an active script runtime.
Use `preview_algorithm` only to inspect draft script behavior; preview output is
not proof and does not mean production trust/rank scoring has switched runtime.

The plugin hook captures every user prompt as an `inp_*` record. Treat that as
durable conversation context, not as an extracted fact. When the input contains
reusable knowledge, decisions, or documents, convert the relevant excerpt
through `ingest_input`/`submit_job_result` or save a narrow CLM with explicit
support. If the CLM says the user decided, confirmed, corrected, or preferred
something, put the relevant `inp_*` in `source_refs`; do not rely on your memory
of the chat as evidence.

The user may configure hooks in the TEP UI. If Bash PreToolUse is set to
`require_capture_run`, run commands through `tep-client run-capture --cwd . --`
so output becomes `src_*` evidence and TEP can compute learning pressure. If
Bash is blocked because open jobs accumulated, resolve or explicitly defer the
jobs before continuing. `run-capture` is still allowed when the job limit is
exceeded; use it to gather evidence needed to complete jobs instead of falling
back to raw Bash.

## Start Of Work

At the beginning of a task:

1. Call `create_task` if the user has not provided a current task.
2. Call `start_session` with the `task_ref`, a short `agent_name`, project refs if known, and 2-6 `focus_tags`.
3. Call `brief(session_ref=...)`.
4. Read `work_focus`, `priority_plan`, `pressure_items`, `job_pressure`,
   `feedback_pressure`, `fact_recall_pack`, `retrieval_plan`, and
   `curiosity_map`; handle relevant pressure before creating broad new CLM
   facts.
5. Tell the user the compact fact chain you will use only when it is relevant to the answer. Prefer `clm_* + short quote + your interpretation`.

Keep the boundary clear:

- `task_*` is the user goal or plan unit.
- `job_*` is a TEP queue item for maintenance, extraction, review, deferred user questions, or mechanical worker work.
- A high-priority job can affect context quality, but it does not become the user's task. Inspect/defer/resolve it, then return to the selected leaf task.

Use `priority_plan` to choose work by priority, not by convenience. If you take
an easier lower-priority task or job, say why and what risk remains.
If `brief.task_context.priority_discipline.status` is `needs_attention`, switch
to the top work item unless it is blocked; if you intentionally continue the
lower-priority leaf, record the reason with `create_note` or update the task
status to `blocked`/`deferred`.

If `brief` returns pending jobs, bridge pressure, stale aggregate warnings,
stale code/document evidence, theory/practice bridge jobs, or missing facts,
handle that before relying on the affected facts.

If `brief` or `prepare_work_context` returns `fact_recall_pack`, treat it as
the current known-fact reminder for this decision. Compare your hypothesis with
the listed CLM quotes and counterfacts before deciding. If the pack is thin or
does not match the work, call `search_facts`, `prepare_work_context`, or
`prepare_reasoning_chain` instead of proceeding from memory.

If `brief.work_focus.recommended_focus` is `job` or `job_then_task`, call
`get_job` first. Use the returned guidance to submit, defer, cancel, or inspect
the job result. Warnings and rejected candidates are soft pressure, not a hard
stop: either repair and resubmit the job result, reopen/defer/cancel the job,
or explicitly continue with the remaining risk visible. Do not treat job
completion as task completion.
Jobs are scoped. A job may target the current task, current project, or your
agent session. If a scoped job is visible in `job_pressure`, do not skip it just
because the main coding path is more convenient. Inspect the highest-priority
scoped job, then either complete it, defer it with a concrete blocker, or state
why continuing is lower risk.
If `brief.job_pressure.status` is `needs_review`, inspect the listed jobs
before treating their submitted results as settled context.
Prefer `brief.job_pressure.top_actionable_jobs` over scanning the full queue.
Those are the jobs TEP thinks are most likely to affect the current work.

If `brief.feedback_pressure.status=needs_utility_feedback`, do not stop the task
only to rate facts. But after a visible CLM helps or misleads you, call
`record_feedback` with `useful` or `not_useful` and a short reason. Feedback
improves retrieval utility; it is not proof and does not change truth by itself.

If `brief` returns user-question pressure, asking the user or creating an
`ask_user` job is a normal valid move. Do not invent a weak CLM when a narrow
user question would resolve the uncertainty.

## Plans And Task Decomposition

When the user is discussing a plan, design direction, or sequence of work,
offer to preserve the plan if that will help future work. Use the best plan
artifact for the situation: an existing document, issue, ADR, captured user
input, `src_*`, or a lightweight `note_*`. Do not force a `note_*` for trivial
one-step work or duplicate an existing plan document.

A plan artifact should summarize or point to the goal, constraints, decisions,
risks, open questions, and user preferences. It is shared intent, not proof.

Turn an approved plan into a `task_*` tree:

1. Create or update the root task that references the plan artifact.
2. Decompose broad work into subtasks.
3. Keep decomposing until every leaf task can be completed in one agent
   iteration.
4. Give each leaf task clear acceptance criteria and expected evidence.
5. Work on the current leaf task, then finish it with support refs or say that
   no durable fact was learned.

Do not execute a broad parent task directly when it needs child tasks. A parent
task is finished by completed, cancelled, or replaced children plus a compact
summary. Proof still comes from `src_*`, `clm_*`, `rel_*`, and validated
support chains.

If you are given a leaf task directly, still read `brief.task_context.root_task`
and `priority_plan`. TEP will show higher-priority sibling leaves and jobs so
you do not get stuck polishing a convenient subtask while a blocking one waits.

## Required Retrieval Order

TEP is the durable memory, not the only place to ask questions. Before you save a fact, ask the right retrieval layer:

1. `brief` and `search_facts`: reuse existing CLM cards, tags, aggregates, and counterfacts.
2. `search_sources` and `get_source`: reuse existing `src_*`/`inp_*` evidence before ingesting the same input again.
3. `search_documents`, `get_document`, and `diff_document_versions`: inspect versioned Jira/GitLab/Rancher/docs context when the source may have changed.
4. PageIndex or another document index: for long docs, find exact sections/passages first; then ingest the excerpt as `src_*` or use an existing `src_*`.
5. `search_code`: ask TEP synced code metadata for candidate files/symbols before direct code browsing.
6. `code_navigation_status`: check whether TEP server-side code navigation is actually available before assuming it is.
7. `probe_code_navigation`: when a synced project root exists, let TEP run a scoped code-navigation probe before relying on code navigation.
8. `discover_bridges`: when more than one project/code snapshot may matter, ask TEP for cross-project bridge candidates.
9. TEP code navigation: inspect exact symbols, references, and file structure through TEP before claiming how the implementation works.
10. `learn_fact` or `relate_facts`: save only the narrow fact you actually learned, with source refs when available.
11. `check_argument`: validate the selected CLM chain before important edits, risky conclusions, or final answers.

Do not skip retrieval and then fill TEP with guesses. If `learn_fact` returns
`reuse_preflight.status=needs_reuse_check`, the CLM was accepted but TEP did not
see a recent search/reuse step. Inspect `similar_claims` and either relate the
overlap (`same_as`, `duplicates`, `different_scope`, `no_relation_for_task`) or
search again before relying on the new CLM. If PageIndex or TEP code navigation
is unavailable, say that explicitly and use the closest available TEP
read/search tool.

When TEP creates a `connect_theory_practice` job, treat it as useful pressure:
a theory/rule/guideline CLM needs practical evidence or a practical observation
needs a rule/doc/user decision. Use the job's candidate refs and suggested
`discover` query, then create positive or negative `rel_*` edges instead of
leaving the bridge implicit.

## What To Save

Create CLM facts for durable knowledge:

- project behavior that will matter again;
- user decisions, constraints, and preferences;
- source-backed rules from docs;
- observed runtime behavior after a command or test;
- contradictions, freshness concerns, or applicability limits.

Do not create CLM facts for bookkeeping such as "I ran a command", "a commit exists", or "I opened a file" unless that observation changes what future agents should believe about the system.

Use `create_note` for useful thoughts that should be remembered but are not yet
facts: code review impressions, design sketches, Obsidian-style notes, scratch
analysis, and reminders. Notes are navigation-only. Before relying on note
content as support, extract a narrow source-backed CLM or capture the exact
source/input.

Every useful CLM should be small enough to reuse. If a statement contains several independent facts, split it.

Before saving, ask:

- Is this a reusable fact, or only bookkeeping?
- What source, command output, code location, or user decision supports it?
- Is there an existing CLM or aggregate that should be reused or related instead?
- Should this become a relation, contradiction, non-applicability note, or aggregate child instead of a new standalone fact?

## Sources And Quotes

When the user gives input, a document excerpt, or a file/link summary:

1. Call `ingest_input` with `source_kind`.
2. If TEP creates an extraction job, submit candidate facts with exact quotes from the source through `submit_job_result`.
3. Use `learn_fact` only for facts you can state narrowly.

If the input was already captured by the hook, reuse that `inp_*` when the tool
returns or briefing shows it. For user decisions and confirmations, the useful
pattern is `inp_* -> clm_*`, with the `inp_*` passed as `source_refs`.

Quotes are for evidence. Your final answer still needs your own interpretation of what the facts imply.

For long documents, prefer PageIndex-style hierarchical retrieval before extraction. The useful flow is: document tree/section search -> exact excerpt -> `src_*` -> narrow `clm_*` -> relation or aggregate.

`doc_*` records are versioned navigation context, not evidence. Jira issues,
GitLab merge requests, Rancher workload snapshots, and future Confluence/docs
imports may be stored as `doc_*` with immutable versions. Use `search_documents`
to find them, `get_document` to inspect versions and linked excerpts, and
`diff_document_versions` when a document-backed source is stale. Use
`get_document_version` plus `extract_source_from_document` to create exact
line-range or quote-backed `src_*` evidence from the right immutable version.
Do not pass `doc_*` as `source_refs`; create or reuse a concrete `src_*`
excerpt before learning or revising a CLM.

## Reasoning Rules

Treat TEP fact cards as support for reasoning chains:

- Build hypotheses from trusted facts, direct observations, or explicit user assumptions.
- Do not build a hypothesis only on another unsupported hypothesis.
- If you suspect a trusted fact is stale, create an alternative hypothesis and relate it with `challenges_freshness` or `contradicts`; do not silently discard the trusted fact.
- Use `relate_facts` to record support, contradiction, applicability, non-applicability, duplicate/not-duplicate decisions, and aggregate membership.
- Use `check_argument` before important claims, risky edits, or final answers.

If `check_argument` reports weak support, either gather more evidence, narrow the claim, or tell the user the remaining gap.

When the user is the best source of truth, ask a narrow question or defer it as
a job. User answers should be captured as `inp_*` and linked to the relevant
CLM. A user confirmation can make a CLM a user-confirmed hypothesis; it does not
turn an external fact into theory-proven truth.

## Search And Briefing

Use `search_facts` before inventing a rule from memory. Search by:

- task keywords;
- project/domain names;
- tags such as `coding_guidelines`, `testing`, `domain_theory`, `user_preference`, `runtime_observation`;
- suspected counter-facts.

TEP search returns compact fact cards first. Open `get_fact` only when you need sources, relations, children of an aggregate, or contradiction details.

Use `search_notes` when you need remembered review thoughts or scratch context.
Do not pass `note_*` refs to `check_argument` as support; notes can guide
retrieval, but only `clm_*` chains support conclusions.

Use `walk_graph(start_ref=...)` when you need to move through the reasoning DAG
around a fact. Use `mode="neighborhood"` to inspect nearby facts,
`mode="path"` with `target_ref` to inspect a candidate support path,
`mode="community"` to see tag clusters, and `projection="glyph|phrase|card"`
to control token load. Graph walk is navigation only; call `get_fact` and
`check_argument` before relying on a chain.

Use `prepare_reasoning_chain` when you need a compact candidate support chain
for the current task, query, target CLM, or selected CLM refs. Treat its output
as a prepared argument draft: inspect gaps and suggested moves, repair missing
sources or relations, then call `check_argument` before relying on the chain.

When code behavior is involved, stay inside TEP code-navigation tools. TEP remembers "what we know" and should mediate adapter-backed answers about where behavior is implemented and referenced.

Use `search_code(query=...)` before broad code exploration when code has been synced. Treat results as navigation: they identify candidate files, symbols, snapshots, and previews. Read each result's `code_navigation` block or call `code_navigation_status` before assuming code navigation is available. If a synced project root exists, call `probe_code_navigation` to let TEP run a scoped adapter health check. If server-side code navigation is not active or probe fails, use `get_snapshot_file`, local file reads, or the available TEP code tool for exact inspection, then cite code ranges before creating CLM about implementation behavior.

When a fact depends on synced code, prefer `cite_code_range(snapshot_ref, path,
start_line, end_line)` to create a `src_*` code excerpt. `get_snapshot_file`
is navigation only; it helps replay what code was in a snapshot, but it is not
support until a `src_*` excerpt exists. In the 0.12 Docker beta, new `snap_*`
records are expected to be backed by Mirage when `status.snapshot_store.backend`
is `mirage`; use `restore_snapshot` when you need to prove that a synced code
snapshot can reconstruct the observed tree.

Use `diff_snapshots(left_snapshot_ref, right_snapshot_ref)` when checking
whether a code-backed fact may be stale. The diff is navigation only; cite exact
changed ranges before creating or updating CLM.

Use `discover_bridges(project_refs=[...], query=...)` when a task may involve multiple projects. Bridge candidates are navigation only: inspect both sides, capture exact excerpts as `src_*`, create one local CLM per side, then create `relate_facts` with `possible_relation_between`, `syncs_object`, `consumes_api`, `applies_to`, or a negative relation such as `no_relation_for_task` / `different_scope`.

Do not use a bridge candidate as final support. It becomes useful support only after exact source excerpts and explicit CLM/REL records exist.

## Aggregates

Aggregated facts are ordinary `clm_*` records with an `aggregate` payload. Use them to compress many related facts into one reusable briefing item.

When `brief` shows aggregate pressure:

1. Create or complete a `propose_aggregate` job.
2. The aggregate must name the child CLM refs, the summary, limits, and known exceptions.
3. Relate children to the aggregate.

If a child fact becomes contradicted or low-trust, do not trust the aggregate blindly. Open the detail and repair or narrow the aggregate.

## Commands

Prefer the local client for process capture when available:

```bash
tep-client run-capture --cwd . -- pytest ...
```

If `tep-client` is not installed on PATH, use the plugin wrapper:

```bash
/Users/kaor4bp/PycharmProjects/tep/plugins/tep/scripts/tep-client run-capture --cwd . -- pytest ...
```

By default `run-capture` streams bounded live stdout/stderr plus occasional
heartbeat lines, then stores the captured output as `src_*` and returns a TEP
digest. Do not infer that a process is hung from silence alone; wait for the
heartbeat, command timeout, or explicit failure. Use `--quiet` only when you
really want digest-only behavior.

Useful variants:

```bash
tep-client run-capture --cwd . --heartbeat-seconds 10 -- pytest ...
tep-client run-capture --cwd . --live-output-lines 800 -- npm test
tep-client run-capture --cwd . --quiet -- pytest -q
```

If you already have command output, call `capture_run`.

`capture_run` returns a digest, not raw output: `source_ref`, summary, important lines, failure hint, learning pressure, suggested facts, and suggested moves. Raw output is stored under `src_*` and should be opened only when the digest is insufficient.

After a command, save a CLM only when the output taught durable behavior. A test failure can be useful; a generic "pytest ran" fact is usually noise. If `learning_pressure.level` is `medium` or `high`, either create a narrow source-backed CLM or explicitly decide that no durable fact was learned. Connect useful run CLM to the reasoning DAG with `relate_facts`.

## Feedback

Use `record_feedback` when a TEP record helped or misled you in practice. This
is especially useful after finishing a leaf task or after discovering that a
fact was stale, too broad, wrong scope, noisy, or duplicate.

Feedback is a rank/utility signal, not proof. A useful mark does not make a CLM
true, and a dislike does not globally ban it. TEP computes where the feedback
applies from task, project, tag, session, and graph context.

## Final Answer

Before finalizing:

1. Call `brief(session_ref=...)`.
2. Check `brief.job_pressure`; inspect or resolve submitted jobs with warnings
   when they affect the conclusion.
3. Call `prepare_reasoning_chain` or select the CLM refs that actually support the answer.
4. Call `check_argument(claim_refs=[...], mode="final")`.
5. Call `finish(session_ref=..., support_refs=[...], outcome="...")`.

In the final answer, show a short support chain when it helps the user verify you:

```text
clm_...: "short quote" -> my interpretation.
clm_...: "short quote" -> my interpretation.
```

If TEP says support is weak, say what is missing instead of pretending the chain is proven.
