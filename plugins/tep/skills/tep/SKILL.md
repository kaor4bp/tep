---
name: tep
description: Use Trust Evidence Protocol (TEP) when a Codex task should capture user inputs, files, command observations, claims, probes, or final-answer support in a local fact ledger instead of relying only on chat memory.
metadata:
  short-description: Use TEP fact ledgers
---

# Trust Evidence Protocol

Use this skill when the user asks to use TEP, preserve facts across agents,
record sources, inspect project memory, run evidence-backed probes, or produce a
final answer that should be checked against local fact support.

## Transport

TEP stores data under the configured `tep_home`, normally `~/.tep`. A repo may
also contain a local `.tep` pointer:

```json
{
  "tep_home": "~/.tep",
  "project_ref": "PRJ-*",
  "mcp_server": "stdio|http://127.0.0.1:8765"
}
```

Prefer HTTP when `mcp_server` is an HTTP URL:

- `GET /health`
- `GET /tools`
- `POST /call` with `{"name":"tool_name","arguments":{...}}`

For Codex MCP integration, prefer the plugin MCP server `tep`, backed by
`tep-mcp`. It exposes the same typed tools through MCP `tools/list` and
`tools/call`.

For local JSONL debug transport, send:

```json
{"method":"tools/list"}
{"method":"tools/call","params":{"name":"tool_name","arguments":{}}}
```

Both transports are thin wrappers over typed tools. Do not edit `~/.tep` files
directly and do not invent raw JSON mutation paths.

Public agent tools are intentionally small:

- `brief`: load current task, context packs, ledger chain, trust index, gaps,
  and valid public moves.
- `capture`: capture user input, text, files, command observations, excerpts,
  fragments, or extraction candidates as evidence.
- `task`: create/attach/decompose/defer tasks and compile/list/revoke task
  context packs.
- `claim`: register one atomic or aggregate `CLM-*` from explicit `based_on`
  refs.
- `relate`: create a relation `CLM-*` explaining support, contradiction,
  applicability, dependency, freshness, or equivalence.
- `reason`: append a selected `CLM-*` into the long-term reasoning ledger.
- `act`: open, capture, close, or preflight a bounded probe.
- `lookup`: search reusable facts and trust posture.
- `finish`: check final answer, task done, or deferral against selected CLM
  support.

Older low-level tool names may exist for internal compatibility, but the normal
agent path should use the public tools above.

## Session Start

At the beginning of a TEP-backed task:

1. Check local hook visibility with `plugins/tep/scripts/check-local-hooks.py`.
   Treat failures as setup blockers for automatic capture, not as permission to
   bypass typed TEP tools. Report the smallest repair step.
2. Read the local `.tep` pointer if present.
3. Confirm whether `mcp_server` is HTTP or stdio. HTTP is useful for standalone
   servers; stdio is valid for Codex MCP and hook fallback.
4. Call `generate_agent_identity` if this thread does not already hold an
   in-memory identity.
5. Keep `agent_private_key` only in memory for the current agent session.
6. Call `start_agent_thread`.
7. Call `brief`.
8. If the current user message contains task facts or instructions that should
   survive the chat, call `capture` with `capture_kind="input"`.
9. Read the `settings.enforcement` block in the briefing. It controls whether
   Bash/edit actions are advisory, classified, or ACT-gated.
10. If a task is active, check `compiled_context.execution_state`. Do not work
    on the task until all required `CTX-*` packs exist.

After the briefing, write a short visible TEP briefing for the user before
doing substantial work:

- Guidelines/context packs you will apply, by `CTX-*` ref or file path when
  available.
- Current task/question from `task.goal` and `working_argument.current_question`.
- Current fact chain: at most 3-5 relevant `CLM-*` refs, each with a short
  quote/snippet and one-line interpretation of what it means for this task.
  Prefer `working_argument.compact_claim_chain` when present.
- Evidence leaves: key `SRC-*`/`RUN-*` refs, if any.
- Gaps/uncertainties from `working_argument.gaps`.

