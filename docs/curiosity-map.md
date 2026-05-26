# Curiosity Map

Curiosity maps help agents navigate facts without treating navigation as proof.
In the server architecture, the map is a heuristic read model over facts,
relations, indexes, source freshness, bridge candidates, unresolved jobs, and
telemetry. It should actively surface pressure items instead of waiting for an
agent to ask the perfect lookup query.

`MAP-*` records can group topics, claims, source clusters, cold zones, and
smaller maps. A map may be a coarse map over more focused maps.

Useful signals:

- TAP: how often a fact/map was used
- cold zones: relevant areas with low recent use
- bridge pressure: project/domain areas that may need relation CLM bridges
- contradiction pressure: areas with unresolved conflicting claims
- aggregate candidates: repeated clusters that could become aggregate CLM
- learning pressure: inputs, sources, command outputs, or code inspections that
  likely taught durable knowledge
- relation pressure: useful CLM nodes that are similar, unlinked, stale, or
  suspiciously broad
- counterfact pressure: negative relations or freshness challenges that should
  be checked before final answers

Maps may be scoped by:

- `project_refs`
- `task_refs`
- `agent_ref`
- topic labels

Maps and external indexers such as CocoIndex, Serena, or PageIndex are
navigation only. If a map points to useful material, the agent must capture a
source excerpt and create/relate CLM records before using it as proof.

Maps can reduce token load by pointing agents to aggregate CLM records first.
The agent can then use `get_fact` or `walk_graph` to inspect children only when
needed.

The detailed pressure and bridge discovery contract is documented in
[Heuristic Pressure And Bridge Discovery](heuristic-pressure.md).

The 0.11 direction is to make maps walkable through a bounded graph API instead
of exposing a flat list of facts. The important distinction is scope:
`neighborhood` shows nearby facts, `path` shows a proof/counterproof chain,
`frontier` shows where to explore next, `community` shows aggregate/topic
clusters, and `timeline` shows how facts changed over snapshots and time. See
[Graph Walk API](graph-walk.md).
