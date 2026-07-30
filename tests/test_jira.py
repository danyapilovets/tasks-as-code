"""Jira sync logic, exercised against a fake client — no network calls."""

from __future__ import annotations

from typing import Any

import pytest

from tasks_as_code.core.config import JiraSettings
from tasks_as_code.core.loader import TaskRef
from tasks_as_code.integrations.jira import (
    JiraCredentials,
    JiraNotConfigured,
    TypeMeta,
    build_description,
    preflight,
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

#: A project that accepts everything sync sends.
OPEN_SCREEN = TypeMeta(
    issue_type_id="10001",
    field_ids=frozenset({"summary", "description", "priority", "labels", "assignee"}),
    priorities=frozenset({"High", "Medium", "Low"}),
)

#: A team-managed project: no priority field anywhere on the create screen.
NO_PRIORITY = TypeMeta(
    issue_type_id="10002",
    field_ids=frozenset({"summary", "description", "labels", "assignee"}),
    priorities=None,
)


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
        self,
        existing: dict[str, Any] | None = None,
        transitions: list[dict[str, Any]] | list[str] | None = None,
        meta: TypeMeta | None = OPEN_SCREEN,
        assignee: str | None = None,
        issue_types: list[str] | None = None,
        statuses: dict[str, frozenset[str]] | None = None,
    ):
        self.credentials = JiraCredentials(
            base_url="https://example.atlassian.net",
            email="dev@example.com",
            api_token="token",
            project_key="ABC",
            assignee_account_id=assignee,
        )
        self._existing = existing
        self._transitions = [
            {"id": str(index), "name": entry}
            if isinstance(entry, str)
            else {"id": str(index)} | entry
            for index, entry in enumerate(transitions or [])
        ]
        self._meta = meta
        self._issue_types = issue_types if issue_types is not None else ["Task", "Bug"]
        self._statuses = (
            statuses if statuses is not None else {"Task": frozenset({"To Do", "Done"})}
        )
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.applied: list[tuple[str, str]] = []
        self.searched: list[str] = []
        self.metadata_asked: list[str] = []

    def find_by_label(self, label: str) -> dict[str, Any] | None:
        self.searched.append(label)
        return self._existing

    def metadata_for(self, issue_type: str) -> TypeMeta | None:
        self.metadata_asked.append(issue_type)
        return self._meta

    def issue_types(self) -> list[dict[str, Any]]:
        return [{"id": str(index), "name": name} for index, name in enumerate(self._issue_types)]

    def project_statuses(self) -> dict[str, frozenset[str]]:
        return self._statuses

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


def open_issue(status: str = "To Do") -> dict[str, Any]:
    return {"key": "ABC-7", "fields": {"status": {"name": status}}}


def test_credentials_require_every_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(JiraNotConfigured, match="JIRA_BASE_URL"):
        JiraCredentials.from_env()


def test_credentials_strip_the_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    assert JiraCredentials.from_env().base_url == "https://example.atlassian.net"


def test_the_assignee_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("JIRA_ASSIGNEE_ACCOUNT_ID", raising=False)
    assert JiraCredentials.from_env().assignee_account_id is None
    monkeypatch.setenv("JIRA_ASSIGNEE_ACCOUNT_ID", "712020:abc")
    assert JiraCredentials.from_env().assignee_account_id == "712020:abc"


def test_label_prefix_is_configurable() -> None:
    assert task_label(JiraSettings(), "api-001") == "tasc-api-001"
    assert task_label(JiraSettings(label_prefix="acme"), "api-001") == "acme-api-001"


# --- description (ADF) ------------------------------------------------------


def text_of(node: dict[str, Any]) -> str:
    return "".join(child.get("text", "") for child in node.get("content", []))


def test_description_puts_each_block_in_its_own_node() -> None:
    """ADF carries line structure in nodes; \\n inside a text node is dropped."""
    document = build_description(
        ref(
            description="Do the thing",
            acceptance_criteria=["it works", "it is tested"],
            depends_on=["api-000"],
        )
    )
    kinds = [block["type"] for block in document["content"]]
    assert kinds == ["paragraph", "paragraph", "bulletList", "paragraph"]
    assert text_of(document["content"][0]) == "Do the thing"
    assert text_of(document["content"][1]) == "Acceptance criteria:"
    assert text_of(document["content"][3]) == "Depends on: api-000"


