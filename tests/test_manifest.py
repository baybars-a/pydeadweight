"""Unit tests for the manifest parser."""

from pathlib import Path

import pytest

from pydeadweight.manifest import ManifestError, parse_manifest


def _names(deps):
    return {d.name for d in deps}


def test_pep621_main_and_optional(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "myproj"
dependencies = ["requests>=2.28,<3", "Flask-SQLAlchemy"]

[project.optional-dependencies]
dev = ["pytest", "requests"]
""",
        encoding="utf-8",
    )
    deps = parse_manifest(tmp_path)
    names = _names(deps)
    assert names == {"requests", "flask-sqlalchemy", "pytest"}
    # requests appears in both main and dev groups -> merged record.
    requests = next(d for d in deps if d.name == "requests")
    assert set(requests.groups) == {"main", "dev"}


def test_canonicalization(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="p"\ndependencies=["Flask_SQLAlchemy"]\n',
        encoding="utf-8",
    )
    deps = parse_manifest(tmp_path)
    assert _names(deps) == {"flask-sqlalchemy"}


def test_self_name_skipped(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="myproj"\ndependencies=["myproj", "requests"]\n',
        encoding="utf-8",
    )
    assert _names(parse_manifest(tmp_path)) == {"requests"}


def test_environment_marker_preserved_in_raw_spec(tmp_path: Path):
    spec = 'importlib-metadata; python_version < "3.8"'
    # Use a single-quoted TOML string since the spec contains double quotes.
    (tmp_path / "pyproject.toml").write_text(
        f"[project]\nname='p'\ndependencies=['{spec}']\n", encoding="utf-8"
    )
    deps = parse_manifest(tmp_path)
    d = deps[0]
    assert d.name == "importlib-metadata"
    assert d.raw_spec == spec


def test_poetry_layout(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "myproj"

[tool.poetry.dependencies]
python = "^3.11"
requests = "^2.28"

[tool.poetry.group.dev.dependencies]
pytest = "^7.0"
""",
        encoding="utf-8",
    )
    deps = parse_manifest(tmp_path)
    assert _names(deps) == {"requests", "pytest"}
    # python pin must not be treated as a dependency
    assert "python" not in _names(deps)


def test_requirements_fallback(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "requests==2.31.0\n# a comment\n-r other.txt\nclick>=8\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
    deps = parse_manifest(tmp_path)
    assert _names(deps) == {"requests", "click", "pytest"}
    pytest_dep = next(d for d in deps if d.name == "pytest")
    assert pytest_dep.groups == ("dev",)


def test_requirements_skips_urls_and_editable(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "-e .\ngit+https://example.com/x.git\nhttps://example.com/y.whl\nrequests\n",
        encoding="utf-8",
    )
    assert _names(parse_manifest(tmp_path)) == {"requests"}


def test_no_manifest_raises(tmp_path: Path):
    with pytest.raises(ManifestError):
        parse_manifest(tmp_path)


def test_pyproject_without_deps_falls_back_to_requirements(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires=["hatchling"]\n', encoding="utf-8"
    )
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    assert _names(parse_manifest(tmp_path)) == {"requests"}
