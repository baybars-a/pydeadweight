"""Stage 6: parse the project manifest into DeclaredDependency records.

Supported manifests, in priority order:

1. ``pyproject.toml`` PEP 621 (``[project] dependencies`` + optional groups)
2. ``pyproject.toml`` Poetry (``[tool.poetry.dependencies]`` + groups)
3. ``requirements*.txt`` fallback when no pyproject exists

Specifier parsing is delegated to ``packaging`` — never hand-rolled.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from .models import DeclaredDependency


class ManifestError(Exception):
    """Raised when no manifest is found or it cannot be parsed."""


# requirements*.txt names we treat as dev/optional rather than main.
_DEV_HINTS = ("dev", "test", "tests", "lint", "ci", "docs")


def parse_manifest(project_path: Path) -> list[DeclaredDependency]:
    """Locate and parse the manifest, returning merged dependency records.

    A dependency appearing in several groups yields a single record carrying
    all its group memberships.
    """
    pyproject = project_path / "pyproject.toml"
    if pyproject.is_file():
        deps = _parse_pyproject(pyproject)
        if deps is not None:
            return deps

    req_files = _find_requirements_files(project_path)
    if req_files:
        return _parse_requirements(req_files, project_path)

    # No static dependency list anywhere. If pyproject declares dynamic
    # dependencies, say so explicitly rather than silently reporting an empty
    # set (which would make every installed dep look unused/unknown).
    if pyproject.is_file() and _declares_dynamic_deps(pyproject):
        raise ManifestError(
            'pyproject.toml declares dynamic dependencies ([project] dynamic = '
            '["dependencies"]); pydeadweight cannot read them statically and '
            "found no requirements*.txt fallback. Generate a static dependency "
            "list (e.g. via your build backend) or add a requirements file."
        )

    raise ManifestError(
        f"no manifest found in {project_path} "
        "(looked for pyproject.toml and requirements*.txt)"
    )


def _declares_dynamic_deps(path: Path) -> bool:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    dynamic = data.get("project", {}).get("dynamic")
    return isinstance(dynamic, list) and "dependencies" in dynamic


# --------------------------------------------------------------------------
# pyproject.toml
# --------------------------------------------------------------------------


def _parse_pyproject(path: Path) -> list[DeclaredDependency] | None:
    """Parse a pyproject.toml. Returns None if it declares no dependencies
    in any recognized layout (so the caller can fall back to requirements)."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"could not parse {path}: {exc}") from exc

    project_name = _project_name(data)
    accum: dict[str, set[str]] = {}
    raw_specs: dict[str, str] = {}
    found_any = False

    project = data.get("project")
    if isinstance(project, dict):
        # PEP 621 main dependencies
        main = project.get("dependencies")
        if isinstance(main, list):
            found_any = True
            _ingest_pep621(main, "main", accum, raw_specs, project_name)
        # PEP 621 optional-dependencies: each key is a named group
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            found_any = True
            for group, specs in optional.items():
                if isinstance(specs, list):
                    _ingest_pep621(specs, group, accum, raw_specs, project_name)

    poetry = data.get("tool", {}).get("poetry")
    if isinstance(poetry, dict):
        found_any = _ingest_poetry(poetry, accum, raw_specs, project_name) or found_any

    if not found_any:
        return None

    return _build_records(accum, raw_specs)


def _project_name(data: dict) -> str | None:
    name = data.get("project", {}).get("name")
    if name is None:
        name = data.get("tool", {}).get("poetry", {}).get("name")
    return canonicalize_name(name) if isinstance(name, str) else None


def _ingest_pep621(
    specs: list,
    group: str,
    accum: dict[str, set[str]],
    raw_specs: dict[str, str],
    project_name: str | None,
) -> None:
    for spec in specs:
        if not isinstance(spec, str):
            continue
        try:
            req = Requirement(spec)
        except InvalidRequirement:
            continue
        name = canonicalize_name(req.name)
        if _is_self_or_local(name, spec, project_name):
            continue
        accum.setdefault(name, set()).add(group)
        raw_specs.setdefault(name, spec)


