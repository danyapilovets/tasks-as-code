"""The Jira HTTP layer, driven by a stubbed session. No sockets are opened."""

from __future__ import annotations

from typing import Any

import pytest

from tasks_as_code.integrations.jira import JiraClient, JiraCredentials

CREDENTIALS = JiraCredentials(
    base_url="https://example.atlassian.net",
    email="dev@example.com",
    api_token="token",
    project_key="ABC",
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Replays the given responses in order, repeating the last one."""

    def __init__(self, *responses: FakeResponse):
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.headers: dict[str, str] = {}
        self.auth = None

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


class Clock:
    """Stands in for time.sleep so retry tests stay instant."""

    def __init__(self) -> None:
        self.waited: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)


@pytest.fixture
def client() -> JiraClient:
    return JiraClient(CREDENTIALS)


def attach(client: JiraClient, *responses: FakeResponse) -> FakeSession:
    session = FakeSession(*responses)
    client.session = session  # type: ignore[assignment]
    return session


def test_client_targets_the_v3_api(client: JiraClient) -> None:
    assert client.api == "https://example.atlassian.net/rest/api/3"


def test_requests_carry_a_timeout(client: JiraClient) -> None:
    """A hung Jira call must not hang the CLI forever."""
    session = attach(client, FakeResponse(200, {"issues": []}))
    client.find_by_label("tasc-api-001")
    assert session.calls[0][2]["timeout"] == 30


def test_error_status_includes_the_body(client: JiraClient) -> None:
    attach(client, FakeResponse(403, text="Forbidden"))
    with pytest.raises(RuntimeError, match=r"403.*Forbidden"):
        client.find_by_label("tasc-api-001")


def test_no_content_response_returns_an_empty_dict(client: JiraClient) -> None:
    """A 204 has no body, so calling .json() on it would raise."""
    attach(client, FakeResponse(204))
    assert client.apply_transition("ABC-1", "5") == {}


def test_find_by_label_scopes_the_query_to_the_project(client: JiraClient) -> None:
    session = attach(client, FakeResponse(200, {"issues": [{"key": "ABC-1"}]}))
    assert client.find_by_label("tasc-api-001") == {"key": "ABC-1"}
    jql = session.calls[0][2]["json"]["jql"]
    assert "project = ABC" in jql
    assert 'labels = "tasc-api-001"' in jql


def test_find_by_label_returns_none_when_nothing_matches(client: JiraClient) -> None:
    attach(client, FakeResponse(200, {"issues": []}))
    assert client.find_by_label("tasc-api-001") is None


def test_create_and_update_hit_the_expected_paths(client: JiraClient) -> None:
    session = attach(client, FakeResponse(200, {"key": "ABC-1"}))
    client.create_issue({"fields": {}})
    client.update_issue("ABC-1", {"fields": {}})
    methods_and_urls = [(method, url) for method, url, _ in session.calls]
    assert methods_and_urls == [
        ("POST", f"{client.api}/issue"),
        ("PUT", f"{client.api}/issue/ABC-1"),
    ]


def test_available_transitions_defaults_to_empty(client: JiraClient) -> None:
    attach(client, FakeResponse(200, {}))
    assert client.available_transitions("ABC-1") == []


# --- retrying ---------------------------------------------------------------


def retrying_client(clock: Clock, max_attempts: int = 3) -> JiraClient:
    return JiraClient(CREDENTIALS, max_attempts=max_attempts, sleep=clock)


def test_a_rate_limited_request_is_retried() -> None:
    clock = Clock()
    client = retrying_client(clock)
    session = attach(client, FakeResponse(429), FakeResponse(200, {"issues": []}))
    assert client.find_by_label("tasc-api-001") is None
    assert len(session.calls) == 2
    assert clock.waited == [1.0]


def test_retry_after_is_honoured() -> None:
    """Jira says when to come back; guessing gets throttled again."""
    clock = Clock()
    client = retrying_client(clock)
    attach(client, FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, {}))
    client.find_by_label("tasc-api-001")
    assert clock.waited == [7.0]


def test_an_unparsable_retry_after_falls_back_to_backoff() -> None:
    clock = Clock()
    client = retrying_client(clock)
    attach(client, FakeResponse(503, headers={"Retry-After": "soon"}), FakeResponse(200, {}))
    client.find_by_label("tasc-api-001")
    assert clock.waited == [1.0]


def test_retries_are_bounded_and_the_last_error_surfaces() -> None:
    clock = Clock()
    client = retrying_client(clock)
    session = attach(client, FakeResponse(503, text="unavailable"))
    with pytest.raises(RuntimeError, match="503"):
        client.find_by_label("tasc-api-001")
    assert len(session.calls) == 3
    assert clock.waited == [1.0, 2.0]


def test_a_bad_request_is_not_retried() -> None:
    """A 400 is a payload to fix, not a call to repeat."""
    clock = Clock()
    client = retrying_client(clock)
    session = attach(client, FakeResponse(400, text="Field 'priority' cannot be set."))
    with pytest.raises(RuntimeError, match="priority"):
        client.find_by_label("tasc-api-001")
    assert len(session.calls) == 1
    assert clock.waited == []


# --- create metadata --------------------------------------------------------


def test_issue_types_use_the_supported_endpoint(client: JiraClient) -> None:
    """The single createmeta call that returned everything now answers 404."""
    session = attach(client, FakeResponse(200, {"issueTypes": [], "total": 0}))
    client.issue_types()
    method, url, _ = session.calls[0]
    assert method == "GET"
    assert url.startswith(f"{client.api}/issue/createmeta/ABC/issuetypes?")


def test_metadata_pages_are_followed(client: JiraClient) -> None:
    session = attach(
        client,
        FakeResponse(200, {"issueTypes": [{"id": "1", "name": "Task"}], "total": 2}),
        FakeResponse(200, {"issueTypes": [{"id": "2", "name": "Bug"}], "total": 2}),
    )
    assert [entry["name"] for entry in client.issue_types()] == ["Task", "Bug"]
    assert "startAt=1" in session.calls[1][1]


def test_metadata_reports_fields_and_priorities(client: JiraClient) -> None:
    attach(
        client,
        FakeResponse(200, {"issueTypes": [{"id": "10001", "name": "Task"}], "total": 1}),
        FakeResponse(
            200,
            {
                "fields": [
                    {"fieldId": "summary"},
                    {"fieldId": "priority", "allowedValues": [{"name": "High"}, {"name": "Low"}]},
                ],
                "total": 2,
            },
        ),
    )
    meta = client.metadata_for("Task")
    assert meta is not None
    assert meta.issue_type_id == "10001"
    assert meta.field_ids == frozenset({"summary", "priority"})
    assert meta.priorities == frozenset({"High", "Low"})


def test_a_project_without_priority_reports_no_priorities(client: JiraClient) -> None:
    """Absent field and absent value are different problems, so they differ here."""
    attach(
        client,
        FakeResponse(200, {"issueTypes": [{"id": "10002", "name": "Task"}], "total": 1}),
        FakeResponse(200, {"fields": [{"fieldId": "summary"}], "total": 1}),
    )
    meta = client.metadata_for("Task")
    assert meta is not None
    assert meta.priorities is None


def test_the_issue_type_list_is_read_once_per_run(client: JiraClient) -> None:
    """One call per issue type is the cost of the new endpoints; repeating the
    list on top of that is how a large project gets rate-limited."""
    session = attach(client, FakeResponse(200, {"issueTypes": [], "total": 0}))
    client.issue_types()
    client.issue_types()
    assert len(session.calls) == 1


def test_metadata_is_read_once_per_issue_type(client: JiraClient) -> None:
    session = attach(
        client,
        FakeResponse(200, {"issueTypes": [{"id": "1", "name": "Task"}], "total": 1}),
        FakeResponse(200, {"fields": [{"fieldId": "summary"}], "total": 1}),
    )
    client.metadata_for("Task")
    calls_after_first = len(session.calls)
    client.metadata_for("Task")
    assert len(session.calls) == calls_after_first


def test_the_issue_type_is_matched_case_insensitively(client: JiraClient) -> None:
    attach(
        client,
        FakeResponse(200, {"issueTypes": [{"id": "1", "name": "Task"}], "total": 1}),
        FakeResponse(200, {"fields": [{"fieldId": "summary"}], "total": 1}),
    )
    assert client.metadata_for("task") is not None


def test_metadata_is_none_for_an_issue_type_the_project_lacks(client: JiraClient) -> None:
    attach(client, FakeResponse(200, {"issueTypes": [{"id": "1", "name": "Bug"}], "total": 1}))
    assert client.metadata_for("Task") is None


def test_metadata_is_none_when_jira_refuses(client: JiraClient) -> None:
    """Fail open, so an unreadable screen does not empty every payload."""
    attach(client, FakeResponse(403, text="Forbidden"))
    assert client.metadata_for("Task") is None


def test_metadata_survives_an_unexpected_shape(client: JiraClient) -> None:
    attach(client, FakeResponse(200, {"issueTypes": "not a list", "total": 1}))
    assert client.metadata_for("Task") is None


# --- batched label lookup ---------------------------------------------------


def test_issues_by_labels_maps_each_result_back_to_its_label(client: JiraClient) -> None:
    session = attach(
        client,
        FakeResponse(
            200,
            {
                "issues": [
                    {"key": "ABC-1", "fields": {"labels": ["tasc-api-001", "epic-api"]}},
                    {"key": "ABC-2", "fields": {"labels": ["tasc-api-002"]}},
                ]
            },
        ),
    )
    found = client.issues_by_labels(["tasc-api-001", "tasc-api-002", "tasc-api-003"])
    assert set(found) == {"tasc-api-001", "tasc-api-002"}
    assert found["tasc-api-001"]["key"] == "ABC-1"
    assert len(session.calls) == 1
    assert "labels IN " in session.calls[0][2]["json"]["jql"]


def test_issues_by_labels_chunks_long_backlogs(client: JiraClient) -> None:
    session = attach(client, FakeResponse(200, {"issues": []}))
    client.issues_by_labels([f"tasc-api-{index:03d}" for index in range(120)])
    assert len(session.calls) == 3


def test_issues_by_labels_handles_an_empty_backlog(client: JiraClient) -> None:
    session = attach(client, FakeResponse(200, {"issues": []}))
    assert client.issues_by_labels([]) == {}
    assert session.calls == []


# --- comments ---------------------------------------------------------------


def test_comments_are_read_across_pages(client: JiraClient) -> None:
    """A marker posted months ago must stay findable under later discussion."""
    session = attach(
        client,
        FakeResponse(200, {"comments": [{"id": "1"}], "total": 2}),
        FakeResponse(200, {"comments": [{"id": "2"}], "total": 2}),
    )
    assert [comment["id"] for comment in client.comments("ABC-1")] == ["1", "2"]
    assert session.calls[0][1].startswith(f"{client.api}/issue/ABC-1/comment?")


def test_adding_a_comment_wraps_the_body(client: JiraClient) -> None:
    session = attach(client, FakeResponse(201, {"id": "10"}))
    document = {"version": 1, "type": "doc", "content": []}
    client.add_comment("ABC-1", document)
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("POST", f"{client.api}/issue/ABC-1/comment")
    assert kwargs["json"] == {"body": document}


# --- issue links ------------------------------------------------------------


def test_link_types_are_listed_by_name(client: JiraClient) -> None:
    types = [{"name": "Blocks"}, {"id": "2"}, {"name": "Clones"}]
    attach(client, FakeResponse(200, {"issueLinkTypes": types}))
    assert client.link_types() == ["Blocks", "Clones"]


def test_link_types_tolerate_an_empty_answer(client: JiraClient) -> None:
    attach(client, FakeResponse(200, {}))
    assert client.link_types() == []


def test_issue_links_ask_for_that_field_only(client: JiraClient) -> None:
    session = attach(client, FakeResponse(200, {"fields": {"issuelinks": [{"id": "1"}]}}))
    assert client.issue_links("ABC-1") == [{"id": "1"}]
    assert session.calls[0][1] == f"{client.api}/issue/ABC-1?fields=issuelinks"


def test_an_issue_without_links_reports_none(client: JiraClient) -> None:
    attach(client, FakeResponse(200, {"fields": {}}))
    assert client.issue_links("ABC-1") == []


def test_linking_sends_both_ends_as_given(client: JiraClient) -> None:
    session = attach(client, FakeResponse(201))
    client.link_issues("Blocks", inward="ABC-1", outward="ABC-2")
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("POST", f"{client.api}/issueLink")
    assert kwargs["json"] == {
        "type": {"name": "Blocks"},
        "inwardIssue": {"key": "ABC-1"},
        "outwardIssue": {"key": "ABC-2"},
    }


def test_an_empty_created_body_is_not_an_error(client: JiraClient) -> None:
    """Creating a link answers 201 with nothing to parse."""

    class NoBody(FakeResponse):
        def json(self) -> Any:
            raise ValueError("No JSON object could be decoded")

    attach(client, NoBody(201))
    assert client.link_issues("Blocks", inward="ABC-1", outward="ABC-2") == {}


# --- project statuses -------------------------------------------------------


def test_project_statuses_group_by_issue_type(client: JiraClient) -> None:
    attach(
        client,
        FakeResponse(
            200,
            [
                {"name": "Task", "statuses": [{"name": "To Do"}, {"name": "Done"}]},
                {"name": "Bug", "statuses": [{"name": "Open"}]},
            ],
        ),
    )
    assert client.project_statuses() == {
        "Task": frozenset({"To Do", "Done"}),
        "Bug": frozenset({"Open"}),
    }


def test_project_statuses_tolerate_an_unexpected_shape(client: JiraClient) -> None:
    attach(client, FakeResponse(200, {"errorMessages": ["nope"]}))
    assert client.project_statuses() == {}
