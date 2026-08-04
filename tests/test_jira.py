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
    _plain_text,
    build_description,
    ensure_epics,
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
    field_ids=frozenset({"summary", "description", "priority", "labels", "assignee", "parent"}),
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
        comments: list[dict[str, Any]] | None = None,
        links: list[dict[str, Any]] | None = None,
        link_types: list[str] | None = None,
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
        self._comments = comments or []
        self._links = links or []
        self._link_types = link_types if link_types is not None else ["Blocks", "Relates"]
        self.created: list[dict[str, Any]] = []
        self.linked: list[tuple[str, str, str]] = []
        self.links_read: list[str] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.applied: list[tuple[str, str]] = []
        self.searched: list[str] = []
        self.metadata_asked: list[str] = []
        self.commented: list[tuple[str, dict[str, Any]]] = []
        self.comments_read: list[str] = []

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

    def comments(self, key: str) -> list[dict[str, Any]]:
        self.comments_read.append(key)
        return self._comments

    def link_types(self) -> list[str]:
        return self._link_types

    def issue_links(self, key: str) -> list[dict[str, Any]]:
        self.links_read.append(key)
        return self._links

    def link_issues(self, link_type: str, inward: str, outward: str) -> dict[str, Any]:
        self.linked.append((link_type, inward, outward))
        return {}

    def add_comment(self, key: str, body: dict[str, Any]) -> dict[str, Any]:
        self.commented.append((key, body))
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


def test_a_task_barred_from_creating_reports_it_and_sends_nothing() -> None:
    client = FakeClient()
    assert sync_task(client, JiraSettings(), ref(), known={}, create=False) == (
        "no issue, left alone"
    )
    assert client.created == []


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


# --- epics as parents -------------------------------------------------------


def test_epics_are_not_touched_unless_asked_for() -> None:
    """A project whose hierarchy is managed elsewhere must not gain a second set."""
    client = FakeClient()
    assert ensure_epics(client, JiraSettings(), [ref()], known={}) == {}
    assert client.created == []


def test_an_existing_epic_is_reused() -> None:
    client = FakeClient()
    known = {"tasc-epic-api": {"key": "ABC-100", "fields": {}}}
    resolved = ensure_epics(client, JiraSettings(epic_as_parent=True), [ref()], known=known)
    assert resolved == {"api": "ABC-100"}
    assert client.created == []


def test_a_missing_epic_is_created_with_its_own_label() -> None:
    client = FakeClient()
    resolved = ensure_epics(client, JiraSettings(epic_as_parent=True), [ref()], known={})
    assert resolved == {"api": "ABC-1"}
    fields = client.created[0]["fields"]
    assert fields["issuetype"] == {"name": "Epic"}
    assert fields["summary"] == "api"
    assert fields["labels"] == ["tasc-epic-api"]


def test_one_epic_is_created_once_for_all_its_tasks() -> None:
    client = FakeClient()
    refs = [ref("api-001"), ref("api-002")]
    resolved = ensure_epics(client, JiraSettings(epic_as_parent=True), refs, known={})
    assert len(client.created) == 1
    assert resolved == {"api": "ABC-1"}


def test_the_epic_issue_type_is_configurable() -> None:
    client = FakeClient()
    settings = JiraSettings(epic_as_parent=True, epic_type="Епік")
    ensure_epics(client, settings, [ref()], known={})
    assert client.created[0]["fields"]["issuetype"] == {"name": "Епік"}


def test_a_dry_run_creates_no_epic() -> None:
    client = FakeClient()
    settings = JiraSettings(epic_as_parent=True)
    assert ensure_epics(client, settings, [ref()], known={}, dry_run=True) == {}
    assert client.created == []


def test_without_the_map_the_epic_is_searched_for() -> None:
    client = FakeClient(existing={"key": "ABC-100", "fields": {}})
    resolved = ensure_epics(client, JiraSettings(epic_as_parent=True), [ref()])
    assert resolved == {"api": "ABC-100"}
    assert client.searched == ["tasc-epic-api"]