Keep it compact. The goal is to make your reasoning anchor visible, not to dump
all records. If no useful CLM chain exists, say that explicitly and start by
looking up or capturing facts instead of inventing a chain.

Do not show bare `CLM-*` ids to the user. User-facing support should look like
`CLM-...: "short quote" -> my interpretation`. The quote may come from the
claim's source excerpt or, if no source quote is available, a compact statement
snippet. This keeps the chain auditable without forcing the user to open raw
records.

Do not create a new `WSP-*` just because a new agent session starts. Reuse the
workspace already attached to the local `.tep` `project_ref`. If no workspace
can be resolved from the project pointer, treat that as setup work instead of
silently creating duplicate workspaces.

`AGENT-*` is a live thread/session, not a reusable personality. Do not continue
another agent's ledger with this thread's key. Foreign ledgers are readable for
coordination but appendable only by their owner identity.

The plugin ships Codex hook adapters for `SessionStart`, `UserPromptSubmit`,
`PreToolUse`, `PostToolUse`, and `Stop`. Hooks are conservative: they check
visibility, block direct `.tep` writes, best-effort capture prompts and Bash
runs through HTTP or local stdio fallback, capture Bash results as `RUN-*` and
`SRC-*`, derive only narrow recognized observation claims, and apply enforcement
settings before Bash execution. Do not treat a captured command as a system
fact by itself: create `CLM-*` only when you can state what you learned about
the system. Explicit MCP/tool calls remain the reliable path. Hooks cannot
append sealed ledger rows without the current agent's in-memory private key;
agents must still ledger support claims explicitly.

## Enforcement Settings

TEP settings live under `~/.tep/settings.json` with optional workspace override
at `~/.tep/workspaces/WSP-*/settings.json`. Read settings from `brief`. Use
legacy settings tools only for explicit administration/debugging.

Default enforcement is `balanced`:

```json
{
  "enforcement": {
    "mode": "off|advisory|balanced|strict",
    "session_start_requires_frame": false,
    "bash_policy": "capture_only|classify|act_for_evidence|act_for_all",
    "edit_policy": "advisory|act_required",
    "final_policy": "advisory|preflight_required",
    "unknown_action_policy": "allow_with_pressure|block_until_act",
    "context_requirements": {
      "task_briefing": "required|on_demand|optional|disabled",
      "coding_guidelines": "required|on_demand|optional|disabled",
      "domain_theory": "required|on_demand|optional|disabled",
      "project_conventions": "required|on_demand|optional|disabled"
    }
  }
}
```

Before Bash or file edits, check the current briefing. If the action is blocked
or ACT-required, use `act(open) -> execute -> act(capture) -> act(close)`. The default
hook gate only checks that a matching open ACT exists in the ledger and has not
expired under `settings.enforcement.act_timeout_seconds` (default 300 seconds).
Use `protected_action_preflight` only when a strict/audited flow explicitly
needs to bind a concrete action hash before execution. Hooks cannot open ACT for
you because `agent_private_key` exists only in the agent's memory.

Strict mode requires all base task context kinds unless overridden in settings:
`task_briefing`, `coding_guidelines`, `domain_theory`, and
`project_conventions`. Balanced mode requires `task_briefing` and leaves the
others on demand by default. Advisory mode makes all context kinds on demand.

## Task Context Packs

Task-scoped context is stored as plain text `CTX-*` markdown artifacts. Use
separate files by kind so the agent can load only what it needs:

- `task_briefing`
- `coding_guidelines`
- `domain_theory`
- `project_conventions`

Use `brief` to discover active/stale context packs. Low-level context
compilation is exposed through `task` with `task_action="compile_context"`.

Context pack compilation takes selected `CLM-*`/`SRC-*` support refs and the
agent-written markdown text. Packs may be task-scoped, project-scoped, or global
workspace packs. `task_briefing` must be task-scoped. Other required kinds may
be satisfied by task, visible project, or global packs, so reusable
guidelines/theory should be compiled once at project/global scope and only
loaded by the agent when needed. When a new `CLM-*` or relation is created,
overlapping active context packs are marked `stale`: task-scoped claims stale
that task, project-scoped claims stale that project plus task packs for tasks in
that project, and unscoped workspace claims stale global packs. Recompile stale
CTX text from current facts before using it as task guidance.

