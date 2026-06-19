"""Regression tests for audit findings F1-F8, F12, F13.

Each test encodes the *correct* behavior and was written to fail against the
pre-fix code. They read real files from disk where the original bug lived in
the file-handling layer (not the pure string helpers).
"""

import sys
from pathlib import Path

import pytest

from pydeadweight import cli, pipeline
from pydeadweight.classifier import classify
from pydeadweight.config import Config
from pydeadweight.discovery import discover_sources
from pydeadweight.extractor import extract_imports
from pydeadweight.manifest import parse_manifest
from pydeadweight.models import DeclaredDependency, Status
from pydeadweight.resolution import Resolution
from pydeadweight.writer import apply, plan_removals


# --------------------------------------------------------------------------
# F1: UTF-8 BOM source file must not be skipped.
# --------------------------------------------------------------------------


def test_f1_bom_file_is_parsed(tmp_path: Path):
    f = tmp_path / "mod.py"
    # UTF-8 BOM followed by a real import (how Windows editors often save).
    f.write_bytes(b"\xef\xbb\xbfimport requests\n")
    imports, skipped = extract_imports([f])
    assert skipped == [], f"BOM file was skipped: {skipped}"
    assert {imp.module for imp in imports} == {"requests"}


def test_f1_coding_cookie_latin1_is_parsed(tmp_path: Path):
    f = tmp_path / "mod.py"
    # PEP 263 coding declaration with a non-UTF-8 byte in a comment.
    f.write_bytes(b"# -*- coding: latin-1 -*-\n# \xe9\nimport click\n")
    imports, skipped = extract_imports([f])
    assert skipped == []
    assert {imp.module for imp in imports} == {"click"}


# --------------------------------------------------------------------------
# F2: a skipped file must not silently produce a deletable "unused" verdict.
# clean must surface skipped files even without --verbose.
# --------------------------------------------------------------------------


