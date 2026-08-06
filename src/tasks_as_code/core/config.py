"""Project configuration read from ``.tasc.yaml`` at the repository root.

YAML rather than TOML on purpose: the tool already depends on PyYAML for task
files, and ``tomllib`` is unavailable on Python 3.10.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

CONFIG_FILENAME = ".tasc.yaml"

DEFAULT_JIRA_STATUS_MAP: dict[str, str] = {
    "todo": "To Do",
    "in_progress": "In Progress",
    "blocked": "To Do",
    "done": "Done",
}


class JiraSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Prefix for the label that links a Jira issue back to a local task id.
    label_prefix: str = "tasc"
    #: Jira workflow status names differ per project and language, so they are
    #: configuration rather than constants.
    status_map: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_JIRA_STATUS_MAP))
    #: Issue type and priority names have the same problem as statuses: a
    #: localised project calls the type "Задача" and priority schemes get renamed.
    #: Empty means the local value is sent unchanged.
    type_map: dict[str, str] = Field(default_factory=dict)
    priority_map: dict[str, str] = Field(default_factory=dict)
    #: Reapply JIRA_ASSIGNEE_ACCOUNT_ID on every update, not only on create.
    #: Off by default: overwriting an assignee chosen in Jira would fight the
    #: people using the board.
    force_assignee: bool = False
    #: Post the note from ``tasc done --note`` as a comment. What a task produced
    #: is the part people in Jira ask about, and a status change does not say it.
    comment_on_done: bool = True
    #: Mirror ``depends_on`` as issue links. A dependency written into the
    #: description is text nobody can filter, sort or see on a board.
    link_dependencies: bool = True
    #: Name of the link type used for that. "Blocks" exists in a default Jira;
    #: instances rename it, and some replace it entirely.
    dependency_link_type: str = "Blocks"
    #: Give each task the Jira epic of its own epic as parent, creating the epic
    #: issue when it does not exist. Off by default: it writes issues the backlog
    #: does not list, and a project whose hierarchy is managed elsewhere would end
    #: up with two sets of epics.
    epic_as_parent: bool = False
    #: Issue type used for those epics.
    epic_type: str = "Epic"


class RefSettings(BaseModel):
    """Rules for ``tasc check-ref``, the gate that ties changes to tasks."""

    model_config = ConfigDict(extra="forbid")

    #: Text containing one of these skips the check. An escape hatch is what keeps
    #: people from disabling the hook altogether the first time it blocks them.
    skip_markers: list[str] = Field(default_factory=lambda: ["[skip-task]"])
    #: Require the referenced task to be in one of these statuses, e.g.
    #: ``in_progress`` or ``[in_progress, done]``. ``None`` accepts any status,
    #: which is what lets the commit that closes a task name it.
    require_status: str | list[str] | None = None
    #: Shape of the subject line ``tasc stamp`` writes. The tracker only needs the
    #: key to appear somewhere, so the rest is the team's convention.
    subject_format: str = "{key} {subject}"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Shown as the heading of the generated index.
    project_name: str = "Project"
    #: Directory (relative to the repo root) holding active/ and archive/.
    tasks_dir: str = "tasks"
    #: Quarterly logs. Defaults to ``<tasks_dir>/done``; set it to adopt a
    #: repository whose logs already live somewhere else.
    done_dir: str | None = None
    #: Days after which an in_progress task is reported by ``tasc stale``.
    stale_after_days: int = Field(default=7, ge=1)
    #: Refuse to close a task without ``--note``. A backlog of closed tasks that
    #: never say what they produced answers "was it done?" and never "what came
    #: out of it", which is the question asked months later.
    require_note: bool = False
    refs: RefSettings = Field(default_factory=RefSettings)
    jira: JiraSettings = Field(default_factory=JiraSettings)

    @classmethod
    def load(cls, path: Path) -> Config:
        """Read a config file, or return defaults when it does not exist."""
        if not path.is_file():
            return cls()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        return cls.model_validate(raw)

    def dump(self, path: Path) -> None:
        path.write_text(
            yaml.safe_dump(
                self.model_dump(),
                sort_keys=False,
                allow_unicode=True,
                width=100,
            ),
            encoding="utf-8",
        )
