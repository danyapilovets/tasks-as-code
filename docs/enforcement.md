# Making a task mandatory

A backlog that is optional records intentions. What makes it record work is a
rule at the repository level: a change arrives with a task, or it does not
arrive. This page is how to get there without the team routing around it.

## What is actually being checked

`tasc check-ref` reads a piece of text — a commit message, a pull request title,
a branch name — and requires it to name a task that exists and is open.

```console
$ tasc check-ref "api-002: retry on timeout"
OK — references api-002

$ tasc check-ref "fix the thing"
No valid task reference:
  - no task reference found — mention a task id such as 'api-002'

$ tasc check-ref "api-999: rewrite everything"
No valid task reference:
  - api-999 does not exist in the backlog — do not invent task ids
```

The suggested id is a real open task from your backlog rather than a
placeholder — a tool that rejects ids which do not exist should not illustrate
itself with one.

That third case is the reason this lives in `tasc` and not in a regex hook. A
pattern like `[a-z]+-[0-9]+` is satisfied by any well-formed string, and the
characteristic failure of an agent is a well-formed string: it needed an id,
none was at hand, so it produced one. Only the backlog can tell `api-002` from
`api-999`.

Three behaviours keep that strictness from becoming noise:

- **Unknown prefixes are not task ids.** `utf-8`, `python-3` and `sha-256` are
  ignored, because no epic is called `utf`. In a repository that *does* have a
  `be` epic, `be-999` is flagged — same rule, opposite outcome, which is what
  you want.
