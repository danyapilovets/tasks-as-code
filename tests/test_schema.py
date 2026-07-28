"""Schema normalisation, validation and priority ranking."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tasks_as_code.core.schema import PRIORITY_ORDER, Task


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("wip", "in_progress"), ("IN-PROGRESS", "in_progress"), ("closed", "done"), ("To Do", "todo")],
)
def test_status_aliases_are_normalised(raw: str, expected: str) -> None:
    assert Task(id="a-1", summary="s", status=raw).status == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("crit", "Critical"), ("HIGH", "High"), ("med", "Medium"), ("minor", "Low")],
)
def test_priority_aliases_are_normalised(raw: str, expected: str) -> None:
    assert Task(id="a-1", summary="s", priority=raw).priority == expected


def test_type_aliases_are_normalised() -> None:
    assert Task(id="a-1", summary="s", type="fix").type == "Bug"


def test_critical_outranks_high() -> None:
    """A missing Critical entry would silently rank it alongside Medium."""
    assert PRIORITY_ORDER["Critical"] < PRIORITY_ORDER["High"] < PRIORITY_ORDER["Medium"]
    assert Task(id="a-1", summary="s", priority="Critical").priority_rank == 0


@pytest.mark.parametrize("bad_id", ["A-1", "1-a", "a_1", "a-", "-1", "a1"])
def test_malformed_ids_are_rejected(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        Task(id=bad_id, summary="s")


def test_empty_summary_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Task(id="a-1", summary="")


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Task(id="a-1", summary="s", status="almost-done")


def test_nested_mapping_in_criteria_is_flattened() -> None:
    """A YAML author writing '- key: value' gets a usable string, not a crash."""
    task = Task.model_validate(
        {"id": "a-1", "summary": "s", "acceptance_criteria": [{"given": "x", "then": "y"}, "plain"]}
    )
    assert task.acceptance_criteria == ["given: x, then: y", "plain"]


def test_none_lists_become_empty() -> None:
    task = Task.model_validate({"id": "a-1", "summary": "s", "depends_on": None})
    assert task.depends_on == []


def test_extra_fields_survive_round_trip() -> None:
    """Teams attach their own fields; the tool must not drop them."""
    task = Task.model_validate({"id": "a-1", "summary": "s", "owner": "dana", "points": 3})
    assert task.model_dump()["owner"] == "dana"
    assert task.model_dump()["points"] == 3


def test_epic_prefix_comes_from_the_id() -> None:
    assert Task(id="infra-042", summary="s").epic_prefix == "infra"
