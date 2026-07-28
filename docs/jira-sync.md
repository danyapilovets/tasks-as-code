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
```

Status names are configured in `.tasc.yaml`, because they differ per project and
per language:

```yaml
jira:
  label_prefix: tasc
  status_map:
    todo: To Do
    in_progress: In Progress
    blocked: To Do
    done: Done
```

## Run it

```sh
tasc sync --dry-run   # show what would change, send nothing
tasc sync             # push active tasks
tasc sync --all       # include archived tasks
```

## How tasks are matched

Each task gets a label, `<label_prefix>-<id>` — for example `tasc-api-001`. Sync
searches the project for that label:

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
| `description`, `acceptance_criteria`, `depends_on` | Description (one document) |
| `priority` | Priority |
| `type` | Issue type |
| `status` | Transition named by `status_map` |
| `id`, `epic` | Labels |

Acceptance criteria and dependencies are folded into the description because
mapping them to custom fields would require per-instance configuration.

## Limits worth knowing before you rely on it

- **One direction only.** Editing an issue in Jira does not update the YAML, and
  the next sync overwrites your Jira edit.
- **Priority names must exist** in your Jira scheme. `Critical`, `High`,
  `Medium` and `Low` are the defaults; a scheme without them rejects the field.
- **Transitions must be reachable** from the issue's current status. If the
  configured name is not offered, the status is left alone rather than failing.
- **Issue types must exist.** `Story` and `Epic` are absent from some project
  templates.
- **No attachments, comments, sprints, assignees or estimates.**

A task that fails to sync is reported in the results table and the command exits
non-zero; the remaining tasks are still attempted.

## Keeping secrets out of the repository

The `.gitignore` excludes `.env`. Nothing in `tasc` writes credentials into task
files, the generated index, or the quarterly logs. In CI, pass the four
variables as encrypted secrets.
