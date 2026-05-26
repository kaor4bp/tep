# Trust Evidence Protocol

TEP is a local fact protocol for coding agents. It gives an agent a typed way
to capture sources, write reusable claims, relate claims, retrieve compact fact
cards, and check selected fact chains before relying on them.

The purpose is not to prove that an LLM "thought correctly". The purpose is to
make the useful part of its work durable and inspectable: what it observed, what
fact it extracted, which facts it used, which gaps remain, and which retrieval
steps it should take next.

## Model

TEP 0.12.0 is server-centered and fact-card driven:

```text
Docker server -> TerminusDB fact graph: src_/clm_/rel_/task_/job_/snap_
              -> Valkey runtime cache -> Mirage code snapshot artifacts
```

There is no public `WSP-*` workspace model. A local `.tep` file may point to a
default `project_ref`, but the current working scope is the active `task_*` and
its `project_refs`.

## Agent Loop

1. `create_task` creates or selects the current work unit.
2. `start_session` binds the current agent session to a task/project focus.
3. `brief` returns compact fact cards, tag cloud, aggregate pressure, pending
   jobs, and a `retrieval_plan`.
4. `search_facts` asks TEP memory for existing facts before making new claims.
5. PageIndex-style document retrieval and Serena/code navigation provide
   evidence candidates when docs or code are involved.
6. `ingest_input` and `capture_run` store evidence as `src_*`.
7. `submit_job_result` extracts quote-backed facts from sources when needed.
8. `learn_fact` saves one narrow reusable `clm_*`.
9. `relate_facts` records support, contradiction, applicability, duplicate, or
   aggregate membership edges.
10. `check_argument` scores a selected CLM chain and reports gaps before
    important edits, risky conclusions, or final answers.
11. `finish` records the outcome and selected support refs.

The server also computes heuristic pressure: learning, relation, bridge,
curiosity, aggregate, counterfact, staleness, retrieval, and quality signals.
Pressure asks the agent to inspect, capture, relate, aggregate, or explicitly
dismiss candidate knowledge. It is navigation, not proof.

The 0.12 rollout direction is bounded graph walking over the reasoning DAG and
curiosity map. The agent should be able to ask for nearby facts, proof paths,
exploration frontiers, topic communities, and temporal views without receiving
the whole graph. The full release plan is tracked in
[docs/0.12-plan.md](docs/0.12-plan.md); graph walking details are in
[docs/graph-walk.md](docs/graph-walk.md).

Another 0.12 direction is competitive fact retrieval: `trust_score` is a
quality signal, while `rank_score` also considers utility feedback, task fit,
diversity, freshness, and competition buckets. The ranking and feedback plan is
documented in [docs/fact-ranking-and-feedback.md](docs/fact-ranking-and-feedback.md).

TEP should also make user questions first-class. Agents may ask now or defer a
question when the user is the best source of truth, and captured answers become
`inp_*` evidence for user-confirmed hypotheses, preferences, corrections, or
working assumptions. See [docs/user-questions.md](docs/user-questions.md).

TEP also has navigation-only notes for review thoughts, scratch analysis, and
future Obsidian sync. Notes are searchable context, not proof. See
[docs/notes.md](docs/notes.md).

For code provenance replay, synced code snapshots store small UTF-8 files in
Mirage snapshot artifacts in Docker beta mode. Agents can inspect
`get_snapshot_file` for navigation, use `restore_snapshot` to prove tree
reconstruction, and use `cite_code_range` to create exact `src_*` evidence
before turning code observations into CLM. See [docs/snapshot-store.md](docs/snapshot-store.md).

## Storage

The Docker beta server uses TerminusDB as the canonical fact-plane. SQLite may
still exist for tests or local control-plane settings, but it must not own
`clm_`, `src_`, `rel_`, `task_`, `job_`, or `snap_` records in Docker beta
mode. The target backend split is documented in
[docs/backend-architecture.md](docs/backend-architecture.md):

```text
TerminusDB:
  Record/<ref>
  Event/<evt_ref>

~/.tep-server/mirage-snapshots/
  <content-hash>.tar
```

Old 0.9 JSON/ledger/hook code is quarantined under `quarantine/legacy-0.9` and
is not part of the active server runtime.

## Boundaries

