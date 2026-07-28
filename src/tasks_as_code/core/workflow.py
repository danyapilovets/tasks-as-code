"""Deterministic task selection, status transitions and archiving."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .loader import (
    TaskRef,
    load_all,
    rewrite_epic_file,
    write_active_file,
    write_archive_task,
)
from .paths import Paths
from .schema import Task


class TaskNotFound(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


def quarter_label(today: date | None = None) -> str:
    today = today or date.today()
    return f"{today.year}-Q{(today.month - 1) // 3 + 1}"


def find(refs: list[TaskRef], task_id: str) -> TaskRef | None:
    return next((ref for ref in refs if ref.task.id == task_id), None)


def require(refs: list[TaskRef], task_id: str) -> TaskRef:
    ref = find(refs, task_id)
    if ref is None:
        raise TaskNotFound(f"Task {task_id} not found")
    return ref


def blocking_dependencies(ref: TaskRef, refs: list[TaskRef]) -> list[str]:
    """Dependency ids that are not done yet, including unknown ids.

    An id that resolves to nothing is reported rather than ignored: a typo in
    ``depends_on`` must not silently make a task look ready.
    """
    done_ids = {r.task.id for r in refs if r.task.status == "done"}
    return [dep for dep in ref.task.depends_on if dep not in done_ids]


def pick_next(refs: list[TaskRef], limit: int = 1) -> list[TaskRef]:
    """Return up to ``limit`` ready tasks, highest priority first.

    Ordering is (priority, id) so the same repository state always yields the
    same answer — an agent re-running the command cannot drift.
    """
    ready = [
        ref for ref in refs if ref.task.status == "todo" and not blocking_dependencies(ref, refs)
    ]
    ready.sort(key=lambda ref: (ref.task.priority_rank, ref.task.id))
    return ready[:limit]


def stale_in_progress(refs: list[TaskRef], days: int, today: date | None = None) -> list[TaskRef]:
    """In-progress tasks whose ``updated`` date is older than ``days``.

    Tasks with a missing or unparsable ``updated`` field are reported too: an
    agent that started work without stamping the date is exactly the drift this
    is meant to surface.
    """
    today = today or date.today()
    stale: list[TaskRef] = []
    for ref in refs:
        if ref.task.status != "in_progress":
            continue
        age = _age_in_days(ref.task.updated, today)
        if age is None or age >= days:
            stale.append(ref)
    return stale


def _age_in_days(updated: str | None, today: date) -> int | None:
    if not updated:
        return None
    try:
        stamped = datetime.strptime(updated.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    return (today - stamped).days


def set_status(paths: Paths, task_id: str, new_status: str) -> TaskRef:
    """Change a task's status in its active file and stamp ``updated``."""
    if new_status not in {"todo", "in_progress", "blocked"}:
        raise InvalidTransition(
            f"Cannot set status '{new_status}' here. Use 'tasc done {task_id}' to close a task."
        )
    refs = load_all(paths)
    ref = require(refs, task_id)
    if ref.location != "active":
        raise InvalidTransition(f"Task {task_id} is archived; it cannot change status")

    ref.task.status = new_status  # type: ignore[assignment]
    ref.task.updated = date.today().isoformat()
    # Write back the in-memory refs. Reloading from disk here would discard the
    # change above and leave the task at its old status.
    same_file = [r.task for r in refs if r.file == ref.file]
    rewrite_epic_file(ref.file, ref.epic, same_file)
    return ref


def archive(paths: Paths, task_id: str, note: str | None = None) -> tuple[Path, Path]:
    """Close a task: mark done, move to archive, append to the quarterly log."""
    refs = load_all(paths)
    ref = require(refs, task_id)
    if ref.location == "archive":
        raise InvalidTransition(f"Task {task_id} is already archived")

    ref.task.status = "done"
    ref.task.updated = date.today().isoformat()
    archive_path = write_archive_task(paths, ref.task, epic=ref.epic)

    remaining = [r.task for r in refs if r.file == ref.file and r.task.id != task_id]
    rewrite_epic_file(ref.file, ref.epic, remaining)

    log_path = _append_done_log(paths, ref, note)
    return archive_path, log_path


def _append_done_log(paths: Paths, ref: TaskRef, note: str | None) -> Path:
    label = quarter_label()
    paths.done.mkdir(parents=True, exist_ok=True)
    log_path = paths.done / f"{label}.md"
    if not log_path.exists():
        log_path.write_text(f"# Done — {label}\n")
    entry = [f"\n## {ref.task.id} — {ref.task.summary}\n"]
    if note and note.strip():
        entry.append(f"\n{note.strip()}\n")
    with log_path.open("a") as handle:
        handle.writelines(entry)
    return log_path


def next_id(refs: list[TaskRef], epic_prefix: str) -> str:
    """Next free id for an epic, zero-padded to three digits."""
    numbers = []
    for ref in refs:
        if not ref.task.id.startswith(f"{epic_prefix}-"):
            continue
        suffix = ref.task.id.rsplit("-", 1)[-1]
        if suffix.isdigit():
            numbers.append(int(suffix))
    return f"{epic_prefix}-{(max(numbers) + 1) if numbers else 1:03d}"


def create(
    paths: Paths,
    epic_prefix: str,
    summary: str,
    priority: str = "Medium",
    description: str = "",
) -> TaskRef:
    """Create a task with an auto-numbered id in ``tasks/active/<epic>.yaml``."""
    refs = load_all(paths)
    task = Task(
        id=next_id(refs, epic_prefix),
        summary=summary,
        description=description,
        priority=priority,  # type: ignore[arg-type]
        status="todo",
        updated=date.today().isoformat(),
    )

    epic_file = paths.active / f"{epic_prefix}.yaml"
    existing = [ref.task for ref in refs if ref.file == epic_file]
    epic_name = next((ref.epic for ref in refs if ref.file == epic_file), epic_prefix)

    if epic_file.is_file():
        rewrite_epic_file(epic_file, epic_name, [*existing, task])
    else:
        write_active_file(epic_file, epic=epic_prefix, description="", tasks=[task])

    return TaskRef(task=task, file=epic_file, epic=epic_name, location="active")