def test_a_parent_is_sent_as_a_field() -> None:
    client = FakeClient()
    sync_task(client, JiraSettings(), ref(), known={}, parent="ABC-100")
    assert client.created[0]["fields"]["parent"] == {"key": "ABC-100"}


def test_a_parent_is_kept_on_updates_too() -> None:
    client = FakeClient(existing=open_issue())
    sync_task(client, JiraSettings(), ref(), parent="ABC-100")
    assert client.updated[0][1]["fields"]["parent"] == {"key": "ABC-100"}


def test_no_parent_field_is_sent_without_one() -> None:
    client = FakeClient()
    sync_task(client, JiraSettings(), ref(), known={})
    assert "parent" not in client.created[0]["fields"]


def test_a_project_without_a_parent_field_still_syncs() -> None:
    client = FakeClient(meta=NO_PRIORITY)
    sync_task(client, JiraSettings(), ref(), known={}, parent="ABC-100")
    assert "parent" not in client.created[0]["fields"]


# --- dependency links -------------------------------------------------------


def known_issue(label: str, key: str) -> dict[str, dict[str, Any]]:
    return {label: {"key": key, "fields": {}}}


def test_a_dependency_becomes_an_issue_link() -> None:
    """Text in a description cannot be filtered, sorted or seen on a board."""
    client = FakeClient()
    known = known_issue("tasc-api-001", "ABC-7") | known_issue("tasc-api-002", "ABC-2")
    sync_task(client, JiraSettings(), ref(depends_on=["api-002"]), known=known)
    assert client.linked == [("Blocks", "ABC-2", "ABC-7")]


def test_the_dependency_is_the_end_that_does_the_blocking() -> None:
    """Verified against Jira Cloud: the inward issue is the one that blocks."""
    client = FakeClient()
    known = known_issue("tasc-api-001", "ABC-7") | known_issue("tasc-api-002", "ABC-2")
    sync_task(client, JiraSettings(), ref(depends_on=["api-002"]), known=known)
    _, inward, outward = client.linked[0]
    assert (inward, outward) == ("ABC-2", "ABC-7")


def test_a_linked_dependency_leaves_the_description() -> None:
    client = FakeClient()
    known = known_issue("tasc-api-001", "ABC-7") | known_issue("tasc-api-002", "ABC-2")
    sync_task(client, JiraSettings(), ref(depends_on=["api-002"]), known=known)
    assert "Depends on" not in _plain_text(client.updated[0][1]["fields"]["description"])


def test_a_dependency_without_an_issue_stays_in_the_description() -> None:
    client = FakeClient()
    known = known_issue("tasc-api-001", "ABC-7")
    sync_task(client, JiraSettings(), ref(depends_on=["api-002"]), known=known)
    assert "Depends on: api-002" in _plain_text(client.updated[0][1]["fields"]["description"])
    assert client.linked == []


def test_only_the_unlinked_dependencies_are_listed() -> None:
    client = FakeClient()
    known = (
        known_issue("tasc-api-001", "ABC-7")
        | known_issue("tasc-api-002", "ABC-2")
        | known_issue("tasc-api-004", "ABC-4")
    )
    sync_task(
        client, JiraSettings(), ref(depends_on=["api-002", "api-003", "api-004"]), known=known
    )
    text = _plain_text(client.updated[0][1]["fields"]["description"])
    assert "Depends on: api-003" in text
    assert "api-002" not in text


def test_an_existing_link_is_not_created_again() -> None:
    client = FakeClient(links=[{"type": {"name": "Blocks"}, "inwardIssue": {"key": "ABC-2"}}])
    known = known_issue("tasc-api-001", "ABC-7") | known_issue("tasc-api-002", "ABC-2")
    sync_task(client, JiraSettings(), ref(depends_on=["api-002"]), known=known)
    assert client.linked == []


