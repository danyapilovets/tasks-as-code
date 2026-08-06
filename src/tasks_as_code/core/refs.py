"""Check that a piece of text refers to a task that actually exists.

The point is not to enforce a message format — a regex in a hook does that. It is
to catch the reference that looks right and means nothing: an agent citing
``be-999`` because it needed an id and invented one. Only the backlog can tell
those apart.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from .loader import TaskRef

#: Same shape as a task id, but matched loosely so an invented id is still found
#: and reported rather than skipped.
_CANDIDATE = re.compile(r"\b([a-z][a-z0-9]*)-(\d+)\b")

#: An issue key of the tracker. Only keys of projects the backlog is already
#: synced to are considered, so a mention of some other project's ticket stays
#: prose rather than becoming a failed reference.
_KEY_CANDIDATE = re.compile(r"\b([A-Z][A-Z0-9]*)-(\d+)\b")

#: Commits git writes itself. Demanding a task id from them means blocking merges
#: and reverts, which people then work around with --no-verify.
EXEMPT_SUBJECTS = re.compile(r"^(Merge |Revert |fixup! |squash! )")


@dataclass
class RefCheck:
    """Outcome of a check, kept explicit so the CLI can report and JSON can carry it."""

    referenced: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    #: Issue keys of a known project that no task carries. Reported but not fatal
    #: on their own: an epic or a ticket outside the backlog is a legitimate thing
    #: to mention alongside the task being worked on.
    unknown_keys: list[str] = field(default_factory=list)
    wrong_status: dict[str, str] = field(default_factory=dict)
    skipped: str | None = None
    #: An id from this backlog, to show the format. A tool that rejects ids which
    #: do not exist should not illustrate itself with one.
    example: str | None = None
    #: Statuses a reference had to be in, empty when any status will do. Carried
    #: so the failure can name the rule it broke instead of assuming one.
    required: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """One valid task is enough; a fabricated id always fails.

        Mentioning another task alongside the one being worked on is normal
        ("follows up on api-001"), so a wrong status only matters when nothing
        valid was referenced at all.
        """
        if self.skipped:
            return True
        if self.invented:
            return False
        return bool(self.referenced)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "referenced": self.referenced,
            "invented": self.invented,
            "unknown_keys": self.unknown_keys,
            "wrong_status": self.wrong_status,
            "required": self.required,
            "skipped": self.skipped,
        }

    def problems(self) -> list[str]:
        problems = [
            f"{task_id} does not exist in the backlog — do not invent task ids"
            for task_id in self.invented
        ]
        if self.referenced:
            return problems

        problems += [
            f"{key} is not the issue of any task in the backlog — run 'tasc sync' if the "
            "task is new, or name the task's own issue"
            for key in self.unknown_keys
        ]
        wanted = " or ".join(f"'{status}'" for status in self.required)
        hint = "; run 'tasc mark {id} in_progress' first" if "in_progress" in self.required else ""
        problems += [
            f"{task_id} is '{status}', and a reference must be {wanted}" + hint.format(id=task_id)
            for task_id, status in sorted(self.wrong_status.items())
        ]
        if not problems:
            example = self.example or "api-004"
            problems.append(f"no task reference found — name a task, such as '{example}'")
        return problems


def _wanted_statuses(require_status: str | Sequence[str] | None) -> list[str]:
    if not require_status:
        return []
    if isinstance(require_status, str):
        return [require_status]
    return [status for status in require_status if status]


def check_text(
    text: str,
    refs: list[TaskRef],
    skip_markers: list[str] | None = None,
    require_status: str | Sequence[str] | None = None,
) -> RefCheck:
    """Verify that ``text`` names a task that exists.

    A candidate is only treated as a task reference when its prefix matches an
    epic that exists. That is what keeps ``utf-8`` or ``python-3`` from being read
    as task ids, while still catching ``be-999`` in a repository that has a ``be``
    epic — the first is noise, the second is a fabricated reference.

    An issue key counts as a reference too, so a message written for the tracker's
    benefit still passes: ``(AI-42) - what changed`` names the same task as
    ``api-004``, provided a sync has written that key onto the task.

    Status is only checked when ``require_status`` asks for it. Any status is a
    valid reference otherwise, ``done`` included: closing a task and committing
    the result is the workflow this tool exists to support, and the commit that
    records a completion has to be able to name what it completed.
    """
    text = text or ""
    for marker in skip_markers or []:
        if marker and marker in text:
            return RefCheck(skipped=marker)

    subject = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if EXEMPT_SUBJECTS.match(subject):
        return RefCheck(skipped="generated commit")

    known = {ref.task.id: ref.task.status for ref in refs}
    prefixes = {task_id.rsplit("-", 1)[0] for task_id in known}
    keys = {ref.task.jira: ref.task.id for ref in refs if ref.task.jira}
    projects = {key.rsplit("-", 1)[0] for key in keys}
    wanted = _wanted_statuses(require_status)

    # Open work first: the example is advice about what to reference, and pointing
    # at a finished task would be poor advice. Named by its issue key where it has
    # one, because that is then the form the message is expected to take.
    by_id = {ref.task.id: ref.task for ref in refs}
    example_id = next(
        (task_id for task_id, status in sorted(known.items()) if status != "done"),
        next(iter(sorted(known)), None),
    )
    example_task = by_id.get(example_id) if example_id else None

    result = RefCheck(
        required=wanted,
        example=(example_task.jira or example_id) if example_task else None,
    )
    for match in _KEY_CANDIDATE.finditer(text):
        candidate, project = match.group(0), match.group(1)
        if project not in projects:
            continue
        task_id = keys.get(candidate)
        if task_id is None:
            if candidate not in result.unknown_keys:
                result.unknown_keys.append(candidate)
            continue
        _accept(result, task_id, known[task_id], wanted)
    for match in _CANDIDATE.finditer(text):
        candidate, prefix = match.group(0), match.group(1)
        if prefix not in prefixes:
            continue
        if candidate not in known:
            if candidate not in result.invented:
                result.invented.append(candidate)
            continue
        _accept(result, candidate, known[candidate], wanted)
    return result


def _accept(result: RefCheck, task_id: str, status: str, wanted: list[str]) -> None:
    """Record a reference to a task that exists, as a reference or a wrong status."""
    if task_id in result.referenced:
        return
    if wanted and status not in wanted:
        result.wrong_status[task_id] = status
        return
    result.wrong_status.pop(task_id, None)
    result.referenced.append(task_id)
