# Security Policy

## Supported versions

This project is pre-1.0. Only the latest released version receives fixes.

| Version | Supported |
|---|---|
| 0.1.x | Yes |
| < 0.1 | No |

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Use GitHub's [private vulnerability
reporting](https://github.com/danyapilovets/tasks-as-code/security/advisories/new),
or email **w.pilovets@gmail.com** with:

- what the problem is and how it can be triggered,
- the version or commit you tested,
- the impact you believe it has.

You can expect an acknowledgement within 7 days and, where a fix is warranted, a
patched release and an advisory crediting you unless you prefer otherwise.

## Scope

`tasc` is a local CLI that reads and writes files in your repository. The areas
worth scrutiny are:

- **Path handling** — writes are expected to stay inside the configured
  `tasks_dir`. A task id or epic name that escapes it is a valid report.
- **YAML parsing** — task files are loaded with `yaml.safe_load`. Any path that
  reaches unsafe deserialisation is a valid report.
- **Jira credentials** — read from environment variables only. They must never
  be written into task files, logs, or the generated index.

## Out of scope

- A malicious `.tasc.yaml` or task file in a repository you chose to clone and
  run the tool against. Treat untrusted repositories as untrusted code.
- The contents of your Jira instance, or its permission model.
