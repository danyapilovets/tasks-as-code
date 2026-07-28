# Contributing

Thanks for taking the time. Issues, bug reports and pull requests are all
welcome.

## Getting set up

```sh
git clone https://github.com/danyapilovets/tasks-as-code.git
cd tasks-as-code
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Verify the checkout:

```sh
pytest          # coverage gate at 95%
ruff check .
ruff format --check .
```

Optional, to catch problems before you push:

```sh
pre-commit install
```

## Making a change

1. Open an issue first for anything beyond a small fix, so we agree on the
   approach before you spend time on it.
2. Branch from `main`.
3. Add tests. Coverage is gated at 95% and CI will fail below it.
4. Keep `ruff check .` and `ruff format --check .` clean.
5. Update `README.md` and `docs/` when behaviour changes, and add a
   `CHANGELOG.md` entry under `## Unreleased`.

## What good tests look like here

Tests document behaviour, so name them after the guarantee they protect:

```python
def test_unknown_dependency_blocks_rather_than_being_ignored():
    """A typo in depends_on must not make a task look ready."""
```

Every test operates on a throwaway project in `tmp_path` (see the `project` and
`in_project` fixtures in `tests/conftest.py`). Nothing touches the network: the
Jira tests drive a stubbed session.

## Design constraints

Please keep these properties intact — they are the reason the tool is useful:

- **Selection stays deterministic.** Same repository state, same next task. No
  randomness, no wall-clock input, no ordering that depends on filesystem order.
- **YAML stays the source of truth.** Integrations push outward; nothing writes
  back into task files from an external system.
- **`--json` stays stable.** It is a contract that agents parse. Add fields
  freely; do not rename or remove them without a changelog entry.
- **stdout stays parseable.** Human-facing errors go to stderr so `--json`
  output is never polluted.
- **No new required dependencies** without a clear reason. Optional features go
  behind an extra, as Jira sync does.

## Commit messages

Short imperative subject, explaining why rather than what:

```text
Report unknown dependencies instead of ignoring them
```

## Releasing

Maintainer only:

1. Update `CHANGELOG.md` and the version in `pyproject.toml` and
   `src/tasks_as_code/__init__.py`. A test fails if the two versions disagree.
2. Update the pinned tag in the install instructions, in `docs/enforcement.md`
   and in the `version` default of `.github/workflows/task-gate.yml`.
3. Tag `vX.Y.Z` and push the tag. The release workflow runs the suite, builds
   the artifacts and attaches them to a GitHub release.

There is no package index in this process: the tag is the release. `pipx`, `pip`
and pre-commit all install straight from it, which is also what lets someone pin
to an exact commit.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By taking
part you agree to uphold it.
