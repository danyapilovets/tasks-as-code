"""Checking that text refers to a task that exists."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tasks_as_code.core.loader import load_all
from tasks_as_code.core.paths import Paths
from tasks_as_code.core.refs import check_text

from .conftest import make_task


@pytest.fixture
def refs(project: Paths, add_epic: Callable[..., object]) -> list:
    add_epic(
        "api",
        [
            make_task("api-001", status="done"),
            make_task("api-002", status="in_progress"),
            make_task("api-003", status="todo"),
        ],
    )
    return load_all(project)


def test_a_real_open_task_passes(refs: list) -> None:
    result = check_text("api-002: retry on timeout", refs)
    assert result.ok
    assert result.referenced == ["api-002"]


def test_text_without_any_reference_fails(refs: list) -> None:
    result = check_text("fix the flaky test", refs)
    assert not result.ok
    assert "no task reference found" in result.problems()[0]


def test_the_suggested_id_comes_from_this_backlog(refs: list) -> None:
    """Illustrating the format with an id that does not exist invites the mistake
    the check exists to catch."""
    assert "api-002" in check_text("nothing here", refs).problems()[0]


def test_an_empty_backlog_still_shows_the_format(project: Paths) -> None:
    assert "api-004" in check_text("nothing here", []).problems()[0]


def test_an_invented_id_is_named_as_such(refs: list) -> None:
    """The reason this tool checks instead of a regex: catching a fabricated id."""
    result = check_text("api-999: rewrite everything", refs)
    assert not result.ok
    assert result.invented == ["api-999"]
    assert "does not exist" in result.problems()[0]


def test_an_invented_id_fails_even_beside_a_real_one(refs: list) -> None:
    result = check_text("api-002 and api-777", refs)
    assert not result.ok
    assert result.referenced == ["api-002"]
    assert result.invented == ["api-777"]
    # Only the fabricated id is worth saying anything about.
    assert result.problems() == ["api-777 does not exist in the backlog — do not invent task ids"]


def test_the_same_invented_id_twice_is_reported_once(refs: list) -> None:
    result = check_text("api-777 blocks api-777", refs)
    assert result.invented == ["api-777"]


def test_unknown_prefixes_are_not_task_ids(refs: list) -> None:
    """Otherwise 'utf-8' and 'python-3' would read as fabricated references."""
    result = check_text("api-002: move to utf-8 on python-3 with sha-256", refs)
    assert result.ok
    assert result.invented == []


def test_a_closed_task_is_a_valid_reference(refs: list) -> None:
    """The commit that records a completion has to be able to name it, and
    `tasc done` has already closed the task by the time it is written."""
    result = check_text("api-001: retry on timeout", refs)
    assert result.ok
    assert result.referenced == ["api-001"]
    assert result.wrong_status == {}


def test_a_closed_task_beside_an_open_one_is_fine(refs: list) -> None:
    """ "Follows up on api-001" is a normal thing to write and must not block."""
    result = check_text("api-003: follows up on api-001", refs)
    assert result.ok
    assert result.referenced == ["api-003", "api-001"]


def test_the_example_prefers_open_work(refs: list) -> None:
    """Any status is a valid reference, but advice should point at live work."""
    assert "api-002" in check_text("nothing here", refs).problems()[0]


def test_the_example_falls_back_to_a_closed_task(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", status="done")])
    refs = load_all(project)
    assert "api-001" in check_text("nothing here", refs).problems()[0]


def test_require_status_rejects_a_task_not_started(refs: list) -> None:
    result = check_text("api-003: work", refs, require_status="in_progress")
    assert not result.ok
    assert result.wrong_status == {"api-003": "todo"}
    assert result.required == ["in_progress"]
    result = check_text("api-002: work", refs, require_status="in_progress")
    assert result.ok


def test_require_status_accepts_a_list(refs: list) -> None:
    statuses = ["in_progress", "done"]
    assert check_text("api-001: work", refs, require_status=statuses).ok
    assert check_text("api-002: work", refs, require_status=statuses).ok
    assert not check_text("api-003: work", refs, require_status=statuses).ok


def test_a_failure_names_the_rule_it_broke(refs: list) -> None:
    problem = check_text("api-003", refs, require_status=["in_progress", "done"]).problems()[0]
    assert problem.startswith("api-003 is 'todo', and a reference must be 'in_progress' or 'done'")
    assert "tasc mark api-003 in_progress" in problem


def test_a_requirement_without_in_progress_offers_no_mark_hint(refs: list) -> None:
    problem = check_text("api-003", refs, require_status="done").problems()[0]
    assert problem == "api-003 is 'todo', and a reference must be 'done'"


def test_an_empty_requirement_list_checks_no_status(refs: list) -> None:
    assert check_text("api-001: work", refs, require_status=[]).ok
    assert check_text("api-001: work", refs, require_status=[""]).ok


def test_a_marker_skips_the_check(refs: list) -> None:
    result = check_text("fix a typo [skip-task]", refs, skip_markers=["[skip-task]"])
    assert result.ok
    assert result.skipped == "[skip-task]"


def test_markers_are_opt_in(refs: list) -> None:
    assert not check_text("fix a typo [skip-task]", refs, skip_markers=[]).ok


@pytest.mark.parametrize(
    "subject",
    [
        "Merge branch 'main' into feature",
        'Revert "api-002: retry on timeout"',
        "fixup! api-002: retry",
    ],
)
def test_git_generated_commits_are_exempt(refs: list, subject: str) -> None:
    """Blocking merges is how a team learns to pass --no-verify by habit."""
    assert check_text(subject, refs).skipped == "generated commit"


def test_a_reference_in_the_body_counts(refs: list) -> None:
    result = check_text("retry on timeout\n\nRefs: api-002\n", refs)
    assert result.ok


def test_empty_text_fails_rather_than_crashes(refs: list) -> None:
    assert not check_text("", refs).ok


def test_the_same_id_twice_is_reported_once(refs: list) -> None:
    result = check_text("api-002 fixes api-002", refs)
    assert result.referenced == ["api-002"]


def test_ids_must_be_whole_words(refs: list) -> None:
    """A trailing digit run, as in a hash or a version, is not a task id."""
    assert not check_text("see xapi-002 and api-0021", refs).ok


# --- issue keys ------------------------------------------------------------
# A message written for the tracker names the issue, not the task file. It has to
# pass the same check, or the two conventions cannot both hold at once.


@pytest.fixture
def synced(project: Paths, add_epic: Callable[..., object]) -> list:
    add_epic(
        "api",
        [
            make_task("api-001", status="done", jira="AI-1"),
            make_task("api-002", status="in_progress", jira="AI-2"),
            make_task("api-003", status="todo"),
        ],
    )
    return load_all(project)


def test_an_issue_key_references_the_task_that_carries_it(synced: list) -> None:
    result = check_text("(AI-2) - retry on timeout", synced)
    assert result.ok
    assert result.referenced == ["api-002"]


def test_a_key_of_a_known_project_with_no_task_is_not_a_reference(synced: list) -> None:
    result = check_text("(AI-404) - retry", synced)
    assert not result.ok
    assert result.unknown_keys == ["AI-404"]
    assert "AI-404 is not the issue of any task" in result.problems()[0]


def test_such_a_key_alongside_a_real_task_still_passes(synced: list) -> None:
    """Mentioning an epic or a ticket outside the backlog is normal."""
    assert check_text("(AI-2) - part of AI-404", synced).ok


def test_a_key_of_another_project_is_prose(synced: list) -> None:
    result = check_text("api-002: as asked in SD-3132879681", synced)
    assert result.ok
    assert result.unknown_keys == []


def test_a_key_is_checked_against_the_required_status_too(synced: list) -> None:
    result = check_text("(AI-1) - work", synced, require_status="in_progress")
    assert not result.ok
    assert result.wrong_status == {"api-001": "done"}


def test_the_key_and_the_id_of_one_task_count_once(synced: list) -> None:
    assert check_text("(AI-2) - see api-002", synced).referenced == ["api-002"]


def test_the_example_is_the_key_where_the_task_has_one(synced: list) -> None:
    """The advice should show the form the message is expected to take."""
    assert "AI-2" in check_text("nothing here", synced).problems()[0]


def test_keys_are_ignored_before_the_first_sync(refs: list) -> None:
    """With no key anywhere in the backlog, AI-2 is just text."""
    result = check_text("(AI-2) - retry", refs)
    assert not result.ok
    assert result.unknown_keys == []
