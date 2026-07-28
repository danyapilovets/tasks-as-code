"""Config loading and project discovery."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tasks_as_code.core.config import CONFIG_FILENAME, Config
from tasks_as_code.core.paths import Paths, ProjectNotFound, find_root


def test_missing_config_falls_back_to_defaults(tmp_path: Path) -> None:
    config = Config.load(tmp_path / CONFIG_FILENAME)
    assert config.project_name == "Project"
    assert config.tasks_dir == "tasks"
    assert config.stale_after_days == 7
    assert config.jira.status_map["in_progress"] == "In Progress"


def test_config_round_trips_through_yaml(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    Config(project_name="Acme", tasks_dir="work", stale_after_days=3).dump(path)
    reloaded = Config.load(path)
    assert (reloaded.project_name, reloaded.tasks_dir, reloaded.stale_after_days) == (
        "Acme",
        "work",
        3,
    )


def test_unknown_config_keys_are_rejected(tmp_path: Path) -> None:
    """A silently ignored typo would look like the setting had no effect."""
    path = tmp_path / CONFIG_FILENAME
    path.write_text(yaml.safe_dump({"projectname": "typo"}), encoding="utf-8")
    with pytest.raises(Exception, match="projectname"):
        Config.load(path)


def test_non_mapping_config_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    path.write_text(yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8")
    with pytest.raises(ValueError, match="YAML mapping"):
        Config.load(path)


def test_zero_stale_days_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    path.write_text(yaml.safe_dump({"stale_after_days": 0}), encoding="utf-8")
    with pytest.raises(Exception, match="stale_after_days"):
        Config.load(path)


def test_custom_tasks_dir_moves_every_path(tmp_path: Path) -> None:
    paths = Paths(tmp_path, Config(tasks_dir="work"))
    assert paths.active == tmp_path / "work" / "active"
    assert paths.archive == tmp_path / "work" / "archive"
    assert paths.done == tmp_path / "work" / "done"
    assert paths.index_md == tmp_path / "work" / "INDEX.md"


def test_find_root_locates_the_config_from_a_subdirectory(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text("project_name: Deep\n", encoding="utf-8")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert find_root(nested) == tmp_path


def test_find_root_falls_back_to_an_uninitialised_tasks_tree(tmp_path: Path) -> None:
    """The tool should work before someone runs `tasc init`."""
    (tmp_path / "tasks" / "active").mkdir(parents=True)
    assert find_root(tmp_path / "tasks" / "active") == tmp_path


def test_config_wins_over_a_nested_tasks_tree(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text("project_name: Root\n", encoding="utf-8")
    nested = tmp_path / "sub"
    (nested / "tasks" / "active").mkdir(parents=True)
    assert find_root(nested) == tmp_path


def test_find_root_explains_how_to_fix_a_missing_project(tmp_path: Path) -> None:
    with pytest.raises(ProjectNotFound, match="tasc init"):
        find_root(tmp_path)


def test_relative_falls_back_to_the_name_for_outside_paths(tmp_path: Path) -> None:
    paths = Paths(tmp_path)
    assert paths.relative(Path("/somewhere/else/file.yaml")) == "file.yaml"
