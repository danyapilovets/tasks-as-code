"""INDEX.md rendering."""

from __future__ import annotations

from datetime import date

from tasks_as_code.core.indexer import counts, render_index, write_index
from tasks_as_code.core.loader import load_all, write_archive_task
from tasks_as_code.core.paths import Paths

from .conftest import make_task


def test_empty_project_renders_explicit_emptiness(project: Paths) -> None:
    body = render_index(project, [])
    assert "Test Project — task index" in body
    assert "_No open tasks._" in body
    assert "_Nothing closed yet._" in body


def test_counts_cover_every_status(project: Paths, add_epic) -> None:
    add_epic(
        "api",
        [
            make_task("api-001"),
            make_task("api-002", status="in_progress"),
            make_task("api-003", status="blocked"),
        ],
    )
    write_archive_task(project, make_task("api-004", status="done"), epic="api")
    assert counts(load_all(project)) == {
        "todo": 1,
        "in_progress": 1,
        "blocked": 1,
        "done": 1,
    }


def test_in_progress_sorts_above_higher_priority_todo(project: Paths, add_epic) -> None:
    """Within the open table, work already started is listed first."""
    add_epic(
        "api",
        [
            make_task("api-001", priority="Critical"),
            make_task("api-002", status="in_progress", priority="Low"),
        ],
    )
    body = render_index(project, load_all(project))
    open_table = body.split("## Open", 1)[1].split("## Done", 1)[0]
    assert open_table.index("api-002") < open_table.index("api-001")


def test_pipe_characters_are_escaped_in_table_cells(project: Paths, add_epic) -> None:
    """An unescaped pipe would break the Markdown table."""
    add_epic("api", [make_task("api-001", summary="Handle a | b")])
    assert "Handle a \\| b" in render_index(project, load_all(project))


def test_newlines_are_collapsed_in_table_cells(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", summary="Line one\nline two")])
    body = render_index(project, load_all(project))
    assert "Line one line two" in body


def test_long_summaries_are_truncated(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", summary="x" * 200)])
    for line in render_index(project, load_all(project)).splitlines():
        if line.startswith("| `api-001`"):
            assert "…" in line


def test_blocked_tasks_are_not_offered_as_next(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", depends_on=["api-999"])])
    body = render_index(project, load_all(project))
    assert "Nothing ready" in body


def test_done_tasks_are_grouped_by_epic(project: Paths) -> None:
    write_archive_task(project, make_task("api-001", status="done"), epic="api")
    write_archive_task(project, make_task("ui-001", status="done"), epic="ui")
    body = render_index(project, load_all(project))
    assert "### api (1)" in body
    assert "### ui (1)" in body


def test_write_index_creates_the_file_and_reports_the_date(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    path = write_index(project, load_all(project))
    assert path == project.index_md
    assert date.today().isoformat() in path.read_text(encoding="utf-8")