TEP writes metadata plus a `.md` file under the workspace artifacts directory
and returns the file path in the briefing. Required context packs gate task
execution: ACT opening, protected preflight, task-bound Bash, task completion,
and task final preflight are blocked until required active packs exist. Setup
operations such as lookup, source capture, claim creation, and context
compilation remain available.

## Source Capture

When the user provides a document, file path, URL content, pasted text, or
important instruction, capture it before deriving claims:

- Use `capture` with `capture_kind="file"` for a local file path.
- Use `capture` with `capture_kind="text"` for pasted document content.
- Use `capture` with `capture_kind="source_fragments"` when an ingested document is too large to
  inspect reliably as one source. Fragments are navigation units, not proof by
  themselves.
- Use `capture` with `capture_kind="confirm_source"` only after capturing explicit user
  confirmation that a source has a given class/scope. This records an accepted
  source event; it does not replace exact quote extraction for document facts.
- Use `capture` with `capture_kind="extract_claim_candidates"` when deriving facts from a document: propose
  candidate `{quote, statement}` pairs so TEP can verify the quote exists and
  create excerpt evidence.
- Use `capture` with `capture_kind="source_excerpt"` to capture the exact quote/span for each
  document-backed fact before creating a `CLM-*` when you are doing the excerpt
  step manually.
- Use `claim` for document-backed CLMs after excerpt evidence exists. It
  requires explicit `based_on` refs and rejects broad compound statements.
- Use `capture` with `capture_kind="input"` for user instructions, assumptions, corrections, and
  approvals.
- Use `capture` with `capture_kind="bash"` after running a command.
- Use `capture` with `capture_kind="run_output"` to turn relevant RUN output into SRC evidence.
- Use `capture` with `capture_kind="extract_run_claim_candidates"` after tests or other evidence-producing
  commands when the output taught you something: propose exact output quotes
  plus atomic statements, then call `claim`.

Do not create CLM facts directly from a whole document source or from a
document fragment. For uploaded documentation, extract one atomic quote into an
excerpt `SRC-*`, then create one atomic CLM from that excerpt. Prefer the short
path: `capture(file) -> capture(extract_claim_candidates) -> claim`.
For long documents, use `capture(source_fragments)` first, then run
`capture(extract_claim_candidates)` on selected fragments. If no useful facts should be
extracted, record that as a bounded decision instead of inventing claims.
If the uploaded document's authority is ambiguous, ask the user and capture the
answer with `capture(input)`, then confirm the source scope with that
`INP-*` as `confirmation_ref`.

For test and command evidence, do not stop at “pytest ran” or “command exited”.
Use `capture(extract_run_claim_candidates)` for exact stdout/stderr quotes that
reveal a system fact, then commit one narrow CLM per useful observation. If the output is
only a smoke result and teaches nothing durable, leave it as `RUN-*`/`SRC-*`.

Secrets are not ignored. TEP may encrypt sensitive payload fields with the host
key. Only call `decrypt_sensitive_field` when the task genuinely needs the
plaintext.

## Claims And Trust

Create `CLM-*` records through `claim` or `relate`. TEP schemas do
not store fixed claim status such as hypothesis/trusted/disputed. Public labels
are runtime evaluations from relations, source classes, and support diversity.

Why this matters: TEP is how you keep what you learn about the concrete system
from evaporating when the chat moves on or another agent joins. Do not only
record that a command ran. Record durable system knowledge: behavior, contracts,
implementation facts, constraints, failure modes, assumptions, and verified
corrections.

Use this mental model:

- Observation: captured evidence from a user message, file, command, test, log,
  artifact, URL, or MCP result. It belongs in `SRC-*`/`RUN-*` first. By itself,
  it is evidence, not a reusable system fact.
- Claim/fact candidate: a `CLM-*` statement of what the observation means about
  the system. Good CLM examples are narrow: “module X reads setting Y from
  file Z”, “test A fails because API B returns 500”, “flow C requires D before
  E”. Avoid mechanical CLM such as “command exited with code 0”.