def test_acceptance_criteria_become_real_list_items() -> None:
    document = build_description(ref(acceptance_criteria=["it works", "it is tested"]))
    bullet_list = document["content"][1]
    assert [item["type"] for item in bullet_list["content"]] == ["listItem", "listItem"]
    assert [text_of(item["content"][0]) for item in bullet_list["content"]] == [
        "it works",
        "it is tested",
    ]


def test_a_multi_line_description_uses_hard_breaks() -> None:
    document = build_description(ref(description="first\nsecond"))
    kinds = [node["type"] for node in document["content"][0]["content"]]
    assert kinds == ["text", "hardBreak", "text"]


def test_description_never_sends_an_empty_document() -> None:
    document = build_description(ref())
    assert text_of(document["content"][0]) == "—"


# --- create and update payloads --------------------------------------------


def test_creating_an_issue_sends_project_type_and_labels() -> None:
    client = FakeClient()
    assert sync_task(client, JiraSettings(), ref(priority="High")) == "created ABC-1"
    fields = client.created[0]["fields"]
    assert fields["project"] == {"key": "ABC"}
    assert fields["issuetype"] == {"name": "Task"}
    assert fields["priority"] == {"name": "High"}
    assert fields["labels"] == ["tasc-api-001", "epic-api"]


def test_a_project_without_priority_still_syncs() -> None:
    """The reported bug: priority is not on a team-managed create screen."""
    client = FakeClient(meta=NO_PRIORITY)
    assert sync_task(client, JiraSettings(), ref(priority="High")) == "created ABC-1"
    fields = client.created[0]["fields"]
    assert "priority" not in fields
    assert fields["summary"] and fields["description"]


def test_pruning_never_drops_the_fields_that_place_the_issue() -> None:
    """Create metadata does not list project or issuetype, but Jira needs both."""
    client = FakeClient(meta=TypeMeta("1", frozenset({"summary"}), None))
    sync_task(client, JiraSettings(), ref())
    fields = client.created[0]["fields"]
    assert fields["project"] == {"key": "ABC"}
    assert fields["issuetype"] == {"name": "Task"}
    assert "description" not in fields


def test_unreadable_metadata_sends_everything() -> None:
    """Fail open: dropping every field would create empty issues."""
    client = FakeClient(meta=None)
    sync_task(client, JiraSettings(), ref())
    assert "priority" in client.created[0]["fields"]


def test_updates_are_pruned_too() -> None:
    client = FakeClient(existing=open_issue(), meta=NO_PRIORITY)
    sync_task(client, JiraSettings(), ref())
    assert "priority" not in client.updated[0][1]["fields"]


def test_existing_issue_is_updated_not_duplicated() -> None:
    client = FakeClient(existing=open_issue())
    assert sync_task(client, JiraSettings(), ref()) == "updated ABC-7"
    assert client.created == []
    assert client.updated[0][0] == "ABC-7"


def test_dry_run_sends_nothing() -> None:
    client = FakeClient()
    assert sync_task(client, JiraSettings(), ref(), dry_run=True) == "would create"
    assert client.created == []

    existing = FakeClient(existing=open_issue())
    assert sync_task(existing, JiraSettings(), ref(), dry_run=True) == "would update ABC-7"
    assert existing.updated == []


# --- mapping ----------------------------------------------------------------


def test_type_and_priority_can_be_mapped() -> None:
    """A localised project calls the type "Задача" and renames priorities."""
    settings = JiraSettings(type_map={"Task": "Задача"}, priority_map={"High": "Высокий"})
    client = FakeClient()
    sync_task(client, settings, ref(priority="High"))
    fields = client.created[0]["fields"]
    assert fields["issuetype"] == {"name": "Задача"}
    assert fields["priority"] == {"name": "Высокий"}
    assert client.metadata_asked == ["Задача"]


