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


def test_a_closed_task_alone_is_rejected(refs: list) -> None:
    result = check_text("api-001: more work", refs)
    assert not result.ok
    assert result.wrong_status == {"api-001": "done"}
    assert "in_progress" in result.problems()[0]


def test_a_closed_task_beside_an_open_one_is_fine(refs: list) -> None:
    """ "Follows up on api-001" is a normal thing to write and must not block."""
    result = check_text("api-003: follows up on api-001", refs)
    assert result.ok
    assert result.referenced == ["api-003"]


def test_require_status_rejects_a_task_not_started(refs: list) -> None:
    result = check_text("api-003: work", refs, require_status="in_progress")
    assert not result.ok
    assert result.wrong_status == {"api-003": "todo"}
    result = check_text("api-002: work", refs, require_status="in_progress")
    assert result.ok


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
