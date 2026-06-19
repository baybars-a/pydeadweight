"""Orchestrates the read-only analysis pipeline end to end.

Kept separate from the CLI so it can be driven directly from tests.
"""

from __future__ import annotations

from pathlib import Path

from .classifier import classify
from .config import Config
from .discovery import discover_sources
from .extractor import extract_imports
from .manifest import parse_manifest
from .models import Status
from .report import AnalysisResult
from .resolution import build_resolution, filter_stdlib


class ProjectError(Exception):
    """Raised for unrecoverable project-level problems (exit code 3)."""


def analyze(project_path: Path, config: Config) -> AnalysisResult:
    """Run manifest parse + discovery + extraction + classification."""
    declared = parse_manifest(project_path)

    if not config.include_dev:
        # Keep only deps that belong to the main group; drop dev/optional-only.
        declared = [d for d in declared if "main" in d.groups]

    files = discover_sources(project_path, config.exclude)
    imports, skipped = extract_imports(files)

    if files and not imports and skipped and len(skipped) == len(files):
        raise ProjectError(
            "every source file failed to parse; cannot analyze the project"
        )

    used_modules = filter_stdlib({imp.module for imp in imports})
    resolution = build_resolution()

    classifications = classify(declared, used_modules, resolution, config)

    environment_complete = not any(
        c.status is Status.UNKNOWN
        and "not installed" in c.reason
        for c in classifications
    )

    return AnalysisResult(
        classifications=classifications,
        skipped_files=skipped,
        files_analyzed=len(files),
        environment_complete=environment_complete,
    )
