# Acceptance Scenarios

These scenarios define what the v1 documentation must support in future
implementation and tests.

## Tool Purpose Fit

These scenarios are mandatory. If an implementation passes ledger/security
tests but fails these, it is not the TEP v1 tool.

Agent starts or resumes work.

Expected:

- runtime returns a briefing before offering action choices
- briefing includes current `WSP-*`, active/related `PRJ-*`, current
  `TASK-*|null`, current `AGENT-*`, selected facts, blockers, done criteria,
  ledger posture, and curiosity pressure
- if no task is active, briefing says that explicitly and `valid_moves` includes
  starting, attaching, or continuing without durable task scope

A new agent enters an existing workspace after another agent worked there.

Expected:

- briefing surfaces the active task or deferred task candidates without the
  user re-explaining the whole problem
- briefing includes selected facts, trust posture, blockers, open gaps,
  compiled flows/models/summaries, relevant retrospective maps, and valid moves
- foreign ledgers are readable as coordination context, but the new agent
  continues through its own `AGENT-*` and ledger

Agent receives a broad task.

Expected:

- runtime can create a `TASK-*`
- runtime can decompose it into subtasks
- any subtask can be decomposed again
- parent task status remains coordination state, not proof
- completing a parent task is blocked while required child tasks or blockers
  remain unresolved

Agent cannot finish current work now.

Expected:

- runtime can defer `TASK-*` or any subtask with a reason and optional resume
  condition
- deferred task keeps claim links, done criteria, blockers, and ledger history
- future briefing surfaces deferred work when relevant

Agent investigates facts.

Expected:

- runtime stores live research focus in `AGENT-*`, not in `TASK-*`
- `AGENT-*` may track selected claims, current ledger head, open ACT, map
  position, inspected candidates, and deferred probes
- another agent can inspect this as context but must continue through its own
  `AGENT-*` and ledger

Agent gets stuck on hot/runtime-heavy facts.

Expected:

- curiosity view surfaces cold relevant facts, bridge candidates,
  contradictions, missing theory/user support, and runtime-heavy theory-weak
  claims
- curiosity results are navigation-only
- important curiosity candidates route to source drilldown, relation creation,
  user confirmation, ACT, or explicit deferral

Agent makes a commitment.

Expected:

- runtime applies predictable reasoning rules before final/protected/task-done
  commitment
- runtime-only observations are not presented as trusted fact without theory,
  documentation, or user confirmation
- blocked commitment returns valid moves such as lookup, source capture,
  relation creation, ACT open/close, deferral, or user question, not just a
  denial

MCP returns a successful response.

Expected:

- response includes useful `valid_moves` when more protocol work would help
- valid moves are choices, not a single mandatory next action
- move entries explain expected output and whether they write data or require
  the user
- the agent can choose a different valid move without breaking protocol state

MCP returns an error.

Expected:

- failed mutation writes nothing
- response includes `repair_options` with valid recovery choices
- error explains the blocked invariant in protocol terms
- recovery options may include lookup, detail, validate, source classification,
  source capture, relation creation, ACT close/cancel, or user question

Agent drafts a final answer.

Expected:

- `validate_answer_support` can decompose the draft into atomic support
  requirements
- each committed requirement maps to a valid `CLM-*`, accepted `SRC-*`, and
  sealed ledger path
- unsupported statements are returned as overclaims with valid repair moves
- the agent may remove unsupported statements, mark uncertainty, ask the user,
  capture sources, or open/close probes before final commitment

Agent abandons a failed route.

Expected:

- runtime may offer a valid move to create or refresh a retrospective `MAP-*`
- the retrospective map records route, involved records, failure/success reason,
  and future inspection hints
- future agents can inspect the map for navigation
- the retrospective map cannot support proof until converted into accepted
  source, claim/relation, and ledger material

## Agent Ownership

Agent A cannot append to Agent B ledger.

Expected:

