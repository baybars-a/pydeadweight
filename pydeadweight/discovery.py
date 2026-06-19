"""Stage 7: discover the ``.py`` files to analyze.

Excludes VCS dirs, virtualenvs, build artifacts, anything matched by the
project's ``.gitignore``, and user-configured glob excludes. Test files are
*not* excluded by default — a dependency used only in tests is still used.
"""

from __future__ import annotations

from pathlib import Path

import pathspec

# Directory names pruned during traversal regardless of .gitignore.
_PRUNE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        ".env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".nox",
        "build",
        "dist",
        ".eggs",
        "node_modules",
    }
)


def discover_sources(
    project_path: Path, exclude_globs: tuple[str, ...] = ()
) -> list[Path]:
    """Return the sorted list of ``.py`` files under ``project_path``."""
    project_path = project_path.resolve()
    gitignore = _load_gitignore(project_path)
    user_spec = (
        pathspec.PathSpec.from_lines("gitwildmatch", exclude_globs)
        if exclude_globs
        else None
    )

    results: list[Path] = []
    _walk(project_path, project_path, gitignore, user_spec, results, set())
    results.sort()
    return results


def _walk(
    root: Path,
    current: Path,
    gitignore: pathspec.PathSpec | None,
    user_spec: pathspec.PathSpec | None,
    out: list[Path],
    visited: set[tuple[int, int]],
) -> None:
    # Guard against symlink cycles (and re-entry via hard links): track the
    # real (device, inode) of each directory we descend into.
    try:
        st = current.stat()
        key = (st.st_dev, st.st_ino)
    except OSError:
        return
    if key in visited:
        return
    visited.add(key)

    try:
        entries = sorted(current.iterdir())
    except (OSError, PermissionError):
        return

    for entry in entries:
        rel = entry.relative_to(root).as_posix()
        if entry.is_dir():
            if entry.name in _PRUNE_DIRS or entry.name.endswith(".egg-info"):
                continue
            if _ignored(gitignore, rel + "/") or _ignored(user_spec, rel + "/"):
                continue
            # The visited-set inside _walk breaks symlink cycles while still
            # following non-cyclic symlinked directories as before.
            _walk(root, entry, gitignore, user_spec, out, visited)
        elif entry.is_file() and entry.suffix == ".py":
            if _ignored(gitignore, rel) or _ignored(user_spec, rel):
                continue
            out.append(entry)


def _ignored(spec: pathspec.PathSpec | None, rel_path: str) -> bool:
    return spec is not None and spec.match_file(rel_path)


def _load_gitignore(project_path: Path) -> pathspec.PathSpec | None:
    gitignore = project_path / ".gitignore"
    if not gitignore.is_file():
        return None
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)