TEP tools are the supported mutation path. Agents should not read or write raw
TEP storage files. The active beta does not use hook-first ACT enforcement; it
uses briefing, retrieval plans, jobs, fact cards, relations, aggregates, and
argument checks to push agents toward better reasoning.

Maps and indexes are navigation only. They can help an agent find facts, but
they are not proof. Final support must flow through selected `clm_*` records,
relation links where needed, exact evidence refs, and a checked `chain_*` route.

`brief` and `search_facts` expose fact cards first: `clm_*` id, short
quote/snippet, runtime trust label, tags/context, and aggregate health. Raw CLM
payloads are available through `get_fact` when the agent needs children,
source leaves, or exact structure. `brief` may also return `relevant_notes`;
these are navigation-only and must be extracted into `clm_*`/`src_*` before they
can support an argument.

## 0.12.0 Beta Slice

TEP 0.12.0 is the Docker-first server beta with a small public API, a local
client, a thin HTTP-backed MCP stdio adapter, PageIndex/Serena retrieval
guidance in `brief`, prefix_uuid7 ids, automatic `inp_*` capture from user
prompts, compact `capture_run` responses with bounded `output_preview`, TEP
`search_code` over synced metadata, configurable Codex hook policy, a
lightweight `hook_policy` endpoint for PreToolUse admission, computed
`pressure_items`, cross-snapshot `discover_bridges`, user-question pressure for
unsupported conversation-derived decisions, `finish` support/evidence ref
separation, compact `doctor` output, and quarantined 0.9 code.

The UI includes a gear-button settings modal for Codex hooks.
`pretooluse_bash_mode` can be
`off`, `warn`, or `require_capture_run`. `block_when_open_jobs_at_least` can
stop Bash when the agent has accumulated too many open TEP jobs. The UI can also
open a `dump_known_facts_to_clm` job to ask the agent to convert known context
into reusable CLM facts.

Run the server locally:

```bash
docker compose up --build
```

Run an isolated development server without touching the active beta data or
port:

```bash
docker compose -p tep-dev -f docker-compose.yml -f docker-compose.dev.yml up -d --build
PYTHONPATH=src python -m tep.server_client --server http://127.0.0.1:8766 status
```

The dev override uses `~/.tep-server-dev`, `127.0.0.1:8766`, and an isolated
TerminusDB port/data dir by default. Equivalent env knobs are also available on
the base compose file: `TEP_DATA_DIR`, `TEP_HTTP_PORT`,
`TEP_TERMINUS_DATA_DIR`, and `TEP_TERMINUS_PORT`. Dev-specific knobs are
`TEP_DEV_DATA_DIR`, `TEP_DEV_HTTP_PORT`, `TEP_DEV_TERMINUS_DATA_DIR`, and
`TEP_DEV_TERMINUS_PORT`.

Or run it directly from the repo:

```bash
PYTHONPATH=src python -m tep.server_http --host 127.0.0.1 --port 8765 --data-dir ~/.tep-server/data
```

Useful smoke checks:

```bash
PYTHONPATH=src python -m tep.server_client doctor --server http://127.0.0.1:8765
PYTHONPATH=src python -m tep.server_client --server http://127.0.0.1:8765 status
```

Capture a command without making the agent read raw process output:

```bash
PYTHONPATH=src python -m tep.server_client --server http://127.0.0.1:8765 \
  run-capture --cwd . -- pytest -q
```

The command stores full stdout/stderr as `src_*` evidence and returns a compact
summary, important lines, failure hint, duration, exit code, `output_ref`, and a
bounded `output_preview` tail. The server-side `capture_run` response also
includes learning pressure, suggested facts, suggested moves, and a raw-output
pointer; full raw output is not returned inline.

`ingest_input` and non-command sources create an `extract_claim_candidates`
`job_*`. Agents submit candidate facts through `submit_job_result`; the server
accepts only candidates with exact quotes present in the source and returns
accepted `clm_*` fact cards plus rejected candidates with repair codes.

Deduplication is heuristic, not truth. `dedup_key` and `similarity_bucket`
identify candidates for review. Exact normalized duplicates strengthen the
existing `clm_*` with another source; similar-but-not-identical claims create a
`resolve_claim_similarity` job. Negative `rel_*` types such as
`different_scope`, `different_meaning`, `unrelated`, and
`no_relation_for_task` are first-class knowledge so the server does not keep
asking the same similarity question.

