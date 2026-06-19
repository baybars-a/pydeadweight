"""Output stage: render classifications as human text or JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .models import Classification, SkippedFile, Status


@dataclass(frozen=True)
class AnalysisResult:
    """Everything the reporter and CLI need after the pipeline runs."""

    classifications: list[Classification]
    skipped_files: list[SkippedFile]
    files_analyzed: int
    environment_complete: bool
    """False if any dependency landed in ``unknown`` due to not being installed."""

    @property
    def unused(self) -> list[Classification]:
        return [c for c in self.classifications if c.status is Status.UNUSED]

    @property
    def unknown(self) -> list[Classification]:
        return [c for c in self.classifications if c.status is Status.UNKNOWN]

    @property
    def used(self) -> list[Classification]:
        return [c for c in self.classifications if c.status is Status.USED]


def render_human(result: AnalysisResult, verbose: bool) -> str:
    lines: list[str] = []
    unused = result.unused
    unknown = result.unknown

    lines.append(
        f"Analyzed {result.files_analyzed} source file(s); "
        f"{len(result.classifications)} declared dependencies."
    )
    lines.append("")

    if unused:
        lines.append(f"Unused dependencies ({len(unused)}):")
        for c in sorted(unused, key=lambda x: x.dependency.name):
            groups = ", ".join(c.dependency.groups)
            lines.append(f"  [unused] {c.dependency.name}  ({groups})")
            if verbose:
                lines.append(f"      {c.reason}")
    else:
        lines.append("No unused dependencies found.")
    lines.append("")

    if unknown:
        lines.append(f"Unknown ({len(unknown)}) - could not be determined statically:")
        for c in sorted(unknown, key=lambda x: x.dependency.name):
            lines.append(f"  ? {c.dependency.name}")
            if verbose:
                lines.append(f"      {c.reason}")
        lines.append("")

    if verbose and result.used:
        lines.append(f"Used ({len(result.used)}):")
        for c in sorted(result.used, key=lambda x: x.dependency.name):
            lines.append(f"  [used]   {c.dependency.name} - {c.reason}")
        lines.append("")

    if result.skipped_files:
        lines.append(f"Skipped {len(result.skipped_files)} unparseable file(s):")
        if verbose:
            for s in result.skipped_files:
                lines.append(f"  ! {s.path}: {s.error}")
        else:
            lines.append("  (re-run with --verbose to list them)")
        lines.append("")

    if not result.environment_complete:
        lines.append(
            "WARNING: some dependencies are not installed in the current "
            "environment, so they could not be analyzed and were marked "
            "'unknown'. Run pydeadweight inside the project's virtualenv "
            "(where its dependencies are installed) for accurate results."
        )

    return "\n".join(lines).rstrip() + "\n"


def render_json(result: AnalysisResult) -> str:
    payload = {
        "files_analyzed": result.files_analyzed,
        "environment_complete": result.environment_complete,
        "summary": {
            "used": len(result.used),
            "unused": len(result.unused),
            "unknown": len(result.unknown),
        },
        "dependencies": [
            {
                "name": c.dependency.name,
                "status": c.status.value,
                "groups": list(c.dependency.groups),
                "reason": c.reason,
                "matched_imports": list(c.matched_imports),
                "raw_spec": c.dependency.raw_spec,
            }
            for c in sorted(result.classifications, key=lambda x: x.dependency.name)
        ],
        "skipped_files": [
            {"path": s.path, "error": s.error} for s in result.skipped_files
        ],
    }
    return json.dumps(payload, indent=2)
