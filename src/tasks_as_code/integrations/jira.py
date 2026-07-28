"""One-way push of local tasks to Jira Cloud (REST API v3).

Local YAML stays the source of truth: this module never writes back into task
files. Credentials come from the environment, workflow status names from
``.tasc.yaml`` — Jira status names differ per project and per language, so they
cannot be constants.

Requires the optional ``jira`` extra; see the install section of the README.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..core.config import JiraSettings
from ..core.loader import TaskRef

REQUIRED_ENV = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY")


class JiraNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class JiraCredentials:
    base_url: str
    email: str
    api_token: str
    project_key: str

    @classmethod
    def from_env(cls) -> JiraCredentials:
        missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
        if missing:
            raise JiraNotConfigured(
                "Missing environment variables: " + ", ".join(missing) + ". See docs/jira-sync.md."
            )
        return cls(
            base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
            email=os.environ["JIRA_EMAIL"],
            api_token=os.environ["JIRA_API_TOKEN"],
            project_key=os.environ["JIRA_PROJECT_KEY"],
        )


def task_label(settings: JiraSettings, task_id: str) -> str:
    """Label that ties a Jira issue to a local task id, used to find it again."""
    return f"{settings.label_prefix}-{task_id}"


def _document(text: str) -> dict[str, Any]:
    """Wrap plain text in Atlassian Document Format, which v3 requires."""
    return {
        "version": 1,
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def build_description(ref: TaskRef) -> dict[str, Any]:
    task = ref.task
    parts: list[str] = []
    if task.description:
        parts.append(task.description)
    if task.acceptance_criteria:
        parts.append("\nAcceptance criteria:")
        parts.extend(f"- {item}" for item in task.acceptance_criteria)
    if task.depends_on:
        parts.append(f"\nDepends on: {', '.join(task.depends_on)}")
    return _document("\n".join(parts) if parts else "—")


class JiraClient:
    def __init__(self, credentials: JiraCredentials):
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on install extras
            raise JiraNotConfigured(
                "Jira sync needs the optional 'jira' extra. Reinstall with it:\n"
                '  pipx install "tasks-as-code[jira] @ '
                'git+https://github.com/danyapilovets/tasks-as-code@v1.0.0"'
            ) from exc

        self.credentials = credentials
        self.api = f"{credentials.base_url}/rest/api/3"
        self.session = requests.Session()
        self.session.auth = requests.auth.HTTPBasicAuth(credentials.email, credentials.api_token)
        self.session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, f"{self.api}{path}", timeout=30, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"Jira {method} {path} -> {response.status_code}: {response.text}")
        return {} if response.status_code == 204 else response.json()

    def find_by_label(self, label: str) -> dict[str, Any] | None:
        body = {
            "jql": f'project = {self.credentials.project_key} AND labels = "{label}"',
            "fields": ["summary", "status", "labels"],
            "maxResults": 1,
        }
        issues = self._request("POST", "/search/jql", json=body).get("issues", [])
        return issues[0] if issues else None

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/issue", json=payload)

    def update_issue(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/issue/{key}", json=payload)

    def available_transitions(self, key: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/issue/{key}/transitions").get("transitions", [])

    def apply_transition(self, key: str, transition_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/issue/{key}/transitions", json={"transition": {"id": transition_id}}
        )


def sync_task(
    client: JiraClient,
    settings: JiraSettings,
    ref: TaskRef,
    dry_run: bool = False,
) -> str:
    """Create or update the Jira issue mirroring one local task."""
    label = task_label(settings, ref.task.id)
    fields: dict[str, Any] = {
        "summary": ref.task.summary,
        "description": build_description(ref),
        "priority": {"name": ref.task.priority},
    }

    existing = client.find_by_label(label)
    if existing:
        key = existing["key"]
        if dry_run:
            return f"would update {key}"
        client.update_issue(key, {"fields": fields})
        _move_to_target_status(client, settings, key, existing, ref.task.status)
        return f"updated {key}"

    if dry_run:
        return "would create"
    created = client.create_issue(
        {
            "fields": {
                **fields,
                "project": {"key": client.credentials.project_key},
                "issuetype": {"name": ref.task.type},
                "labels": [label, f"epic-{ref.epic}"],
            }
        }
    )
    key = created["key"]
    if ref.task.status != "todo":
        _move_to_target_status(client, settings, key, None, ref.task.status)
    return f"created {key}"


def _move_to_target_status(
    client: JiraClient,
    settings: JiraSettings,
    key: str,
    existing: dict[str, Any] | None,
    status: str,
) -> None:
    target = settings.status_map.get(status)
    if not target:
        return
    if existing:
        current = existing.get("fields", {}).get("status", {}).get("name")
        if current and current.casefold() == target.casefold():
            return
    for transition in client.available_transitions(key):
        if transition["name"].casefold() == target.casefold():
            client.apply_transition(key, transition["id"])
            return
