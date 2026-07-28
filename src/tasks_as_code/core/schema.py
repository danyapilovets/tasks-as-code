"""Task schema — the machine-checkable contract every task file must satisfy."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["todo", "in_progress", "done", "blocked"]
Priority = Literal["Critical", "High", "Medium", "Low"]
TaskType = Literal["Task", "Story", "Bug", "Epic"]

OPEN_STATUSES: tuple[Status, ...] = ("todo", "in_progress", "blocked")

#: Sort weight per priority. Lower sorts first. ``Critical`` must be listed
#: explicitly — a missing entry would silently rank it alongside ``Medium``.
PRIORITY_ORDER: dict[str, int] = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

TASK_ID_RE = re.compile(r"^[a-z][a-z0-9]*-\d+$")

_PRIORITY_ALIASES = {
    "critical": "Critical",
    "crit": "Critical",
    "blocker": "Critical",
    "high": "High",
    "medium": "Medium",
    "med": "Medium",
    "normal": "Medium",
    "low": "Low",
    "minor": "Low",
}
_STATUS_ALIASES = {
    "todo": "todo",
    "to_do": "todo",
    "open": "todo",
    "backlog": "todo",
    "in_progress": "in_progress",
    "inprogress": "in_progress",
    "wip": "in_progress",
    "doing": "in_progress",
    "blocked": "blocked",
    "done": "done",
    "closed": "done",
    "complete": "done",
    "completed": "done",
}
_TYPE_ALIASES = {
    "task": "Task",
    "story": "Story",
    "bug": "Bug",
    "fix": "Bug",
    "epic": "Epic",
}


def _alias_key(value: str) -> str:
    """Fold case and separators so "To Do", "to-do" and "to_do" all match.

    Jira and spreadsheet exports use spaces and dashes; hand-written YAML uses
    underscores. All of them should mean the same status.
    """
    return re.sub(r"[\s\-]+", "_", value.strip().lower())


class Task(BaseModel):
    """One unit of work.

    ``extra="allow"`` is deliberate: teams attach their own fields (estimates,
    owners, links) and the tool must round-trip them instead of dropping them.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., pattern=TASK_ID_RE.pattern)
    summary: str = Field(..., min_length=1)
    description: str = ""
    type: TaskType = "Task"
    priority: Priority = "Medium"
    status: Status = "todo"
    acceptance_criteria: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    epic: str | None = None
    #: ISO date of the last status change. Stamped on create/mark/done so
    #: ``tasc stale`` can flag work that has been in progress too long.
    updated: str | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _PRIORITY_ALIASES.get(_alias_key(value), value)
        return value

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _STATUS_ALIASES.get(_alias_key(value), value)
        return value

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _TYPE_ALIASES.get(_alias_key(value), value)
        return value

    @field_validator("acceptance_criteria", "depends_on", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> Any:
        """Accept YAML nested mappings, which are easy to write by accident.

        ``- key: value`` parses as a dict, not a string. Flatten it rather than
        failing, so a hand-edited file stays usable.
        """
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        flattened = []
        for item in value:
            if isinstance(item, dict):
                flattened.append(", ".join(f"{k}: {v}" for k, v in item.items()))
            else:
                flattened.append(item)
        return flattened

    @property
    def epic_prefix(self) -> str:
        return self.id.split("-", 1)[0]

    @property
    def priority_rank(self) -> int:
        return PRIORITY_ORDER[self.priority]


class EpicFile(BaseModel):
    """Schema for ``tasks/active/<epic>.yaml`` — many tasks per file."""

    epic: str
    description: str = ""
    tasks: list[Task] = Field(default_factory=list)


class ArchiveFile(BaseModel):
    """Schema for ``tasks/archive/<id>.yaml`` — one task per file."""

    epic: str | None = None
    task: Task
