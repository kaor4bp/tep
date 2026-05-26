# Agent Identity And Seals

> Historical 0.9/0.10 design note. The active 0.12 beta keeps `agent_*` for
> session attribution and telemetry, but it does not make sealed per-agent
> ledgers the normal proof path. Current proof should be expressed as checked
> `chain_*` routes over CLM/REL/SRC evidence.

`agent_*` represents one live agent thread/session, not a reusable personality.
The same model/user may create many agents.

`generate_agent_identity` returns:

```json
{
  "agent_ref": "agent_*",
  "agent_name": "worker",
  "agent_private_key": "...",
  "public_key": "...",
  "key_fingerprint": "sha256:...",
  "seal_suite": "cryptography-ed25519-v1"
}
```

The private key is never stored by TEP. It must stay in the agent's memory and
be passed explicitly to `reason` or `act`. `agents/agent_*/agent.json` stores
only public ownership metadata:

```json
{
  "id": "agent_*",
  "thread_ref": "...",
  "task_ref": "task_*",
  "public_key": "...",
  "key_fingerprint": "sha256:...",
  "seal_suite": "cryptography-ed25519-v1"
}
```

## Threat Model

TEP does not sandbox the filesystem. An agent with local file access can still
write files. The protocol aims to make accidental continuation, casual direct
writes, row deletion/reordering, and bulk fake-history rewriting detectable or
expensive.

Because foreign ledgers include public keys, other agents can structurally
validate them. They cannot append to them without the matching private key.

## Ledger Context

Ledger rows do not repeat `agent_ref` as mutable row truth. The selected
task/agent/ledger path is bound through `ledger_context_hash`, derived from:

- `task_ref`
- `agent_ref`
- public key and fingerprint
- seal suite
- canonicalization policy
- relative ledger path
- PoW policy

Each row also includes `task_scope_hash`, derived from the current task status,
parent, and `project_refs`. Task scope changes do not rewrite old rows; they
show where the reasoning chain changed scope.

## Seal Contract

Each ledger row signs:

- canonical row payload excluding `seal`
- selected branch predecessor `prev`
- previous physical append row `append_prev`
- previous state hash
- previous append-log hash
- cited `CLM` snapshot and ledger-local revision
- source snapshots and source-event acceptance hashes
- PoW nonce/work hash
- ledger context hash
- task scope hash

This gives:

- branch integrity
- physical append integrity
- claim snapshot integrity
- source acceptance replay checks
- owner-key binding

Weak PoW is calibrated to about 1-2 seconds for normal local use. It is friction
against casual mass rewriting, not sandbox security.
