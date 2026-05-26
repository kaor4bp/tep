# Prior Art And Agent Adoption

TEP is not trying to invent every component from scratch. It combines useful
patterns from agent memory, RAG, verification, provenance, and multi-agent
systems, then adds a local trust protocol around them.

## Useful Prior Art

`MemGPT`
: Teaches the useful memory-tier idea: a small current context backed by a
larger archival store. TEP uses this as briefing plus `agent_*` working context
over the durable TEP context store. TEP does not let the agent rewrite memory
freely; durable commitments go through typed `src_*`, `clm_*`, `rel_*`, and
checked chain operations.

`Generative Agents`
: Shows the value of observation, planning, reflection, and memory retrieval.
TEP uses this for TAP, curiosity map, retrospective maps, and task situation
briefings. TEP quarantines reflection: reflections are navigation or
hypothesis-level claims until supported by sources.

`ReAct`
: Shows that reasoning and acting work better when interleaved with
observations. TEP turns that into a lighter sequence:
`prepare context -> run/capture -> SRC/RUN -> CLM/REL -> checked CHAIN`. The
private reasoning trace is not proof; captured observations and selected
evidence/relations are.

`Reflexion`
: Shows that agents can improve across attempts by storing verbal feedback.
TEP can keep feedback as retrospective `MAP-*`, failure-pattern claims, or
compiled flows. Self-reflection alone is never trusted support.

`RAG`
: Confirms that non-parametric memory helps when model parameters are stale or
too general. TEP treats retrieval as navigation until source material is
captured and accepted.

`GraphRAG`
: Confirms that graph construction and hierarchical/community summaries help
with broad sensemaking over private corpora. TEP uses this idea as `MAP-*`,
map-of-maps, claim graph, and compiled `clm_*` summaries/models/flows. Generated
graph summaries remain navigation or compiled claims with explicit support.

`FActScore`
: Supports the idea that long-form output should be decomposed into atomic
facts and checked against reliable sources. TEP should expose a validation path
that decomposes final/draft answers into claim support requirements.

`Chain-of-Verification`
: Supports verification questions before final answers. In TEP, verification
questions become valid moves such as lookup, source capture, open probe,
check chain, or user question.

`W3C PROV` and `OpenLineage`
: Support event/provenance thinking: entities, activities, agents, runs,
datasets, extensible metadata. TEP keeps a smaller local model:
`src_*`, `run_*`, `agent_*`, relation edges, and selected chains.

`AutoGen`
: Confirms the importance of multi-agent/tool/human collaboration patterns.
TEP adds cross-agent continuity by making facts, notes, tasks, and selected
chains shareable while preserving session attribution.

`Voyager`
: Shows that skill libraries and curricula can produce reuse without model
fine-tuning. TEP can later propose skill/flow candidates from stable compiled
claims, but a single successful runtime episode is not enough to create trusted
procedure.

## Design Consequences

TEP v1 adopts these constraints:

- Memory is externalized into durable records, not assumed to live in the LLM.
- Retrieval, maps, indexes, embeddings, and backend output are navigation until
  source capture.
- Reflection and self-critique are useful, but start as navigation or
  hypothesis-level material.
- Final/protected/task-done paths should be decomposable into supported
  `clm_*` claims.
- Repeated patterns should compile into `clm_*` summaries/models/flows only
  when supported by trusted or user-confirmed inputs.
- Multi-agent coordination reads shared facts, notes, tasks, and checked chains
  while preserving which session created or used them.

## Agent Adoption Mechanics

The protocol must motivate agents to use it. TEP does this with several layers.

`SKILL.md`
: Teaches the agent the operating loop: prepare context, retrieve before
guessing, capture/classify source, create/select/dedup CLM, relate facts,
prepare/check a chain, decompose broad work, and finish only when support is
good enough.

MCP guided choices
: Every meaningful MCP response returns `valid_moves`, and failed responses
return `repair_options`. The agent keeps strategic choice, but does not need to
infer mechanical validity from scratch.

Briefing advantage
: Using TEP gives the agent a shorter, more relevant starting context:
active task, selected facts, blockers, curiosity position, trust posture,
counterfacts, gaps, priority plan, and deferred work.

Search advantage
: Lookup, curiosity map, source indexes, dedup indexes, and compiled claims make
TEP cheaper than rediscovering facts manually.

Commitment gates
: Final answer and task-done paths require selected CLM support, evidence, and
a checked chain. The agent can explore without TEP, but cannot make TEP-backed
commitments without using the fact graph.

Mechanical reward
: Successful protocol use creates reusable facts, source captures, compiled
flows, and retrospective maps that reduce future work for the same or another
agent.

Error recovery
: When the agent is blocked, MCP explains why and offers valid recovery choices
instead of a dead-end error. This turns protocol friction into navigation.

## Reference Links

- [MemGPT](https://research.memgpt.ai/)
- [Generative Agents](https://research.google/pubs/generative-agents-interactive-simulacra-of-human-behavior/)
- [ReAct](https://arxiv.org/abs/2210.03629)
- [Reflexion](https://arxiv.org/abs/2303.11366)
- [Retrieval-Augmented Generation](https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)
- [GraphRAG](https://arxiv.org/abs/2404.16130)
- [FActScore](https://arxiv.org/abs/2305.14251)
- [Chain-of-Verification](https://arxiv.org/abs/2309.11495)
- [W3C PROV-DM](https://www.w3.org/TR/prov-dm/Overview.html)
- [OpenLineage](https://openlineage.io/docs/)
- [AutoGen](https://arxiv.org/abs/2308.08155)
- [Voyager](https://arxiv.org/abs/2305.16291)
- [Model Context Protocol](https://modelcontextprotocol.io/specification/draft)

## Non-Goals

- Do not make the model "learn" by pretending its hidden state changed.
- Do not trust reflection, memory retrieval, or graph summaries as proof.
- Do not make one mandatory next action when several valid moves exist.
- Do not let convenience writes bypass `src_*`, `clm_*`, `rel_*`, or chain
  validation.
