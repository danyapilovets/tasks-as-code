"""Put the issue key of a task into a commit message.

A tracker links a commit to an issue by finding its key in the message, and
nothing else. So either every message is written with the key in it by hand — and
the key is the one part of a task nobody remembers — or something puts it there.

This is that something. It reads the task the message already names, takes the key
a sync wrote onto it, and rewrites the subject line. Nothing here talks to the
tracker: a commit is written offline, and a hook that needs the network is a hook
that gets bypassed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .loader import TaskRef
from .refs import EXEMPT_SUBJECTS

#: A task id at the start of the subject, in the shapes people write it: bare,
#: bracketed, followed by a colon or a dash. Removed rather than kept, because the
#: key replaces it — carrying both says the same thing twice.
_LEADING_ID = re.compile(
    r"^\s*[\(\[]?(?P<id>[a-z][a-z0-9]*-\d+)[\)\]]?\s*[:\-\u2013\u2014]?\s*",
)

_ANY_ID = re.compile(r"\b[a-z][a-z0-9]*-\d+\b")
_ANY_KEY = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")


@dataclass
class Stamp:
    """The rewritten message, and why it came out that way."""

    text: str
    changed: bool = False
    key: str | None = None
    task_id: str | None = None
    #: Why nothing was written, when nothing was. Shown to the author rather than
    #: raised: refusing the commit is the job of the check that follows.
    reason: str | None = None


def stamp_message(
    text: str,
    refs: list[TaskRef],
    subject_format: str = "{key} {subject}",
    skip_markers: list[str] | None = None,
) -> Stamp:
    """Rewrite the subject of ``text`` so it carries the task's issue key.

    The task is the one the message names. Where it names none, an unambiguous
    single task in progress is used instead — the common case of committing while
    one thing is being worked on. Two tasks in progress is not guessed at.
    """
    lines = text.splitlines()
    index = next((i for i, line in enumerate(lines) if line.strip()), None)
    if index is None:
        return Stamp(text=text, reason="the message is empty")

    subject = lines[index].strip()
    for marker in skip_markers or []:
        if marker and marker in text:
            return Stamp(text=text, reason=f"the message carries {marker}")
    if EXEMPT_SUBJECTS.match(subject):
        return Stamp(text=text, reason="git wrote this message itself")

    by_key = {ref.task.jira: ref for ref in refs if ref.task.jira}
    if any(match.group(0) in by_key for match in _ANY_KEY.finditer(subject)):
        return Stamp(text=text, reason="the subject already names an issue")

    by_id = {ref.task.id: ref for ref in refs}
    named = [match.group(0) for match in _ANY_ID.finditer(subject) if match.group(0) in by_id]
    if named:
        ref = by_id[named[0]]
    else:
        in_progress = [r for r in refs if r.task.status == "in_progress"]
        if len(in_progress) != 1:
            return Stamp(
                text=text,
                reason=(
                    "the subject names no task, and "
                    + (
                        "no task is in progress"
                        if not in_progress
                        else f"{len(in_progress)} tasks are in progress"
                    )
                ),
            )
        ref = in_progress[0]

    if not ref.task.jira:
        return Stamp(
            text=text,
            task_id=ref.task.id,
            reason=f"{ref.task.id} has no issue yet — run 'tasc sync'",
        )

    # Only the id of the task being stamped is dropped. Any other id stays in the
    # text, invented ones included: hiding one would rewrite a message into passing
    # the check that exists to catch it.
    leading = _LEADING_ID.match(subject)
    stripped = subject
    if leading and leading.group("id") == ref.task.id:
        stripped = subject[leading.end() :] or subject
    lines[index] = subject_format.format(key=ref.task.jira, subject=stripped)
    rewritten = "\n".join(lines)
    if text.endswith("\n"):
        rewritten += "\n"
    return Stamp(
        text=rewritten,
        changed=rewritten != text,
        key=ref.task.jira,
        task_id=ref.task.id,
    )