- append attempt returns `ownership_mismatch`
- no row is written
- `ledger_pressure.valid_moves` includes valid recovery choices such as
  `start_agent_thread` or `validate_ledger`

Same thread with mismatched key fingerprint cannot continue old `AGENT-*`.

Expected:

- current-agent continuation is invalid
- runtime does not silently fall back to the old agent
- foreign ledger remains readable only

Append without the in-memory private key, or with the wrong private key.

Expected:

- append fails before write
- no private key material is persisted, logged, returned, captured, or written
  to `RUN-*`
- `repair_options` includes valid choices such as `start_agent_thread` or a
  corrected `append_ledger`

## Ledger Tamper Detection

Manual ledger row insertion without valid seal fails replay.

Manual deletion or reorder of JSONL rows fails append-log hash validation.

A valid row is copied into another agent ledger.

Expected:

- `ledger_context_hash` mismatch is reported
- seal verification against the target ledger owner fails

An `AGENT-*` public key or ledger header is changed after rows exist.

Expected:

- existing row seals fail validation
- runtime refuses commitment gates on that ledger

Manual rewrite of the current mutable `CLM-*` after it was snapshotted does not
silently change old ledger reasoning.

Expected:

- old ledger rows replay against their inline `CLM@rev` snapshot
- runtime reports that the current `CLM-*` differs from the old snapshot when
  that difference matters
- using the changed claim for new commitment requires a new ledger snapshot or
  branch

Manual rewrite of ledger snapshot material inside a row fails replay for rows
that depend on that snapshot.

Mass ledger rewrite requires recomputing:

- every row payload hash
- every predecessor state hash
- every append-log hash
- every public-key signature
- every weak PoW nonce

Payload changes after PoW or seal computation.

Expected:

- row payload hash, PoW, or seal validation fails

Expected:

- validator reports exact failing row and reason
- commitment gates reject invalid ledger

## CLM Direct Writes

An agent manually creates a `CLM-*` file.

Expected:

- lookup may report it as untrusted or structurally invalid
- it cannot support final/protected gates
- it must be created/updated/selected through typed MCP and sealed ledger append

An agent rewrites a claim after it was snapshotted into ledger.

Expected:

- current `CLM-*` may have changed
- old ledger rows remain tied to the old `CLM@rev` snapshot
- if ledger snapshot material itself was rewritten, validation reports the
  mismatch
- new reasoning over the changed `CLM-*` requires a new ledger snapshot

An agent manually changes `SRC-*` from `unknown` to `accepted`.

Expected:

- source acceptance is not trusted without a matching source audit event
- protected/final gates reject the source path
- runtime reports source validation failure and suggests `accept_source` or
  source recapture

An agent manually inserts, deletes, or reorders a source audit event.

Expected:

- source event replay detects hash-chain mismatch
- source acceptance derived from the broken event chain is invalid
- any ledger row snapshotting the affected source event path fails replay
- structural ACT admission can still open a fresh probe from a valid
  agent-owned ledger branch; the source-event failure remains a blocker for
  final/protected proof commitments

An agent rewrites a source quote or classification after a ledger row used it.

Expected:

- ledger replay compares source snapshot hashes
- replay fails for the affected row/path
- new reasoning requires a fresh accepted source event and new ledger snapshot

## Trust Posture

A `CLM-*` has 1000 runtime observations and no theory/document support or user
confirmation.

Expected:

- schema still stores no claim truth status
- public API may label it `hypothesis` or `needs_theory_support`
- it may support exploration and probes
- it must not be presented as a trusted fact for final/protected commitment

The user explicitly confirms a runtime-heavy claim as a usable working
hypothesis.

Expected:

- public API may label it `user_confirmed_hypothesis`
- the confirmation affects computed trust posture
- the CLM schema still does not store `supported` or `trusted` status

A new under-supported claim has no source path and no inference relation.

Expected:

- public API may label it `unclassified_hypothesis`
- trust posture includes `inference_posture.kind=unclassified`
- final/protected/task-done gates reject it
- `valid_moves` includes source capture, relation creation, user confirmation,
  or claim deletion/deferral

Agent creates a deduction hypothesis.

Expected:

- the conclusion claim is connected through relation `deduced_from`
- the relation cites explicit premise and rule/policy claim refs
- runtime labels inference posture as `deduction`
- the deduction does not become trusted unless required premises/rules have
  sufficient trust posture

Agent creates an induction hypothesis from repeated runtime observations.

Expected:

- the general claim is connected through relation `induced_from`
- sample scope, source refs, and independence keys are visible
- repeated observations from one independence key saturate as runtime support
- theory/document support or user confirmation is still needed for trusted use

Agent proposes a possible relation between two facts.

Expected:

- the candidate edge is represented as relation `possible_relation_between`
- runtime labels inference posture as `possible_relation`
- it may guide lookup, curiosity, and ACT probes
- it does not bridge projects or support final/protected gates until converted
  into a supported relation claim and ledgered

Agent challenges a trusted fact as possibly stale.

Expected:

- challenge is represented by relation `challenges_freshness`
- runtime labels inference posture as `freshness_challenge`
- challenged fact may be returned as `trusted_but_challenged` in the current
  scope
- the challenge does not erase the fact's existing support or old `CLM@rev`
  ledger snapshots
- `valid_moves` includes lookup, source capture, ACT probe, user question, or
  claim update path
- final/protected commitment cannot ignore the trusted fact unless the
  freshness challenge is supported and ledgered

Agent verifies that a trusted fact is stale.

Expected:

- accepted source/probe evidence is captured
- ledger records the challenge and the confirming evidence path
- runtime creates a new supported path by updating the claim, creating a
  replacement claim, or adding an appropriate `contradicts`/`refines` relation
- old ledger snapshots remain replayable and scoped to their original state

Agent tries to build a hypothesis on top of another hypothesis.

Expected:

- mutation is blocked before write, or converted into an alternative
  verification branch without creating a supporting hypothesis chain
- response explains `hypothesis_on_hypothesis` or equivalent invariant
- `valid_moves` includes lookup, source capture, user question, ACT probe,
  selecting a trusted basis claim, or deferral
- final/protected gates continue to require grounding by accepted source
  material, theory/document support, or explicit user confirmation

Agent uses a freshness challenge to discard a trusted fact without checking.

Expected:

- final/protected mutation is blocked
- trusted fact remains on the active commitment path
- freshness challenge remains an alternative verification branch
- runtime offers valid moves to check the branch through lookup, source capture,
  ACT probe, user question, or claim update path

## Source Classification

The user gives an instruction: "Use project B only as an example."

Expected:

- `SRC-*` is classified as `input_class=instruction`
- it may support task/workspace intent claims
- it is not treated as proof of an external implementation fact

The user asserts an external technical fact without claiming authority.

Expected:

- `SRC-*` is classified as `input_class=domain_assertion`
- the claim may become a hypothesis or user-provided assertion
- final/protected gates still require document/theory support or explicit
  user-confirmed-hypothesis acceptance

The user is configured as source of truth for a workspace policy.

Expected:

- the same user message may support `authority_scope=workspace_policy`
- source trust posture reflects the configured authority scope
- the CLM still stores no truth status

A captured source contains a credential.

Expected:

- source is classified as `input_class=secret_or_credential` or equivalent
- raw secret is not stored in `quote`
- runtime redacts or rejects capture and returns `source_pressure`

## Source Trust Index

Runtime captures an official API reference and a random mirrored blog page for
the same claim.

Expected:

- canonical `SRC-*` records store classification/provenance, not
  `trusted=true`
- `source_trust` index gives different derived postures based on source class,
  document kind, provenance, freshness, and scope fit
- claim `trust_score` can prefer official/source-of-truth support without
  making the index itself proof