`brief` also reports `aggregate_pressure` when many point `clm_*` records share
a tag or similarity bucket. Agents can open a `propose_aggregate` job and submit
one ordinary aggregate `clm_*` with `underlying_refs`, `limits`, and optional
exceptions. Aggregate cards are prioritized in lookup and carry child count,
child trust hints, and stale/contested warnings.

Document-backed evidence is freshness-aware. If a `src_*` excerpt cites an
older `doc_*` version, `brief` reports `document_staleness_pressure`,
`prepare_finish` lowers its recommendation, and trust score explains the
freshness penalty. The repair path is `get_document` or
`diff_document_versions`, then a fresh `src_*` excerpt and narrow `clm_*` if the
document changed the fact.

Codex/MCP clients should use the thin HTTP-backed stdio adapter:

```bash
tep-server-mcp --server http://127.0.0.1:8765
```

The new server tools are intentionally small: create projects/tasks, ingest
input, learn facts, relate facts, search fact cards, validate an argument,
create/submit jobs, capture process output, and sync code metadata.

Agents should start work with `start_session`, then call `brief` with the
returned session ref. Session-aware briefing prioritizes focus tags, records
recent fact cards, and writes lightweight `evt_*` telemetry. Before a final
answer, `finish` checks task/session context, support `clm_*` refs, pending
source jobs, aggregate pressure, and argument gaps.

The Codex `UserPromptSubmit` hook captures every user prompt as an `inp_*`
record. This preserves durable conversation context without forcing every prompt
to become a source-backed CLM. Agents should extract facts from input only when
the prompt contains reusable knowledge, decisions, constraints, or documents.
When a CLM is based on a user decision, confirmation, correction, or preference,
it should reference the captured `inp_*`; otherwise runtime should score it as
unsupported agent memory.

`brief` also returns a `retrieval_plan`. The beta order is:

1. ask TEP for existing fact cards, tags, aggregates, and counterfacts;
2. ask PageIndex-style document indexes for exact passages before interpreting
   long docs;
3. ask TEP `search_code` for synced candidate files/symbols;
4. ask TEP `discover_bridges` when several projects/code snapshots may be
   related;
5. ask Serena/code navigation for symbols and references before claiming code
   behavior;
6. save only the narrow reusable CLM that was actually learned;
7. run `check_argument` over the selected CLM chain before important conclusions.

## Server Pivot

The 0.9 local MCP implementation is a prototype. The 0.10 direction moves TEP
behind a Dockerized server boundary with a thin MCP/HTTP client, a local
code-sync client, internal code/document tools, a task/job pool, and a proper
fact store. The server plan is documented in
[docs/server-pivot-plan.md](docs/server-pivot-plan.md). Backend boundaries are
tracked in [docs/backend-architecture.md](docs/backend-architecture.md).

### TerminusDB Primary Backend

The normal Docker compose includes TerminusDB as the canonical fact-plane
backend. SQLite may still exist for tests or local control-plane settings, but
canonical `prj_/task_/src_/inp_/clm_/rel_/job_/snap_` records and telemetry
events must be read and written through TerminusDB in Docker beta mode.

```bash
docker compose up --build
```

The compose file starts:

- `terminusdb` on `127.0.0.1:6363`
- `tep-server` on `127.0.0.1:8765`

The server enables the primary backend with:

```text
TEP_STORE_BACKEND=terminus
TEP_TERMINUS_URL=http://terminusdb:6363
TEP_TERMINUS_DB=tep
TEP_SNAPSHOT_BACKEND=mirage
```

`status.terminus` and `status.integration_status.components[terminusdb]` report
whether the primary backend is reachable. In `terminus` mode, failed canonical
writes fail instead of silently falling back to SQLite.

Backfill an old SQLite beta store into TerminusDB:

```bash
TEP_TERMINUS_URL=http://127.0.0.1:6363 \
TEP_TERMINUS_ENABLED=1 \
tep-migrate-terminus --data-dir ~/.tep-server
```

The next step is to move graph reads/search/argument traversal from list/filter
projections to TerminusDB-native queries once the reasoning DAG schema lands.
