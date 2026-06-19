"""Stage 9: resolve distribution names <-> import names.

Distribution names and import names differ: you ``pip install Pillow`` but
``import PIL``. We do not guess or hardcode this mapping — we read it from
installed package metadata via ``importlib.metadata.packages_distributions``.

Consequence: pydeadweight must run inside the project's installed environment.
A declared dependency that isn't installed has no metadata, so its import name
is unknowable here and it is classified ``unknown`` (never ``unused``).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from importlib.metadata import packages_distributions

from packaging.utils import canonicalize_name


@dataclass(frozen=True)
class Resolution:
    """The metadata-derived view of the current environment."""

    dist_to_imports: dict[str, frozenset[str]]
    """Canonical distribution name -> import names it provides."""

    installed_dists: frozenset[str]
    """Canonical names of all installed distributions."""


def build_resolution() -> Resolution:
    """Invert ``packages_distributions()`` into a dist -> imports mapping."""
    import_to_dists = packages_distributions()
    dist_to_imports: dict[str, set[str]] = {}
    installed: set[str] = set()

    for import_name, dists in import_to_dists.items():
        for dist in dists:
            canon = canonicalize_name(dist)
            installed.add(canon)
            dist_to_imports.setdefault(canon, set()).add(import_name)

    return Resolution(
        dist_to_imports={k: frozenset(v) for k, v in dist_to_imports.items()},
        installed_dists=frozenset(installed),
    )


def filter_stdlib(modules: set[str]) -> set[str]:
    """Drop standard-library modules; they are never dependencies."""
    return {m for m in modules if m not in sys.stdlib_module_names}
