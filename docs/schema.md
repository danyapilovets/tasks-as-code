# Task schema

## Layout

```text
tasks/
├── active/<epic>.yaml    open work, many tasks per file
├── archive/<id>.yaml     closed work, one task per file
├── done/<YYYY>-Q<n>.md   quarterly log of what shipped
└── INDEX.md              generated and git-ignored; do not edit
```

Open work is grouped so a reader — human or agent — loads a whole epic in one
read. Closed work is split so history costs nothing until you ask for it.

`done/` can live anywhere via `done_dir`, so a repository that already keeps
release notes elsewhere can adopt the tool without moving files. `INDEX.md` is
derived from the YAML and regenerated on every write, so it is git-ignored rather
than tracked — see [parallel-agents.md](parallel-agents.md).

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
| `owner` | string | unset | Who is doing it; filters `next` and `list` |
| `acceptance_criteria` | list of strings | `[]` | What "done" means |
| `depends_on` | list of ids | `[]` | Blocks selection until each is done |
| `epic` | string | inferred | Falls back to the id prefix |
| `updated` | ISO date | set by CLI | Last status change; drives `tasc stale` |

Unassigned tasks omit `owner` entirely rather than writing `owner: null`, so files
stay readable. Any string is accepted — an agent name, a git handle, a person.

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
done_dir: null               # quarterly logs; defaults to <tasks_dir>/done
stale_after_days: 7          # threshold for `tasc stale`
refs:                        # rules for `tasc check-ref`
  skip_markers: ["[skip-task]"]   # a message containing one of these is skipped
  require_status: null            # e.g. in_progress; null accepts any open status
jira:
  label_prefix: tasc         # label linking an issue to a task id
  status_map:                # local status -> Jira status to transition into
    todo: To Do
    in_progress: In Progress
    blocked: To Do
    done: Done
  type_map: {}               # local type -> Jira issue type, e.g. Task: Задача
  priority_map: {}           # local priority -> Jira priority, e.g. High: Высокий
  force_assignee: false      # reapply the assignee on update, not only on create
```

Unknown keys are rejected: a silently ignored typo would look like the setting
had no effect.

`type_map` and `priority_map` are empty by default, which sends the local value
unchanged. Together with `status_map` they cover the three names Jira lets each
project choose freely; `tasc sync --check` reports the ones that do not match.

`skip_markers: []` removes the escape hatch from `check-ref`; see
[enforcement.md](enforcement.md) for why that is usually the wrong trade.

The project root is found by walking up from the current directory looking for
`.tasc.yaml`, then for a `tasks/active/` tree — so the tool also works in a
repository where nobody has run `tasc init` yet.
