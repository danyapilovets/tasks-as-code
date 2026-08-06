# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.0] — 2026-08-06

Commits and merge requests can now name the issue of the task they belong to, which
is the only thing a tracker looks for when linking work to a ticket. No breaking
changes: the new task field and the new hook are both optional, and a message in the
old form still passes.

### Added

- Task field `jira`, written by `tasc sync` after it creates or finds the issue. A
  commit message is written offline, so the key has to be readable from git rather
  than from a search; the sync says how many keys it wrote so they can be committed.
- `tasc stamp <file>` rewrites the subject of a commit message to carry that key.
  Built for `prepare-commit-msg`, and installed by `tasc install-hook` alongside the
  existing check, or as the `tasc-stamp` pre-commit hook. It takes the task the
  message names, or the single task in progress when it names none, and never fails
  the commit — accepting or refusing a message is `check-ref`'s job.
- `refs.subject_format` shapes what `stamp` writes, defaulting to `{key} {subject}`.
  A tracker only needs the key to appear somewhere, so the rest is convention.
- `tasc check-ref` accepts an issue key as a reference, so a message written in the
  tracker's terms passes the same gate: `(AI-42) - what changed` names the same task
  as `api-004`. A key of a known project that belongs to no task is reported rather
  than accepted, and is not fatal on its own — an epic or a ticket outside the
  backlog is a legitimate thing to mention. Keys of other projects stay prose.

## [1.2.0] — 2026-08-04

Another round from running the tool against a real Jira board: everything here is
about the sync telling the truth about a backlog it already mirrors. No breaking
changes — the CLI surface, the YAML format and the `--json` shapes still hold, and
the new task field is optional.

### Fixed

- The outcome of a task reaches Jira. `tasc done <id> --note "..."` recorded what
  a task produced in the quarterly log and nowhere else, so the issue people read
  showed a transition into `Done` and no reason for it. The note is now kept on the
  task itself and posted as a comment, once: it carries a marker line
  (`tasc:<id> done`) that later runs recognise instead of commenting again. Set
  `jira.comment_on_done: false` to keep the old behaviour.
- Closing a task no longer stops syncing it. Only active tasks were pushed, and
  `tasc done` moves a task to the archive — so the very status change people wait
  for was the one that never arrived, and the issue kept claiming work was in
  progress. A plain sync now also updates archived tasks whose issue exists, while
  still not creating issues for the rest of the archive; `--all` does that, as
  before. Telling the two apart needs the batched lookup, so when that query fails
  the run says archived tasks are skipped rather than spending a search each.

### Added

- `depends_on` becomes a real Jira issue link, not a line of description text
  nobody can filter or sort. The dependency is the end that blocks — verified
  against Jira Cloud, whose field names suggest the opposite. A dependency with no
  issue yet stays as text and becomes a link on a later run, and `--check` fails
  when `jira.dependency_link_type` names a link type the instance does not have,
  because that would be a `400` per dependent task. `jira.link_dependencies:
  false` turns it off.
- `jira.epic_as_parent` puts each task under a Jira epic of its own epic, creating
  the epic issue when it does not exist and labelling it
  `<label_prefix>-epic-<epic>`. An epic used to be a label only, which is a filter
  rather than a hierarchy. Off by default: it writes issues no task names, and a
  project whose hierarchy is managed elsewhere would end up with two sets of them.
  Epics are resolved once per run, so two tasks of one epic cannot each create it.
- Task field `note`, written by `tasc done --note`. The quarterly log is prose for
  people; an integration needs the result as a field.
- `require_note: true` in `.tasc.yaml` refuses `tasc done` without `--note`, so
  the outcome is part of closing a task rather than an option somebody remembers.
  Off by default, which leaves existing repositories unchanged.

## [1.1.0] — 2026-08-04

Everything here came from using the tool against a real Jira project and a real
backlog. No breaking changes: the CLI surface, the YAML format and the `--json`
shapes from 1.0.0 all still hold, and `check-ref` accepts strictly more than it
did.

### Fixed

- A commit can reference the task it closes. `tasc done` archives the task, and
  `check-ref` then refused the id as `done` — so the one commit that records a
  completion could not name what it completed, and the workflow the tool enforces
  was only expressible through `[skip-task]`. Status is now checked only when
  `require_status` asks for it, which is also what `require_status: null` always
  claimed. Telling the closing commit from a later one citing the same task would
  mean reading the diff, and a hook sees the staged diff while CI sees a finished
  commit — the two layers would disagree about the same change, so status is
  compared and nothing else.
- `tasc sync` no longer fails on team-managed Jira projects. It reads the create
  screen for the issue type and drops fields the project does not have, instead of
  always sending `priority` — which a team-managed project has no field for,
  answering `400` for every task and making the command unusable. If the screen
  cannot be read, everything is sent as before and Jira decides, because dropping
  fields on a failed metadata read would be worse than a clear error.
- Descriptions are real Atlassian Document Format: a paragraph per block and
  acceptance criteria as a bullet list. ADF carries line structure in nodes, so
  the newlines that used to separate them inside a single text node were dropped
  and the whole description rendered as one run-on line.
- A status transition is matched by the status it leads to, not by the transition's
  own name. `status_map` holds status names, and a workflow is free to call the
  transition into `In Progress` something else entirely, in which case the status
  was silently left alone.

### Added

- `refs.require_status` accepts a list, and `--require-status` is repeatable, so
  `[in_progress, done]` expresses the strict rule that still permits the commit
  closing a task. The `require-status` input of the task gate takes several
  statuses for the same reason. A failure now names the rule it broke rather than
  assuming `in_progress` was wanted, and `--json` carries the `required` list.
- `tasc sync --check` compares the backlog against the project before anything is
  sent: issue types, the priorities of its scheme, the statuses of its workflow
  and the fields on its create screen. A mismatch is one line up front instead of
  one HTTP 400 per task halfway through a push. Unlike `--dry-run`, it asks the
  project whether the payload would be accepted.
- `jira.type_map` and `jira.priority_map` in `.tasc.yaml`, mirroring `status_map`.
  Types and priorities were sent verbatim, which breaks on a localised project or
  a renamed priority scheme. Empty by default, so behaviour is unchanged.
- `JIRA_ASSIGNEE_ACCOUNT_ID` assigns created issues, so they appear on boards
  filtered by assignee rather than existing invisibly in the project. Applied on
  create only; `jira.force_assignee: true` reapplies it on every update for teams
  that want the local configuration to win over reassignment in Jira.
- A `429` or `5xx` from Jira is retried up to three times, waiting as long as
  `Retry-After` asks. Rate limiting used to look exactly like a configuration
  error: a red cell and a non-zero exit.

### Changed

- Sync looks up every label in one query instead of one search per task, which
  was the bulk of its call budget and the quickest way to meet the rate limit.
- Python 3.14 is tested in CI and declared in the classifiers.
- Distribution is the git tag rather than a package index. `pipx`, `pip` and
  pre-commit all install from a tag, which pins to an exact commit; install
  instructions, the Jira extra hint and the release workflow say so. Nothing is
  published to PyPI, so the publish job is gone rather than sitting disabled.

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

[Unreleased]: https://github.com/danyapilovets/tasks-as-code/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/danyapilovets/tasks-as-code/releases/tag/v1.2.0
[1.1.0]: https://github.com/danyapilovets/tasks-as-code/releases/tag/v1.1.0
[1.0.0]: https://github.com/danyapilovets/tasks-as-code/releases/tag/v1.0.0
