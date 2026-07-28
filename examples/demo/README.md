# Demo project

A small backlog you can poke at without touching your own repository.

```sh
cd examples/demo

tasc list                # api-002 is in progress, api-003 is ready
tasc next                # api-003: api-002 is in progress, api-004 is blocked
tasc show api-004        # blocked by api-003
tasc validate            # passes: api-001 is archived, so the dependency resolves
tasc stale --days 1      # api-002 has been in progress since 2026-07-27
tasc reindex && cat tasks/INDEX.md
```

Things worth noticing:

- `api-002` is `Critical` but already `in_progress`, so `tasc next` reports it
  separately instead of offering it again.
- `api-004` depends on `api-003`, which is not done, so it is never selected —
  even though nothing else is competing for attention.
- `api-001` lives in `archive/` yet still satisfies `api-002`'s dependency:
  closed work stays resolvable without being loaded into the active backlog.
- `api-002` is owned by `agent-a`, so `tasc next --owner agent-b` does not even
  mention it — including in the in-progress warning.
- `tasks/INDEX.md` is absent until you run `tasc reindex`: it is generated, and
  `.gitignore` here keeps it out of version control.

Nothing here is used by the test suite; edit it freely.
