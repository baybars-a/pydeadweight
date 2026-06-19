"""Stage 13: remove dependencies from the manifest, preserving formatting.

pyproject.toml is edited with ``tomlkit`` so comments, ordering, and style
survive untouched except for the removed entries. requirements*.txt is edited
line-wise, leaving comments and unrelated lines intact.

Lockfiles are never regenerated automatically in v1 — detecting which manager
owns the lock is brittle. We only surface the command the user should run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


@dataclass(frozen=True)
class Removal:
    """A single applied removal, for the diff summary."""

    name: str
    location: str  # e.g. "project.dependencies" or "requirements-dev.txt"
    line: str  # the removed text


@dataclass(frozen=True)
class FileEdit:
    """One file to rewrite. ``new_content`` is normalized to ``\\n``; ``newline``
    is the line ending the original used, applied verbatim on write."""

    path: Path
    new_content: str
    newline: str
    removals: list[Removal]


@dataclass(frozen=True)
class WriteResult:
    edits: list[FileEdit]
    lockfile_hint: str | None

    # Backwards-compatible convenience views over the (possibly multiple) edits.
    @property
    def removals(self) -> list[Removal]:
        return [r for e in self.edits for r in e.removals]

    @property
    def manifest_path(self) -> Path | None:
        return self.edits[0].path if self.edits else None

    @property
    def new_content(self) -> str | None:
        return self.edits[0].new_content if self.edits else None


def _detect_newline(data: bytes) -> str:
    return "\r\n" if b"\r\n" in data else "\n"


def plan_removals(
    project_path: Path, names_to_remove: set[str]
) -> WriteResult:
    """Compute the edited manifest(s) without writing. Pure; safe for dry-run."""
    targets = {canonicalize_name(n) for n in names_to_remove}
    pyproject = project_path / "pyproject.toml"
    if pyproject.is_file():
        return _plan_pyproject(pyproject, targets, project_path)

    req_files = sorted(p for p in project_path.glob("requirements*.txt") if p.is_file())
    if req_files:
        # Edit *every* requirements file, so a dep declared in
        # requirements-dev.txt is actually removed, not silently skipped.
        edits = [_plan_requirements_file(f, targets) for f in req_files]
        edits = [e for e in edits if e.removals]
        return WriteResult(edits=edits, lockfile_hint=None)

    raise FileNotFoundError(f"no manifest found in {project_path}")


def apply(result: WriteResult) -> None:
    """Write each planned edit to disk atomically (temp file + replace).

    A failure mid-write leaves the original file intact rather than truncated.
    """
    for edit in result.edits:
        if not edit.removals:
            continue
        data = edit.new_content.replace("\n", edit.newline).encode("utf-8")
        tmp = edit.path.with_name(edit.path.name + ".pydeadweight.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, edit.path)
        except OSError:
            # Clean up the temp file; the original is untouched.
            try:
                tmp.unlink()
            except OSError:
                pass
            raise


# --------------------------------------------------------------------------
# pyproject.toml
# --------------------------------------------------------------------------


def _plan_pyproject(
    path: Path, targets: set[str], project_path: Path
) -> WriteResult:
    raw = path.read_bytes()
    newline = _detect_newline(raw)
    doc = tomlkit.parse(raw.decode("utf-8"))
    removals: list[Removal] = []

    project = doc.get("project")
    if project is not None:
        if "dependencies" in project:
            _strip_pep621_array(
                project["dependencies"], targets, "project.dependencies", removals
            )
        optional = project.get("optional-dependencies")
        if optional is not None:
            for group in list(optional.keys()):
                _strip_pep621_array(
                    optional[group],
                    targets,
                    f"project.optional-dependencies.{group}",
                    removals,
                )

    poetry = doc.get("tool", {}).get("poetry") if "tool" in doc else None
    if poetry is not None:
        if "dependencies" in poetry:
            _strip_poetry_table(
                poetry["dependencies"],
                targets,
                "tool.poetry.dependencies",
                removals,
            )
        if "dev-dependencies" in poetry:
            _strip_poetry_table(
                poetry["dev-dependencies"],
                targets,
                "tool.poetry.dev-dependencies",
                removals,
            )
        groups = poetry.get("group")
        if groups is not None:
            for gname in list(groups.keys()):
                gtable = groups[gname]
                if "dependencies" in gtable:
                    _strip_poetry_table(
                        gtable["dependencies"],
                        targets,
                        f"tool.poetry.group.{gname}.dependencies",
                        removals,
                    )

    # Normalize to \n; apply() converts back to the file's original newline.
    content = tomlkit.dumps(doc).replace("\r\n", "\n")
    edit = FileEdit(
        path=path, new_content=content, newline=newline, removals=removals
    )
    return WriteResult(edits=[edit], lockfile_hint=_lockfile_hint(project_path))


def _strip_pep621_array(
    array, targets: set[str], location: str, removals: list[Removal]
) -> None:
    # Delete matching items in place (in reverse, so indices stay valid).
    # This preserves inline comments and formatting on the items we keep,
    # which rebuilding the array would destroy.
    to_delete: list[int] = []
    for index, item in enumerate(array):
        spec = str(item)
        name = _spec_name(spec)
        if name is not None and name in targets:
            removals.append(Removal(name=name, location=location, line=spec))
            to_delete.append(index)
    for index in reversed(to_delete):
        del array[index]


def _strip_poetry_table(
    table, targets: set[str], location: str, removals: list[Removal]
) -> None:
    for raw_name in list(table.keys()):
        if raw_name.lower() == "python":
            continue
        if canonicalize_name(raw_name) in targets:
            removals.append(
                Removal(name=canonicalize_name(raw_name), location=location, line=raw_name)
            )
            del table[raw_name]


# --------------------------------------------------------------------------
# requirements*.txt
# --------------------------------------------------------------------------


def _plan_requirements_file(path: Path, targets: set[str]) -> FileEdit:
    raw = path.read_bytes()
    newline = _detect_newline(raw)
    # Normalize to \n internally; apply() restores the original newline.
    original = raw.decode("utf-8").replace("\r\n", "\n")
    out_lines: list[str] = []
    removals: list[Removal] = []

    for line in original.splitlines(keepends=True):
        name = _requirement_line_name(line)
        if name is not None and name in targets:
            removals.append(
                Removal(name=name, location=path.name, line=line.rstrip("\n"))
            )
            continue
        out_lines.append(line)

    return FileEdit(
        path=path,
        new_content="".join(out_lines),
        newline=newline,
        removals=removals,
    )


def _requirement_line_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("-"):
        return None
    if " #" in stripped:
        stripped = stripped.split(" #", 1)[0].strip()
    return _spec_name(stripped)


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _spec_name(spec: str) -> str | None:
    try:
        return canonicalize_name(Requirement(spec).name)
    except InvalidRequirement:
        return None


def _lockfile_hint(project_path: Path) -> str | None:
    if (project_path / "uv.lock").is_file():
        return "uv lock"
    if (project_path / "poetry.lock").is_file():
        return "poetry lock"
    if (project_path / "requirements.in").is_file():
        return "pip-compile requirements.in"
    return None


def format_diff(result: WriteResult, show_lockfile_hint: bool = True) -> str:
    if not result.removals:
        return "No changes: nothing to remove."
    lines: list[str] = []
    for edit in result.edits:
        if not edit.removals:
            continue
        lines.append(f"Changes to {edit.path.name}:")
        for r in edit.removals:
            lines.append(f"  - {r.line}    ({r.location})")
    if show_lockfile_hint and result.lockfile_hint:
        lines.append("")
        lines.append(
            f"Lockfile not modified. To regenerate it, run: {result.lockfile_hint}"
        )
    return "\n".join(lines)