def _ingest_poetry(
    poetry: dict,
    accum: dict[str, set[str]],
    raw_specs: dict[str, str],
    project_name: str | None,
) -> bool:
    found = False
    main = poetry.get("dependencies")
    if isinstance(main, dict):
        found = True
        _ingest_poetry_table(main, "main", accum, raw_specs, project_name)

    # Legacy dev-dependencies table
    legacy_dev = poetry.get("dev-dependencies")
    if isinstance(legacy_dev, dict):
        found = True
        _ingest_poetry_table(legacy_dev, "dev", accum, raw_specs, project_name)

    # [tool.poetry.group.<name>.dependencies]
    groups = poetry.get("group")
    if isinstance(groups, dict):
        for group_name, group_data in groups.items():
            if isinstance(group_data, dict):
                table = group_data.get("dependencies")
                if isinstance(table, dict):
                    found = True
                    _ingest_poetry_table(
                        table, group_name, accum, raw_specs, project_name
                    )
    return found


def _ingest_poetry_table(
    table: dict,
    group: str,
    accum: dict[str, set[str]],
    raw_specs: dict[str, str],
    project_name: str | None,
) -> None:
    for raw_name, constraint in table.items():
        if raw_name.lower() == "python":
            continue  # Poetry's python version pin, not a dependency
        # Skip local path / editable installs.
        if isinstance(constraint, dict) and ("path" in constraint or "url" in constraint):
            continue
        name = canonicalize_name(raw_name)
        if project_name is not None and name == project_name:
            continue
        accum.setdefault(name, set()).add(group)
        raw_specs.setdefault(name, raw_name)


# --------------------------------------------------------------------------
# requirements*.txt
# --------------------------------------------------------------------------


def _find_requirements_files(project_path: Path) -> list[Path]:
    return sorted(p for p in project_path.glob("requirements*.txt") if p.is_file())


def _parse_requirements(
    files: list[Path], project_path: Path
) -> list[DeclaredDependency]:
    accum: dict[str, set[str]] = {}
    raw_specs: dict[str, str] = {}

    for file in files:
        group = _requirements_group(file.name)
        try:
            lines = file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ManifestError(f"could not read {file}: {exc}") from exc
        for line in lines:
            spec = _clean_requirement_line(line)
            if spec is None:
                continue
            try:
                req = Requirement(spec)
            except InvalidRequirement:
                continue
            name = canonicalize_name(req.name)
            accum.setdefault(name, set()).add(group)
            raw_specs.setdefault(name, line.strip())

    if not accum:
        raise ManifestError("requirements file(s) found but declared no dependencies")
    return _build_records(accum, raw_specs)


def _requirements_group(filename: str) -> str:
    stem = filename[: -len(".txt")] if filename.endswith(".txt") else filename
    lowered = stem.lower()
    for hint in _DEV_HINTS:
        if hint in lowered and lowered != "requirements":
            return "dev"
    return "main"


def _clean_requirement_line(line: str) -> str | None:
    """Return a parseable requirement string, or None to skip the line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    # Strip inline comments (only when preceded by whitespace, per pip).
    if " #" in stripped:
        stripped = stripped.split(" #", 1)[0].strip()
    # Skip options, includes, and editable/local installs.
    if stripped.startswith("-"):
        return None
    if stripped.startswith(("git+", "http://", "https://", ".", "/")):
        return None
    return stripped or None


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _is_self_or_local(name: str, spec: str, project_name: str | None) -> bool:
    if project_name is not None and name == project_name:
        return True
    if "@" in spec and ("file://" in spec or spec.strip().endswith(".")):
        return True
    return False


def _build_records(
    accum: dict[str, set[str]], raw_specs: dict[str, str]
) -> list[DeclaredDependency]:
    records = [
        DeclaredDependency(
            name=name,
            raw_spec=raw_specs.get(name, name),
            groups=tuple(sorted(groups)),
        )
        for name, groups in accum.items()
    ]
    records.sort(key=lambda d: d.name)
    return records
