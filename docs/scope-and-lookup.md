# Scope And Lookup

TEP separates project identity from workspace knowledge scope.

## Projects

`PRJ-*` is global. It represents a repository, service, product codebase, or
other implementation root.

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
  "name": "service-api",
  "roots": ["/path/to/repo"],
  "aliases": ["api"],
  "status": "active",
  "created_at": "iso8601",
  "updated_at": "iso8601"
}
```

## Workspaces

`WSP-*` is a durable knowledge scope. It owns workspace-domain claims, tasks,
agent threads, maps, indexes, artifacts, and project memberships.

Project membership row:

```json
{
  "project_ref": "PRJ-*",
  "role": "primary|dependency|example|reference|comparison|archived",
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
