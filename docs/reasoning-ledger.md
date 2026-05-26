# Reasoning Ledger

> Historical 0.9/0.10 design note. The active 0.12 proof primitive is
> `chain_*` over `clm_*`/`rel_*`/`src_*` evidence. Do not use this document as
> the current agent-facing MCP contract.

The ledger is the long-term logical chain for one `task_*` and one `agent_*`:

```text
~/.tep/tasks/task_*/ledgers/agent_*.jsonl
```

It is append-only JSONL. Branches are represented by `prev`; physical file order
is represented by `append_prev`. There is no separate branch record.

## Row Kinds

- `claim`: selected claim support
- `relation`: selected relation support
- `act`: open bounded probe
- `capture`: evidence captured for the open probe
- `close_act`: close the probe

Rows can include:

- `argument_role`
- `branch_note`
- `supersedes`
- `rejects_refs`

These are metadata for reasoning, not separate canonical branch entities.

## CLM Revisions

CLM revision exists only in the ledger. A `clm_*` file is the current global
claim record. When a ledger snapshots a CLM, that snapshot receives a
ledger-local `rev`. A later row can branch from the same CLM with a different
snapshot if the agent decides that the fact changed or must be reconsidered.

Outside the ledger, agents refer to bare `clm_*`.

## ACT

ACT is a pressure mechanism, not a punishment mechanism. It creates an
obligation to say what claim the next evidence-producing/protected action is
probing, then capture and close the result.

`act(open)` can write the first snapshot for a CLM directly. Agents should not
need a long ritual of `claim -> reason -> act` for ordinary probes. The hook
gate checks only that a fresh ACT exists in the current task/agent ledger and
has not expired under settings.

ACT close is tied to the CLM that opened the ACT. A capture row and close row
must reference the same opening ACT. Closing without captured evidence is only
valid with an explicit `no_signal_reason`, for example when a retry attempt was
aborted before a command ran. This keeps ACT useful as pressure without forcing
agents to fabricate evidence.

## Hard Gates

Final/task-done checks require:

- valid task/agent ledger
- no open ACT
- selected support refs are `clm_*`
- selected support refs were ledgered by the current task/agent chain
- support posture is answer-usable
- no unresolved task blockers for task done

`src_*` and `run_*` cannot be final support directly. They must be interpreted
into `clm_*`.

## Soft Pressure

TEP returns pressure instead of trying to perfectly classify every statement.
Examples:

- bookkeeping-like CLM
- unsupported CLM
- low argument trust index
- open ACT
- stale or missing source support

A formally valid ledger can still have low argument quality. The agent should
strengthen the chain instead of adding more command-log CLM records.

Use `check_argument` before final support or risky actions when the chain is
unclear. It is a runtime quality check over selected `clm_*` refs: it does not
create proof, but it points out bookkeeping claims, unsupported leaves,
hypothesis-on-hypothesis links, stale aggregates, and missing ledger snapshots.