A source document becomes stale or contradicted.

Expected:

- `source_trust` and claim `trust_score` indexes become stale
- runtime response includes `source_pressure` or `index_pressure`
- `valid_moves` includes recapture, bridge, contradiction relation, or index
  refresh where valid

A CLM has many command-output captures from the same repeated test.

Expected:

- repeated `independence_key` support saturates as runtime confidence
- `independent_source_class_count` does not increase after the first equivalent
  source group
- `valid_moves` includes independent confirmation when final/protected trust
  requires it

## CLM Dedup Without Z3

Agent creates a claim with the same normalized statement, form, kind, and scope
as an existing claim.

Expected:

- runtime computes the same `dedup_key`
- mutation fails with `duplicate_claim`
- response returns the existing `CLM-*`
- failed mutation writes nothing

Agent creates a relation already represented by another relation claim.

Expected:

- canonical relation dedup key matches relation type, endpoints, direction, and
  scope
- `valid_moves` includes reusing the existing relation
- creating another relation requires `distinction_reason`

Agent creates a near-duplicate claim with different wording.

Expected:

- dedup index returns candidate duplicates from normalized text/source/relation
  overlap or sketch similarity
- candidates are navigation-only
- runtime asks for reuse, relation, split, merge, or `distinction_reason`
- no solver-based equivalence is claimed

Runtime merges confirmed duplicate claims.

Expected:

- `merge_claims` chooses a canonical `CLM-*` and records reason
- dedup and claim graph indexes refresh
- old ledger snapshots remain replayable

## Compiled Claims

Runtime sees a trusted cluster repeatedly used in lookup, TAP, and ledger rows.

Expected:

- response includes `compilation_pressure`
- `valid_moves` includes `tool=mutate_record` and
  `operation_kind=compile_claim`
- the selected compilation move writes a `CLM-*` with `claim_form=aggregate`
- `compilation.compiled_kind` is `summary`, `model`, or `flow`
- no public `MODEL-*` or `FLOW-*` record is created
- aggregate trust posture is derived from the underlying `CLM-*` set, not from
  the aggregate statement alone
- the aggregate response exposes weakest underlying refs and limits

Agent tries to compile a model/flow from runtime-only hypotheses.

Expected:

- mutation is blocked or creates only hypothesis-level aggregate posture
- compiled trusted model/flow requires trusted facts or user-confirmed
  hypotheses
- blocked response returns valid recovery choices, such as source capture, user
  confirmation, relation creation, or deferral

Agent creates an aggregate over one trusted fact and one runtime-only
observation.

Expected:

- the aggregate can be created when it names both underlying refs and explicit
  limits
- its trust score is lower than the trusted leaf because the weak leaf remains
  visible
- it is usable for exploration/probes but not final answer support until the
  weak leaf is strengthened or the answer marks the uncertainty

Agent creates an aggregate over trusted/user-confirmed leaves.

Expected:

- runtime may return `trusted_aggregate`
- final/protected gates still validate the ledger snapshots and source support
  for the underlying chain
- contradictions or stale underlying claims lower or invalidate aggregate
  posture

Underlying claims for a compiled model/flow change.

Expected:

- compiled `CLM-*` becomes stale
- `trust_score` and claim graph indexes are marked stale
- runtime valid moves include `compile_claim` or `refresh_index`
- stale compiled claim cannot satisfy final/protected/task-done gates without
  refresh or explicit uncertainty

## RISC And Guided Moves

Any blocked or high-pressure response.

Expected:

- response provides `valid_moves` ordered by runtime priority
- each move uses one primitive tool: `brief`, `lookup`, `detail`, `status`,
  `validate`, `mutate_record`, `append_ledger`, `probe_step`, or
  `refresh_runtime`
- each move provides typed `operation_kind` and whether it writes
- the agent chooses among valid moves instead of manually inferring mechanical
  recomputation or refresh validity

Runtime detects stale trust index before protected mutation.

