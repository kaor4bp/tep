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

For local JSONL stdio transport, send:

```json
{"method":"tools/list"}
{"method":"tools/call","params":{"name":"tool_name","arguments":{}}}
```

The transport is a thin wrapper over typed tools. Do not edit `~/.tep` files
directly and do not invent raw JSON mutation paths.

## Session Start

At the beginning of a TEP-backed task:

1. Check local hook visibility with `plugins/tep/scripts/check-local-hooks.py`.
   Treat failures as setup blockers for automatic capture, not as permission to
   bypass typed TEP tools. Report the smallest repair step.
2. Read the local `.tep` pointer if present.
3. Confirm whether `mcp_server` is HTTP or stdio. Prefer HTTP for standalone
   hook capture; stdio is still valid for explicit local tool calls.
4. Call `generate_agent_identity` if this thread does not already hold an
   in-memory identity.
5. Keep `agent_private_key` only in memory for the current agent session.
6. Call `start_agent_thread`.
7. Call `brief_current_context`.
8. If the current user message contains task facts or instructions that should
   survive the chat, call `capture_input`.

`AGENT-*` is a live thread/session, not a reusable personality. Do not continue
another agent's ledger with this thread's key. Foreign ledgers are readable for
coordination but appendable only by their owner identity.

The plugin ships Codex hook adapters for `SessionStart`, `UserPromptSubmit`,
`PreToolUse`, `PostToolUse`, and `Stop`. Hooks are conservative: they check
visibility, block direct `.tep` writes, and best-effort capture prompts and Bash
runs only when a local `.tep` pointer, HTTP transport, and `TEP_WORKSPACE_REF`
are available. Explicit MCP/tool calls remain the reliable path.

## Source Capture

When the user provides a document, file path, URL content, pasted text, or
important instruction, capture it before deriving claims:

- Use `ingest_file` for a local file path.
- Use `ingest_text` for pasted document content.
- Use `capture_input` for user instructions, assumptions, corrections, and
  approvals.
- Use `capture_bash_command` after running a command.
- Use `capture_run_output_source` to turn relevant RUN output into SRC evidence.

Secrets are not ignored. TEP may encrypt sensitive payload fields with the host
key. Only call `decrypt_sensitive_field` when the task genuinely needs the
plaintext.

## Claims And Trust

Create `CLM-*` records through `create_claim` or `link_claims`. TEP schemas do
not store fixed claim status such as hypothesis/trusted/disputed. Public labels
are runtime evaluations from relations, source classes, and support diversity.

Rules:

- A runtime-only claim remains hypothesis-like even if repeated many times.
- User confirmation, documents, theory, or observed sources can improve trust.
- Do not build a hypothesis on an unsupported hypothesis.
- To challenge a trusted fact, create an alternate probe branch; do not silently
  discard the trusted fact.
- Use `link_claims` for support, contradiction, applicability, dependency,
  equivalence, duplicate, and revision reasoning.

For foreign/example project facts, treat lookup results as navigation until a
ledgered applicability relation connects them to the current scope.

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

Final answers should call `final_answer_preflight` with the selected support
refs. Task completion should call `task_done_preflight`. Do not present blocked
support as final truth.

## Let TEP Reduce Thinking Load

Use TEP responses as steering signals. On successful responses and errors, look
at `ledger_pressure`, `repair_options`, `valid_next_operations`, blockers, and
trust posture. These are candidate valid moves; choose the one that best matches
the task instead of inventing a bypass.

Good default loop:

1. Brief context.
2. Lookup relevant facts.
3. Capture new inputs or observations.
4. Create/link claims.
5. Append supported reasoning.
6. Open and close probes for uncertain or protected work.
7. Validate ledger before final answer or task done.
