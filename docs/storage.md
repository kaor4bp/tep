# Storage

TEP v1 stores user data under `~/.tep`.

```text
~/.tep/
  registry/
    projects/PRJ-*.json
    workspaces/WSP-*.json
  journals/
    operations/YYYY-MM.jsonl
  runtime/
    tx/TX-*/
  records/
    src/YYYY/MM/SRC-*.json
    src/source_events.jsonl
    clm/YYYY/MM/CLM-*.json
  workspaces/WSP-*/
    memberships/projects.jsonl
    records/inp/INP-*.json
    records/run/RUN-*.json
    tasks/TASK-*.json
    agents/AGENT-*/agent.json
    agents/AGENT-*/ledger.jsonl
    maps/MAP-*.json
    maps/tap.jsonl
    maps/views/
    indexes/
      manifests/IDX-*.json
      trust_score/
      source_trust/
      claim_graph/
      source_acceptance/
      dedup/
      ledger_heads/
      map_coverage/
      tap_heat/
      coco/CIX-*.json
    artifacts/
```

## Context Store And Project Pointer

`~/.tep` is the default TEP context store. Product language may call this the
`.tep_context` store, but v1 docs use `~/.tep` as the concrete default path.

A project root may contain a small local `.tep` pointer file:

```json
{
  "tep_home": "~/.tep",
  "project_ref": "PRJ-*",
  "mcp_server": "stdio|http://127.0.0.1:..."
}
```

The local `.tep` file is not a fact store. It must not contain `workspace_ref`,
private key material, claims, sources, ledger rows, or trust scores. A project
can belong to multiple workspaces, so the active `WSP-*` is resolved at runtime
from project membership and the current task/scope.

## Storage Zones

Canonical:

- `registry/projects/PRJ-*.json`
- `registry/workspaces/WSP-*.json`
- `records/src/YYYY/MM/SRC-*.json`
- `records/src/source_events.jsonl`
- `records/clm/YYYY/MM/CLM-*.json`
- `workspaces/WSP-*/memberships/projects.jsonl`
- `workspaces/WSP-*/records/inp/INP-*.json`
- `workspaces/WSP-*/records/run/RUN-*.json`
- `workspaces/WSP-*/tasks/TASK-*.json`
- `workspaces/WSP-*/agents/AGENT-*/agent.json`
- `workspaces/WSP-*/agents/AGENT-*/ledger.jsonl`

Canonical navigation:

- `workspaces/WSP-*/maps/MAP-*.json`
- `workspaces/WSP-*/maps/tap.jsonl`

Runtime-private:

- no private key material is stored under `~/.tep`
- the active agent holds its private key in memory and passes it explicitly to
  signing operations
- `runtime/tx/TX-*` stores in-flight transaction intent, staged files, optional
  backups, and commit manifests

Generated or rebuildable:

- `maps/views/`
- `indexes/`
- generated reports
- backend projections
- `indexes/manifests/IDX-*.json`
- `indexes/trust_score/`
- `indexes/source_trust/`
- `indexes/claim_graph/`
- `indexes/source_acceptance/`
- `indexes/dedup/`
- `indexes/ledger_heads/`
- `indexes/map_coverage/`
- `indexes/tap_heat/`
- `indexes/coco/CIX-*.json`

Artifact storage:

- `artifacts/`

Artifacts can hold command excerpts, screenshots, copied files, URL snapshots,
and other raw material. An artifact becomes proof-capable only when cited by an
accepted `SRC-*`.

## JSON And JSONL Rules

- One canonical JSON object per `SRC-*`, `CLM-*`, `TASK-*`, `AGENT-*`, `PRJ-*`,
  and `WSP-*` file.
- Ledger and membership files are JSONL.
- Source acceptance/classification audit events are JSONL.
- Source audit events are append-only and hash-chained.
- Ledger rows are append-only. A valid implementation must not edit or delete
  prior rows.
- Failed MCP mutations write nothing.
- Generated files must not be treated as canonical proof.

## Transactions And Journals

Canonical JSON files are changed through typed storage transactions, not by
writing each file independently. This matters for compound operations such as
project initialization, where `PRJ-*` and the local project `.tep` pointer must
appear together.

Transaction layout:

```text
~/.tep/runtime/tx/TX-*/
  intent.json
  staged/*.blob
  backup/*.bak
  commit.json
```

Rules:

- A transaction first writes intent and staged content under `runtime/tx`.
- Commit preflights every destination before touching canonical files.
- If commit fails after replacing some files, the implementation rolls back
  already replaced files from backups.
- If `init` cannot commit the local `.tep` pointer, the newly staged `PRJ-*`
  record is not left in the registry.
- Empty directories created while preparing a workspace are not protocol
  objects and do not count as committed facts.
- Failed MCP/storage mutations do not create canonical records.

Every committed typed storage mutation appends an operation journal row:

```text
~/.tep/journals/operations/YYYY-MM.jsonl
```

The operation journal is runtime audit metadata. It records operation name,
`TX-*`, affected refs, write count, and write hashes. It is not a substitute
for proof: source audit chains and sealed ledgers still define source
acceptance and reasoning commitment.

## Global Fact Records And Workspace Views

`SRC-*` and `CLM-*` are physically global and sharded by id date. A workspace
does not own facts; it owns a working view over facts through project
membership, tasks, agents, maps, indexes, and ledgers.

Visibility rules:

- A workspace can see facts scoped directly to that workspace.
- A workspace can see facts scoped to attached `PRJ-*` records.
- If a membership has `include_children=true`, child `PRJ-*` records are also
  visible with the parent's membership role.
- A fact from a visible example/reference/comparison project is still
  navigation-only until a valid bridge relation makes it usable for the current
  commitment path.
- A bridge relation cannot be created, even as a hypothesis, unless both sides'
  project scopes are visible in the current workspace.

Agents must not scan `records/clm` directly. Retrieval goes through MCP lookup,
runtime scope views, and indexes so policy can filter over-retrieved backend
candidates before commitment.

## Canonical JSON And Hashing

All hashes, seals, dedup keys, source snapshots, claim snapshots, and index
input hashes require one deterministic serialization profile.

V1 implementation must define a single canonical JSON profile before any
ledger row is accepted. The recommended baseline is an RFC 8785/JCS-compatible
profile with these extra protocol rules:

- UTF-8 output
- no duplicate JSON object keys
- deterministic object property ordering
- stable number representation, or strings for values where numeric round-trip
  would be ambiguous
- timestamps normalized to ISO 8601 UTC strings
- excluded fields listed explicitly for each hash

If the implementation chooses a different canonicalization profile, the profile
id must be stored in the ledger genesis/header and included in
`ledger_context_hash`.

## Direct Filesystem Writes

Agents may technically have filesystem access. TEP does not assume the storage
directory is a security boundary.

Direct writes are unsupported for protocol mutation:

- raw `CLM-*` files may be visible as untrusted storage, but cannot satisfy
  commitment gates until selected through a valid sealed ledger append.
- raw `SRC-*` edits may be visible as untrusted storage, but source acceptance
  for commitment must be derived from valid source audit events and ledger
  source snapshots, not from a mutable field alone.
- manual deletion, reorder, or rewrite of source audit events breaks source
  event replay validation.
- raw ledger rows without valid seal, branch hash, append-log hash, and PoW fail
  replay validation.
- manual deletion, reorder, or rewrite of ledger rows breaks append-log
  validation.
