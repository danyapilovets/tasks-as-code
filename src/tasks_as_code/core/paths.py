"""Locate the project root and the files inside it, regardless of cwd."""

from __future__ import annotations

from pathlib import Path

from .config import CONFIG_FILENAME, Config


class ProjectNotFound(RuntimeError):
    """Raised when no initialised project is found at or above the cwd."""


def find_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` looking for an initialised project.

    A directory qualifies if it holds ``.tasc.yaml`` (explicit, wins) or a
    ``tasks/active`` tree (implicit, so the tool works before ``tasc init``).
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / CONFIG_FILENAME).is_file():
            return candidate
    for candidate in [current, *current.parents]:
        if (candidate / "tasks" / "active").is_dir():
            return candidate
    raise ProjectNotFound(
        f"No {CONFIG_FILENAME} or tasks/active/ found in this directory or any parent. "
        "Run 'tasc init' in your repository root to create one."
    )


class Paths:
    """Resolved locations of everything the tool reads or writes."""

    def __init__(self, root: Path, config: Config | None = None):
        self.root = root
        self.config = config if config is not None else Config.load(root / CONFIG_FILENAME)
        self.config_file = root / CONFIG_FILENAME
        self.tasks = root / self.config.tasks_dir
        self.active = self.tasks / "active"
        self.archive = self.tasks / "archive"
        self.done = self.tasks / "done"
        self.index_md = self.tasks / "INDEX.md"

    @classmethod
    def discover(cls, start: Path | None = None) -> Paths:
        return cls(find_root(start))

    def relative(self, path: Path) -> str:
        """Path relative to the root, for stable output across machines."""
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return path.name
