# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-07-28

First public release. Released at 1.0 rather than 0.x deliberately: the CLI
surface, the YAML task format and the `--json` shapes are what other tools and
agents build against, so they are covered by semantic versioning from the start.
A breaking change to any of them requires a major version.

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
- `tasc list`, `tasc show`, `tasc reindex`, and a generated `INDEX.md`. The index
  is git-ignored by `tasc init`, because a file regenerated on every write
  conflicts in nearly every pull request; `--track-index` opts out.
- Support for several agents on one backlog, without a coordinating server:
  `tasc next --shard i/n` partitions the backlog deterministically by a CRC32 of
  the task id, `--epic` scopes it to one area, and `--owner` hides work claimed by
  others. Tasks carry an `owner` field, set by `tasc new --owner` or
  `tasc mark <id> in_progress --owner`; claiming a task someone else owns fails.
  `TASC_OWNER`, `TASC_EPIC` and `TASC_SHARD` set a lane once instead of repeating
  flags; `tasc next` names the filters it applied, and `tasc list` ignores them so
  one command always shows the whole backlog.
- Repository-level enforcement, so a change arrives with a task or does not
  arrive: `tasc check-ref` accepts a commit message, pull request title or branch
  name and requires it to name a task that exists and is open. It resolves the id
  against the backlog rather than matching a pattern, which is what catches an
  agent citing a task it invented; text that merely looks like an id (`utf-8`,
  `sha-256`) is ignored, and merges, reverts and fixups are exempt.
  `tasc install-hook` installs it as a `commit-msg` hook, `.pre-commit-hooks.yaml`
  exposes it to pre-commit, and a reusable GitHub workflow
  (`.github/workflows/task-gate.yml`) makes it a required status check.
  `[skip-task]` in the message is a visible, greppable escape hatch; both the
  markers and an optional required status are configurable under `refs:`.
- `--json` on every read command, so AI coding agents consume a stable contract
  rather than scraped console output. Human-facing errors go to stderr to keep
  stdout parseable. Paths are emitted with forward slashes on every platform.
- Every file is read and written as UTF-8 explicitly, so task text in Ukrainian,
  Polish or any other non-latin script survives a round trip on Windows, whose
  default encoding is cp1252.
- Error output is not word-wrapped, so a file path inside a message stays on one
  line and can be copied.
- Configuration via `.tasc.yaml`: project name, tasks directory, done-log
  directory, stale threshold, and Jira label prefix and status map. `done_dir`
  lets an existing repository adopt the tool without moving its release notes.
- Optional one-way Jira Cloud sync (`tasc sync`, extra: `[jira]`). Local YAML
  remains the source of truth; nothing is written back into task files.
- Status, priority and type values are normalised on read, so `To Do`, `to-do`,
  `WIP` and `closed` resolve to canonical values.
- Unknown task fields are preserved on write, so teams can attach their own.

[Unreleased]: https://github.com/danyapilovets/tasks-as-code/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/danyapilovets/tasks-as-code/releases/tag/v1.0.0
