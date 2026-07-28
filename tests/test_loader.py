"""Reading and writing task files."""

from __future__ import annotations

import pytest
import yaml

from tasks_as_code.core.loader import (
    TaskFileError,
    load_active,
    load_all,
    load_archive,
    write_active_file,
    write_archive_task,
)
from tasks_as_code.core.paths import Paths

from .conftest import make_task


def test_empty_project_loads_nothing(project: Paths) -> None:
    assert load_all(project) == []


def test_missing_directories_are_not_an_error(tmp_path) -> None:
    paths = Paths(tmp_path)
    assert load_active(paths) == []
    assert load_archive(paths) == []


def test_active_tasks_carry_their_epic_and_file(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001"), make_task("api-002")])
    refs = load_active(project)
    assert [ref.id for ref in refs] == ["api-001", "api-002"]
    assert {ref.epic for ref in refs} == {"api"}
    assert all(ref.location == "active" for ref in refs)


def test_files_without_a_tasks_key_are_skipped(project: Paths) -> None:
    (project.active / "notes.yaml").write_text(yaml.safe_dump({"epic": "notes"}), encoding="utf-8")
    assert load_active(project) == []


def test_archive_accepts_wrapped_and_bare_tasks(project: Paths) -> None:
    write_archive_task(project, make_task("api-001"), epic="api")
    (project.archive / "ui-001.yaml").write_text(
        yaml.safe_dump({"id": "ui-001", "summary": "bare form", "status": "done"}),
        encoding="utf-8",
    )
    refs = {ref.id: ref for ref in load_archive(project)}
    assert set(refs) == {"api-001", "ui-001"}
    assert refs["ui-001"].epic == "ui"
    assert all(ref.location == "archive" for ref in refs.values())


def test_invalid_yaml_names_the_file(project: Paths) -> None:
    (project.active / "broken.yaml").write_text("tasks: [unclosed\n", encoding="utf-8")
    with pytest.raises(TaskFileError, match=r"broken\.yaml"):
        load_active(project)


def test_schema_violation_names_the_file(project: Paths) -> None:
    (project.active / "bad.yaml").write_text(
        yaml.safe_dump({"epic": "bad", "tasks": [{"id": "NOPE", "summary": "x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(TaskFileError, match=r"bad\.yaml"):
        load_active(project)


def test_non_mapping_file_is_rejected(project: Paths) -> None:
    (project.active / "list.yaml").write_text(yaml.safe_dump(["a", "b"]), encoding="utf-8")
    with pytest.raises(TaskFileError, match="expected a YAML mapping"):
        load_active(project)


def test_written_yaml_omits_empty_optional_fields(project: Paths) -> None:
    path = project.active / "api.yaml"
    write_active_file(path, epic="api", description="", tasks=[make_task("api-001")])
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))["tasks"][0]
    assert "acceptance_criteria" not in payload
    assert "depends_on" not in payload
    assert "updated" not in payload


def test_written_yaml_keeps_populated_fields(project: Paths) -> None:
    path = project.active / "api.yaml"
    task = make_task("api-001", acceptance_criteria=["works"], depends_on=["api-000"])
    write_active_file(path, epic="api", description="An epic", tasks=[task])
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["description"] == "An epic"
    assert raw["tasks"][0]["acceptance_criteria"] == ["works"]
    assert raw["tasks"][0]["depends_on"] == ["api-000"]


def test_unicode_is_stored_readably(project: Paths) -> None:
    path = project.active / "api.yaml"
    write_active_file(
        path, epic="api", description="", tasks=[make_task("api-001", summary="Ціна")]
    )
    assert "Ціна" in path.read_text(encoding="utf-8")


def test_to_dict_uses_paths_relative_to_the_root(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])
    payload = load_active(project)[0].to_dict(project)
    assert payload["file"] == "tasks/active/api.yaml"
    assert payload["epic"] == "api"
    assert payload["location"] == "active"