def test_f2_clean_warns_when_files_skipped(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="demo"\ndependencies=["requests"]\n', encoding="utf-8"
    )
    # A file the running interpreter cannot parse (broken syntax stands in for
    # "syntax newer than the analyzer"). It is the *only* place requests is used.
    (tmp_path / "app.py").write_text("import requests\ndef (:\n", encoding="utf-8")
    # A second, parseable file so the run isn't an all-files-failed abort.
    (tmp_path / "ok.py").write_text("import os\n", encoding="utf-8")

    def _res():
        return Resolution(
            dist_to_imports={"requests": frozenset({"requests"})},
            installed_dists=frozenset({"requests"}),
        )

    monkeypatch.setattr(pipeline, "build_resolution", _res)
    code = cli.main(["clean", str(tmp_path), "--dry-run"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_OK
    # The skip must be announced on the error stream, not hidden behind verbose.
    assert "could not be parsed" in err.lower() or "not counted" in err.lower()


# --------------------------------------------------------------------------
# F3: clean must remove unused deps from secondary requirements*.txt files.
# --------------------------------------------------------------------------


def test_f3_clean_removes_from_secondary_requirements(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text(
        "unused-dev-pkg\npytest\n", encoding="utf-8"
    )
    plan = plan_removals(tmp_path, {"unused-dev-pkg"})
    assert any(r.name == "unused-dev-pkg" for r in plan.removals), (
        "dep in requirements-dev.txt was not planned for removal"
    )
    apply(plan)
    assert "unused-dev-pkg" not in (
        tmp_path / "requirements-dev.txt"
    ).read_text(encoding="utf-8")
    # Untouched entries survive.
    assert "pytest" in (tmp_path / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "requests" in (tmp_path / "requirements.txt").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# F4: removing one line must not rewrite every line ending.
# --------------------------------------------------------------------------


def test_f4_lf_pyproject_stays_lf(tmp_path: Path):
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'[project]\nname="x"\ndependencies=["requests","dead"]\n')
    plan = plan_removals(tmp_path, {"dead"})
    apply(plan)
    data = path.read_bytes()
    assert b"\r\n" not in data, "LF file gained CRLF line endings"


def test_f4_crlf_pyproject_stays_crlf(tmp_path: Path):
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'[project]\r\nname="x"\r\ndependencies=["requests","dead"]\r\n')
    plan = plan_removals(tmp_path, {"dead"})
    apply(plan)
    data = path.read_bytes()
    # Original was CRLF throughout; result must not contain lone LF.
    assert data.count(b"\n") == data.count(b"\r\n"), "CRLF file lost its line endings"


# --------------------------------------------------------------------------
# F5: a write failure must not corrupt the existing manifest (atomic write).
# --------------------------------------------------------------------------


def test_f5_failed_write_preserves_original(tmp_path: Path, monkeypatch):
    path = tmp_path / "pyproject.toml"
    original = b'[project]\nname="x"\ndependencies=["requests","dead"]\n'
    path.write_bytes(original)
    plan = plan_removals(tmp_path, {"dead"})

    # Simulate a crash during the rename/replace step.
    import pydeadweight.writer as writer_mod

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(writer_mod.os, "replace", _boom)
    with pytest.raises(OSError):
        apply(plan)
    # The original manifest must be intact, not truncated.
    assert path.read_bytes() == original


# --------------------------------------------------------------------------
# F6: an installed-but-never-imported console-script package must not be
# reported as "used". It belongs in "unknown" (surfaced, not deletable).
# --------------------------------------------------------------------------


def test_f6_console_script_only_dep_is_not_used():
    # pytest is installed in the dev env and ships a console script, but here
    # it is imported nowhere.
    from pydeadweight.resolution import build_resolution

    res = build_resolution()
    dep = DeclaredDependency("pytest", "pytest", ("main",))
    out = classify([dep], set(), res, Config())
    assert out[0].status is not Status.USED, (
        f"stale console-script dep wrongly marked used: {out[0].reason}"
    )


# --------------------------------------------------------------------------
# F7: PEP 621 dynamic dependencies with no static list must be flagged, not
# silently treated as an empty dependency set.
# --------------------------------------------------------------------------


def test_f7_dynamic_dependencies_raise_or_warn(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="dyn"\ndynamic=["dependencies"]\n', encoding="utf-8"
    )
    from pydeadweight.manifest import ManifestError

    with pytest.raises(ManifestError):
        parse_manifest(tmp_path)


# --------------------------------------------------------------------------
# F8: a directory symlink cycle must not crash discovery.
# --------------------------------------------------------------------------


def test_f8_symlink_cycle_does_not_crash(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("import requests\n", encoding="utf-8")
    loop = pkg / "loop"
    try:
        loop.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported in this environment")
    # Must terminate and still find the real file.
    files = discover_sources(tmp_path)
    assert any(f.name == "a.py" for f in files)


# --------------------------------------------------------------------------
# F12: --no-lockfile must have an observable effect (suppress the lock hint).
# --------------------------------------------------------------------------


def test_f12_no_lockfile_suppresses_hint(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="d"\ndependencies=["dead"]\n', encoding="utf-8"
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "app.py").write_text("import os\n", encoding="utf-8")

    def _res():
        return Resolution(
            dist_to_imports={"dead": frozenset({"dead"})},
            installed_dists=frozenset({"dead"}),
        )

    monkeypatch.setattr(pipeline, "build_resolution", _res)
    cli.main(["clean", str(tmp_path), "--dry-run", "--no-lockfile"])
    out = capsys.readouterr().out
    assert "uv lock" not in out, "--no-lockfile did not suppress the lockfile hint"


# --------------------------------------------------------------------------
# F13: an unexpected error in the clean/write path must map to a clean exit
# code, not an uncaught traceback.
# --------------------------------------------------------------------------


def test_f13_unexpected_writer_error_is_handled(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="d"\ndependencies=["dead"]\n', encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("import os\n", encoding="utf-8")

    def _res():
        return Resolution(
            dist_to_imports={"dead": frozenset({"dead"})},
            installed_dists=frozenset({"dead"}),
        )

    monkeypatch.setattr(pipeline, "build_resolution", _res)

    import pydeadweight.cli as cli_mod

    def _boom(*a, **k):
        raise RuntimeError("unexpected tomlkit failure")

    monkeypatch.setattr(cli_mod, "plan_removals", _boom)
    code = cli.main(["clean", str(tmp_path), "--yes"])
    assert code == cli.EXIT_PROJECT
    assert "error" in capsys.readouterr().err.lower()
