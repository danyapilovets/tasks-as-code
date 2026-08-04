"""Selection, transitions, archiving and id allocation."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import yaml

from tasks_as_code.core.loader import load_all, load_archive
from tasks_as_code.core.paths import Paths
from tasks_as_code.core.workflow import (
    InvalidTransition,
    TaskNotFound,
    archive,
    blocking_dependencies,
    create,
    next_id,
    pick_next,
    quarter_label,
    require,
    set_status,
    stale_in_progress,
)

from .conftest import make_task


def test_next_prefers_critical_over_high(project: Paths, add_epic) -> None:
    add_epic(
        "api",
        [
            make_task("api-001", priority="Low"),
            make_task("api-002", priority="Critical"),
            make_task("api-003", priority="High"),
        ],
    )
    assert [ref.id for ref in pick_next(load_all(project), limit=3)] == [
        "api-002",
        "api-003",
        "api-001",
    ]


def test_next_is_stable_for_equal_priorities(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-002"), make_task("api-001")])
    refs = load_all(project)
    assert [r.id for r in pick_next(refs, limit=2)] == [r.id for r in pick_next(refs, limit=2)]
    assert [r.id for r in pick_next(refs, limit=2)] == ["api-001", "api-002"]


def test_next_skips_tasks_with_unmet_dependencies(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", depends_on=["api-002"]), make_task("api-002")])
    assert [ref.id for ref in pick_next(load_all(project), limit=5)] == ["api-002"]


def test_next_includes_a_task_once_its_dependency_is_done(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", depends_on=["api-002"])])
    add_epic("dep", [make_task("dep-001")])
    from tasks_as_code.core.loader import write_archive_task

    write_archive_task(project, make_task("api-002", status="done"), epic="api")
    assert "api-001" in [ref.id for ref in pick_next(load_all(project), limit=5)]


def test_next_ignores_non_todo_statuses(project: Paths, add_epic) -> None:
    add_epic(
        "api",
        [
            make_task("api-001", status="in_progress"),
            make_task("api-002", status="blocked"),
        ],
    )
    assert pick_next(load_all(project), limit=5) == []


def test_unknown_dependency_blocks_rather_than_being_ignored(project: Paths, add_epic) -> None:
    """A typo in depends_on must not make a task look ready."""
    add_epic("api", [make_task("api-001", depends_on=["typo-999"])])
    refs = load_all(project)
    assert blocking_dependencies(refs[0], refs) == ["typo-999"]
    assert pick_next(refs, limit=5) == []


def test_require_raises_for_a_missing_id(project: Paths) -> None:
    with pytest.raises(TaskNotFound, match="nope-001"):
        require(load_all(project), "nope-001")


def test_set_status_persists_and_stamps_the_date(project: Paths, add_epic) -> None:
    """Reloading from disk mid-write once discarded the change silently."""
    add_epic("api", [make_task("api-001"), make_task("api-002")])
    set_status(project, "api-001", "in_progress")

    reloaded = {ref.id: ref.task for ref in load_all(project)}
    assert reloaded["api-001"].status == "in_progress"
    assert reloaded["api-001"].updated == date.today().isoformat()
    assert reloaded["api-002"].status == "todo"


def test_set_status_preserves_the_epic_header(project: Paths, add_epic) -> None:
    path = add_epic("api", [make_task("api-001")], description="Keep me")
    set_status(project, "api-001", "blocked")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["description"] == "Keep me"
    assert raw["epic"] == "api"


def test_set_status_rejects_done(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    with pytest.raises(InvalidTransition, match="tasc done"):
        set_status(project, "api-001", "done")


def test_set_status_rejects_archived_tasks(project: Paths) -> None:
    from tasks_as_code.core.loader import write_archive_task

    write_archive_task(project, make_task("api-001", status="done"), epic="api")
    with pytest.raises(InvalidTransition, match="archived"):
        set_status(project, "api-001", "todo")


def test_archive_moves_the_task_and_writes_a_log(project: Paths, add_epic) -> None:
    path = add_epic("api", [make_task("api-001"), make_task("api-002")])
    archive_path, log_path = archive(project, "api-001", note="Shipped it")

    assert archive_path.is_file()
    assert [ref.id for ref in load_archive(project)] == ["api-001"]
    assert yaml.safe_load(archive_path.read_text(encoding="utf-8"))["task"]["status"] == "done"

    remaining = [task["id"] for task in yaml.safe_load(path.read_text(encoding="utf-8"))["tasks"]]
    assert remaining == ["api-002"]

    log = log_path.read_text(encoding="utf-8")
    assert "api-001" in log
    assert "Shipped it" in log
    assert log_path.name == f"{quarter_label()}.md"


def test_archive_keeps_the_note_on_the_task(project: Paths, add_epic) -> None:
    """The log is prose for people; an integration needs the note as a field."""
    add_epic("api", [make_task("api-001")])
    archive(project, "api-001", note="  Shipped it  ")
    assert load_archive(project)[0].task.note == "Shipped it"


def test_archive_without_a_note_leaves_the_field_out(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    archive_path, _ = archive(project, "api-001")
    assert "note" not in yaml.safe_load(archive_path.read_text(encoding="utf-8"))["task"]


def test_archive_without_a_note_still_logs_the_heading(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    _, log_path = archive(project, "api-001")
    assert "api-001" in log_path.read_text(encoding="utf-8")


def test_archive_appends_to_an_existing_log(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001"), make_task("api-002")])
    archive(project, "api-001", note="first")
    _, log_path = archive(project, "api-002", note="second")
    body = log_path.read_text(encoding="utf-8")
    assert body.count("## ") == 2
    assert "first" in body and "second" in body


def test_archive_twice_is_rejected(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    archive(project, "api-001")
    with pytest.raises(InvalidTransition, match="already archived"):
        archive(project, "api-001")


def test_create_allocates_the_next_free_id(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001"), make_task("api-007")])
    ref = create(project, epic_prefix="api", summary="New work", priority="High")
    assert ref.task.id == "api-008"
    assert ref.task.priority == "High"
    assert ref.task.updated == date.today().isoformat()
    assert [r.id for r in load_all(project)] == ["api-001", "api-007", "api-008"]


def test_create_starts_a_new_epic_file(project: Paths) -> None:
    ref = create(project, epic_prefix="ui", summary="First UI task")
    assert ref.task.id == "ui-001"
    assert ref.file.name == "ui.yaml"
    assert ref.file.is_file()


def test_create_preserves_the_epic_description(project: Paths, add_epic) -> None:
    path = add_epic("api", [make_task("api-001")], description="Backend work")
    create(project, epic_prefix="api", summary="Another")
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["description"] == "Backend work"


def test_next_id_ignores_non_numeric_suffixes(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-003")])
    assert next_id(load_all(project), "api") == "api-004"
    assert next_id(load_all(project), "brand-new") == "brand-new-001"


def test_stale_flags_old_in_progress_work(project: Paths, add_epic) -> None:
    old = (date.today() - timedelta(days=10)).isoformat()
    fresh = date.today().isoformat()
    add_epic(
        "api",
        [
            make_task("api-001", status="in_progress", updated=old),
            make_task("api-002", status="in_progress", updated=fresh),
            make_task("api-003", status="todo", updated=old),
        ],
    )
    assert [ref.id for ref in stale_in_progress(load_all(project), days=7)] == ["api-001"]


def test_stale_flags_in_progress_without_a_date(project: Paths, add_epic) -> None:
    """Starting work without stamping the date is the drift this catches."""
    add_epic("api", [make_task("api-001", status="in_progress")])
    assert [ref.id for ref in stale_in_progress(load_all(project), days=7)] == ["api-001"]


def test_stale_flags_an_unparsable_date(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", status="in_progress", updated="yesterday")])
    assert [ref.id for ref in stale_in_progress(load_all(project), days=7)] == ["api-001"]


def test_quarter_label_maps_months_to_quarters() -> None:
    assert quarter_label(date(2026, 1, 31)) == "2026-Q1"
    assert quarter_label(date(2026, 4, 1)) == "2026-Q2"
    assert quarter_label(date(2026, 9, 30)) == "2026-Q3"
    assert quarter_label(date(2026, 12, 1)) == "2026-Q4"
