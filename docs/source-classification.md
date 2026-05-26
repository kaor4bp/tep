# Source Classification And Dedup

TEP must classify evidence before it can use evidence. The goal is not to
declare a source globally true. The goal is to let runtime policy estimate how
much a source should affect a `clm_*` in the current task and what confirmation
is still missing.

## Classification Axes

Every `src_*` has three independent classifications:

1. Capture channel: how the source entered TEP (`source_kind`).
2. Source class: what kind of authority or observation the source represents.
3. Document kind: what kind of document or artifact was captured.

For user input, `src_*` also records what the input is doing.

```json
{
  "source_kind": "user_message|file_quote|command_output|artifact_snapshot|url_snapshot|mcp_capture",
  "classification": {
    "input_class": "instruction|preference|domain_assertion|working_assumption|user_confirmation|correction|question|secret_or_credential|irrelevant|null",
    "source_class": "user|first_party_project|runtime_observation|test_or_check|official_doc|standard_or_paper|third_party_doc|issue_discussion|generated_backend|agent_synthesis|unknown",
    "document_kind": "message|source_code|test|config|log|trace|spec|api_reference|manual|paper|dataset|issue|pull_request|web_page|release_notes|binary_artifact|unknown",
    "independence_key": "user:owner|repo:/path|domain:example.com|publisher:vendor|run:run_*|unknown"
  }
}
```

`input_class` is `null` for non-user sources.

## User Input Rules

User input is accepted as evidence for what the user said, wanted, approved, or
corrected. It is not automatically evidence for an external fact.

Minimum rules:

- `instruction` and `preference` can support task intent, done criteria, and
  task/project policy claims.
- `domain_assertion` can support a fact only when the user is the configured
  source of truth for that scope.
- `working_assumption` and `user_confirmation` can support a
  `user_confirmed_hypothesis` posture, not theory-proven truth.
- `correction` raises contradiction pressure against earlier claims and should
  trigger lookup or revision.
- `secret_or_credential` must not be stored in plaintext in ordinary source
  fields. Secret handling should encrypt sensitive material with a host key
  under `~/.tep`; it should not silently drop the fact that a secret was
  provided.

Conversation-derived CLM must be evidence-bound. If the agent writes a CLM
about a user decision, preference, correction, or confirmation, it should first
capture or reuse the relevant `inp_*` and pass that ref in `source_refs`. The
claim should not rely on the agent's transcript memory alone.

Valid flow:

```text
user says/approves/corrects -> inp_* -> clm_* source_refs=[inp_*]
```

Invalid flow:

```text
user says/approves/corrects -> clm_* with no source_refs
```

The invalid flow may still store a weak note, but trust scoring should mark it
as unsupported until an `inp_*`, `src_*`, or relation-backed support path is
added.

## Source Trust Posture

Source trust is computed, not stored as mutable truth on `src_*`.

API/index output may return:

```json
{
  "source_ref": "src_*",
  "source_trust_score": 0.0,
  "derived_label": "unrated|low|medium|high|blocked",
  "factors": {
    "critique_status": "accepted|audited|rejected|unknown",
    "source_class": "official_doc",
    "document_kind": "api_reference",
    "content_hash_present": true,
    "quote_or_span_verified": true,
    "freshness": "fresh|stale|unknown",
    "scope_fit": "local|bridged|foreign|unknown",
    "independence_key": "domain:vendor.example",
    "known_contradictions": 0
  },
  "usable_for": ["exploration", "probe", "answer", "protected_action"]
}
```

Source trust affects heuristics and gates, but accepted source status still
matters. A high-trust source that has not been captured or accepted cannot
support commitment. A low-trust source may still be useful for curiosity and
probe planning.

For commitment gates, accepted status must replay through
`records/sources/source_events.jsonl`. A mutable `src_*` field is only a lookup
cache; it is not enough to prove acceptance. Source events are append-only and
hash-chained, and checked chains snapshot or cite the accepted event hash when that source
supports a committed claim.

Runtime should score sources with bounded, inspectable factors:

- verified quote/span and stable content hash raise trust;
- official docs, standards, papers, and first-party project files can raise
  trust when scope fits;
- command/test output is strong only for the observed local run and weak for
  general theory claims;
- generated backend output, summaries, embeddings, maps, and indexes are
  navigation-only unless inspected and captured from an underlying source;
- stale, contradicted, unauthored, mirrored, or scope-foreign sources lower
  trust.

## Cross-Source Confirmation

Every important `clm_*` should move toward independent confirmation. Runtime
should track source diversity and offer valid confirmation moves.

Computed claim posture may include:

```json
{
  "source_diversity": {
    "accepted_source_count": 0,
    "independent_source_class_count": 0,
    "independence_keys": ["domain:vendor.example", "repo:/work/project"],
    "missing": ["official_doc|standard_or_paper|user_confirmation|test_or_check"]
  }
}
```

Runtime support is not linear truth. One thousand `runtime_observation` sources
with the same independence key should saturate as repeated observation. They do
not become a trusted fact without theory/document support or explicit user
confirmation that the hypothesis is usable.

Mirrors, copied docs, duplicated command outputs, and summaries of the same
material do not count as independent confirmation. Independence is computed
from `source_class`, `document_kind`, `independence_key`, content hashes, and
claim scope.

## Dedup Without Logical Solvers

TEP v1 does not use Z3 or any other logical equivalence solver for claim
deduplication. Dedup is a protocol safety rail, not a theorem prover.

Runtime uses two levels:

1. Exact duplicate block.
   A deterministic `dedup_key` is computed from normalized statement, claim
   form, relation endpoints, and semantic scope. If a new claim has the same
   `dedup_key` as an existing claim in the same effective scope, `create_claim`
   fails with `duplicate_claim` and returns the existing `clm_*`.

2. Near-duplicate candidates.
   Lexical normalization, shingle/MinHash-style sketches, embeddings, source
   overlap, and relation overlap may retrieve candidate duplicates. These are
   hints only. Runtime must ask the agent to reuse the existing claim, provide a
   `distinction_reason`, or run an explicit merge operation.

Near-duplicate candidates are navigation/index output. They cannot appear in
`source_refs`, `support_refs`, contradiction refs, or chain proof paths.

`merge_claims` is a typed mutation for confirmed duplicates. It selects a
canonical `clm_*`, records why the claims are being merged, and refreshes the
dedup/claim graph indexes. It must not silently delete historical chain or ledger
snapshots.

## External Vocabulary Boundary

TEP's provenance shape follows the stable idea that data provenance tracks
entities, activities, and responsible agents. Document/resource classification
may map to existing vocabularies such as DCMI Type or schema.org, but TEP keeps
its own small v1 vocabulary so agents do not need to reason over broad external
ontologies during normal work.

Reference points:

- W3C PROV-DM for the provenance intuition of entities, activities, and agents:
  <https://www.w3.org/TR/prov-dm/>
- DCMI Type Vocabulary for broad resource/document type examples:
  <https://www.dublincore.org/specifications/dublin-core/dcmi-type-vocabulary/2006-08-28/>
- schema.org `CreativeWork` for common web/document metadata fields:
  <https://schema.org/CreativeWork>
- Broder's resemblance/containment work for the idea that near-duplicate
  detection should be candidate retrieval, not proof of semantic equivalence:
  <https://www.cs.princeton.edu/courses/archive/spr05/cos598E/bib/broder97resemblance.pdf>