def test_unmapped_values_are_sent_unchanged() -> None:
    client = FakeClient()
    sync_task(client, JiraSettings(type_map={"Bug": "Дефект"}), ref())
    assert client.created[0]["fields"]["issuetype"] == {"name": "Task"}


# --- assignee ---------------------------------------------------------------


def test_a_new_issue_gets_the_configured_assignee() -> None:
    client = FakeClient(assignee="712020:abc")
    sync_task(client, JiraSettings(), ref())
    assert client.created[0]["fields"]["assignee"] == {"id": "712020:abc"}


def test_an_update_leaves_the_assignee_alone_by_default() -> None:
    """Reassignment happens in Jira; the sync must not fight it every run."""
    client = FakeClient(existing=open_issue(), assignee="712020:abc")
    sync_task(client, JiraSettings(), ref())
    assert "assignee" not in client.updated[0][1]["fields"]


def test_force_assignee_reapplies_it_on_update() -> None:
    client = FakeClient(existing=open_issue(), assignee="712020:abc")
    sync_task(client, JiraSettings(force_assignee=True), ref())
    assert client.updated[0][1]["fields"]["assignee"] == {"id": "712020:abc"}


def test_no_assignee_field_is_sent_when_none_is_configured() -> None:
    client = FakeClient()
    sync_task(client, JiraSettings(force_assignee=True), ref())
    assert "assignee" not in client.created[0]["fields"]


# --- batched lookup ---------------------------------------------------------


def test_a_prefetched_map_replaces_the_per_task_search() -> None:
    client = FakeClient()
    result = sync_task(
        client, JiraSettings(), ref(), known={"tasc-api-001": {"key": "ABC-9", "fields": {}}}
    )
    assert result == "updated ABC-9"
    assert client.searched == []


def test_a_task_missing_from_the_map_is_created() -> None:
    client = FakeClient()
    assert sync_task(client, JiraSettings(), ref(), known={}) == "created ABC-1"
    assert client.searched == []


# --- transitions ------------------------------------------------------------


def test_a_transition_is_matched_by_where_it_leads() -> None:
    """Workflows name transitions freely; status_map holds a status name."""
    client = FakeClient(
        existing=open_issue(),
        transitions=[{"name": "Start progress", "to": {"name": "In Progress"}}],
    )
    sync_task(
        client, JiraSettings(status_map={"in_progress": "In Progress"}), ref(status="in_progress")
    )
    assert client.applied == [("ABC-7", "0")]


def test_status_transition_uses_the_configured_name() -> None:
    settings = JiraSettings(status_map={"in_progress": "Started"})
    client = FakeClient(existing=open_issue(), transitions=["Started", "Done"])
    sync_task(client, settings, ref(status="in_progress"))
    assert client.applied == [("ABC-7", "0")]


def test_matching_status_is_not_transitioned_again() -> None:
    client = FakeClient(existing=open_issue("in progress"), transitions=["In Progress"])
    sync_task(
        client, JiraSettings(status_map={"in_progress": "In Progress"}), ref(status="in_progress")
    )
    assert client.applied == []


def test_an_unmapped_status_is_left_alone() -> None:
    client = FakeClient(existing=open_issue(), transitions=["Done"])
    sync_task(client, JiraSettings(status_map={}), ref(status="blocked"))
    assert client.applied == []


def test_a_missing_transition_is_skipped_rather_than_crashing() -> None:
    """Jira workflows vary; a name we cannot reach must not abort the sync."""
    client = FakeClient(existing=open_issue(), transitions=["Something Else"])
    sync_task(
        client, JiraSettings(status_map={"in_progress": "In Progress"}), ref(status="in_progress")
    )
    assert client.applied == []


def test_a_new_issue_that_is_already_in_progress_is_moved() -> None:
    client = FakeClient(transitions=[{"name": "Start", "to": {"name": "In Progress"}}])
    sync_task(client, JiraSettings(), ref(status="in_progress"))
    assert client.applied == [("ABC-1", "0")]


def test_a_new_todo_issue_is_not_transitioned() -> None:
    client = FakeClient(transitions=["Done"])
    sync_task(client, JiraSettings(), ref(status="todo"))
    assert client.applied == []


