"""Cross-platform text handling: file encodings, and output that survives wrapping.

Both guarantees here failed silently on one platform while passing on another,
which is the worst kind of bug to own in a tool other people install.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tasks_as_code.cli import app
from tasks_as_code.core.config import Config
from tasks_as_code.core.loader import load_all, write_active_file
from tasks_as_code.core.paths import Paths
from tasks_as_code.core.workflow import archive

from .conftest import make_task

runner = CliRunner()

UKRAINIAN = "Реєстрація та отримання API-ключа для кадастру"


def test_non_ascii_text_round_trips_through_every_written_file(project: Paths) -> None:
    """Guards Windows, where the default encoding is cp1252 and this would raise."""
    write_active_file(
        project.active / "cad.yaml",
        epic="cadastre",
        description="Кадастрові інтеграції",
        tasks=[make_task("cad-001", summary=UKRAINIAN)],
    )

    assert load_all(project)[0].task.summary == UKRAINIAN
    assert UKRAINIAN in (project.active / "cad.yaml").read_text(encoding="utf-8")

    archive_path, log_path = archive(project, "cad-001", note="Готово")
    assert UKRAINIAN in archive_path.read_text(encoding="utf-8")
    assert UKRAINIAN in log_path.read_text(encoding="utf-8")
    assert "Готово" in log_path.read_text(encoding="utf-8")


def test_index_and_config_are_written_as_utf8(in_project: Paths, add_epic) -> None:
    add_epic("cad", [make_task("cad-001", summary=UKRAINIAN, owner="агроном")])
    result = runner.invoke(app, ["reindex"], catch_exceptions=False)

    assert result.exit_code == 0
    body = in_project.index_md.read_text(encoding="utf-8")
    assert UKRAINIAN in body
    assert "агроном" in body


def test_a_long_path_in_an_error_stays_in_one_piece(tmp_path: Path, monkeypatch) -> None:
    """Rich word-wrap must not fold a file path, or the user cannot copy it.

    The failure depended on how long the temporary directory happened to be, so it
    passed on macOS and failed on Linux and Windows. A deliberately long path
    reproduces it everywhere.
    """
    deep = tmp_path
    for part in ("a-rather-long-directory-name", "and-another-long-one", "plus-one-more"):
        deep = deep / part
    deep.mkdir(parents=True)

    config = Config(project_name="Deep")
    paths = Paths(deep, config)
    for folder in (paths.active, paths.archive, paths.done):
        folder.mkdir(parents=True, exist_ok=True)
    config.dump(paths.config_file)
    (paths.active / "broken.yaml").write_text("tasks: [oops\n", encoding="utf-8")

    monkeypatch.chdir(deep)
    result = runner.invoke(app, ["validate"])
    combined = " ".join(f"{result.stdout}\n{result.stderr}".split())

    assert result.exit_code == 1
    assert "broken.yaml" in combined
