# Storage

TEP v1 stores user data under `~/.tep`.

```text
~/.tep/
  registry/
    projects/PRJ-*.json
    workspaces/WSP-*.json
  workspaces/WSP-*/
    memberships/projects.jsonl
    records/src/SRC-*.json
    records/src/source_events.jsonl
    records/clm/CLM-*.json
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
- `workspaces/WSP-*/memberships/projects.jsonl`
- `workspaces/WSP-*/records/src/SRC-*.json`
- `workspaces/WSP-*/records/src/source_events.jsonl`
- `workspaces/WSP-*/records/clm/CLM-*.json`
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
