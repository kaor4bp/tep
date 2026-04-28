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
7. Call `brief_current_context`.
8. If the current user message contains task facts or instructions that should
   survive the chat, call `capture_input`.
9. Read the `settings.enforcement` block in the briefing. It controls whether
   Bash/edit actions are advisory, classified, or ACT-gated.
10. If a task is active, check `compiled_context.execution_state`. Do not work
    on the task until all required `CTX-*` packs exist.

Do not create a new `WSP-*` just because a new agent session starts. Reuse the
workspace already attached to the local `.tep` `project_ref`; when calling
`create_workspace`, pass `project_ref` so TEP can return the existing workspace
instead of creating a duplicate.

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
at `~/.tep/workspaces/WSP-*/settings.json`. Use typed tools only:

- `read_settings`
- `update_settings`
- `action_pressure`

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

Before Bash or file edits, check the current briefing or call
`action_pressure`. If the action is blocked or ACT-required, use
`open_probe -> protected_action_preflight -> execute -> capture_probe_result ->
close_probe`. Hooks cannot open ACT for you because `agent_private_key` exists
only in the agent's memory.

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

Use typed tools:

- `compile_context_pack`
- `list_context_packs`
- `revoke_context_pack`

`compile_context_pack` takes selected `CLM-*`/`SRC-*` support refs and the
agent-written markdown text. It can compile task-scoped packs with `task_ref`,
project-scoped packs with `project_ref`, or global workspace packs with neither.
`task_briefing` must be task-scoped. Other required kinds may be satisfied by
task, visible project, or global packs, so reusable guidelines/theory should be
compiled once at project/global scope and only loaded by the agent when needed.
When a new `CLM-*` or relation is created, overlapping active context packs are
marked `stale`: task-scoped claims stale that task, project-scoped claims stale
that project plus task packs for tasks in that project, and unscoped workspace
claims stale global packs. Recompile stale CTX text from current facts before
using it as task guidance.

TEP writes metadata plus a `.md` file under the workspace artifacts directory
and returns the file path in the briefing. Required context packs gate task
execution: ACT opening, protected preflight, task-bound Bash, task completion,
and task final preflight are blocked until required active packs exist. Setup
operations such as lookup, source capture, claim creation, and context
compilation remain available.

## Source Capture

When the user provides a document, file path, URL content, pasted text, or
important instruction, capture it before deriving claims:

- Use `ingest_file` for a local file path.
- Use `ingest_text` for pasted document content.
- Use `capture_source_excerpt` to capture the exact quote/span for each
  document-backed fact before creating a `CLM-*`.
- Use `capture_input` for user instructions, assumptions, corrections, and
  approvals.
- Use `capture_bash_command` after running a command.
- Use `capture_run_output_source` to turn relevant RUN output into SRC evidence.

Do not create CLM facts directly from a whole document source. For uploaded
documentation, extract one atomic quote into an excerpt `SRC-*`, then create one
atomic CLM from that excerpt. If no useful facts should be extracted, record
that as a bounded decision instead of inventing claims.

Secrets are not ignored. TEP may encrypt sensitive payload fields with the host
key. Only call `decrypt_sensitive_field` when the task genuinely needs the
plaintext.

## Claims And Trust

Create `CLM-*` records through `create_claim` or `link_claims`. TEP schemas do
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
- To challenge a trusted fact, create an alternate probe branch; do not silently
  discard the trusted fact.
- Use `link_claims` for support, contradiction, applicability, dependency,
  equivalence, duplicate, and revision reasoning.

For foreign/example project facts, treat lookup results as navigation until a
ledgered applicability relation connects them to the current scope. Do not link
two project scopes unless both are visible in the current workspace. When a
bridge is needed, prefer explicit bridge context: `general`, `task`, or
`object_sync` with the concrete synchronized object.

## Ledger And ACT Flow

Use `append_ledger` to commit selected claim snapshots into the current
agent-owned reasoning ledger. The ledger seal binds the row payload, ledger
context, previous branch row, previous physical append row, cited CLM revision
hash, and calibrated weak PoW. Failed appends write nothing.

Use ACT records when an action may change protected state or when a hypothesis
needs an evidence-producing probe:

1. `open_probe` with the claim, intent, allowed action kind, and expected evidence.
2. `protected_action_preflight` before the protected command or mutation.
3. Execute the action only if preflight allows it.
4. Capture the result as source evidence.
5. `capture_probe_result`.
6. `close_probe`.

ACT is for the next bounded action, not for laundering old observations into
permission. Open ACT against a narrow action intent or probe hypothesis such as
“run pytest to inspect current auth behavior” or “verify whether fact X is
stale in this checkout”. Do not open ACT against broad historical summaries,
mechanical command observations, or claims that only say a previous run had some
result. Such observations should remain `RUN-*`/`SRC-*` evidence or become
separate system-behavior CLM facts before they guide a new probe.

ACTs expire according to `settings.enforcement.act_timeout_seconds`. If an ACT
expires, close it or open a fresh ACT with a current intent before protected
work.

Final answers should call `final_answer_preflight` with the selected support
refs. Task completion should call `task_done_preflight`. Do not present blocked
support as final truth.

## Let TEP Reduce Thinking Load

Use TEP responses as steering signals. On successful responses and errors, look
at `ledger_pressure`, `claim_pressure`, `source_pressure`, `dedup_pressure`,
`repair_options`, `valid_moves`, blockers, and trust posture. These are
candidate valid moves; choose the one that best matches the task instead of
inventing a bypass.

When `claim_pressure` asks analysis questions, answer them by creating narrower
`CLM-*` records and linking them to the broader claim. Prefer one point fact per
claim. Do not hide observations, inference, applicability, and uncertainty in a
single heavy statement.

Good default loop:

1. Brief context.
2. Lookup relevant facts.
3. Capture new inputs or observations.
4. Create/link claims.
5. Append supported reasoning.
6. Open and close probes for uncertain or protected work.
7. Validate ledger before final answer or task done.
