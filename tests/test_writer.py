"""Writer round-trip tests: removal must be surgical and style-preserving."""

from pathlib import Path

from pydeadweight.writer import apply, format_diff, plan_removals

PYPROJECT = """\
[project]
name = "demo"
# core runtime deps
dependencies = [
    "requests>=2.28",  # http client
    "click",
    "rich",
]

[project.optional-dependencies]
dev = ["pytest", "rich"]
"""


def test_removes_from_all_groups_and_preserves_comments(tmp_path: Path):
    path = tmp_path / "pyproject.toml"
    path.write_text(PYPROJECT, encoding="utf-8")

    plan = plan_removals(tmp_path, {"rich"})
    apply(plan)

    new = path.read_text(encoding="utf-8")
    # Comments and untouched deps survive.
    assert "# core runtime deps" in new
    assert "# http client" in new
    assert '"requests>=2.28"' in new
    assert '"click"' in new
    # rich is gone from both main and dev.
    assert "rich" not in new
    # pytest (dev) untouched.
    assert "pytest" in new
    assert len(plan.removals) == 2


def test_dry_run_does_not_write(tmp_path: Path):
    path = tmp_path / "pyproject.toml"
    path.write_text(PYPROJECT, encoding="utf-8")
    plan = plan_removals(tmp_path, {"click"})
    # We simply don't call apply() in a dry run.
    assert path.read_text(encoding="utf-8") == PYPROJECT
    assert any(r.name == "click" for r in plan.removals)


def test_requirements_line_removal_preserves_rest(tmp_path: Path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# top comment\nrequests==2.31.0\nclick>=8  # cli\nrich\n", encoding="utf-8"
    )
    plan = plan_removals(tmp_path, {"click"})
    apply(plan)
    new = req.read_text(encoding="utf-8")
    assert "# top comment" in new
    assert "requests==2.31.0" in new
    assert "rich" in new
    assert "click" not in new


def test_format_diff_mentions_removals(tmp_path: Path):
    path = tmp_path / "pyproject.toml"
    path.write_text(PYPROJECT, encoding="utf-8")
    plan = plan_removals(tmp_path, {"click"})
    diff = format_diff(plan)
    assert "click" in diff