Expected:

- mutation is blocked or downgraded before write
- response includes `index_pressure`
- `valid_moves` includes `tool=refresh_runtime` and
  `operation_kind=refresh_index`
- final/protected gates require fresh relevant indexes or direct validation

## Protected Mutation

Agent tries protected mutation without open ACT.

Expected:

- mutation is blocked
- `ledger_pressure.level=blocked`
- `valid_moves` includes `tool=probe_step` and `operation_kind=open_probe`
- non-commitment moves such as lookup, source capture, task deferral, or user
  question may also be valid

Agent opens ACT, runs inspection/test, captures output, creates observation
`CLM-*`, and closes ACT.

Expected:

- command output becomes source-backed only after capture
- `RUN-*` is recorded and linked to the open ACT
- observation enters claim graph
- ACT closes through a material claim/update/no-update reason

## Finalization

Agent tries final answer with open ACT.

Expected:

- final is blocked
- `valid_moves` includes `tool=probe_step` with
  `operation_kind=capture_probe_result|close_probe`
- non-final moves remain available when they do not violate ledger state

Agent finalizes with valid ledger path and no open ACT.

Expected:

- final response may cite committed claims
- unresolved hypotheses remain labeled as uncertainty

## Cross-Project Example

Agent searches for implementation examples and finds `PRJ-B` with
`role=example`.

Expected:

- fact is returned with `requires_bridge=true`
- it is navigation only

Agent creates an `applies_to` relation claim from `PRJ-B` fact to current
`PRJ-A` task and appends it to ledger.

Expected:

- bridge relation becomes part of the valid reasoning path
- protected mutation can use it only with required source-backed support

## Curiosity And Backends

CocoIndex or Serena returns a code candidate.

Expected:

- candidate is labeled navigation-only
- it cannot support `CLM-*` directly
- agent must inspect/capture source before ledger use

Curiosity map suggests a cold bridge candidate.

Expected:

- candidate includes `why_suggested`
- candidate includes required drilldown route
- no proof claim is created automatically

## Map-Of-Maps And Visual Thinking

Agent opens an `L3` task situation map and moves down to `L2` and `L1` cells.

Expected:

- movement updates only current `AGENT-*` working context
- parent/child map containment is navigation, not proof
- final/protected/task-done gates reject a path that stops at `MAP-*`
- `map_drilldown` must route to `CLM-*`, accepted `SRC-*`, `RUN-*`, or source
  capture before commitment

A parent `MAP-*` contains a child map with a strong bridge candidate.

Expected:

- the child map does not prove the parent summary
- the bridge candidate does not connect topology clusters until represented by
  relation `CLM-*`
- cross-project bridge still requires applicability relation and ledger append

Runtime returns a partial map viewport.

Expected:

- response marks `partial_view=true`
- collapsed maps, expected missing links, known rejected/tested-absent links,
  and expansion points are explicit
- absence of a visible edge is not treated as evidence of absence

Agent rejects a spatial/analogy candidate.

Expected:

- candidate lifecycle is stored in `AGENT-*` with reason
- `rejected` alone does not create evidence of absence
- `tested_absent` requires source-backed `CLM-*` with recorded method and scope

Agent converts a curiosity candidate.

Expected:

- `converted_to_source` includes created `SRC-*` in `outcome_refs`
- `converted_to_relation` includes relation `CLM-*` in `outcome_refs`
- `opened_act` includes ACT ledger row `L-*` in `outcome_refs`

A historical shortcut map suggests a faster route.

Expected:

- stale or historical route is navigation only
- runtime asks for revalidation when source set, project scope, or index hash
  changed
- external factor drift is represented as candidate, not proof

Agent tries to create a claim supported by `MAP-*`, `IDX-*`, `CIX-*`, or
`MAP-*/entry/*`.

Expected:

- mutation fails with `navigation_as_proof` or `needs_source`
- failed mutation writes nothing
