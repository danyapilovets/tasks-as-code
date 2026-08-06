"""Putting the issue key of a task into a commit message."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tasks_as_code.core.loader import load_all
from tasks_as_code.core.messages import stamp_message
from tasks_as_code.core.paths import Paths

from .conftest import make_task


@pytest.fixture
def refs(project: Paths, add_epic: Callable[..., object]) -> list:
    add_epic(
        "api",
        [
            make_task("api-001", status="done", jira="AI-1"),
            make_task("api-002", status="in_progress", jira="AI-2"),
            make_task("api-003", status="todo"),
        ],
    )
    return load_all(project)


def test_the_named_task_lends_its_key(refs: list) -> None:
    result = stamp_message("api-002: retry on timeout", refs)
    assert result.text == "AI-2 retry on timeout"
    assert (result.key, result.task_id) == ("AI-2", "api-002")


def test_the_id_is_not_kept_alongside_the_key(refs: list) -> None:
    """Both would say the same thing twice, and the key is what links the commit."""
    assert "api-002" not in stamp_message("api-002: retry on timeout", refs).text


@pytest.mark.parametrize(
    "subject",
    ["api-002: retry", "api-002 - retry", "(api-002) retry", "[api-002] retry", "api-002 retry"],
)
def test_an_id_is_recognised_however_it_is_punctuated(refs: list, subject: str) -> None:
    assert stamp_message(subject, refs).text == "AI-2 retry"


def test_the_shape_of_the_subject_is_configurable(refs: list) -> None:
    result = stamp_message("api-002: retry", refs, subject_format="({key}) - {subject}")
    assert result.text == "(AI-2) - retry"


def test_a_message_that_already_names_the_issue_is_left_alone(refs: list) -> None:
    result = stamp_message("(AI-2) - retry on timeout", refs)
    assert not result.changed
    assert result.reason == "the subject already names an issue"


def test_the_single_task_in_progress_is_assumed(refs: list) -> None:
    """The common case: one thing is being worked on, and the message just says what."""
    result = stamp_message("retry on timeout", refs)
    assert result.text == "AI-2 retry on timeout"


def test_two_tasks_in_progress_are_not_guessed_between(
    project: Paths, add_epic: Callable[..., object]
) -> None:
    add_epic(
        "api",
        [
            make_task("api-002", status="in_progress", jira="AI-2"),
            make_task("api-004", status="in_progress", jira="AI-4"),
        ],
    )
    result = stamp_message("retry on timeout", load_all(project))
    assert not result.changed
    assert "2 tasks are in progress" in (result.reason or "")


def test_nothing_in_progress_and_nothing_named_says_so(
    project: Paths, add_epic: Callable[..., object]
) -> None:
    add_epic("api", [make_task("api-003", status="todo", jira="AI-3")])
    result = stamp_message("retry on timeout", load_all(project))
    assert not result.changed
    assert "no task is in progress" in (result.reason or "")


def test_a_task_without_an_issue_is_reported_not_invented(refs: list) -> None:
    result = stamp_message("api-003: start the work", refs)
    assert not result.changed
    assert result.reason == "api-003 has no issue yet — run 'tasc sync'"


def test_a_skipped_message_is_untouched(refs: list) -> None:
    result = stamp_message("[skip-task] tidy up", refs, skip_markers=["[skip-task]"])
    assert not result.changed
    assert "[skip-task]" in (result.reason or "")


@pytest.mark.parametrize("subject", ["Merge branch 'main'", 'Revert "api-002: retry"'])
def test_messages_git_writes_itself_are_untouched(refs: list, subject: str) -> None:
    assert not stamp_message(subject, refs).changed


def test_the_body_and_the_comments_survive(refs: list) -> None:
    """git hands over the whole file, comments included; rewriting the subject
    must not eat the rest of it."""
    original = "api-002: retry\n\nWhy it retries.\n\n# Please enter the commit message\n"
    result = stamp_message(original, refs)
    assert result.text == "AI-2 retry\n\nWhy it retries.\n\n# Please enter the commit message\n"


def test_a_leading_blank_line_does_not_shift_the_subject(refs: list) -> None:
    assert stamp_message("\napi-002: retry\n", refs).text == "\nAI-2 retry\n"


def test_an_empty_message_is_reported(refs: list) -> None:
    result = stamp_message("\n\n", refs)
    assert not result.changed
    assert result.reason == "the message is empty"


def test_an_id_mentioned_mid_sentence_gains_the_key_and_keeps_its_wording(refs: list) -> None:
    result = stamp_message("close out the work of api-002", refs)
    assert result.text == "AI-2 close out the work of api-002"


def test_an_unknown_id_falls_back_to_the_task_in_progress(refs: list) -> None:
    """Checking the id against the backlog is check-ref's job, not this one's."""
    assert stamp_message("api-999: something", refs).text == "AI-2 api-999: something"
