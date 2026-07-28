# Driving tasks-as-code from an AI agent

The problem this solves: an agent asked "what should we do next?" produces a
plausible answer whether or not it knows. Replace the question with a command
whose answer is derived from files in the repository.

## The rule to give your agent

Put this in `AGENTS.md`, `CLAUDE.md`, a `.cursor/rules/` file, or your system
prompt:

```markdown
## Task workflow

- Before writing code, run `tasc next --json` and work only on the task it
  returns. If it returns nothing, stop and ask.
- Run `tasc mark <id> in_progress` before you start.
- Run `tasc done <id> --note "<what you actually changed>"` when finished.
- Never invent a task id. To add work, run
  `tasc new <epic> --summary "..." --json` and use the id it returns.
- Reference the task id in the commit message.
```

When more than one agent works the same backlog, give each its own slice and its
own name:

```markdown
- You are `agent-a`. Always pass `--shard 1/3 --owner agent-a` to `tasc next`,
  and claim work with `tasc mark <id> in_progress --owner agent-a`.
```

Two properties make this reliable: selection is deterministic, so the same
repository state always yields the same task; and ids are allocated by the tool,
so an agent cannot reference a task that does not exist.

The last line of that rule is the one an agent quietly drops, so it is worth
enforcing rather than requesting. `tasc check-ref`, wired to a `commit-msg` hook
and to CI, rejects a commit that names no task — and rejects an invented id,
which is what "never invent a task id" actually looks like when it fails. See
[enforcement.md](enforcement.md).

## Why deterministic selection matters

`tasc next` orders ready tasks by priority, then by id, and excludes any task
whose dependencies are unmet. There is no randomness and no clock input. The
same repository state gives the same answer to every agent, on every run.

An id in `depends_on` that resolves to nothing is treated as blocking, not
ignored — a typo cannot promote a task to "ready".

The same property has a sharp edge with several agents: they all receive the
identical task, because another agent's `in_progress` is invisible until it
pushes. Partition the backlog with `--shard`, `--epic` or `--owner`; see
[parallel-agents.md](parallel-agents.md).

## JSON shapes

### `tasc next --json`

Anything already in progress is reported separately from what is ready, so an
agent can notice it left something unfinished.

```json
{
  "in_progress": [],
  "next": [
    {
      "id": "api-004",
      "summary": "Add retry to the payment webhook",
      "description": "The provider returns 502 under load; retry with backoff.",
      "type": "Task",
      "priority": "High",
      "status": "todo",
      "owner": null,
      "acceptance_criteria": ["Retries 3 times with exponential backoff"],
      "depends_on": [],
      "epic": "api",
      "location": "active",
      "file": "tasks/active/api.yaml",
      "updated": "2026-07-28"
    }
  ]
}
```

`--owner NAME` restricts `next` to unassigned tasks and the agent's own, and
filters `in_progress` the same way. `--epic NAME` and `--shard i/n` narrow it
further. `file` paths always use forward slashes, including on Windows.

### `tasc show <id> --json`

Same fields plus `blocking_dependencies`, listing the ids that are not done:

```json
{ "id": "api-004", "blocking_dependencies": ["api-003"], "...": "..." }
```

### `tasc list --json`

```json
{ "count": 2, "tasks": [ { "id": "api-004", "...": "..." } ] }
```

Filterable by `--epic`, `--status` and `--owner`. Pass `--owner none` for tasks
nobody has claimed.

### `tasc validate --json`

Exits `1` when `problems` is non-empty.

```json
{
  "ok": false,
  "tasks": 42,
  "problems": [
    "duplicate id: api-004",
    "api-007 depends on unknown task: api-999"
  ]
}
```

### `tasc stale --json`

Exits `1` when `count` is greater than zero.

```json
{ "threshold_days": 7, "count": 1, "stale": [ { "id": "api-002", "...": "..." } ] }
```

### `tasc check-ref --json`

Exits `1` unless `ok`. `invented` is the field to pay attention to: those ids
were cited and do not exist.

```json
{
  "ok": false,
  "referenced": ["api-002"],
  "invented": ["api-404"],
  "wrong_status": {},
  "skipped": null
}
```

### `tasc new`, `tasc mark`, `tasc done` with `--json`

`new` and `mark` return the resulting task. `done` returns where it went:

```json
{
  "id": "api-004",
  "archived_to": "tasks/archive/api-004.yaml",
  "logged_in": "tasks/done/2026-Q3.md"
}
```

## Error handling

On failure the exit code is `1`. With `--json`, stdout stays valid JSON:

```json
{ "error": "Task api-999 not found" }
```

Without `--json`, human-readable errors go to **stderr**. This is deliberate:
stdout remains parseable in every case, so an agent can read stdout and a person
can read stderr from the same invocation.

## Recommended guardrails in CI

```yaml
- run: tasc validate   # duplicate ids, unknown or self dependencies
- run: tasc stale      # work started and abandoned
- run: tasc reindex    # INDEX.md is generated, not committed
- run: tasc check-ref "$PR_TITLE"   # the change names a task that exists
```

`tasc stale` catches the specific failure mode of agent-driven work: a task
marked `in_progress` that nobody ever closed. Tasks with no `updated` date are
reported too, since starting work without stamping it is the same drift.

## Keeping context small

Open work is grouped per epic in one file, so an agent reads the epic it needs
rather than the entire backlog. Closed work is one file per task and is only
opened on request. `INDEX.md` gives the whole picture in a single read — run
`tasc reindex` first, since it is generated rather than tracked.
