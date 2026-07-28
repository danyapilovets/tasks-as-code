"""Check that a piece of text refers to a task that actually exists.

The point is not to enforce a message format — a regex in a hook does that. It is
to catch the reference that looks right and means nothing: an agent citing
``be-999`` because it needed an id and invented one. Only the backlog can tell
those apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .loader import TaskRef

#: Same shape as a task id, but matched loosely so an invented id is still found
#: and reported rather than skipped.
_CANDIDATE = re.compile(r"\b([a-z][a-z0-9]*)-(\d+)\b")

#: Commits git writes itself. Demanding a task id from them means blocking merges
#: and reverts, which people then work around with --no-verify.
_EXEMPT_SUBJECTS = re.compile(r"^(Merge |Revert |fixup! |squash! )")


@dataclass
class RefCheck:
    """Outcome of a check, kept explicit so the CLI can report and JSON can carry it."""

    referenced: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    wrong_status: dict[str, str] = field(default_factory=dict)
    skipped: str | None = None
    #: An id from this backlog, to show the format. A tool that rejects ids which
    #: do not exist should not illustrate itself with one.
    example: str | None = None

    @property
    def ok(self) -> bool:
        """One valid open task is enough; a fabricated id always fails.

        Mentioning a closed task alongside the one being worked on is normal
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
            "wrong_status": self.wrong_status,
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
            f"{task_id} is '{status}'; run 'tasc mark {task_id} in_progress' first"
            for task_id, status in sorted(self.wrong_status.items())
        ]
        if not problems:
            example = self.example or "api-004"
            problems.append(f"no task reference found — mention a task id such as '{example}'")
        return problems


def check_text(
    text: str,
    refs: list[TaskRef],
    skip_markers: list[str] | None = None,
    require_status: str | None = None,
) -> RefCheck:
    """Verify that ``text`` names a real, open task.

    A candidate is only treated as a task reference when its prefix matches an
    epic that exists. That is what keeps ``utf-8`` or ``python-3`` from being read
    as task ids, while still catching ``be-999`` in a repository that has a ``be``
    epic — the first is noise, the second is a fabricated reference.
    """
    text = text or ""
    for marker in skip_markers or []:
        if marker and marker in text:
            return RefCheck(skipped=marker)

    subject = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if _EXEMPT_SUBJECTS.match(subject):
        return RefCheck(skipped="generated commit")

    known = {ref.task.id: ref.task.status for ref in refs}
    prefixes = {task_id.rsplit("-", 1)[0] for task_id in known}

    result = RefCheck(
        example=next((task_id for task_id, s in sorted(known.items()) if s != "done"), None)
    )
    for match in _CANDIDATE.finditer(text):
        candidate, prefix = match.group(0), match.group(1)
        if prefix not in prefixes:
            continue
        if candidate not in known:
            if candidate not in result.invented:
                result.invented.append(candidate)
            continue
        if candidate in result.referenced:
            continue
        status = known[candidate]
        wanted = require_status or None
        if (wanted and status != wanted) or (not wanted and status == "done"):
            result.wrong_status[candidate] = status
        else:
            result.referenced.append(candidate)
    return result
