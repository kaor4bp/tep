# Storage

> Historical local-filesystem prototype note. The active server-centered beta
> stores canonical fact-plane records through the configured backend
> (TerminusDB in Docker beta), keeps caches in Valkey when configured, and uses
> Mirage artifacts for snapshots. Use this file only to understand legacy
> quarantine and local pointer ideas unless a section explicitly names the
> server backend.

TEP stores local protocol state under `~/.tep` by default. The local project
pointer is a small `.tep` file in a repo:

```json
{
  "tep_home": "~/.tep",
  "project_ref": "prj_*",
  "mcp_server": "stdio"
}
```

The pointer is not a fact store. It names the TEP home, the default project for
the repo, and the preferred MCP transport.

## Layout

```text
~/.tep/
  settings.json
  registry/
    projects/prj_*.json
  records/
    sources/
      source_events.jsonl
      YYYY/MM/src_*.json
    claims/
      YYYY/MM/clm_*.json
    runs/
      YYYY/MM/run_*.json
    inputs/
      YYYY/MM/inp_*.json
  tasks/
    task_*/
      task.json
      settings.json
      ledgers/agent_*.jsonl
      context/<kind>/CTX-*.json
      context/<kind>/CTX-*.md
      artifacts/
  agents/
    agent_*/agent.json
  runtime/
    sessions/<thread_hash>.json
    journal/*.jsonl
    tx/
  indexes/
  maps/
  quarantine/
```

`src_*`, `clm_*`, `run_*`, and `inp_*` records are global and sharded by id date.
Visibility is computed from the current task and project refs, not from a
workspace directory.

## Legacy Quarantine

TEP keeps active workspace storage removed. If the runtime sees old:

```text
~/.tep/workspaces/
~/.tep/registry/workspaces/
```

it moves them into:

```text
~/.tep/quarantine/legacy-workspaces-<timestamp>/
```

The quarantine is not replayed as active protocol state. Old ledgers with old
signatures should not block new task ledgers.

## Transactions And Journals

Multi-record operations use `runtime/tx/TX-*` staging. A transaction preflights
all staged writes and then commits the files as one logical mutation. Empty
directories created during preparation are not considered protocol records.

Committed transactions are summarized in `runtime/journal/transactions.jsonl`.
MCP calls and results are summarized in `runtime/journal/mcp_calls.jsonl` and
`runtime/journal/mcp_results.jsonl`; private keys are redacted before writing.

## Zones

Canonical records:

- `registry/projects`
- `records/sources`
- `records/claims`
- `records/runs`
- `records/inputs`
- `tasks/*/task.json`
- `tasks/*/ledgers`
- `agents/*/agent.json`

Runtime/generated records:

- `runtime/sessions`
- `runtime/journal`
- `runtime/tx`
- `indexes`
- `maps`
- `tasks/*/context`
- `tasks/*/artifacts`

Quarantine:

- legacy WSP storage
- damaged or intentionally excluded old protocol data