def test_a_link_of_another_type_does_not_count_as_the_dependency() -> None:
    client = FakeClient(links=[{"type": {"name": "Relates"}, "inwardIssue": {"key": "ABC-2"}}])
    known = known_issue("tasc-api-001", "ABC-7") | known_issue("tasc-api-002", "ABC-2")
    sync_task(client, JiraSettings(), ref(depends_on=["api-002"]), known=known)
    assert len(client.linked) == 1


def test_a_new_issue_is_not_read_for_links_it_cannot_have() -> None:
    client = FakeClient()
    known = known_issue("tasc-api-002", "ABC-2")
    sync_task(client, JiraSettings(), ref(depends_on=["api-002"]), known=known)
    assert client.links_read == []
    assert client.linked == [("Blocks", "ABC-2", "ABC-1")]


def test_the_link_type_is_configurable() -> None:
    client = FakeClient()
    known = known_issue("tasc-api-001", "ABC-7") | known_issue("tasc-api-002", "ABC-2")
    sync_task(
        client,
        JiraSettings(dependency_link_type="Залежить від"),
        ref(depends_on=["api-002"]),
        known=known,
    )
    assert client.linked[0][0] == "Залежить від"


def test_linking_can_be_switched_off() -> None:
    client = FakeClient()
    known = known_issue("tasc-api-001", "ABC-7") | known_issue("tasc-api-002", "ABC-2")
    sync_task(
        client, JiraSettings(link_dependencies=False), ref(depends_on=["api-002"]), known=known
    )
    assert client.linked == []
    assert "Depends on: api-002" in _plain_text(client.updated[0][1]["fields"]["description"])


def test_without_the_batched_map_dependencies_stay_text() -> None:
    """Resolving them would cost a search each, for a link that can wait a run."""
    client = FakeClient(existing=open_issue())
    sync_task(client, JiraSettings(), ref(depends_on=["api-002"]))
    assert client.linked == []
    assert "Depends on: api-002" in _plain_text(client.updated[0][1]["fields"]["description"])


# --- outcome comment --------------------------------------------------------


def comment_of(client: FakeClient, index: int = 0) -> str:
    return _plain_text(client.commented[index][1])


def test_a_closed_task_posts_what_it_produced() -> None:
    """A transition into Done says the work stopped, not what came out of it."""
    client = FakeClient(existing=open_issue(), transitions=["Done"])
    sync_task(client, JiraSettings(), ref(status="done", note="Cluster is up, nodes ready."))
    assert client.commented[0][0] == "ABC-7"
    assert "Cluster is up, nodes ready." in comment_of(client)


def test_the_outcome_carries_the_marker_that_makes_it_findable() -> None:
    client = FakeClient(existing=open_issue())
    sync_task(client, JiraSettings(), ref(status="done", note="Done and verified."))
    assert comment_of(client).startswith("tasc:api-001 done")


def test_an_outcome_already_on_the_issue_is_not_posted_twice() -> None:
    marker = {"body": {"content": [{"content": [{"text": "tasc:api-001 done"}]}]}}
    client = FakeClient(existing=open_issue(), comments=[marker])
    sync_task(client, JiraSettings(), ref(status="done", note="Done and verified."))
    assert client.commented == []


def test_another_task_s_outcome_does_not_suppress_this_one() -> None:
    marker = {"body": {"content": [{"content": [{"text": "tasc:api-002 done"}]}]}}
    client = FakeClient(existing=open_issue(), comments=[marker])
    sync_task(client, JiraSettings(), ref(status="done", note="Done and verified."))
    assert len(client.commented) == 1


def test_a_comment_stored_as_plain_text_is_still_matched() -> None:
    """Older comments come back as a string body rather than an ADF document."""
    client = FakeClient(existing=open_issue(), comments=[{"body": "tasc:api-001 done\nnote"}])
    sync_task(client, JiraSettings(), ref(status="done", note="Done and verified."))
    assert client.commented == []


def test_a_closed_task_without_a_note_comments_nothing() -> None:
    client = FakeClient(existing=open_issue())
    sync_task(client, JiraSettings(), ref(status="done"))
    assert client.commented == []
    assert client.comments_read == []


