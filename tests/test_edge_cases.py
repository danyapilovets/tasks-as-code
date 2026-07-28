"""Edge cases that are easy to regress: non-string input and unreadable files."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tasks_as_code.core.loader import TaskFileError, load_active, load_archive
from tasks_as_code.core.paths import Paths
from tasks_as_code.core.schema import Task


@pytest.mark.parametrize("field", ["status", "priority", "type"])
def test_non_string_values_reach_the_type_error(field: str) -> None:
    """Normalisers must pass unexpected types through, not crash on .lower()."""
    with pytest.raises(ValidationError):
        Task.model_validate({"id": "a-1", "summary": "s", field: 7})


def test_non_list_criteria_reaches_the_type_error() -> None:
    with pytest.raises(ValidationError):
        Task.model_validate({"id": "a-1", "summary": "s", "acceptance_criteria": "not a list"})


def test_empty_active_file_is_skipped(project: Paths) -> None:
    (project.active / "blank.yaml").write_text("")
    assert load_active(project) == []


def test_empty_archive_file_is_skipped(project: Paths) -> None:
    (project.archive / "blank.yaml").write_text("")
    assert load_archive(project) == []


def test_invalid_archive_yaml_names_the_file(project: Paths) -> None:
    (project.archive / "broken.yaml").write_text("task: [oops\n")
    with pytest.raises(TaskFileError, match=r"broken\.yaml"):
        load_archive(project)


def test_archive_schema_violation_names_the_file(project: Paths) -> None:
    (project.archive / "bad.yaml").write_text("task:\n  id: NOPE\n  summary: x\n")
    with pytest.raises(TaskFileError, match=r"bad\.yaml"):
        load_archive(project)


def test_archive_epic_falls_back_to_the_task_field(project: Paths) -> None:
    (project.archive / "x-001.yaml").write_text(
        "task:\n  id: x-001\n  summary: s\n  status: done\n  epic: custom\n"
    )
    assert load_archive(project)[0].epic == "custom"
