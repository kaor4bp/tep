# Scope And Lookup

TEP separates project identity from workspace knowledge scope.

## Projects

`PRJ-*` is global. It is the only canonical project/scope node in v1. A
`PRJ-*` may represent a repository, service, documentation set, domain object,
system, aggregate of projects, external reference, or implementation example.
Repository is a project type, not the definition of `PRJ-*`.

It is not owned by one workspace. The same project can be attached to multiple
workspaces with different roles.

When a repository uses a local `.tep` pointer file, it stores `project_ref`,
not `workspace_ref`. Workspace selection is runtime scope because the same
project may be reused as primary, dependency, example, or reference in different
workspaces.

Minimal fields:

```json
{
  "id": "PRJ-*",
  "record_type": "project",
  "project_type": "domain|system|project_group|repo|service|library|docs|external_reference|example",
  "name": "service-api",
  "parent_project_refs": ["PRJ-*"],
  "roots": ["/path/to/repo"],
  "aliases": ["api"],
  "status": "active",
  "created_at": "iso8601",
  "updated_at": "iso8601"
}
```

## Workspaces

`WSP-*` is a durable working scope. It owns tasks, agent threads, maps, indexes,
artifacts, and project memberships. It does not physically own `SRC-*` or
`CLM-*`; those records are global and become visible through workspace/project
scope policy.

Project membership row:

```json
{
  "project_ref": "PRJ-*",
  "role": "primary|dependency|example|reference|comparison|archived",
  "include_children": true,
  "reason": "why this project is in this workspace",
  "active": true,
  "added_at": "iso8601"
}
```

Role meanings:

- `primary`: the current work target.
- `dependency`: project whose behavior or API directly affects the primary.
- `example`: implementation example or pattern source.
- `reference`: useful background implementation or documentation source.
- `comparison`: project used to compare behavior or design.
- `archived`: known but not part of normal lookup.

If `include_children=true`, the workspace sees recursive child `PRJ-*` records
with the parent membership role. This lets a workspace attach a domain/system
project and see its implementation repositories without introducing a separate
canonical `DOM-*` or `SYS-*` record type.

Hard scope rule:

- The agent cannot create a relation between two `PRJ-*` scopes unless both
  scopes are visible in the current workspace, directly or through
  `include_children`.
- This applies to hypotheses too. A possible relation is still a relation
  attempt; the agent must first attach the other project/scope to the
  workspace with a reason.

## Default Lookup Mode

Default lookup mode is `workspace_scoped`.

Ranking order:

1. Current task pinned claims.
2. Current primary project facts.
3. Workspace-domain claims.
4. Dependency project facts.
5. Reference, example, and comparison project facts.
6. Global project registry metadata.
7. Historical or archived records only by explicit request or fallback mode.

Every lookup result includes scope metadata. Local/current-scope facts may be
usable immediately if their trust posture permits it. Foreign/example/reference
facts require a bridge relation before commitment.
Source classification also matters: a local runtime observation is not the same
kind of support as an official doc, project source file, standard/paper, or
explicit user confirmation. Lookup should expose source diversity gaps instead
of hiding them inside a single score.

Local current-project result:

```json
{
  "record_ref": "CLM-*",
  "scope_origin": "primary_project",
  "workspace_ref": "WSP-*",
  "project_ref": "PRJ-*",
  "proof_usable_now": true,
  "requires_bridge": false,
  "drilldown": ["SRC-*"]
}
```

Foreign/example result:

```json
{
  "record_ref": "CLM-*",
  "scope_origin": "example",
  "workspace_ref": "WSP-*",
  "project_ref": "PRJ-*",
  "proof_usable_now": false,
  "requires_bridge": true,
  "drilldown": ["SRC-*"]
}
```

Bridge-aware result:

```json
{
  "record_ref": "CLM-*",
  "scope_origin": "example",
  "requires_bridge": true,
  "bridge_context": {
    "bridge_ref": "CLM-*",
    "bridge_scope": "general|task|object_sync",
    "task_specific": true,
    "task_refs": ["TASK-*"],
    "object_sync": false,
    "synced_object": null,
    "bridge_limits": {"max_depth": 1}
  }
}
```

`bridge_context` distinguishes a general applicability relation from a relation
that applies to a specific task or to synchronization of a concrete object,
field, API route, schema, contract, or artifact.

## Foreign Project Facts

Foreign/example project facts can guide inspection and curiosity. They cannot
justify commitment in the current project until bridged.

To use a foreign fact for protected mutation, final answer, or task completion,
the agent must create or select a relation `CLM-*`, for example:

- `applies_to`
- `analogous_to`
- `differs_from`
- `implements_pattern`
- `depends_on`

The relation claim must explain why the source project fact applies to the
current workspace, task, or primary project. That relation itself must enter the
ledger before the foreign fact can support commitment.

Bridge relations are bounded:

- `general`: the relation explains broad applicability but still does not merge
  whole project domains.
- `task`: the relation is valid only for listed `TASK-*` records.
- `object_sync`: the relation is valid for a concrete synchronized object,
  field, route, schema, artifact, or contract described in `synced_object`.

An `object_sync` bridge should identify both sides of the synchronized object
and the boundary being synchronized. It does not authorize unrelated facts from
either project.

## Multi-Project Tasks And Indexing

A `TASK-*` can be scoped to two or more `PRJ-*` records when the work genuinely
crosses project boundaries. Project roles still matter: a task may include one
primary project and several dependencies/examples, or it may compare multiple
projects directly.

CocoIndex may index two or more `PRJ-*` records in one workspace/job. Every
`CIX-*` candidate must carry its source `project_refs`, membership role, and
scope origin. Mixed-project candidates stay navigation-only until the agent
captures source material and, where needed, creates a bridge relation claim.
Captured material from different projects should keep distinct
`independence_key` and source classification metadata so source-diversity
heuristics do not mistake copied examples for independent confirmation.

## Analogy Warning

Lookup must mark cross-project facts that are not yet bridged:

```json
{
  "analogy_warning": "Fact is from PRJ-example and is not ledger-bridged to the current task."
}
```