- Hypothesis: a `CLM-*` whose trust posture is still weak or exploratory. It
  must be grounded in observations, trusted facts, or user-confirmed working
  assumptions, and it must not become the basis for another hypothesis.
- Trusted fact: a derived runtime posture, not stored status. A CLM becomes
  answer/protected-action usable only through sufficient source support,
  relation support, user confirmation, and ledger posture.
- Relation: a `CLM-*` edge explaining how claims connect: support,
  contradiction, dependency, applicability, equivalence, duplicate, induction,
  deduction, abduction, assumption, possible relation, or freshness challenge.
- Aggregate: a `CLM-*` with `claim_form="aggregate"` that summarizes a group of
  existing `CLM-*` records to reduce repeated lookup/token load. It must name
  `aggregation.underlying_refs` and `aggregation.limits`. Its trust is computed
  from the underlying claims; it cannot make weak leaves trusted by wording the
  summary confidently.

When you learn something, ask:

1. What did I observe?
2. What system fact does that imply?
3. Is it a fact, a hypothesis, or a freshness challenge?
4. What source supports it?
5. Does it need a relation to existing CLM-*?
6. Should it be split into smaller point facts?

Rules:

- A runtime-only claim remains hypothesis-like even if repeated many times.
- User confirmation, documents, theory, or observed sources can improve trust.
- Do not build a hypothesis on an unsupported hypothesis.
- Use aggregates when several stable point facts are repeatedly needed in the
  same task, but keep their limits narrow and inspect `aggregate.weakest_refs`
  before relying on them.
- To challenge a trusted fact, create an alternate probe branch; do not silently
  discard the trusted fact.
- Use `relate` for support, contradiction, applicability, dependency,
  equivalence, duplicate, and revision reasoning.

For foreign/example project facts, treat lookup results as navigation until a
ledgered applicability relation connects them to the current scope. Do not link
two project scopes unless both are visible in the current workspace. When a
bridge is needed, prefer explicit bridge context: `general`, `task`, or
`object_sync` with the concrete synchronized object.

## Building Logical Chains

Build arguments as explicit, inspectable chains. A useful chain has this shape:

```text
SRC/RUN/INP observation -> CLM point fact -> relation CLM -> task conclusion
```

Do not skip the relation step when the conclusion depends on more than one
claim, crosses project scope, challenges an older fact, or uses an inference
rather than a direct quote/observation. The relation is the place where you
state why the link is valid.

Use predictable inference patterns:

- Deduction: trusted rule/policy plus observed case implies a specific result.
- Induction: several independent observations suggest a pattern, but the result
  remains hypothesis-like until supported by theory, documentation, or user
  confirmation.
- Abduction: facts make one explanation plausible; use it only to plan a probe,
  not as final support.
- Applicability: a fact from another project/scope applies here because a
  bridge relation names the shared interface, task, or synchronized object.
- Freshness challenge: a trusted fact may be stale; keep the old branch and open
  an alternate probe branch instead of replacing it silently.
- Contradiction: two claims cannot both guide the same task as-is; create a
  relation that states the conflict and what evidence would resolve it.

Stop the chain when the next step would require a hypothesis built only on
another hypothesis. At that point, open an ACT for a bounded probe, capture more
evidence, ask the user for an assumption/confirmation, or leave the gap visible.

Before final/task-done support, read the chain backwards:

1. What conclusion am I about to rely on?
2. Which `CLM-*` directly supports it?
3. Which relation explains the support, contradiction, applicability, or
   freshness reasoning?
4. Which `SRC-*`, `RUN-*`, or `INP-*` evidence anchors the leaf claim?
5. Is any link only runtime repetition, command bookkeeping, or an unsupported
   hypothesis?

If the answer to step 5 is yes, do not present the chain as trusted final
support. Either mark the gap in the visible support summary or gather stronger
evidence first.

## Ledger And ACT Flow

Use `reason` to commit selected claim snapshots into the current
agent-owned reasoning ledger. The ledger seal binds the row payload, ledger
context, previous branch row, previous physical append row, cited CLM revision
hash, and calibrated weak PoW. Failed appends write nothing.

