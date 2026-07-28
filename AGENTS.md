# Guidance for AI agents working on this repository

This file is for agents contributing to `tasks-as-code` itself. For using the
tool in *your* project, see [`docs/ai-agents.md`](docs/ai-agents.md).

## Before you change anything

```sh
pip install -e ".[dev]"
pytest && ruff check .
```

Both must be clean before and after your change.

## Properties you must not break

These are the reasons the tool is worth using. A change that violates one is a
bug even if the tests pass.

1. **Selection is deterministic.** `pick_next` sorts by priority rank then id.
   No randomness, no clock, no reliance on filesystem ordering.
2. **YAML is the source of truth.** Integrations push outward only. Nothing
   external writes back into task files.
3. **stdout stays parseable.** Human-facing output and errors go to stderr in
   `--json` mode. An agent must be able to `json.loads` stdout in every case,
   including failures.
4. **`--json` fields are a contract.** Adding fields is fine; renaming or
   removing them needs a `CHANGELOG.md` entry.
5. **Unknown task fields survive a round trip.** Users attach their own data;
   dropping it silently loses their work.
6. **Unmet dependencies block, including unknown ids.** A typo must never make a
   task look ready.

## Layout

```text
src/tasks_as_code/
├── cli.py            Typer commands; presentation and exit codes only
├── core/
│   ├── schema.py     Pydantic models, normalisation, priority ranking
│   ├── config.py     .tasc.yaml
│   ├── paths.py      root discovery, resolved locations
│   ├── loader.py     reading and writing task files
│   ├── workflow.py   selection, transitions, archiving, id allocation
│   └── indexer.py    INDEX.md rendering
└── integrations/
    └── jira.py       optional, one-way
```

Keep business logic in `core/`. `cli.py` should format and choose exit codes,
nothing more.

## Testing rules

- Every test runs against a throwaway project in `tmp_path`. Use the `project`
  and `in_project` fixtures from `tests/conftest.py`.
- No network access. The Jira tests drive a stubbed session; keep it that way.
- Name tests after the guarantee they protect, and add a docstring when the
  reason is not obvious from the name.
- Coverage is gated at 95%.
- Assertions on console output must tolerate line wrapping: Rich wraps at the
  terminal width. The `run()` helper in the CLI tests collapses whitespace.

## Do not

- Add a required dependency without a clear reason; optional features go behind
  an extra.
- Introduce a database, server, daemon or background process.
- Add telemetry.
- Write comments that restate the code. Comment a constraint the code cannot
  express, or say nothing.
