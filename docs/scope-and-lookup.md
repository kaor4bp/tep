# Scope And Lookup

TEP 0.12 scope is task-centered.

`prj_*` records are global. A project may represent:

- a concrete repo
- a service
- a domain object
- a domain/system aggregate
- an example/reference implementation
- a comparison target

Projects may be recursive through `parent_project_refs`. Do not create a new
canonical entity just because a domain contains repos; represent it as a
project with a project type and child projects.

`task_*` carries the current project set:

```json
{
  "id": "task_*",
  "project_refs": ["prj_*"],
  "parent_task_ref": null,
  "child_task_refs": []
}
```

An agent may know about many projects, but commitment rules use the task
project set. A relation that links facts across two project scopes is valid only
if both projects are in the current task's `project_refs`.

## Foreign And Example Facts

Facts from projects outside the task are navigation only. They can be inspected
with `search_facts`, `get_fact`, or `walk_graph`, but they cannot justify final
support until the task is expanded to include the project and a `rel_*` explains
applicability.

Use bridge metadata when the relation is not just "there is a connection":

- `bridge_scope="task"` when the relation exists only for the current task
- `bridge_scope="object_sync"` when a named object/interface is synchronized
- `synced_object` for the concrete object, API, schema, or artifact
- `bridge_limits` for what the relation does not cover

This prevents broad domain logic from being merged just because two systems
have one connecting object.

## Lookup Result Shape

A lookup result includes derived posture and scope:

```json
{
  "claim_ref": "clm_*",
  "claim_form": "assertion|relation|aggregate",
  "display": {
    "claim_ref": "clm_*",
    "quote": "short quote or statement snippet",
    "statement": "..."
  },
  "fact_card": {
    "claim_ref": "clm_*",
    "quote": "short quote or statement snippet",
    "tags": ["testing"],
    "context": "when this fact should be used",
    "why_shown": "matched_tags:testing"
  },
  "trust_posture": {
    "derived_label": "hypothesis|trusted_fact|contested|...",
    "trust_score_bps": 8000,
    "usable_for": ["exploration", "probe", "answer"]
  },
  "scope": {
    "scope_origin": "global|task_project|partial_task_project|foreign",
    "proof_usable_now": true,
    "requires_bridge": false
  }
}
```

Aggregate CLM records are ranked before matching children. Agents can drill
down with `get_fact` and `walk_graph` to inspect child refs, weakest refs,
evidence, and exact quotes.

## CocoIndex And Other Indexes

CocoIndex/Serena/PageIndex-style backends are navigation backends. They may
index multiple project combinations, but their output is not proof. A result
becomes proof-capable only after the agent captures the relevant excerpt/source
and creates a CLM through typed TEP tools.