# --- preflight --------------------------------------------------------------


def messages(findings) -> str:
    return "\n".join(finding.message for finding in findings)


def test_preflight_is_quiet_when_everything_lines_up() -> None:
    client = FakeClient(statuses={"Task": frozenset({"To Do", "In Progress", "Done"})})
    assert preflight(client, JiraSettings(), [ref(priority="High")]) == []


def test_preflight_reports_an_unknown_issue_type() -> None:
    client = FakeClient(issue_types=["Story"], statuses={"Story": frozenset({"To Do"})})
    findings = preflight(client, JiraSettings(status_map={}), [ref()])
    assert findings[0].blocking
    assert "Issue type 'Task' does not exist" in findings[0].message
    assert "type_map" in findings[0].message


def test_preflight_reports_a_priority_the_scheme_does_not_offer() -> None:
    """A renamed priority scheme: the field exists, the value does not."""
    renamed = TypeMeta("1", OPEN_SCREEN.field_ids, frozenset({"Высокий", "Средний"}))
    client = FakeClient(meta=renamed, statuses={"Task": frozenset({"To Do"})})
    findings = preflight(client, JiraSettings(status_map={}), [ref(priority="Medium")])
    assert findings[0].blocking
    assert "Priority 'Medium' is not in the scheme" in findings[0].message
    assert "priority_map" in findings[0].message


def test_preflight_names_the_fields_that_will_be_dropped() -> None:
    """The one line the reporter wanted instead of a 400 per task."""
    client = FakeClient(meta=NO_PRIORITY, statuses={"Task": frozenset({"To Do"})})
    findings = preflight(client, JiraSettings(status_map={}), [ref()])
    assert [finding.blocking for finding in findings] == [False]
    assert "no priority on its create screen" in findings[0].message


def test_preflight_reports_a_status_that_does_not_exist() -> None:
    client = FakeClient(statuses={"Task": frozenset({"To Do", "Done"})})
    findings = preflight(client, JiraSettings(status_map={"in_progress": "Started"}), [ref()])
    assert findings[0].blocking
    assert "status_map maps 'in_progress' to 'Started'" in messages(findings)


def test_preflight_survives_a_project_it_cannot_read() -> None:
    class Refuses(FakeClient):
        def issue_types(self):
            raise RuntimeError("Jira GET /issue/createmeta -> 403: Forbidden")

    findings = preflight(Refuses(), JiraSettings(), [ref()])
    assert findings[0].blocking
    assert "Could not read the project's issue types" in findings[0].message


def test_preflight_notes_unreadable_field_metadata() -> None:
    client = FakeClient(meta=None, statuses={"Task": frozenset({"To Do", "Done"})})
    findings = preflight(client, JiraSettings(status_map={}), [ref()])
    assert [finding.blocking for finding in findings] == [False]
    assert "Could not read the create screen" in findings[0].message


def test_preflight_notes_unreadable_statuses() -> None:
    class Refuses(FakeClient):
        def project_statuses(self):
            raise RuntimeError("Jira GET /project/ABC/statuses -> 404: no project")

    findings = preflight(Refuses(), JiraSettings(), [ref(priority="High")])
    assert [finding.blocking for finding in findings] == [False]
    assert "Could not read the project's statuses" in findings[0].message


def test_preflight_checks_the_assignee_field_only_when_one_is_set() -> None:
    without_assignee = FakeClient(
        meta=TypeMeta("1", frozenset({"summary", "description", "priority", "labels"}), None),
        statuses={"Task": frozenset({"To Do"})},
    )
    assert preflight(without_assignee, JiraSettings(status_map={}), [ref()]) == []

    with_assignee = FakeClient(
        meta=TypeMeta("1", frozenset({"summary", "description", "priority", "labels"}), None),
        statuses={"Task": frozenset({"To Do"})},
        assignee="712020:abc",
    )
    findings = preflight(with_assignee, JiraSettings(status_map={}), [ref()])
    assert "no assignee on its create screen" in messages(findings)
