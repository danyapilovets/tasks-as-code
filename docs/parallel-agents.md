# Several agents on one backlog

Two properties collide. `tasc next` is deterministic, so the same repository
state always yields the same task. And another agent's `in_progress` only becomes
visible to you once it has pushed. Together they mean three agents asking at the
same moment all start the same task.

The answer here is to partition the backlog rather than to lock it. Locking needs
a coordinator; partitioning needs nothing.

## Shards: no coordination at all

```sh
tasc next --shard 1/3 --json   # agent A
tasc next --shard 2/3 --json   # agent B
tasc next --shard 3/3 --json   # agent C
```

`--shard i/n` keeps a task if `crc32(id) % n == i - 1`. The slices are disjoint
and cover every task, so no task is handed out twice and none is stranded. CRC32
rather than Python's `hash()` matters: string hashing is salted per process, so a
`hash()`-based shard would reshuffle between runs and hand the same task to two
agents — the exact failure this prevents.

Membership depends only on the id, so agents need no shared state, no network and
no knowledge of each other. Give each one a fixed shard in its prompt and forget
about it. The cost is that a shard can be empty while another has work queued;
with a backlog much larger than the number of agents this is not worth solving.

## Epics: partition by meaning

```sh
tasc next --epic api    # backend agent
tasc next --epic ui     # frontend agent
```

Use this when agents are specialised, or when you want work on one area confined
to one branch. Unlike shards, the split is yours to keep balanced.

This is also the split that works for people rather than agents. Because open
tasks are grouped one file per epic, teams working different epics touch
different files, so git has nothing to merge and no conflict to report. Three
specialities on one backlog:

```text
tasks/active/be.yaml       backend
tasks/active/mlops.yaml    MLOps
tasks/active/bi.yaml       BI
```

## Setting a lane once

Typing the same flags all day is how a convention gets abandoned. `tasc next`
reads its filters from the environment, so each person or agent declares its lane
once, in a shell profile or a container spec:

```sh
export TASC_OWNER=olena
export TASC_EPIC=bi
```

An explicit flag always beats the environment, and `tasc next` names the filters
it applied — a variable exported weeks ago must not make a full backlog look like
an empty one. `tasc list` ignores the environment on purpose, so there is always
one command that shows the whole picture regardless of who is asking.

## Owners: explicit claims

```sh
tasc next --owner agent-a                        # unassigned work, plus your own
tasc mark api-004 in_progress --owner agent-a    # claim it
tasc list --owner agent-a                        # what you hold
tasc list --owner none                           # what nobody has taken
```

`--owner` on `next` hides tasks owned by somebody else and leaves unassigned ones
available to whoever asks first; it filters the `in_progress` report the same way,
so an agent is not warned about work that is not its own. Claiming a task another
owner holds fails rather than quietly reassigning it — clear `owner` in the YAML
if a handover is intended.

Owners are visible in review, which is their real advantage over a lock: the claim
arrives as a diff in a pull request, alongside the code it belongs to.

Owners alone do not remove the race, because two agents can still claim the same
unassigned task before either pushes. Combine them with shards when that matters:

```sh
tasc next --shard 2/3 --owner agent-b
```

## What about a real lock?

Git can provide one. A ref update is an atomic compare-and-swap, so if claims are
pushed as tiny commits straight to the main branch, the first push wins and the
second is rejected as non-fast-forward; the loser pulls, re-reads the owner and
picks something else. That is a correct distributed lock with no server.

It is documented here rather than implemented because it needs direct pushes to
the main branch, which branch protection usually forbids, and because sharding
removes the race without any of it.

## Why there is no server

A service with its own database would hold three things, and all three already
exist somewhere better:

- **The tasks.** Storing them again creates a second source of truth that drifts
  from the branch, and something has to decide which one wins.
- **The claims.** Solved by shards and owners, above.
- **History and metrics.** `git log` already has them, with authorship and with
  the code diff attached.

Against that: a cluster, backups, authentication, schema migrations, an HTTP
client in every agent, and the loss of the one thing that makes this useful — the
backlog travelling in the same commit as the code, readable offline and inside a
CI sandbox.

Reasonable reasons to change this decision: many agents contending on the same
epic file; people editing tasks who have no repository access; one backlog across
many repositories; a live dashboard requirement. Until then, the shared view is
cheaper as a rendering step — have CI run `tasc reindex` and publish `INDEX.md`
to Pages, a job summary or a chat message. For an audience that never opens the
repository, [Jira sync](jira-sync.md) is the shop window and git stays the source
of truth.

## Why INDEX.md is not committed

It is regenerated by every `new`, `mark` and `done`. Tracked, it conflicts in
almost every pull request — over a file derived entirely from the YAML beside it.
`tasc init` adds it to `.gitignore`; generate it locally with `tasc reindex` and
again in CI if you want a published view. `tasc init --track-index` opts out.
