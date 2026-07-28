## What this changes

<!-- One or two sentences on the behaviour change, and why. -->

Closes #

## Checklist

- [ ] `pytest` passes (coverage gate at 95%)
- [ ] `ruff check .` and `ruff format --check .` are clean
- [ ] Tests added for the new behaviour, named after the guarantee they protect
- [ ] `README.md` / `docs/` updated if behaviour changed
- [ ] `CHANGELOG.md` entry added under `## Unreleased`

## Design constraints

Confirm the change preserves these (see [AGENTS.md](../AGENTS.md)):

- [ ] Next-task selection is still deterministic
- [ ] YAML files remain the source of truth
- [ ] `--json` stdout is still parseable, including on errors
- [ ] Unknown task fields still survive a read/write round trip
- [ ] No new required dependency, server, database or telemetry
