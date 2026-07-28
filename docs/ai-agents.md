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

Two properties make this reliable: selection is deterministic, so the same
repository state always yields the same task; and ids are allocated by the tool,
so an agent cannot reference a task that does not exist.

## Why deterministic selection matters

`tasc next` orders ready tasks by priority, then by id, and excludes any task
whose dependencies are unmet. There is no randomness and no clock input. The
same repository state gives the same answer to every agent, on every run.

An id in `depends_on` that resolves to nothing is treated as blocking, not
ignored — a typo cannot promote a task to "ready".

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

### `tasc show <id> --json`

Same fields plus `blocking_dependencies`, listing the ids that are not done:

```json
{ "id": "api-004", "blocking_dependencies": ["api-003"], "...": "..." }
```

### `tasc list --json`

```json
{ "count": 2, "tasks": [ { "id": "api-004", "...": "..." } ] }
```

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
```

`tasc stale` catches the specific failure mode of agent-driven work: a task
marked `in_progress` that nobody ever closed. Tasks with no `updated` date are
reported too, since starting work without stamping it is the same drift.

## Keeping context small

Open work is grouped per epic in one file, so an agent reads the epic it needs
rather than the entire backlog. Closed work is one file per task and is only
opened on request. `INDEX.md` gives the whole picture in a single read.
