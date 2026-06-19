"""Command-line interface: argparse setup, dispatch, and exit codes.

Exit codes:
  0  success (no unused, or unused found without --fail-on-unused)
  1  unused dependencies found AND --fail-on-unused set
  2  usage error (bad flags, conflicting options)
  3  project error (no manifest, unparseable manifest, all source unparseable)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load_config, merge_cli_overrides
from .manifest import ManifestError
from .pipeline import ProjectError, analyze
from .report import render_human, render_json
from .writer import apply, format_diff, plan_removals

EXIT_OK = 0
EXIT_UNUSED_FOUND = 1
EXIT_USAGE = 2
EXIT_PROJECT = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pydeadweight",
        description=(
            "Detect (and optionally remove) declared Python dependencies that "
            "the project no longer imports.\n\n"
            "IMPORTANT: run this inside the project's installed environment "
            "(the virtualenv where its dependencies are installed). Distribution"
            "-to-import name resolution reads installed package metadata; "
            "dependencies that are not installed are reported as 'unknown', "
            "never 'unused'."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- check ----------------------------------------------------------
    check = sub.add_parser("check", help="Analyze and report (read-only).")
    check.add_argument("path", nargs="?", default=".", help="Project path.")
    check.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    check.add_argument(
        "--fail-on-unused",
        action="store_true",
        help="Exit non-zero if any unused dependency is found (for CI).",
    )
    dev = check.add_mutually_exclusive_group()
    dev.add_argument(
        "--include-dev",
        dest="include_dev",
        action="store_true",
        default=None,
        help="Include dev/optional dependency groups (default).",
    )
    dev.add_argument(
        "--no-include-dev",
        dest="include_dev",
        action="store_false",
        help="Analyze only main dependencies.",
    )
    check.add_argument("--config", type=Path, help="Path to config file.")
    check.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="NAME",
        help="Treat NAME as used for this run (repeatable).",
    )
    check.add_argument(
        "-v", "--verbose", action="store_true", help="Show per-dependency reasoning."
    )

    # ---- clean ----------------------------------------------------------
    clean = sub.add_parser(
        "clean", help="Analyze, then remove unused dependencies (mutating)."
    )
    clean.add_argument("path", nargs="?", default=".", help="Project path.")
    clean.add_argument(
        "--interactive", action="store_true", help="Prompt y/n per dependency."
    )
    clean.add_argument(
        "--yes", action="store_true", help="Skip confirmation (non-interactive removal)."
    )
    clean.add_argument(
        "--dry-run", action="store_true", help="Show what would change; write nothing."
    )
    clean.add_argument(
        "--no-lockfile",
        action="store_true",
        help="Edit the manifest but do not touch the lockfile (default behavior).",
    )
    cdev = clean.add_mutually_exclusive_group()
    cdev.add_argument(
        "--include-dev", dest="include_dev", action="store_true", default=None
    )
    cdev.add_argument("--no-include-dev", dest="include_dev", action="store_false")
    clean.add_argument("--config", type=Path)
    clean.add_argument("--ignore", action="append", default=[], metavar="NAME")
    clean.add_argument("-v", "--verbose", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_path = Path(args.path).resolve()
    if not project_path.is_dir():
        print(f"error: {project_path} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    try:
        config = load_config(project_path, args.config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROJECT

    config = merge_cli_overrides(
        config,
        include_dev=args.include_dev,
        extra_ignore=tuple(args.ignore),
    )

    try:
        result = analyze(project_path, config)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROJECT
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROJECT

    if args.command == "check":
        return _run_check(args, result)
    if args.command == "clean":
        return _run_clean(args, project_path, result)
    parser.error("unknown command")  # pragma: no cover
    return EXIT_USAGE


def _run_check(args, result) -> int:
    if args.json:
        print(render_json(result))
    else:
        print(render_human(result, args.verbose), end="")

    if result.unused and args.fail_on_unused:
        return EXIT_UNUSED_FOUND
    return EXIT_OK


def _run_clean(args, project_path: Path, result) -> int:
    # Refuse to silently rewrite files.
    if not (args.interactive or args.yes or args.dry_run):
        print(
            "error: clean mutates the manifest; pass one of --dry-run, "
            "--interactive, or --yes to proceed.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # F2: a skipped (unparseable) file may hold the only import of a dep now
    # flagged unused. Never let that lead to a silent deletion — warn loudly,
    # regardless of --verbose.
    if result.skipped_files:
        print(
            f"warning: {len(result.skipped_files)} source file(s) could not be "
            "parsed; their imports were NOT counted, so a dependency flagged "
            "unused may still be used there. Review before deleting (run "
            "'pydeadweight check --verbose' to list the skipped files).",
            file=sys.stderr,
        )

    unused = result.unused
    if not unused:
        print("No unused dependencies to remove.")
        if not result.environment_complete:
            print(
                "(Note: some deps were 'unknown' because they are not installed; "
                "run inside the project venv for a complete result.)"
            )
        return EXIT_OK

    names = {c.dependency.name for c in unused}

    if args.interactive:
        names = _prompt_each(unused)
        if not names:
            print("Nothing selected for removal.")
            return EXIT_OK

    try:
        plan = plan_removals(project_path, names)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROJECT
    except Exception as exc:  # F13: don't leak a raw traceback to the user.
        print(f"error: failed to plan manifest edit: {exc}", file=sys.stderr)
        return EXIT_PROJECT

    # F12: --no-lockfile suppresses the lockfile-regeneration hint.
    print(format_diff(plan, show_lockfile_hint=not args.no_lockfile))

    if args.dry_run:
        print("\nDry run: no files were modified.")
        return EXIT_OK

    if not plan.removals:
        return EXIT_OK

    try:
        apply(plan)
    except Exception as exc:  # F13
        print(f"error: failed to write manifest: {exc}", file=sys.stderr)
        return EXIT_PROJECT
    print(f"\nRemoved {len(plan.removals)} dependency entr(ies).")
    return EXIT_OK


def _prompt_each(unused) -> set[str]:
    selected: set[str] = set()
    for c in sorted(unused, key=lambda x: x.dependency.name):
        groups = ", ".join(c.dependency.groups)
        try:
            answer = input(f"Remove {c.dependency.name} [{groups}]? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"
        if answer in ("y", "yes"):
            selected.add(c.dependency.name)
    return selected


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
