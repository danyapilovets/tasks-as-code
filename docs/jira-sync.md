# Jira Cloud sync

One-way push: local YAML is the source of truth, Jira is a mirror for people who
live in Jira. Nothing is ever written back into your task files.

## Install and configure

```sh
pipx install "tasks-as-code[jira] @ git+https://github.com/danyapilovets/tasks-as-code@v1.0.0"
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
```

`type_map` and `priority_map` are empty by default, which sends the local value
unchanged.

## Run it

```sh
tasc sync --check     # compare the backlog against the project, send nothing
tasc sync --dry-run   # show what would change, send nothing
tasc sync             # push active tasks
tasc sync --all       # include archived tasks
```

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
| `description`, `acceptance_criteria`, `depends_on` | Description (paragraphs and a bullet list) |
| `priority` | Priority, via `priority_map` |
| `type` | Issue type, via `type_map` |
| `status` | Transition into the status named by `status_map` |
| `id`, `epic` | Labels |
| `JIRA_ASSIGNEE_ACCOUNT_ID` | Assignee |

Acceptance criteria and dependencies are folded into the description because
mapping them to custom fields would require per-instance configuration.

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
three times, waiting as long as `Retry-After` asks. A task that still fails is
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
- **No attachments, comments, sprints or estimates.**

## Keeping secrets out of the repository

The `.gitignore` excludes `.env`. Nothing in `tasc` writes credentials into task
files, the generated index, or the quarterly logs. In CI, pass the variables as
encrypted secrets.
