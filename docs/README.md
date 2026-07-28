# Documentation

- [`schema.md`](schema.md) — the file layout, every field, normalisation rules,
  validation and configuration.
- [`ai-agents.md`](ai-agents.md) — how to drive the tool from an AI coding
  agent: the rule to give it, the JSON shapes, and CI guardrails.
- [`parallel-agents.md`](parallel-agents.md) — running several agents on one
  backlog with shards, epics and owners, and why there is no server.
- [`enforcement.md`](enforcement.md) — making a task mandatory: the commit-msg
  hook, the CI gate, the escape hatch, and how to roll it out on a live repo.
- [`jira-sync.md`](jira-sync.md) — one-way Jira Cloud sync, how issues are
  matched, and what it does not do.

Start with the [project README](../README.md) for install and a quickstart.

An example project you can copy lives in [`../examples/demo/`](../examples/demo).
