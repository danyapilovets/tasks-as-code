# Task schema

## Layout

```text
tasks/
├── active/<epic>.yaml    open work, many tasks per file
├── archive/<id>.yaml     closed work, one task per file
├── done/<YYYY>-Q<n>.md   quarterly log of what shipped
└── INDEX.md              generated; do not edit
```

Open work is grouped so a reader — human or agent — loads a whole epic in one
read. Closed work is split so history costs nothing until you ask for it.

## Active file

```yaml
epic: api
description: Public HTTP surface.
tasks:
  - id: api-001
    summary: Add retry to the payment webhook
    ...
```

## Archive file

Written by `tasc done`:

```yaml
epic: api
task:
  id: api-001
  summary: Add retry to the payment webhook
  status: done
  updated: 2026-07-28
```

A bare task mapping without the `task:` wrapper is also accepted on read.

## Fields

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | string | required | `<epic>-<number>`, lowercase. Allocated by `tasc new` |
| `summary` | string | required | One line. Must not be empty |
| `description` | string | `""` | Free text |
| `type` | enum | `Task` | `Task`, `Story`, `Bug`, `Epic` |
| `priority` | enum | `Medium` | `Critical`, `High`, `Medium`, `Low` |
| `status` | enum | `todo` | `todo`, `in_progress`, `blocked`, `done` |
| `acceptance_criteria` | list of strings | `[]` | What "done" means |
| `depends_on` | list of ids | `[]` | Blocks selection until each is done |
| `epic` | string | inferred | Falls back to the id prefix |
| `updated` | ISO date | set by CLI | Last status change; drives `tasc stale` |

### Ids

Pattern: `^[a-z][a-z0-9]*-\d+$`. Valid: `api-001`, `ui-42`, `infra2-7`.
Rejected: `API-1`, `1-api`, `api_1`, `api`.

Let `tasc new <epic>` allocate ids — it takes the next free number for that
epic, zero-padded to three digits.

### Normalisation on read

Values are folded for case and separators, so exports from Jira or a spreadsheet
load without editing:

| Written | Read as |
|---|---|
| `To Do`, `to-do`, `open`, `backlog` | `todo` |
| `In Progress`, `in-progress`, `WIP`, `doing` | `in_progress` |
| `closed`, `complete`, `completed` | `done` |
| `crit`, `blocker` | `Critical` |
| `med`, `normal` | `Medium` |
| `minor` | `Low` |
| `fix` | `Bug` |

Anything outside these lists is a validation error rather than a silent guess.

### Priority ordering

`Critical` → `High` → `Medium` → `Low`. `tasc next` sorts by this rank, then by
id, so equal priorities resolve in a stable order.

### Custom fields

Unknown keys are preserved through read and write:

```yaml
  - id: api-001
    summary: Add retry
    owner: dana
    points: 3
    tracker_url: https://...
```

The tool ignores them; your team and your agent can use them.

## Validation

`tasc validate` reports, and exits non-zero on:

- schema violations, naming the file
- duplicate ids across all files
- `depends_on` entries that match no known task
- a task that depends on itself

Unparsable YAML is reported with the filename rather than a bare parser error.

## Configuration

`.tasc.yaml` at the repository root:

```yaml
project_name: Your Project   # heading of the generated index
tasks_dir: tasks             # where the tree lives
stale_after_days: 7          # threshold for `tasc stale`
jira:
  label_prefix: tasc
  status_map:
    todo: To Do
    in_progress: In Progress
    blocked: To Do
    done: Done
```

Unknown keys are rejected: a silently ignored typo would look like the setting
had no effect.

The project root is found by walking up from the current directory looking for
`.tasc.yaml`, then for a `tasks/active/` tree — so the tool also works in a
repository where nobody has run `tasc init` yet.
