# Jira Cloud sync

One-way push: local YAML is the source of truth, Jira is a mirror for people who
live in Jira. Nothing is ever written back into your task files.

## Install and configure

```sh
pipx install "tasks-as-code[jira] @ git+https://github.com/danyapilovets/tasks-as-code@v1.2.0"
```

Credentials come from the environment, never from a file in the repository:

```sh
export JIRA_BASE_URL=https://your-domain.atlassian.net
export JIRA_EMAIL=you@example.com
export JIRA_API_TOKEN=...        # id.atlassian.com/manage-profile/security/api-tokens
export JIRA_PROJECT_KEY=ABC
export JIRA_ASSIGNEE_ACCOUNT_ID= # optional, see "Assignee" below
```

Names differ per project and per language, so they live in `.tasc.yaml` rather
than in the code:

```yaml
jira:
  label_prefix: tasc
  status_map:
    todo: To Do
    in_progress: In Progress
    blocked: To Do
    done: Done
  type_map: {}        # e.g. Task: Задача
  priority_map: {}    # e.g. High: Высокий
  force_assignee: false
  comment_on_done: true          # post the note from `tasc done --note`
  link_dependencies: true        # depends_on as issue links
  dependency_link_type: Blocks   # the link type used for them
  epic_as_parent: false          # put tasks under a Jira epic
  epic_type: Epic                # issue type used for those epics
```

`type_map` and `priority_map` are empty by default, which sends the local value
unchanged.

## Run it

```sh
tasc sync --check     # compare the backlog against the project, send nothing
tasc sync --dry-run   # show what would change, send nothing
tasc sync             # push active tasks, refresh closed ones that have an issue
tasc sync --all       # create issues for archived tasks too
```

### Which tasks are pushed

A plain `tasc sync` creates issues for active tasks only, but it still updates
every archived task whose issue already exists — closing a task locally would
otherwise leave its issue claiming, forever, that the work is in progress. The
archive is not poured into the project: a closed task with no issue is left
alone, and `--all` is what creates issues for those.

Sorting the two apart needs the batched label lookup. If that query fails, the
run says so and archived tasks wait for the next one, rather than costing a
search each.

### Check before you push

`--check` reads the project's issue types, the priorities of its scheme, the
statuses of its workflow and the fields on its create screen, and compares them
with your backlog:

```
$ tasc sync --check
Checking 34 task(s) against ABC on https://your-domain.atlassian.net
note    'Task' has no priority on its create screen; those values will not be sent.
blocker status_map maps 'in_progress' to 'Started', which is not a status in this project
```

A blocker exits non-zero; a note is something you should know about but that will
not fail the push. This is not the same as `--dry-run`, which reports what it
would send without asking the project whether it would be accepted.

## How tasks are matched

Each task gets a label, `<label_prefix>-<id>` — for example `tasc-api-001`. One
search covers the whole backlog:

- **found** → update summary, description and priority, then transition the
  status if it differs;
- **not found** → create the issue with that label plus `epic-<epic>`.

The label is the only link, so renaming a Jira issue or moving it between
sprints does not break the mapping. Removing the label does: the next sync
creates a duplicate.

## What is pushed

| Local | Jira |
|---|---|
| `summary` | Summary |
| `description`, `acceptance_criteria` | Description (paragraphs and a bullet list) |
| `depends_on` | Issue links, or description text where the dependency has no issue |
| `priority` | Priority, via `priority_map` |
| `type` | Issue type, via `type_map` |
| `status` | Transition into the status named by `status_map` |
| `note` | Comment, once, when the task is closed |
| `id`, `epic` | Labels, plus a parent epic when `epic_as_parent` is on |
| `JIRA_ASSIGNEE_ACCOUNT_ID` | Assignee |

Acceptance criteria are folded into the description because mapping them to
custom fields would require per-instance configuration.

### What the task produced

`tasc done <id> --note "..."` is where the outcome of a task is recorded, and a
transition into `Done` does not carry it: the issue says the work stopped, not
what came out of it. Sync posts the note as a comment, prefixed with a marker
line (`tasc:api-001 done`) that is how a later run recognises its own comment and
does not post it again. Delete the comment and the next sync restores it.

This costs one extra read per closed task that has a note. Set
`comment_on_done: false` to skip it entirely.

### Dependencies

`depends_on` becomes a real issue link, so a blocked task is visible as blocked
on the board instead of being described as blocked in prose. The dependency is
the end that blocks: the link reads *dependency* **blocks** *task*.

A dependency whose issue does not exist yet stays as `Depends on:` text in the
description and becomes a link on a later run — resolving it early would cost a
search per dependency. `tasc sync --check` fails if `dependency_link_type` names
a link type this Jira does not have, because that would otherwise be a `400` on
every task with a dependency.

### Epics

By default an epic is only a label (`epic-<epic>`), which is enough to filter by
and nothing more. With `epic_as_parent: true`, sync also resolves one Jira issue
of type `epic_type` per epic — labelled `<label_prefix>-epic-<epic>`, created if
absent — and sets it as the parent of every task in that epic, so the board shows
the same hierarchy the backlog has.

It is off by default because it writes issues no task in the backlog names, and a
project whose hierarchy is managed elsewhere would end up with two sets of epics.
Epics are resolved once per run, before any task is sent, so two tasks of one
epic cannot each create their own copy of it.

### Fields your project does not have

A team-managed project decides which fields are on its create screen, and many
have no `priority` field at all. Sync reads the create screen once per issue type
and drops anything the project does not accept, so a missing field costs you that
value rather than the whole push. `--check` lists what will be dropped.

If the screen cannot be read — no permission, an unexpected response — sync sends
everything and lets Jira answer. Silently dropping every field would be worse
than a clear error.

### Assignee

Boards are routinely filtered by assignee, and an unassigned issue is invisible
on the board people actually look at. Set `JIRA_ASSIGNEE_ACCOUNT_ID` to an
`accountId` — Jira Cloud no longer accepts usernames or emails here. You can read
it from the board URL (`?jql=assignee = 712020:...`) or from
`/rest/api/3/myself`.

It is applied when an issue is created. Updates leave the assignee alone, so
reassigning in Jira sticks; set `force_assignee: true` if you would rather the
local configuration win on every sync.

## Rate limits

Jira Cloud rate-limits per user. Sync keeps the call count down by looking up all
labels in one query instead of one per task, and retries a `429` or a `5xx` up to
three times, waiting as long as `Retry-After` asks. Beyond that one query, a task
costs an extra call only where it needs one: reading comments when it is closed
with a note, and reading links when it has dependencies. A task that still fails is
reported in the results table and the command exits non-zero; the remaining tasks
are still attempted.

## Limits worth knowing before you rely on it

- **One direction only.** Editing an issue in Jira does not update the YAML, and
  the next sync overwrites your Jira edit.
- **Priority and type names must exist** in the project, or be mapped to names
  that do. `tasc sync --check` tells you which ones do not.
- **Transitions must be reachable** from the issue's current status. If no
  transition leads to the configured status, the status is left alone rather than
  failing.
- **Comments go one way too.** Sync writes the outcome of a closed task and reads
  comments only to find its own marker. Discussion in Jira is never pulled back.
- **No attachments, sprints or estimates.**

## Keeping secrets out of the repository

The `.gitignore` excludes `.env`. Nothing in `tasc` writes credentials into task
files, the generated index, or the quarterly logs. In CI, pass the variables as
encrypted secrets.