- **Any status is a valid reference, `done` included.** The commit that records a
  completion has to be able to name what it completed, and by the time it is
  written `tasc done` has already closed the task. See
  [Demanding a status](#demanding-a-status) to check status anyway.
- **Commits git writes itself are exempt.** Merges, reverts and `fixup!` pass
  untouched. Blocking them is how a team learns to type `--no-verify` by reflex,
  and a habit of bypassing the hook costs more than the commits it caught.

Read commands speak JSON, this one included:

```console
$ tasc check-ref --json "api-002 and api-404"
{
  "invented": ["api-404"],
  "ok": false,
  "referenced": ["api-002"],
  "required": [],
  "skipped": null,
  "unknown_keys": [],
  "wrong_status": {}
}
```

Exit code is 0 or 1, so it composes with anything that cares about exit codes.

## The two layers

Neither layer alone is enough, and it is worth being clear about why.

**A local hook is fast feedback, not enforcement.** It tells you at the moment
you commit, before a push and a red build. But git hooks live in `.git/`, which
is not committed, so every clone installs its own; and `--no-verify` bypasses
any of them. Treat it as a convenience for the person, not a guarantee for the
repository.

```sh
tasc install-hook          # writes commit-msg and prepare-commit-msg
tasc install-hook --force  # replace existing ones
```

The generated hook shells out to `tasc`, so upgrading the tool upgrades the
rule. If `tasc` is not on the person's `PATH` it warns and lets the commit
through — a teammate who has not installed the tool should not be unable to
commit.

`prepare-commit-msg` is the other half: it fills the task's issue key into the
subject before the check reads it, so the message the tracker needs and the message
the gate accepts are the same message. It never fails a commit, and it leaves
merges and squashes to git.

**CI is the enforcement.** It runs on the server, on every pull request, and
`--no-verify` cannot reach it. One reusable workflow is the whole setup:

```yaml
# .github/workflows/tasks.yml
name: Tasks
on: [pull_request]
jobs:
  gate:
    uses: danyapilovets/tasks-as-code/.github/workflows/task-gate.yml@v1.3.0
```

Then mark **Tasks / gate** as a required status check in branch protection.
Until you do, the workflow reports and nothing is blocked.

| Input | Default | Effect |
|---|---|---|
| `version` | the workflow's own tag | Which version of the tool to install. `main` to track latest. |
| `require-status` | — | Demand the task be in one of these statuses, space-separated, e.g. `in_progress done`. |
| `check-commits` | `false` | Require a reference in every commit, not only the title. |

It checks the **pull request title** by default, because on a squash merge that
title becomes the commit message on the main branch — the thing that ends up in
the history. Individual commits on a branch are drafts. Turn on
`check-commits` if your team merges without squashing, or if you want each
commit to stand on its own.

If you use pre-commit, the hooks ship from this repository:

```yaml
repos:
  - repo: https://github.com/danyapilovets/tasks-as-code
    rev: v1.3.0
    hooks:
      - id: tasc-stamp
      - id: tasc-check-ref
      - id: tasc-validate
```

These two run at message stages, which pre-commit only installs when asked:
`pre-commit install --hook-type commit-msg --hook-type prepare-commit-msg`.
Without that the hooks are configured and silently never run — worth verifying
once with a deliberately bad commit.

## The escape hatch

`[skip-task]` anywhere in the message skips the check.

```sh
git commit -m "fix a typo in the README [skip-task]"
```

This is deliberate, and it is the difference between a gate that lasts and one
that gets deleted in month two. A rule with no exit is tested by the first
genuine exception — a typo fix at 19:00 on Friday — and loses. An exception that
is one visible marker in the message is greppable, shows up in review, and
costs nothing to audit:

```sh
git log --oneline --grep='\[skip-task\]' | wc -l
```

If that number is large, the problem is not the hatch. Either the backlog is
missing the small work people actually do, or the rule is wrong for this
repository.

Rename it if you like:

```yaml
# .tasc.yaml
refs:
  skip_markers: ["[skip-task]", "#trivial"]
```

Setting `skip_markers: []` removes the hatch. Then `--no-verify` becomes the
only way out, which is worse: it leaves no trace in the history.

## Demanding a status

By default any status passes. Stricter, the task must be in progress — or closed,
so that the commit which finishes it is still expressible:

```yaml
refs:
  require_status: [in_progress, done]
```

```console
$ tasc check-ref "api-003: work"
No valid task reference:
  - api-003 is 'todo', and a reference must be 'in_progress' or 'done'; run 'tasc mark api-003 in_progress' first
```

This closes a real gap — a commit against a task nobody ever started means the
backlog does not reflect the world — at the price of one extra command before
the first commit. Worth it once the basic gate is habitual; a poor place to
start.

A bare `require_status: in_progress` is also accepted and is stricter still, but
be deliberate about it: `tasc done` closes the task before the commit that
reports it, so the closing commit then needs `[skip-task]` every time. Listing
`done` alongside is what keeps the hatch for the cases it was meant for.

## Rolling it out on a live repository

Turning this on for an existing team, in the order that works:

1. **Fill the backlog first.** `tasc validate` should pass and the open work
   people are doing this week should exist as tasks. A gate in front of an empty
   backlog teaches everyone to use the escape hatch on day one.
2. **Add the workflow, do not require it.** Let it run on pull requests for a
   week. The failures it reports are your evidence about what the rule costs.
3. **Fix what it finds.** Usually two things: work that has no task, and epics
   nobody thought to create. Both are the point.
4. **Make it required.** Branch protection, `Tasks / gate`.
5. **Then the local hook.** `tasc install-hook`, mentioned in the README's setup
   section. Moving the failure from CI to the commit is the ergonomic win, and
   it lands better once people already accept the rule.
6. **Tighten later, if at all.** `require-status`, then `check-commits`. Each is
   a real increase in friction; adopt it because something went wrong that it
   would have caught.

## Bots and automation

Dependabot, release automation and merge queues do not know your backlog and
should not be blocked by it.

- Merges and reverts are already exempt.
- For bot pull requests, skip the job rather than weakening the rule:

```yaml
jobs:
  gate:
    if: github.actor != 'dependabot[bot]'
    uses: danyapilovets/tasks-as-code/.github/workflows/task-gate.yml@v1.3.0
```

- For a release commit, `[skip-task]` in the message is the honest answer.

Do not solve this by adding a `chore` prefix that passes the check. A message
format the tool ignores is a hole with no audit trail; a marker is one you can
count.

## What this does not do

- **It does not check that the code matches the task.** Nothing can, short of
  review. The gate makes the claim explicit and reviewable.
- **It does not stop a `todo` task being invented and committed in the same pull
  request.** That is legitimate — most work starts that way — and the diff shows
  it, because the task is a file.
- **It does not know whether a reference is the commit that closed the task or a
  later one citing it.** Telling those apart means reading the diff, and the diff
  a hook sees (staged) is not the one CI sees (a commit already made), so the two
  layers would disagree about the same change. A rule that passes locally and
  fails in CI is worse than one that is merely permissive, so status is compared
  and nothing else.
- **It does not work on the server side.** These are checks in CI, not a
  pre-receive hook. Someone with the right to push to a protected branch, or to
  disable a status check, can bypass it. That is a permissions question, not
  something a CLI can answer.
