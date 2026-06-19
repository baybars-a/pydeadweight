"""Typed records passed between pipeline stages.

Stages communicate via these frozen dataclasses, not loose dicts. No stage
reads another stage's internals; everything it needs is on the record.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    USED = "used"
    UNUSED = "unused"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeclaredDependency:
    """A single dependency as declared in the manifest.

    ``name`` is the canonical distribution name (see
    ``packaging.utils.canonicalize_name``). ``raw_spec`` keeps the full
    original specifier string so the cleanup writer can match the exact line.
    ``groups`` records every dependency group the entry appeared in.
    """

    name: str
    raw_spec: str
    groups: tuple[str, ...]


@dataclass(frozen=True)
class ImportName:
    """A top-level imported module name with provenance for --verbose."""

    module: str
    source_file: str


@dataclass(frozen=True)
class SkippedFile:
    """A source file that could not be parsed."""

    path: str
    error: str


@dataclass(frozen=True)
class Classification:
    """The verdict for one declared dependency."""

    dependency: DeclaredDependency
    status: Status
    reason: str
    matched_imports: tuple[str, ...] = ()
