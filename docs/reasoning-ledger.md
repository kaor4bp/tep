# Reasoning Ledger

The reasoning ledger is an append-only per-agent graph ledger over claim
snapshots. It validates reasoning structure, ownership, and tamper evidence. It
does not prove that the agent chose the best interpretation.

Ledger gates use computed trust posture, not stored claim status. The runtime
may return labels such as `hypothesis`, `unclassified_hypothesis`,
`trusted_fact`, or `contested` to the agent, but those labels are derived from
the CLM graph and current context.

## Row Kinds

- `claim`: snapshot or advance through a `CLM-*` as ledger-local `CLM@rev`.
- `relation`: snapshot or enter a relation `CLM-*` that connects endpoint claims.
- `act`: open a probe or intended check.
- `capture`: bind observed result material to the open probe.
- `close_act`: close the open probe by integration, cancellation,
  supersession, or explicit no-update reason.

## State Rules

- A ledger row must belong to the current `AGENT-*`.
- A row must extend a valid branch predecessor.
- A row must preserve physical append-log order.
- `claim` and `relation` rows cite a bare `CLM-*` plus ledger-local `rev` and
  include the resolved snapshot hash.
- Rows that commit a claim path include hashes of accepted `SRC-*` snapshots
  and source acceptance events used by that snapshot.
- A branch continues from the selected ledger predecessor, not from the current
  mutable `CLM-*` file by default.
- Different claim-to-claim transitions require a relation claim.
- Relation ledger rows must carry endpoint snapshots for the branch they enter.
- Repeating the same `CLM@rev` without material change does not advance state.
- Invalid appends write nothing.

## ACT Lifecycle

```text
none
  -> open_probe / act
  -> protected_action_preflight, when action is protected
  -> RUN, when command/tool execution happens
  -> capture_probe_result
  -> close_probe
  -> none
```

Closure outcomes:

- `claim_updated`
- `claim_contested`
- `relation_supported`
- `relation_rejected`
- `no_relevant_evidence`
- `cancelled`
- `superseded`
- `expired`

Rules:

- Minimal v1 keeps one open ACT per agent ledger.
- Protected mutation requires an open ACT.
- Final answer and task completion require no open ACT.
- Another ACT cannot open from the same branch without new material state.
- Captured command/test output cannot support commitment until integrated into
  `SRC-*` and `CLM-*`.

## ACT Execution Contract

`open_probe` must declare:

- target `CLM-*` or relation refs
- intent
- allowed action kind
- workspace/project/task scope
- expected evidence
- current ledger head

Protected work follows this sequence:

```text
open_probe
  -> protected_action_preflight
  -> execute action
  -> record_run
  -> capture_probe_result
  -> create/update CLM or relation, or explicit no-update
  -> close_probe
```

`protected_action_preflight` binds the action to the ACT by action kind,
command/action hash, cwd/scope, and expiry. `RUN-*` stores the observed
execution result. `SRC-*` cites the relevant RUN output or artifact. `close_probe`
must reference the evidence or an explicit no-update/cancel/supersede reason.

## Ledger Pressure

Every serious MCP response includes:

```json
{
  "ledger_pressure": {
    "level": "none|low|medium|high|blocked",
    "current_agent": "AGENT-*|null",
    "ledger_valid": true,
    "current_head": "L-*|null",
    "open_act": "L-*|null",
    "level_reason": "...",
    "valid_moves": [
      {
        "priority": 10,
        "tool": "probe_step|append_ledger|lookup|detail|validate|mutate_record|refresh_runtime|status",
        "operation_kind": "typed operation name, e.g. create_source|open_probe|close_probe|refresh_index",
        "why": "...",
        "writes": false,
        "requires_user": false,
        "expected_output": "..."
      }
    ]
  }
}
```

Pressure is guidance until the agent reaches a commitment boundary. Even at a
boundary, MCP returns valid choices rather than one forced next move.

## Hard Gates

Protected mutation:

- current `AGENT-*` is valid
- ledger validates
- open ACT exists
- ACT is downstream of source-backed claim path
- no unresolved contradiction is on the required path

Final answer:

- ledger validates
- committed claims are on the current valid ledger path
- committed claim path source snapshots and acceptance events validate
- answer support validates: draft/final statements can be decomposed into
  atomic support requirements, and each committed requirement maps to an
  acceptable `CLM-*`/`SRC-*`/ledger path
- no open ACT remains
- unsupported statements are removed, represented as uncertainty/open question,
  or routed through a valid repair move before final commitment

Task done:

- ledger validates
- no open ACT remains
- child tasks and blockers are resolved
- done criteria have source-backed support claims
- source-backed support includes valid source acceptance events and source
  snapshot hashes

Cross-project commitment:

- foreign/example fact is bridged by a relation claim
- bridge relation enters the ledger

Runtime-only hypothesis:

- runtime observations alone can justify exploration and probes
- runtime observations alone do not make a trusted fact
- hypothesis use must carry a classified inference posture such as deduction,
  induction, abduction, fact-based assumption, possible relation, analogy, or
  freshness challenge, or user working assumption
- a hypothesis cannot be the basis for another hypothesis; it may only route
  the agent to lookup, source capture, user question, or an ACT verification
  branch
- unclassified hypotheses are blocked for final/protected commitment
- a freshness challenge may justify lookup or an ACT probe against a trusted
  fact, but it does not invalidate the trusted fact or its old `CLM@rev`
  snapshots until supported evidence is ledgered
- theory/document support or explicit user confirmation is required before the
  derived posture can become trusted for final or protected-action commitment
- source diversity matters: repeated observations from the same independence
  key saturate as runtime confidence and do not replace independent
  theory/document/user support
