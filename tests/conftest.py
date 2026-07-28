"""Shared fixtures. Every test works on a throwaway project in tmp_path."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tasks_as_code.core.config import Config
from tasks_as_code.core.loader import write_active_file
from tasks_as_code.core.paths import Paths
from tasks_as_code.core.schema import Task


@pytest.fixture
def project(tmp_path: Path) -> Paths:
    """An initialised, empty project."""
    config = Config(project_name="Test Project")
    paths = Paths(tmp_path, config)
    for folder in (paths.active, paths.archive, paths.done):
        folder.mkdir(parents=True, exist_ok=True)
    config.dump(paths.config_file)
    return paths


@pytest.fixture
def add_epic(project: Paths) -> Callable[..., Path]:
    """Write an epic file with the given tasks."""

    def _add(epic: str, tasks: list[Task], description: str = "") -> Path:
        path = project.active / f"{epic}.yaml"
        write_active_file(path, epic=epic, description=description, tasks=tasks)
        return path

    return _add


@pytest.fixture
def in_project(project: Paths, monkeypatch: pytest.MonkeyPatch) -> Iterator[Paths]:
    """Run with the cwd inside the project, so discovery finds it."""
    monkeypatch.chdir(project.root)
    yield project


def make_task(task_id: str, **overrides) -> Task:
    payload = {"id": task_id, "summary": f"Summary for {task_id}"}
    payload.update(overrides)
    return Task.model_validate(payload)
