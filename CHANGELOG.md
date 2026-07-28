# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-07-28

First public release.

### Added

- `tasc init` — scaffold `tasks/{active,archive,done}`, `.tasc.yaml` and an
  example epic in any repository.
- Deterministic next-task selection (`tasc next`), ordered by priority then id,
  excluding tasks with unmet dependencies.
- Task lifecycle: `tasc new`, `tasc mark`, `tasc done`. Closing a task archives
  its file and appends to a quarterly Markdown log.
- `tasc validate` — rejects duplicate ids, unknown dependencies and
  self-dependencies. Exits non-zero, so it works as a CI gate or pre-commit hook.
- `tasc stale` — reports in-progress work older than a configurable threshold,
  including tasks that were started without an `updated` date. Exits non-zero.
- `tasc list`, `tasc show`, `tasc reindex`, and a generated `INDEX.md`.
- `--json` on every read command, so AI coding agents consume a stable contract
  rather than scraped console output. Human-facing errors go to stderr to keep
  stdout parseable.
- Configuration via `.tasc.yaml`: project name, tasks directory, stale
  threshold, and Jira label prefix and status map.
- Optional one-way Jira Cloud sync (`tasc sync`, extra: `[jira]`). Local YAML
  remains the source of truth; nothing is written back into task files.
- Status, priority and type values are normalised on read, so `To Do`, `to-do`,
  `WIP` and `closed` resolve to canonical values.
- Unknown task fields are preserved on write, so teams can attach their own.

[Unreleased]: https://github.com/danyapilovets/tasks-as-code/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/danyapilovets/tasks-as-code/releases/tag/v0.1.0