Use ACT records when an action may change protected state or when a hypothesis
needs an evidence-producing probe:

1. `act(open)` with the claim, intent, allowed action kind, and expected evidence.
2. Execute the action while the ACT is still fresh.
3. Capture the result as source evidence.
4. `act(capture)`.
5. `act(close)`.

`protected_action_preflight` remains available for stricter audits, but it is
not the default requirement for ordinary Bash hook admission.

ACT is for the next bounded action, not for laundering old observations into
permission. Open ACT against a narrow action intent or probe hypothesis such as
“run pytest to inspect current auth behavior” or “verify whether fact X is
stale in this checkout”. Do not open ACT against broad historical summaries,
mechanical command observations, or claims that only say a previous run had some
result. A narrow retry claim is valid when it states that the previous attempt
failed/did not finish and names the bounded check to try again. Otherwise such
observations should remain `RUN-*`/`SRC-*` evidence or become separate
system-behavior CLM facts before they guide a new probe.

ACTs expire according to `settings.enforcement.act_timeout_seconds`. If an ACT
expires, close it or open a fresh ACT with a current intent before protected
work.

Final answers should call `finish` with selected `CLM-*` support
refs. `SRC-*`/`RUN-*` evidence must first be converted into a claim. Task
completion should call `finish` with `finish_kind="task_done"`. Do not present blocked support as
final truth.

At the end of a TEP-backed task, include a short visible support summary before
or inside the final answer:

- `CLM-*` refs you actually relied on, each with a short quote/snippet.
- Your interpretation of those claims in plain language.
- `SRC-*`/`RUN-*` evidence that matters.
- Remaining gaps, unsupported runtime observations, or assumptions.

Do not hide behind “tests passed” or “commit created”. Explain which system
fact, contract, behavior, or task outcome those observations support.

## Let TEP Reduce Thinking Load

Use TEP responses as steering signals. On successful responses and errors, look
at `ledger_pressure`, `claim_pressure`, `source_pressure`, `dedup_pressure`,
`working_argument.chain_trust_index`, `repair_options`, `valid_moves`, blockers, and trust
posture. These are candidate valid moves; choose the one that best matches the
task instead of inventing a bypass.

`brief` returns `working_argument`: the current task question,
recent ledgered CLM chain, evidence leaves, and gaps. Read it before protected
work and after evidence-producing commands. If it says the current chain is
mostly bookkeeping, do not create another command/commit CLM; either leave the
observation as RUN/SRC evidence or extract the durable system fact it supports.
If `chain_trust_index.label` is `low`, say plainly that the ledger may be
formally valid but weak, then strengthen the chain before relying on it.

When `claim_pressure` asks analysis questions, answer them by creating narrower
`CLM-*` records and linking them to the broader claim with `relate`. Prefer one point fact per
claim. Do not hide observations, inference, applicability, and uncertainty in a
single heavy statement. If `claim_pressure` says a CLM looks like execution
bookkeeping, use it as evidence, not as the center of the argument.

When lookup/briefing returns many related point facts, reduce token load by
creating or reusing a narrow aggregate `CLM-*`:

- Use only visible underlying `CLM-*` refs, normally facts you already inspected.
- Include `aggregation.limits` in plain language.
- Treat the aggregate as a compact handle for the chain, not as stronger proof.
- Expect lookup to prefer aggregates over matching children. Expand
  `aggregate_drilldown.underlying_refs` with `record_detail` when you need leaf
  evidence, weakest refs, or exact quotes.
- If `trust_posture.aggregate.weakest_refs` names weak leaves, strengthen those
  leaves with sources or relations before final/protected reliance.

Good default loop:

1. Brief context.
2. Lookup relevant facts.
3. Create/attach/decompose task scope or compile missing task context with
   `task` when briefing says task context is missing.
4. Capture new inputs or observations.
5. Create claims and relations.
6. Append supported reasoning with `reason`.
7. Open and close probes for uncertain or protected work.
8. Validate ledger before final answer or task done.
