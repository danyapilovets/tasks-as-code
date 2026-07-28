"""CLI behaviour, including the --json contract that agents depend on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tasks_as_code import __version__
from tasks_as_code.cli import app
from tasks_as_code.core.config import CONFIG_FILENAME
from tasks_as_code.core.paths import Paths

from .conftest import make_task

runner = CliRunner()


def run(*args: str) -> tuple[int, str]:
    """Exit code plus both streams, with whitespace collapsed.

    Human-facing errors go to stderr so stdout stays parseable, and Rich wraps
    console output at the terminal width — so assertions must not depend on
    which stream a message used or where the line breaks fell.
    """
    result = runner.invoke(app, list(args))
    combined = f"{result.stdout}\n{result.stderr}"
    return result.exit_code, " ".join(combined.split())


def payload(*args: str) -> dict:
    """Parse stdout alone — the contract an agent consumes."""
    result = runner.invoke(app, list(args))
    return json.loads(result.stdout)


def test_version_works_without_a_subcommand() -> None:
    code, out = run("--version")
    assert code == 0
    assert __version__ in out


def test_commands_outside_a_project_fail_with_guidance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    code, out = run("next")
    assert code == 1
    assert "tasc init" in out


def test_json_error_outside_a_project_is_still_valid_json(tmp_path: Path, monkeypatch) -> None:
    """An agent parsing stdout must not choke on a human-formatted error."""
    monkeypatch.chdir(tmp_path)
    assert "error" in payload("next", "--json")


def test_init_creates_the_tree_config_and_index(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    code, _ = run("init", "--name", "Acme")
    assert code == 0
    assert (tmp_path / CONFIG_FILENAME).is_file()
    for folder in ("active", "archive", "done"):
        assert (tmp_path / "tasks" / folder).is_dir()
    assert "Acme — task index" in (tmp_path / "tasks" / "INDEX.md").read_text()


def test_init_refuses_to_overwrite_without_force(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    run("init")
    code, out = run("init")
    assert code == 1
    assert "--force" in out
    assert run("init", "--force")[0] == 0


def test_init_honours_a_custom_tasks_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert run("init", "--tasks-dir", "work")[0] == 0
    assert (tmp_path / "work" / "active").is_dir()


def test_next_json_separates_in_progress_from_ready(in_project: Paths, add_epic) -> None:
    add_epic(
        "api",
        [make_task("api-001", status="in_progress"), make_task("api-002", priority="High")],
    )
    data = payload("next", "--json")
    assert [task["id"] for task in data["in_progress"]] == ["api-001"]
    assert [task["id"] for task in data["next"]] == ["api-002"]


def test_next_limit_caps_the_suggestions(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task(f"api-00{n}") for n in range(1, 5)])
    assert len(payload("next", "--json", "--limit", "2")["next"]) == 2


def test_next_reports_an_empty_backlog_without_failing(in_project: Paths) -> None:
    code, out = run("next")
    assert code == 0
    assert "Nothing ready" in out


def test_show_reports_blocking_dependencies(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", depends_on=["api-002"]), make_task("api-002")])
    assert payload("show", "api-001", "--json")["blocking_dependencies"] == ["api-002"]


def test_show_unknown_id_fails(in_project: Paths) -> None:
    code, out = run("show", "api-999")
    assert code == 1
    assert "not found" in out


def test_list_filters_by_epic_and_status(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001"), make_task("api-002", status="blocked")])
    add_epic("ui", [make_task("ui-001")])
    assert payload("list", "--json", "--epic", "api")["count"] == 2
    assert payload("list", "--json", "--status", "blocked")["count"] == 1
    assert [t["id"] for t in payload("list", "--json", "--epic", "ui")["tasks"]] == ["ui-001"]


def test_list_excludes_archived_tasks_unless_asked(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    run("done", "api-001")
    assert payload("list", "--json")["count"] == 0
    assert payload("list", "--json", "--all")["count"] == 1


def test_new_mark_done_is_reflected_in_json_and_on_disk(in_project: Paths) -> None:
    created = payload("new", "api", "--summary", "Ship it", "-p", "Critical", "--json")
    assert created["id"] == "api-001"
    assert created["priority"] == "Critical"

    marked = payload("mark", "api-001", "in_progress", "--json")
    assert marked["status"] == "in_progress"

    closed = payload("done", "api-001", "--note", "shipped", "--json")
    assert closed["archived_to"] == "tasks/archive/api-001.yaml"
    assert (in_project.root / closed["logged_in"]).is_file()


def test_mark_rejects_done_and_points_at_the_right_command(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    code, out = run("mark", "api-001", "done")
    assert code == 1
    assert "tasc done" in out


def test_mark_rejects_an_unknown_status(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    assert run("mark", "api-001", "sideways")[0] == 1


def test_validate_passes_on_a_clean_project(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001"), make_task("api-002", depends_on=["api-001"])])
    code, out = run("validate")
    assert code == 0
    assert "OK" in out


def test_validate_reports_duplicate_ids(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    add_epic("ui", [make_task("api-001")])
    data = payload("validate", "--json")
    assert data["ok"] is False
    assert any("duplicate id: api-001" in problem for problem in data["problems"])


def test_validate_reports_unknown_and_self_dependencies(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", depends_on=["ghost-001", "api-001"])])
    problems = payload("validate", "--json")["problems"]
    assert any("unknown task: ghost-001" in problem for problem in problems)
    assert any("depends on itself" in problem for problem in problems)


def test_validate_exits_non_zero_so_it_can_gate_ci(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", depends_on=["ghost-001"])])
    assert run("validate")[0] == 1
    assert run("validate", "--json")[0] == 1


def test_validate_names_a_broken_file(in_project: Paths) -> None:
    (in_project.active / "broken.yaml").write_text("tasks: [oops\n")
    code, out = run("validate")
    assert code == 1
    assert "broken.yaml" in out


def test_stale_exits_non_zero_and_lists_the_task(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", status="in_progress", updated="2020-01-01")])
    code, out = run("stale")
    assert code == 1
    assert "api-001" in out
    assert payload("stale", "--json")["count"] == 1


def test_stale_days_override_can_silence_a_recent_task(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", status="in_progress", updated="2020-01-01")])
    assert payload("stale", "--json", "--days", "1000000")["count"] == 0


def test_stale_reports_the_threshold_it_used(in_project: Paths) -> None:
    assert payload("stale", "--json")["threshold_days"] == in_project.config.stale_after_days


def test_reindex_writes_the_index_and_reports_counts(in_project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001"), make_task("api-002", status="blocked")])
    data = payload("reindex", "--json")
    assert data == {
        "blocked": 1,
        "done": 0,
        "in_progress": 0,
        "index": "tasks/INDEX.md",
        "tasks": 2,
        "todo": 1,
    }
    assert in_project.index_md.is_file()


def test_write_commands_keep_the_index_current(in_project: Paths) -> None:
    """A stale index is worse than none: an agent would act on old state."""
    run("new", "api", "--summary", "Fresh work")
    assert "Fresh work" in in_project.index_md.read_text()


@pytest.mark.parametrize("command", ["next", "list", "reindex", "stale"])
def test_read_commands_emit_parseable_json(in_project: Paths, add_epic, command: str) -> None:
    add_epic("api", [make_task("api-001")])
    code, out = run(command, "--json")
    assert code in (0, 1)
    assert isinstance(json.loads(out), dict)
