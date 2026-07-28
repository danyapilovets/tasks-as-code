"""Jira sync logic, exercised against a fake client — no network calls."""

from __future__ import annotations

from typing import Any

import pytest

from tasks_as_code.core.config import JiraSettings
from tasks_as_code.core.loader import TaskRef
from tasks_as_code.integrations.jira import (
    JiraCredentials,
    JiraNotConfigured,
    build_description,
    sync_task,
    task_label,
)

from .conftest import make_task

ENV = {
    "JIRA_BASE_URL": "https://example.atlassian.net/",
    "JIRA_EMAIL": "dev@example.com",
    "JIRA_API_TOKEN": "token",
    "JIRA_PROJECT_KEY": "ABC",
}


def ref(task_id: str = "api-001", **overrides) -> TaskRef:
    from pathlib import Path

    return TaskRef(
        task=make_task(task_id, **overrides),
        file=Path("tasks/active/api.yaml"),
        epic="api",
        location="active",
    )


class FakeClient:
    """Records calls instead of performing them."""

    def __init__(
        self, existing: dict[str, Any] | None = None, transitions: list[str] | None = None
    ):
        self.credentials = JiraCredentials(
            base_url="https://example.atlassian.net",
            email="dev@example.com",
            api_token="token",
            project_key="ABC",
        )
        self._existing = existing
        self._transitions = [
            {"id": str(index), "name": name} for index, name in enumerate(transitions or [])
        ]
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.applied: list[tuple[str, str]] = []

    def find_by_label(self, label: str) -> dict[str, Any] | None:
        self.searched = label
        return self._existing

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.created.append(payload)
        return {"key": "ABC-1"}

    def update_issue(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.updated.append((key, payload))
        return {}

    def available_transitions(self, key: str) -> list[dict[str, Any]]:
        return self._transitions

    def apply_transition(self, key: str, transition_id: str) -> dict[str, Any]:
        self.applied.append((key, transition_id))
        return {}


def test_credentials_require_every_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(JiraNotConfigured, match="JIRA_BASE_URL"):
        JiraCredentials.from_env()


def test_credentials_strip_the_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    assert JiraCredentials.from_env().base_url == "https://example.atlassian.net"


def test_label_prefix_is_configurable() -> None:
    assert task_label(JiraSettings(), "api-001") == "tasc-api-001"
    assert task_label(JiraSettings(label_prefix="acme"), "api-001") == "acme-api-001"


def test_description_includes_criteria_and_dependencies() -> None:
    task_ref = ref(
        description="Do the thing",
        acceptance_criteria=["it works", "it is tested"],
        depends_on=["api-000"],
    )
    text = build_description(task_ref)["content"][0]["content"][0]["text"]
    assert "Do the thing" in text
    assert "- it works" in text
    assert "Depends on: api-000" in text


def test_description_never_sends_an_empty_document() -> None:
    text = build_description(ref())["content"][0]["content"][0]["text"]
    assert text == "—"


def test_creating_an_issue_sends_project_type_and_labels() -> None:
    client = FakeClient()
    assert sync_task(client, JiraSettings(), ref(priority="High")) == "created ABC-1"
    fields = client.created[0]["fields"]
    assert fields["project"] == {"key": "ABC"}
    assert fields["issuetype"] == {"name": "Task"}
    assert fields["priority"] == {"name": "High"}
    assert fields["labels"] == ["tasc-api-001", "epic-api"]


def test_existing_issue_is_updated_not_duplicated() -> None:
    client = FakeClient(existing={"key": "ABC-7", "fields": {"status": {"name": "To Do"}}})
    assert sync_task(client, JiraSettings(), ref()) == "updated ABC-7"
    assert client.created == []
    assert client.updated[0][0] == "ABC-7"


def test_dry_run_sends_nothing() -> None:
    client = FakeClient()
    assert sync_task(client, JiraSettings(), ref(), dry_run=True) == "would create"
    assert client.created == []

    existing = FakeClient(existing={"key": "ABC-7", "fields": {"status": {"name": "To Do"}}})
    assert sync_task(existing, JiraSettings(), ref(), dry_run=True) == "would update ABC-7"
    assert existing.updated == []


def test_status_transition_uses_the_configured_name() -> None:
    settings = JiraSettings(status_map={"in_progress": "Started"})
    client = FakeClient(
        existing={"key": "ABC-7", "fields": {"status": {"name": "To Do"}}},
        transitions=["Started", "Done"],
    )
    sync_task(client, settings, ref(status="in_progress"))
    assert client.applied == [("ABC-7", "0")]


def test_matching_status_is_not_transitioned_again() -> None:
    client = FakeClient(
        existing={"key": "ABC-7", "fields": {"status": {"name": "in progress"}}},
        transitions=["In Progress"],
    )
    sync_task(
        client, JiraSettings(status_map={"in_progress": "In Progress"}), ref(status="in_progress")
    )
    assert client.applied == []


def test_an_unmapped_status_is_left_alone() -> None:
    client = FakeClient(
        existing={"key": "ABC-7", "fields": {"status": {"name": "To Do"}}},
        transitions=["Done"],
    )
    sync_task(client, JiraSettings(status_map={}), ref(status="blocked"))
    assert client.applied == []


def test_a_missing_transition_is_skipped_rather_than_crashing() -> None:
    """Jira workflows vary; a name we cannot reach must not abort the sync."""
    client = FakeClient(
        existing={"key": "ABC-7", "fields": {"status": {"name": "To Do"}}},
        transitions=["Something Else"],
    )
    sync_task(
        client, JiraSettings(status_map={"in_progress": "In Progress"}), ref(status="in_progress")
    )
    assert client.applied == []


def test_a_new_todo_issue_is_not_transitioned() -> None:
    client = FakeClient(transitions=["Done"])
    sync_task(client, JiraSettings(), ref(status="todo"))
    assert client.applied == []
