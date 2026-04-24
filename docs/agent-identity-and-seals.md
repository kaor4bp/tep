# Agent Identity And Seals

TEP assumes agents may have direct filesystem access. The protocol therefore
cannot rely on "do not write files" as a security boundary. Instead, it makes
valid commitment paths depend on owner-bound sealed ledger rows.

## Agent Identity

`AGENT-*` represents one live thread/session.

```json
{
  "id": "AGENT-*",
  "record_type": "agent",
  "workspace_ref": "WSP-*",
  "thread_ref": "...",
  "public_key": "algorithm:public-key-material",
  "seal_suite": "implementation-supported-suite",
  "key_fingerprint": "sha256:<public-key-hash>",
  "ledger_path": "agents/AGENT-*/ledger.jsonl",
  "working_context": {
    "active_task_path": ["TASK-*"],
    "attached_task_refs": ["TASK-*"],
    "selected_ledger_head": "L-*|null",
    "selected_claim_refs_by_task": {
      "TASK-*": ["CLM-*"]
    },
    "current_assumptions": [
      {"text": "...", "claim_ref": "CLM-*|null", "scope": "local"}
    ],
    "open_act_ref": "L-*|null",
    "curiosity": {
      "current_map_ref": "MAP-*|null",
      "breadcrumbs": ["MAP-*"],
      "active_lens": "topology|topic|scope|code|activity|inquiry|task|mixed|null",
      "inspected_candidate_refs": ["..."],
      "deferred_candidate_refs": ["..."],
      "candidate_states": [
        {
          "candidate_ref": "MAP-*/entry/*",
          "map_ref": "MAP-*",
          "task_ref": "TASK-*|null",
          "state": "suggested|inspected|deferred|converted_to_source|converted_to_relation|opened_act|rejected",
          "outcome_refs": ["SRC-*|CLM-*|L-*|TASK-*"],
          "reason": "...",
          "updated_at": "iso8601"
        }
      ]
    },
    "deferred_probe_refs": ["..."],
    "last_briefing_at": "iso8601|null"
  },
  "task_refs": ["TASK-*"],
  "created_at": "iso8601"
}
```

Private key material is not stored in `~/.tep`. The active agent holds it in
memory and passes it explicitly to append/signing operations. The public key and
its fingerprint are stored in `AGENT-*` so other agents can verify foreign
ledger rows without being able to append to that ledger.

Rules:

- Same user/model may create many `AGENT-*`.
- The current thread can append only to its current `AGENT-*` ledger.
- If the same thread appears with a different key fingerprint, continuation is
  invalid and the runtime must create or select a different `AGENT-*`.
- A foreign ledger is readable and independently verifiable with the owner
  public key, but not appendable without the owner private key.
- `agents_for_task(TASK-*)` is a derived view from agent attachments, ledger
  rows, and captures.
- Updating `working_context` changes only the live agent state. It does not
  change canonical CLM truth or task completion state.

## Ledger Row

Ledger rows are append-only JSONL.

```json
{
  "id": "L-000042",
  "prev": "L-000041",
  "append_prev": "L-000041",
  "kind": "claim|relation|act|capture|close_act",
  "ref": "CLM-*",
  "rev": 3,
  "why": "...",
  "ledger_context_hash": "sha256:...",
  "claim_snapshot": {
    "ref": "CLM-*",
    "rev": 3,
    "canonical_payload": {}
  },
  "claim_snapshot_hash": "sha256:...",
  "source_snapshots": [
    {
      "ref": "SRC-*",
      "source_hash": "sha256:...",
      "acceptance_event_ref": "SE-*",
      "acceptance_event_hash": "sha256:...",
      "source_event_log_hash": "sha256:...",
      "acceptance_hash": "sha256:...",
      "classification_hash": "sha256:..."
    }
  ],
  "source_set_hash": "sha256:...",
  "payload_hash": "sha256:...",
  "prev_state_hash": "sha256:...",
  "append_log_hash": "sha256:...",
  "pow": {
    "nonce": "...",
    "difficulty_bits": 18,
    "work_hash": "sha256:..."
  },
  "seal_suite": "implementation-supported-suite",
  "seal": "signature:..."
}
```

`ledger_context_hash` is derived from the ledger genesis/header material:

- `AGENT-*` id
- owner public key and key fingerprint
- seal suite
- canonicalization profile id
- PoW policy id or policy hash
- workspace id
- ledger path/id
- creation timestamp

Normal rows do not repeat `agent_ref` or `key_fingerprint`. If row, path, and
header disagree, the header/context hash wins and validation fails.

The concrete signature algorithm is not fixed by the v1 documentation. Runtime
must select a supported `seal_suite` at agent creation and keep it immutable for
that ledger. Normal rows sign the ledger context hash, so rows cannot silently
disagree with the header seal suite.

## Seal Coverage

The `seal` signs:

- canonical row payload excluding `seal`
- ledger context hash
- selected branch predecessor `prev`
- previous physical append-log row `append_prev`
- previous ledger state hash
- previous append-log hash
- referenced `CLM@rev` ledger snapshot canonical payload and hash
- referenced accepted `SRC-*` snapshot hashes, source event hashes, source
  event log hashes, and `source_set_hash`
- PoW nonce and work hash

This creates two independent integrity paths:

- Branch integrity: parent reasoning cannot be silently rewritten.
- Append-log integrity: rows cannot be silently deleted, reordered, or inserted.

## Weak Proof-Of-Work

Weak PoW is applied to every accepted ledger append.

Default target:

- configurable per workspace
- approximately 1-2 seconds on the local machine
- enough to make casual bulk rewriting costly
- never described as sandbox protection

The work hash must commit to the row payload, ledger context hash, predecessor
hashes, and nonce. Changing any signed field invalidates both seal and PoW.

The active PoW policy must be replayable. The ledger genesis/header stores the
initial policy id/hash. If a workspace changes PoW policy, validators must be
able to determine which signed policy applied to each row; otherwise the row is
invalid for commitment gates.

## Tamper Detection

Validation fails when:

- a row seal does not verify against the ledger owner's public key
- a row cites a `CLM@rev` whose ledger snapshot hash no longer matches replay
- a row cites a `SRC-*` whose source, classification, or acceptance event hash
  no longer matches replay
- `append_prev` does not match the previous physical JSONL row
- `append_log_hash` does not match replayed append-log state
- `prev_state_hash` does not match replayed branch state
- PoW does not meet configured difficulty
- a row's `ledger_context_hash` does not match the ledger header
- a row uses a claim snapshot revision not valid for its ledger branch

Ledger rows must carry enough snapshot material to replay old reasoning after
the current mutable `CLM-*` changes. In the v1 baseline this means
`claim_snapshot.canonical_payload` is stored inline and covered by the row seal.
A hash alone is insufficient.

Invalid rows are not repaired in place. The runtime reports them and routes the
agent to create a new valid branch or restore from trusted backup.
