"""The repository-level gate: 'tasc check-ref' and the hook that installs it."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tasks_as_code.cli import app
from tasks_as_code.core.config import Config
from tasks_as_code.core.paths import Paths

from .conftest import make_task

runner = CliRunner()


def run(*args: str, stdin: str | None = None) -> tuple[int, str]:
    result = runner.invoke(app, list(args), input=stdin)
    combined = f"{result.stdout}\n{result.stderr}"
    return result.exit_code, " ".join(combined.split())


@pytest.fixture
def backlog(in_project: Paths, add_epic: Callable[..., object]) -> Paths:
    add_epic(
        "api",
        [
            make_task("api-001", status="done"),
            make_task("api-002", status="in_progress"),
            make_task("api-003", status="todo"),
        ],
    )
    return in_project


def test_a_real_task_passes(backlog: Paths) -> None:
    code, out = run("check-ref", "api-002: retry on timeout")
    assert code == 0
    assert "api-002" in out


def test_a_missing_reference_fails_with_a_next_step(backlog: Paths) -> None:
    code, out = run("check-ref", "fix the thing")
    assert code == 1
    assert "no task reference found" in out
    assert "tasc next" in out


def test_the_skip_marker_survives_rich_markup(backlog: Paths) -> None:
    """Markers are bracketed, which is Rich's markup syntax: it must be escaped."""
    code, out = run("check-ref", "fix the thing")
    assert code == 1
    assert "[skip-task]" in out

    code, out = run("check-ref", "typo [skip-task]")
    assert code == 0
    assert "[skip-task]" in out


def test_reads_a_file_the_way_a_commit_msg_hook_passes_it(backlog: Paths, tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("api-002: retry on timeout\n\nDetail.\n", encoding="utf-8")
    assert run("check-ref", "--file", str(message))[0] == 0

    message.write_text("wip\n", encoding="utf-8")
    assert run("check-ref", "--file", str(message))[0] == 1


def test_an_unreadable_file_is_reported(backlog: Paths, tmp_path: Path) -> None:
    code, out = run("check-ref", "--file", str(tmp_path / "nope.txt"))
    assert code == 1
    assert "nope.txt" in out


def test_reads_stdin_when_given_nothing(backlog: Paths) -> None:
    assert run("check-ref", stdin="api-002: work\n")[0] == 0
    assert run("check-ref", stdin="work\n")[0] == 1


def test_json_output_carries_the_detail(backlog: Paths) -> None:
    result = runner.invoke(app, ["check-ref", "--json", "api-002 and api-404"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data == {
        "ok": False,
        "referenced": ["api-002"],
        "invented": ["api-404"],
        "wrong_status": {},
        "required": [],
        "skipped": None,
    }


def test_json_output_on_success(backlog: Paths) -> None:
    result = runner.invoke(app, ["check-ref", "--json", "api-003: work"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True


def test_require_status_can_be_demanded_on_the_command_line(backlog: Paths) -> None:
    code, out = run("check-ref", "--require-status", "in_progress", "api-003: work")
    assert code == 1
    assert "api-003 is 'todo'" in out


def test_require_status_can_be_configured(backlog: Paths) -> None:
    config = Config.load(backlog.config_file)
    config.refs.require_status = "in_progress"
    config.dump(backlog.config_file)
    assert run("check-ref", "api-003: work")[0] == 1
    assert run("check-ref", "api-002: work")[0] == 0


def test_a_commit_may_reference_the_task_it_closes(backlog: Paths) -> None:
    """`tasc done` then commit is the workflow; the hook must not forbid it."""
    assert run("done", "api-002")[0] == 0
    code, out = run("check-ref", "api-002: retry on timeout")
    assert code == 0
    assert "api-002" in out


def test_several_statuses_can_be_required(backlog: Paths) -> None:
    """The strict setting that still lets a task be closed and committed."""
    config = Config.load(backlog.config_file)
    config.refs.require_status = ["in_progress", "done"]
    config.dump(backlog.config_file)
    assert run("check-ref", "api-002: work")[0] == 0
    assert run("check-ref", "api-001: work")[0] == 0

    code, out = run("check-ref", "api-003: work")
    assert code == 1
    assert "api-003 is 'todo', and a reference must be 'in_progress' or 'done'" in out


def test_repeated_require_status_flags_accumulate(backlog: Paths) -> None:
    args = ("--require-status", "in_progress", "--require-status", "done")
    assert run("check-ref", *args, "api-001: work")[0] == 0
    assert run("check-ref", *args, "api-003: work")[0] == 1


def test_configured_markers_replace_the_default(backlog: Paths) -> None:
    config = Config.load(backlog.config_file)
    config.refs.skip_markers = ["#trivial"]
    config.dump(backlog.config_file)
    assert run("check-ref", "typo #trivial")[0] == 0
    assert run("check-ref", "typo [skip-task]")[0] == 1


def test_install_hook_writes_a_commit_msg_hook(backlog: Paths) -> None:
    (backlog.root / ".git").mkdir()
    code, out = run("install-hook")
    assert code == 0

    hook = backlog.root / ".git" / "hooks" / "commit-msg"
    assert "tasc check-ref --file" in hook.read_text(encoding="utf-8")
    assert "--no-verify" in out


@pytest.mark.skipif(os.name != "posix", reason="Windows has no execute bit to set")
def test_the_hook_is_executable(backlog: Paths) -> None:
    """Without the bit, git reports the hook as ignored and commits go through."""
    (backlog.root / ".git").mkdir()
    assert run("install-hook")[0] == 0
    hook = backlog.root / ".git" / "hooks" / "commit-msg"
    assert hook.stat().st_mode & stat.S_IXUSR


def test_install_hook_refuses_to_clobber_an_existing_hook(backlog: Paths) -> None:
    hooks = backlog.root / ".git" / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "commit-msg"
    hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")

    code, out = run("install-hook")
    assert code == 1
    assert "--force" in out
    assert "echo mine" in hook.read_text(encoding="utf-8")

    assert run("install-hook", "--force")[0] == 0
    assert "tasc check-ref" in hook.read_text(encoding="utf-8")


def test_install_hook_follows_a_worktree_gitfile(backlog: Paths, tmp_path: Path) -> None:
    """A worktree has a .git file pointing elsewhere, not a .git directory."""
    real = tmp_path / "elsewhere" / "worktrees" / "wt"
    real.mkdir(parents=True)
    (backlog.root / ".git").write_text(f"gitdir: {real}\n", encoding="utf-8")

    assert run("install-hook")[0] == 0
    assert (real / "hooks" / "commit-msg").is_file()


def test_install_hook_without_a_repository_says_so(backlog: Paths) -> None:
    code, out = run("install-hook")
    assert code == 1
    assert "No git repository" in out


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="no POSIX shell to run it with")
def test_the_installed_hook_is_a_working_shell_script(backlog: Paths) -> None:
    """Run the generated script directly: a syntax error in it would only ever
    show up as a mysteriously failing commit."""
    (backlog.root / ".git").mkdir()
    assert run("install-hook")[0] == 0
    hook = backlog.root / ".git" / "hooks" / "commit-msg"

    message = backlog.root / "msg.txt"
    message.write_text("api-002: work\n", encoding="utf-8")
    result = subprocess.run(
        ["/bin/sh", str(hook), str(message)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=backlog.root,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
    )
    # tasc is not on that PATH, so the hook takes its "not installed" branch,
    # which must warn rather than block.
    assert result.returncode == 0
    assert "skipping" in result.stderr
