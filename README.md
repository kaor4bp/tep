# Trust Evidence Protocol v1

Trust Evidence Protocol (TEP) is a local work protocol for coding agents. It is
not a truth oracle, not a raw RAG memory, and not a permission system. Its job
is to brief the agent, structure tasks, guide curiosity, and make committed
reasoning pass through source-backed claims, computed trust posture, a sealed
reasoning ledger, and explicit probe capture.

TEP v1 starts from a clean design. Old `.codex_context`, `WCTX-*`, `STEP-*`,
`GRANT-*`, and hook-first permission models are not the public baseline.

TEP exists because human-agent collaboration otherwise decays into repeated
re-explanation. Humans expect collaborators to learn the concrete task over
time. LLMs instead start broad, then often drift into unsupported abstractions
as local task details accumulate. TEP moves that learning outside the model:
durable tasks, source-backed claims, user-confirmed assumptions, curiosity
maps, compiled flows, and sealed ledger paths.

## Core Loop

```text
agent thread
  -> briefing: current workspace, projects, task, agent focus, ledger posture
  -> task decomposition or resume/defer decision
  -> lookup facts and curiosity signals
  -> drill down to classified sources
  -> refresh source trust and dedup indexes when needed
  -> create or select CLM-*
  -> compile repeated trusted clusters into CLM-* summaries/models/flows
  -> ledger snapshots CLM-* as CLM@rev
  -> inspect computed trust posture
  -> append sealed ledger row
  -> open ACT before commitment work
  -> capture result
  -> update claim graph or close with no-update reason
```

The protocol cannot validate private reasoning quality. It can validate whether
the agent's committed reasoning path is anchored to explicit facts, source
material, ledger claim snapshots, and tamper-evident ledger transitions.
Here, `CLM@rev` is a ledger snapshot reference. Outside the ledger, the public
claim id is just `CLM-*`.

## Three Protection Layers

1. Typed MCP path
   Agents read and write through typed tools such as `lookup_facts`,
   `create_source`, `create_claim`, `append_ledger`, and `open_probe`. There is
   no raw JSON write API.

2. Agent ownership
   `AGENT-*` represents one live thread/session. The current thread can append
   only to its current agent ledger with the matching key fingerprint. Foreign
   ledgers are readable for coordination, but not appendable.

3. Sealed ledger
   Every ledger row signs its canonical payload, branch predecessor, previous
   physical append-log row, cited `CLM@rev` material, and weak proof-of-work.
   This detects accidental/manual rewrites and makes bulk forgery expensive
   enough to discourage casual bypasses.

Seal and proof-of-work are not sandbox security. A process with filesystem
access can write files. TEP makes unsupported direct writes unusable for
commitment gates and detectable by replay validation.

## Work Discipline

TEP keeps the agent oriented while work evolves:

- briefing reminds the agent what it is working on now;
- any `TASK-*` can be split into subtasks, and subtasks can be split again;
- tasks can be deferred, blocked, resumed, or completed with explicit criteria;
- `AGENT-*` stores live working context such as selected task, selected facts,
  assumptions, open ACT, current ledger head, and curiosity position;
- curiosity map supports fact research without turning map signals into proof;
- runtime returns valid mechanical moves such as source capture, claim
  compilation, index refresh, ledger validation, deferral, or user question;
- successful protocol use creates reusable facts, source captures, compiled
  flows, and retrospective maps that reduce repeated explanation for future
  agents;
- reasoning rules make the agent more predictable for the user.

The short formula:

```text
memory + briefing + recursive tasks + agent working context
+ curiosity + predictable reasoning discipline
```

## Proof And Navigation Boundary

Proof-capable material:

- `SRC-*`: accepted classified source/provenance.
- `CLM-*`: claims whose trust posture is computed from graph links.
- sealed ledger rows over ledger-local `CLM@rev` snapshots.

Navigation-only material:

- curiosity maps
- indexes
- CocoIndex, Serena, embeddings, and other backend candidates
- TAP/cold-zone/bridge pressure
- foreign project examples before an applicability relation is ledgered

Navigation can suggest where to inspect. It cannot justify protected mutation,
final answers, or task completion by itself.

TEP does not store claim truth status. Labels such as `hypothesis`,
`unclassified_hypothesis`, `trusted_fact`, `contested`, or
`user_confirmed_hypothesis` may be returned to the agent as derived API labels,
but they are computed from the CLM graph, source classification, source trust,
source diversity, inference posture, claim trust score, contradiction pressure,
and current context. Hypotheses must be explainable as deduction, induction,
abduction, fact-based assumption, possible relation, analogy, user working
assumption, freshness challenge, or explicitly unclassified. A freshness
challenge can question whether a trusted fact is stale for the current scope,
but it does not erase the fact's existing support until revalidated through
sources, probes, and ledgered claim updates. Duplicate CLMs are controlled by
deterministic dedup keys and near-duplicate candidates; TEP does not try to
prove logical equivalence with a solver.

## Documentation

- [Concepts](docs/concepts.md)
- [Storage](docs/storage.md)
- [Scope And Lookup](docs/scope-and-lookup.md)
- [Data Model](docs/data-model.md)
- [MCP Contract](docs/mcp-contract.md)
- [Agent Identity And Seals](docs/agent-identity-and-seals.md)
- [Reasoning Ledger](docs/reasoning-ledger.md)
- [Curiosity Map](docs/curiosity-map.md)
- [Runtime Indexes](docs/indexes.md)
- [Source Classification And Dedup](docs/source-classification.md)
- [Prior Art And Agent Adoption](docs/prior-art-and-agent-adoption.md)
- [Acceptance Scenarios](docs/acceptance-scenarios.md)