def test_an_open_task_comments_nothing() -> None:
    client = FakeClient(existing=open_issue())
    sync_task(client, JiraSettings(), ref(status="in_progress", note="not closed yet"))
    assert client.commented == []


def test_the_outcome_comment_can_be_switched_off() -> None:
    client = FakeClient(existing=open_issue())
    sync_task(client, JiraSettings(comment_on_done=False), ref(status="done", note="whatever"))
    assert client.commented == []


def test_a_freshly_created_issue_is_not_read_before_commenting() -> None:
    """It cannot hold the marker yet, so the lookup would only cost a call."""
    client = FakeClient(transitions=["Done"])
    sync_task(client, JiraSettings(), ref(status="done", note="Closed before the first sync."))
    assert client.comments_read == []
    assert client.commented[0][0] == "ABC-1"


def test_a_dry_run_posts_no_comment() -> None:
    client = FakeClient(existing=open_issue())
    sync_task(client, JiraSettings(), ref(status="done", note="whatever"), dry_run=True)
    assert client.commented == []


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


def test_preflight_reports_a_link_type_this_jira_lacks() -> None:
    """Otherwise it is a 400 on every task that depends on another."""
    client = FakeClient(
        statuses={"Task": frozenset({"To Do"})}, link_types=["Relates", "Duplicate"]
    )
    findings = preflight(client, JiraSettings(status_map={}), [ref(depends_on=["api-002"])])
    assert findings[0].blocking
    assert "Link type 'Blocks' does not exist" in findings[0].message


def test_preflight_accepts_a_link_type_this_jira_has() -> None:
    client = FakeClient(statuses={"Task": frozenset({"To Do"})})
    settings = JiraSettings(status_map={})
    assert preflight(client, settings, [ref(depends_on=["api-002"])]) == []


def test_preflight_ignores_link_types_when_nothing_depends_on_anything() -> None:
    client = FakeClient(statuses={"Task": frozenset({"To Do"})}, link_types=[])
    assert preflight(client, JiraSettings(status_map={}), [ref()]) == []


def test_preflight_ignores_link_types_when_linking_is_off() -> None:
    client = FakeClient(statuses={"Task": frozenset({"To Do"})}, link_types=[])
    settings = JiraSettings(status_map={}, link_dependencies=False)
    assert preflight(client, settings, [ref(depends_on=["api-002"])]) == []


def test_preflight_notes_unreadable_link_types() -> None:
    class Refuses(FakeClient):
        def link_types(self):
            raise RuntimeError("Jira GET /issueLinkType -> 403: Forbidden")

    client = Refuses(statuses={"Task": frozenset({"To Do"})})
    findings = preflight(client, JiraSettings(status_map={}), [ref(depends_on=["api-002"])])
    assert [finding.blocking for finding in findings] == [False]
    assert "Could not read the instance's link types" in findings[0].message


def test_preflight_reports_a_missing_epic_type() -> None:
    client = FakeClient(issue_types=["Task"], statuses={"Task": frozenset({"To Do"})})
    settings = JiraSettings(status_map={}, epic_as_parent=True)
    findings = preflight(client, settings, [ref()])
    assert findings[0].blocking
    assert "needs the issue type 'Epic'" in findings[0].message


def test_preflight_notes_a_type_that_cannot_hold_a_parent() -> None:
    client = FakeClient(
        issue_types=["Task", "Epic"], meta=NO_PRIORITY, statuses={"Task": frozenset({"To Do"})}
    )
    settings = JiraSettings(status_map={}, epic_as_parent=True)
    findings = preflight(client, settings, [ref()])
    assert "no parent field on its create screen" in messages(findings)


def test_preflight_says_nothing_about_epics_unless_asked_for() -> None:
    client = FakeClient(issue_types=["Task"], statuses={"Task": frozenset({"To Do"})})
    assert preflight(client, JiraSettings(status_map={}), [ref()]) == []


def test_plain_text_ignores_a_node_that_is_neither_text_nor_container() -> None:
    assert _plain_text(None) == ""
    assert _plain_text(7) == ""
