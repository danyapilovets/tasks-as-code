"""Read and write task files.

Active work lives in ``tasks/active/<epic>.yaml`` (grouped, so an agent loads a
whole epic in one read). Closed work lives in ``tasks/archive/<id>.yaml`` (one
file each, so it is only read on demand).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .paths import Paths
from .schema import EpicFile, Task


class TaskFileError(RuntimeError):
    """A task file exists but does not satisfy the schema."""


@dataclass
class TaskRef:
    """A task plus where it lives on disk."""

    task: Task
    file: Path
    epic: str
    location: str

    @property
    def id(self) -> str:
        return self.task.id

    def to_dict(self, paths: Paths | None = None) -> dict[str, Any]:
        """Flat, JSON-serialisable view for ``--json`` output."""
        data = self.task.model_dump(exclude_none=True)
        data["epic"] = self.epic
        data["location"] = self.location
        data["file"] = paths.relative(self.file) if paths else str(self.file)
        return data


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaskFileError(f"{path}: invalid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TaskFileError(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    return data


def load_active(paths: Paths) -> list[TaskRef]:
    """Load every task from ``tasks/active/*.yaml``."""
    refs: list[TaskRef] = []
    if not paths.active.is_dir():
        return refs
    for path in sorted(paths.active.glob("*.yaml")):
        raw = _read_yaml(path)
        if "tasks" not in raw:
            continue
        epic = raw.get("epic", path.stem)
        try:
            epic_file = EpicFile.model_validate(raw)
        except Exception as exc:
            raise TaskFileError(f"{path}: {exc}") from exc
        refs.extend(
            TaskRef(task=task, file=path, epic=epic, location="active") for task in epic_file.tasks
        )
    return refs


def load_archive(paths: Paths) -> list[TaskRef]:
    """Load every task from ``tasks/archive/*.yaml``."""
    refs: list[TaskRef] = []
    if not paths.archive.is_dir():
        return refs
    for path in sorted(paths.archive.glob("*.yaml")):
        raw = _read_yaml(path)
        if not raw:
            continue
        # Accept both the wrapped form written by `tasc done` and a bare task.
        payload = raw.get("task", raw)
        try:
            task = Task.model_validate(payload)
        except Exception as exc:
            raise TaskFileError(f"{path}: {exc}") from exc
        epic = raw.get("epic") or task.epic or task.epic_prefix
        refs.append(TaskRef(task=task, file=path, epic=epic, location="archive"))
    return refs


def load_all(paths: Paths) -> list[TaskRef]:
    return load_active(paths) + load_archive(paths)


def _clean_task_payload(task: Task) -> dict[str, Any]:
    """Serialise a task, dropping empty optional fields to keep YAML readable."""
    payload = task.model_dump()
    for key in ("acceptance_criteria", "depends_on"):
        if not payload.get(key):
            payload.pop(key, None)
    for key in ("epic", "updated", "owner", "note"):
        if payload.get(key) is None:
            payload.pop(key, None)
    return payload


def write_active_file(path: Path, epic: str, description: str, tasks: list[Task]) -> None:
    """Rewrite an epic file with the given tasks."""
    data = {
        "epic": epic,
        "description": description,
        "tasks": [_clean_task_payload(task) for task in tasks],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _dump_yaml(path, data)


def write_archive_task(paths: Paths, task: Task, epic: str) -> Path:
    """Write one closed task to ``tasks/archive/<id>.yaml``."""
    paths.archive.mkdir(parents=True, exist_ok=True)
    path = paths.archive / f"{task.id}.yaml"
    _dump_yaml(path, {"epic": epic, "task": _clean_task_payload(task)})
    return path


def _dump_yaml(path: Path, data: dict) -> None:
    """Write YAML as UTF-8, keeping non-latin text readable.

    ``allow_unicode`` keeps Ukrainian or Polish summaries as themselves rather
    than escapes, and the explicit encoding is what makes that writable on
    Windows, whose default is cp1252.
    """
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


def rewrite_epic_file(path: Path, fallback_epic: str, tasks: list[Task]) -> None:
    """Rewrite an epic file, preserving its ``epic`` and ``description`` header."""
    raw = _read_yaml(path) if path.is_file() else {}
    write_active_file(
        path,
        epic=raw.get("epic", fallback_epic),
        description=raw.get("description", ""),
        tasks=tasks,
    )
