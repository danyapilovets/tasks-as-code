"""Several agents on one backlog, plus the layout knobs that make that work.

The hazard these cover: ``tasc next`` is deterministic, so agents asking at the
same moment all receive the same task, and another agent's ``in_progress`` is
invisible until it pushes. Owners, epics and shards partition the backlog so the
collision cannot happen in the first place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tasks_as_code.core.config import Config
from tasks_as_code.core.loader import load_all
from tasks_as_code.core.paths import Paths
from tasks_as_code.core.workflow import (
    InvalidTransition,
    archive,
    create,
    in_shard,
    parse_shard,
    pick_next,
    set_status,
)

from .conftest import make_task


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1/1", (1, 1)), ("2/3", (2, 3)), ("3/3", (3, 3)), (" 2 / 4 ", (2, 4))],
)
def test_parse_shard_accepts_index_of_total(value: str, expected: tuple[int, int]) -> None:
    assert parse_shard(value) == expected


@pytest.mark.parametrize("value", ["", "2", "2/", "/3", "a/3", "2/b", "0/3", "4/3", "-1/3", "2/0"])
def test_parse_shard_rejects_nonsense(value: str) -> None:
    with pytest.raises(ValueError, match=r"[Ss]hard"):
        parse_shard(value)


def test_shards_partition_every_id_exactly_once() -> None:
    """Disjoint and total: no task is taken twice, and none is stranded."""
    ids = [f"api-{n:03d}" for n in range(200)]
    for total in (2, 3, 5):
        assignments = [sum(in_shard(i, (k, total)) for k in range(1, total + 1)) for i in ids]
        assert set(assignments) == {1}


def test_shard_membership_is_stable_across_processes() -> None:
    """Golden values: CRC32, not hash(), so PYTHONHASHSEED cannot reshuffle shards.

    A shard that changed membership between runs would hand the same task to two
    agents, which is the exact failure sharding exists to prevent.
    """
    first = [i for i in (f"api-{n:03d}" for n in range(50)) if in_shard(i, (1, 3))]
    assert first == [
        "api-000",
        "api-002",
        "api-004",
        "api-011",
        "api-015",
        "api-017",
        "api-018",
        "api-030",
        "api-031",
        "api-034",
        "api-035",
        "api-036",
        "api-041",
        "api-042",
    ]


def test_next_skips_tasks_owned_by_someone_else(project: Paths, add_epic) -> None:
    add_epic(
        "api",
        [
            make_task("api-001", priority="Critical", owner="agent-b"),
            make_task("api-002", priority="High"),
        ],
    )
    refs = load_all(project)

    assert [r.task.id for r in pick_next(refs, limit=5, owner="agent-a")] == ["api-002"]
    # Unowned work stays available to whoever asks; only rivals are hidden.
    assert [r.task.id for r in pick_next(refs, limit=5, owner="agent-b")] == ["api-001", "api-002"]
    assert len(pick_next(refs, limit=5)) == 2


def test_next_can_be_restricted_to_one_epic(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", priority="Critical")])
    add_epic("ui", [make_task("ui-001", priority="Low")])
    refs = load_all(project)

    assert [r.task.id for r in pick_next(refs, limit=5, epic="ui")] == ["ui-001"]


def test_parallel_agents_with_shards_never_collide(project: Paths, add_epic) -> None:
    add_epic("api", [make_task(f"api-{n:03d}") for n in range(30)])
    refs = load_all(project)

    picked = [pick_next(refs, limit=1, shard=(k, 3)) for k in (1, 2, 3)]
    ids = [refs[0].task.id for refs in picked if refs]
    assert len(ids) == len(set(ids)) == 3


def test_shard_and_owner_compose(project: Paths, add_epic) -> None:
    add_epic("api", [make_task(f"api-{n:03d}", owner="agent-b" if n else None) for n in range(30)])
    refs = load_all(project)

    for ref in pick_next(refs, limit=99, owner="agent-a", shard=(1, 3)):
        assert ref.task.owner is None
        assert in_shard(ref.task.id, (1, 3))


def test_mark_claims_the_task_in_the_same_write(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001")])

    ref = set_status(project, "api-001", "in_progress", owner="agent-a")
    assert ref.task.owner == "agent-a"
    assert load_all(project)[0].task.owner == "agent-a"


def test_claiming_someone_elses_task_fails(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", owner="agent-b")])

    with pytest.raises(InvalidTransition, match="already owned by agent-b"):
        set_status(project, "api-001", "in_progress", owner="agent-a")
    assert load_all(project)[0].task.owner == "agent-b"


def test_reclaiming_your_own_task_is_allowed(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", owner="agent-a")])

    assert set_status(project, "api-001", "blocked", owner="agent-a").task.owner == "agent-a"


def test_status_change_without_owner_leaves_ownership_alone(project: Paths, add_epic) -> None:
    add_epic("api", [make_task("api-001", owner="agent-b")])

    assert set_status(project, "api-001", "blocked").task.owner == "agent-b"


def test_create_can_assign_an_owner(project: Paths) -> None:
    ref = create(project, epic_prefix="api", summary="Wire the webhook", owner="agent-a")

    assert ref.task.owner == "agent-a"
    assert load_all(project)[0].task.owner == "agent-a"


def test_owner_survives_a_round_trip_through_yaml(project: Paths, add_epic) -> None:
    path = add_epic("api", [make_task("api-001", owner="agent-a"), make_task("api-002")])

    assert "owner: agent-a" in path.read_text()
    # Absent rather than 'owner: null' for unassigned tasks, to keep files clean.
    assert path.read_text().count("owner:") == 1


def test_done_dir_can_live_outside_the_tasks_tree(tmp_path: Path) -> None:
    """Lets an existing repo adopt tasc without moving its logs."""
    config = Config(project_name="Legacy", tasks_dir="tasks", done_dir="docs/changelog")
    paths = Paths(tmp_path, config)
    for folder in (paths.active, paths.archive, paths.done):
        folder.mkdir(parents=True, exist_ok=True)
    config.dump(paths.config_file)
    assert paths.done == tmp_path / "docs" / "changelog"

    from tasks_as_code.core.loader import write_active_file

    write_active_file(paths.active / "api.yaml", epic="api", description="", tasks=[])
    create(paths, epic_prefix="api", summary="Ship it")
    _, log_path = archive(paths, "api-001")

    assert log_path.parent == tmp_path / "docs" / "changelog"


def test_done_dir_defaults_under_tasks_dir(tmp_path: Path) -> None:
    paths = Paths(tmp_path, Config(tasks_dir="backlog"))
    assert paths.done == tmp_path / "backlog" / "done"
