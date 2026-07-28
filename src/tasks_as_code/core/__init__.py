"""Core domain: schema, config, file IO, selection and index rendering."""

from __future__ import annotations

from .config import Config, JiraSettings
from .indexer import render_index, write_index
from .loader import TaskFileError, TaskRef, load_active, load_all, load_archive
from .paths import Paths, ProjectNotFound, find_root
from .schema import ArchiveFile, EpicFile, Task
from .workflow import (
    InvalidTransition,
    TaskNotFound,
    archive,
    blocking_dependencies,
    create,
    find,
    pick_next,
    set_status,
    stale_in_progress,
)

__all__ = [
    "ArchiveFile",
    "Config",
    "EpicFile",
    "InvalidTransition",
    "JiraSettings",
    "Paths",
    "ProjectNotFound",
    "Task",
    "TaskFileError",
    "TaskNotFound",
    "TaskRef",
    "archive",
    "blocking_dependencies",
    "create",
    "find",
    "find_root",
    "load_active",
    "load_all",
    "load_archive",
    "pick_next",
    "render_index",
    "set_status",
    "stale_in_progress",
    "write_index",
]
