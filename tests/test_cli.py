"""CLI / exit-code tests and an end-to-end golden run.

Resolution is monkeypatched so the test does not depend on which packages are
installed in the environment running the suite.
"""

from pathlib import Path

import pytest

from pydeadweight import cli, pipeline
from pydeadweight.resolution import Resolution


@pytest.fixture
def fake_resolution(monkeypatch):
    """Pretend requests, Pillow, and gunicorn are installed."""

    def _build():
        return Resolution(
            dist_to_imports={
                "requests": frozenset({"requests"}),
                "pillow": frozenset({"PIL"}),
                "gunicorn": frozenset({"gunicorn"}),
                "click": frozenset({"click"}),
            },
            installed_dists=frozenset({"requests", "pillow", "gunicorn", "click"}),
        )

    monkeypatch.setattr(pipeline, "build_resolution", _build)


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"
dependencies = ["requests", "Pillow", "gunicorn", "click"]
""",
        encoding="utf-8",
    )
    src = tmp_path / "demo"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    # Uses requests and PIL (Pillow). gunicorn unused-but-runtime-only.
    # click is genuinely unused.
    (src / "app.py").write_text(
        "import requests\nfrom PIL import Image\n", encoding="utf-8"
    )
    return tmp_path


def test_check_reports_unused(tmp_path, fake_resolution, capsys):
    project = _make_project(tmp_path)
    code = cli.main(["check", str(project), "--verbose"])
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    # click is unused; gunicorn rescued by runtime-only; requests/Pillow used.
    assert "Unused dependencies (1)" in out
    assert "click" in out


def test_fail_on_unused_exit_code(tmp_path, fake_resolution):
    project = _make_project(tmp_path)
    code = cli.main(["check", str(project), "--fail-on-unused"])
    assert code == cli.EXIT_UNUSED_FOUND


def test_json_output(tmp_path, fake_resolution, capsys):
    import json

    project = _make_project(tmp_path)
    cli.main(["check", str(project), "--json"])
    payload = json.loads(capsys.readouterr().out)
    statuses = {d["name"]: d["status"] for d in payload["dependencies"]}
    assert statuses["requests"] == "used"
    assert statuses["pillow"] == "used"
    assert statuses["gunicorn"] == "used"
    assert statuses["click"] == "unused"


def test_ignore_flag(tmp_path, fake_resolution):
    project = _make_project(tmp_path)
    # Ignoring click makes the project clean -> fail-on-unused passes.
    code = cli.main(["check", str(project), "--ignore", "click", "--fail-on-unused"])
    assert code == cli.EXIT_OK


def test_clean_refuses_without_flag(tmp_path, fake_resolution, capsys):
    project = _make_project(tmp_path)
    code = cli.main(["clean", str(project)])
    err = capsys.readouterr().err
    assert code == cli.EXIT_USAGE
    assert "--dry-run" in err or "--yes" in err


def test_clean_dry_run_writes_nothing(tmp_path, fake_resolution):
    project = _make_project(tmp_path)
    original = (project / "pyproject.toml").read_text(encoding="utf-8")
    code = cli.main(["clean", str(project), "--dry-run"])
    assert code == cli.EXIT_OK
    assert (project / "pyproject.toml").read_text(encoding="utf-8") == original


def test_clean_yes_removes_unused(tmp_path, fake_resolution):
    project = _make_project(tmp_path)
    code = cli.main(["clean", str(project), "--yes"])
    assert code == cli.EXIT_OK
    new = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert "click" not in new
    # used and runtime-only deps stay.
    assert "requests" in new
    assert "gunicorn" in new
    assert "Pillow" in new


def test_no_manifest_exit_code(tmp_path, fake_resolution):
    code = cli.main(["check", str(tmp_path)])
    assert code == cli.EXIT_PROJECT


def test_bad_path_usage_error(fake_resolution):
    code = cli.main(["check", "/no/such/dir/here/xyz"])
    assert code == cli.EXIT_USAGE
