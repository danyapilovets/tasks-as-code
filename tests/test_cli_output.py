"""Human-facing rendering and the sync command."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, ClassVar

import pytest
from typer.testing import CliRunner

from tasks_as_code import __version__
from tasks_as_code.cli import app
from tasks_as_code.core.paths import Paths

from .conftest import make_task

runner = CliRunner()


def run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    combined = f"{result.stdout}\n{result.stderr}"
    return result.exit_code, " ".join(combined.split())


def test_module_entry_point_works() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "tasks_as_code", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert __version__ in completed.stdout


def test_next_renders_description_and_criteria(in_project: Paths, add_epic) -> None:
    add_epic(
        "api",
        [
            make_task(
                "api-001",
                description="Wire up the health endpoint",
                acceptance_criteria=["returns 200", "covered by a test"],
            )
        ],
    )
    code, out = run("next")
    assert code == 0
    assert "Wire up the health endpoint" in out
    assert "returns 200" in out
    assert "tasc mark api-001 in_progress" in out


def test_next_warns_about_work_already_in_progress(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", status="in_progress"), make_task("api-002")])
    code, out = run("next")
    assert code == 0
    assert "Already in progress" in out
    assert "api-001" in out


def test_show_renders_every_field(in_project: Paths, add_epic) -> None:
    add_epic(
        "api",
        [
            make_task(
                "api-001",
                description="Details here",
                acceptance_criteria=["done when green"],
                depends_on=["api-002"],
                updated="2026-01-01",
            ),
            make_task("api-002"),
        ],
    )
    code, out = run("show", "api-001")
    assert code == 0
    for expected in (
        "api-001",
        "Details here",
        "done when green",
        "blocked by: api-002",
        "2026-01-01",
        "tasks/active/api.yaml",
    ):
        assert expected in out


def test_show_marks_a_ready_task_as_unblocked(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    code, out = run("show", "api-001")
    assert code == 0
    assert "blocked by" not in out


def test_list_renders_a_table_with_a_total(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001"), make_task("api-002", status="in_progress")])
    code, out = run("list")
    assert code == 0
    assert "api-001" in out and "api-002" in out
    assert "Total: 2" in out


def test_list_of_an_empty_project_reports_zero(in_project: Paths) -> None:
    code, out = run("list")
    assert code == 0
    assert "Total: 0" in out


def test_done_reports_both_destinations(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    code, out = run("done", "api-001", "--note", "shipped")
    assert code == 0
    assert "tasks/archive/api-001.yaml" in out
    assert "Logged in" in out


def test_reindex_reports_the_task_count(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    code, out = run("reindex")
    assert code == 0
    assert "tasks/INDEX.md" in out
    assert "1 tasks" in out


def test_new_reports_the_file_it_wrote(in_project: Paths) -> None:
    code, out = run("new", "api", "--summary", "Fresh")
    assert code == 0
    assert "api-001" in out
    assert "tasks/active/api.yaml" in out


def test_new_rejects_an_unknown_priority(in_project: Paths) -> None:
    code, out = run("new", "api", "--summary", "Fresh", "-p", "Urgent")
    assert code == 1
    assert "Could not create task" in out


def test_stale_success_names_the_threshold(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    code, out = run("stale")
    assert code == 0
    assert "7 days" in out


def test_stale_lists_a_task_that_was_never_stamped(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", status="in_progress")])
    code, out = run("stale")
    assert code == 1
    assert "never" in out


class StubClient:
    """Stands in for JiraClient so no session is ever constructed."""

    #: Labels of the last batched lookup, so a test can see it happened once.
    looked_up: ClassVar[list[str]] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    def issues_by_labels(self, labels: list[str]) -> dict[str, Any]:
        StubClient.looked_up = list(labels)
        return {}


@pytest.fixture
def stub_jira(monkeypatch: pytest.MonkeyPatch):
    """Supply credentials and a client stub; nothing touches the network."""
    from tasks_as_code.integrations import jira

    credentials = jira.JiraCredentials(
        base_url="https://example.atlassian.net",
        email="dev@example.com",
        api_token="token",
        project_key="ABC",
    )
    monkeypatch.setattr(jira.JiraCredentials, "from_env", classmethod(lambda cls: credentials))
    monkeypatch.setattr(jira, "JiraClient", StubClient)
    return jira


def test_sync_reports_each_task(in_project: Paths, add_epic, stub_jira, monkeypatch) -> None:
    add_epic("api", [make_task("api-001"), make_task("api-002")])
    monkeypatch.setattr(stub_jira, "sync_task", lambda *a, **k: "created ABC-1")
    code, out = run("sync")
    assert code == 0
    assert "api-001" in out and "api-002" in out


def test_sync_dry_run_says_nothing_is_sent(in_project: Paths, add_epic, stub_jira, monkeypatch):
    add_epic("api", [make_task("api-001")])
    monkeypatch.setattr(stub_jira, "sync_task", lambda *a, **k: "would create")
    code, out = run("sync", "--dry-run")
    assert code == 0
    assert "nothing is sent" in out


def test_sync_exits_non_zero_when_a_task_fails(in_project: Paths, add_epic, stub_jira, monkeypatch):
    add_epic("api", [make_task("api-001")])

    def explode(*_: Any, **__: Any) -> str:
        raise RuntimeError("Jira rejected it")

    monkeypatch.setattr(stub_jira, "sync_task", explode)
    code, out = run("sync")
    assert code == 1
    assert "failed to sync" in out


def test_sync_of_an_empty_project_is_a_no_op(in_project: Paths, stub_jira) -> None:
    code, out = run("sync")
    assert code == 0
    assert "No tasks to sync" in out


def test_sync_without_credentials_explains_what_is_missing(
    in_project: Paths, add_epic, monkeypatch
) -> None:
    add_epic("api", [make_task("api-001")])
    for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(name, raising=False)
    code, out = run("sync")
    assert code == 1
    assert "JIRA_BASE_URL" in out


def test_sync_looks_up_the_whole_backlog_in_one_query(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    add_epic("api", [make_task("api-001"), make_task("api-002")])
    monkeypatch.setattr(stub_jira, "sync_task", lambda *a, **k: "created ABC-1")
    assert run("sync")[0] == 0
    assert StubClient.looked_up == ["tasc-api-001", "tasc-api-002"]


def test_sync_falls_back_to_searching_per_task(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    """A failed batch must not cost the sync; it only costs the saved queries."""
    add_epic("api", [make_task("api-001")])
    monkeypatch.setattr(
        StubClient, "issues_by_labels", lambda *_: (_ for _ in ()).throw(RuntimeError("429"))
    )
    monkeypatch.setattr(stub_jira, "sync_task", lambda *a, **k: "created ABC-1")
    code, out = run("sync")
    assert code == 0
    assert "searching per task" in out
    assert "created ABC-1" in out


def test_sync_check_lists_blockers_and_stops(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    add_epic("api", [make_task("api-001")])
    finding = stub_jira.Finding(True, "Issue type 'Task' does not exist in the project")
    monkeypatch.setattr(stub_jira, "preflight", lambda *a, **k: [finding])
    monkeypatch.setattr(stub_jira, "sync_task", lambda *a, **k: pytest.fail("must not send"))
    code, out = run("sync", "--check")
    assert code == 1
    assert "blocker" in out
    assert "does not exist" in out


def test_sync_check_passes_notes_without_failing(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    add_epic("api", [make_task("api-001")])
    note = stub_jira.Finding(False, "'Task' has no priority on its create screen")
    monkeypatch.setattr(stub_jira, "preflight", lambda *a, **k: [note])
    code, out = run("sync", "--check")
    assert code == 0
    assert "note" in out


def test_sync_check_says_so_when_everything_lines_up(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    add_epic("api", [make_task("api-001")])
    monkeypatch.setattr(stub_jira, "preflight", lambda *a, **k: [])
    code, out = run("sync", "--check")
    assert code == 0
    assert "line up" in out


# --- archived tasks ---------------------------------------------------------


def archive_task(project: Paths, task_id: str) -> None:
    from tasks_as_code.core.loader import write_archive_task

    write_archive_task(project, make_task(task_id, status="done"), epic="api")


def record_sync(stub_jira, monkeypatch) -> list[tuple[str, bool]]:
    """Capture which tasks reach sync_task, and whether they may be created."""
    calls: list[tuple[str, bool]] = []

    def _sync(_client, _settings, ref, dry_run=False, known=None, create=True, parent=None) -> str:
        calls.append((ref.task.id, create))
        return "updated ABC-1"

    monkeypatch.setattr(stub_jira, "sync_task", _sync)
    return calls


def test_sync_updates_a_closed_task_whose_issue_exists(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    """Otherwise its issue keeps claiming work that finished weeks ago."""
    add_epic("api", [make_task("api-001")])
    archive_task(in_project, "api-002")
    monkeypatch.setattr(
        StubClient, "issues_by_labels", lambda *_: {"tasc-api-002": {"key": "ABC-2", "fields": {}}}
    )
    calls = record_sync(stub_jira, monkeypatch)
    assert run("sync")[0] == 0
    assert calls == [("api-001", True), ("api-002", False)]


def test_sync_leaves_a_closed_task_with_no_issue_out(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    """The archive is history; a plain sync must not pour it into the project."""
    add_epic("api", [make_task("api-001")])
    archive_task(in_project, "api-002")
    calls = record_sync(stub_jira, monkeypatch)
    assert run("sync")[0] == 0
    assert calls == [("api-001", True)]


def test_sync_all_creates_issues_for_closed_tasks(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    add_epic("api", [make_task("api-001")])
    archive_task(in_project, "api-002")
    calls = record_sync(stub_jira, monkeypatch)
    assert run("sync", "--all")[0] == 0
    assert calls == [("api-001", True), ("api-002", True)]


def test_sync_skips_closed_tasks_when_the_lookup_failed(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    """Without the map, sorting them out would cost a search per archived task."""
    add_epic("api", [make_task("api-001")])
    archive_task(in_project, "api-002")
    monkeypatch.setattr(
        StubClient, "issues_by_labels", lambda *_: (_ for _ in ()).throw(RuntimeError("429"))
    )
    calls = record_sync(stub_jira, monkeypatch)
    code, out = run("sync")
    assert code == 0
    assert calls == [("api-001", True)]
    assert "Archived tasks are skipped" in out


def test_sync_check_ignores_the_archive_by_default(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    add_epic("api", [make_task("api-001")])
    archive_task(in_project, "api-002")
    monkeypatch.setattr(stub_jira, "preflight", lambda _c, _s, refs: [] if len(refs) == 1 else None)
    code, out = run("sync", "--check")
    assert code == 0
    assert "Checking 1 task(s)" in out


# --- issue keys reach the task files ----------------------------------------


def test_sync_writes_the_key_onto_the_task(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    """Whoever writes a commit message is offline; the key has to be in git."""
    add_epic("api", [make_task("api-001")])
    monkeypatch.setattr(
        stub_jira, "sync_task", lambda *a, **k: stub_jira.SyncOutcome("created ABC-1", "ABC-1")
    )
    code, out = run("sync")
    assert code == 0
    assert "1 issue key(s)" in out

    from tasks_as_code.core.loader import load_all

    assert load_all(in_project)[0].task.jira == "ABC-1"


def test_a_dry_run_writes_no_key(in_project: Paths, add_epic, stub_jira, monkeypatch) -> None:
    add_epic("api", [make_task("api-001")])
    monkeypatch.setattr(
        stub_jira, "sync_task", lambda *a, **k: stub_jira.SyncOutcome("would update ABC-1", "ABC-1")
    )
    assert run("sync", "--dry-run")[0] == 0

    from tasks_as_code.core.loader import load_all

    assert load_all(in_project)[0].task.jira is None


def test_a_key_already_on_the_task_is_not_rewritten(
    in_project: Paths, add_epic, stub_jira, monkeypatch
) -> None:
    add_epic("api", [make_task("api-001", jira="ABC-1")])
    monkeypatch.setattr(
        stub_jira, "sync_task", lambda *a, **k: stub_jira.SyncOutcome("updated ABC-1", "ABC-1")
    )
    code, out = run("sync")
    assert code == 0
    assert "issue key(s)" not in out
