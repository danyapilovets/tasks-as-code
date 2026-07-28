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
    def __init__(self, status_code: int, payload: Any = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse):
        self._response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.headers: dict[str, str] = {}
        self.auth = None

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self._response


@pytest.fixture
def client() -> JiraClient:
    return JiraClient(CREDENTIALS)


def attach(client: JiraClient, response: FakeResponse) -> FakeSession:
    session = FakeSession(response)
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
