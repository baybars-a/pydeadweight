"""Stage 10: classify each declared dependency and apply the convention layer.

Buckets:
  used    - at least one import name the distribution provides was imported.
  unused  - installed, import names known, none imported anywhere.
  unknown - not installed (import name unresolvable), or provides no importable
            top-level module.

The convention layer runs *before* a dep is finalized as unused. Any match
downgrades it to ``used`` with a recorded reason, so static-analysis blind
spots (CLIs, runtime backends, dynamically loaded packages) do not become
false positives. Every convention match is explained for --verbose.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution

from packaging.utils import canonicalize_name

from .config import Config
from .models import Classification, DeclaredDependency, Status
from .resolution import Resolution

# Packages conventionally required without being imported in source. Short,
# documented, and extendable via [tool.pydeadweight] runtime_only. Database
# drivers, WSGI/ASGI servers, and build backends are the usual suspects.
BUILTIN_RUNTIME_ONLY: frozenset[str] = frozenset(
    canonicalize_name(n)
    for n in (
        # Database drivers / backends
        "psycopg2",
        "psycopg2-binary",
        "psycopg",
        "asyncpg",
        "mysqlclient",
        "pymysql",
        "mariadb",
        "cx-oracle",
        "pyodbc",
        # WSGI / ASGI servers
        "gunicorn",
        "uvicorn",
        "hypercorn",
        "daphne",
        "waitress",
        "gevent",
        "eventlet",
        "uvloop",
        # Build backends / packaging
        "setuptools",
        "wheel",
        "pip",
        "build",
        "hatchling",
        "flit-core",
        "poetry-core",
        "pdm-backend",
        "maturin",
    )
)


def classify(
    declared: list[DeclaredDependency],
    used_modules: set[str],
    resolution: Resolution,
    config: Config,
) -> list[Classification]:
    """Classify every declared dependency."""
    allowlist = {canonicalize_name(n) for n in config.ignore}
    runtime_only = BUILTIN_RUNTIME_ONLY | {
        canonicalize_name(n) for n in config.runtime_only
    }

    results = [
        _classify_one(dep, used_modules, resolution, allowlist, runtime_only)
        for dep in declared
    ]
    return results


def _classify_one(
    dep: DeclaredDependency,
    used_modules: set[str],
    resolution: Resolution,
    allowlist: set[str],
    runtime_only: set[str],
) -> Classification:
    name = dep.name

    # 1. User allowlist always wins.
    if name in allowlist:
        return Classification(dep, Status.USED, "allowlisted (ignore)", ())

    provided = resolution.dist_to_imports.get(name, frozenset())

    # 2. Direct import match -> used.
    matched = sorted(provided & used_modules)
    if matched:
        return Classification(
            dep,
            Status.USED,
            f"imported as {', '.join(matched)}",
            tuple(matched),
        )

    # 3. Not installed: import name unresolvable -> unknown, not unused.
    if name not in resolution.installed_dists:
        return Classification(
            dep,
            Status.UNKNOWN,
            "not installed in current environment; cannot resolve import name",
            (),
        )

    # Installed but no provided import names appeared. Run the convention
    # layer before declaring it unused.

    # 4a. Runtime-only convention list.
    if name in runtime_only:
        return Classification(
            dep, Status.USED, "matches runtime-only package list", ()
        )

    # 4b. Provides console scripts / entry points -> it MIGHT be used as a CLI
    #     without ever being imported. We cannot statically confirm the CLI is
    #     actually invoked, so this is 'unknown', not 'used': it is surfaced for
    #     review and is never auto-deleted, but it is not hidden as used either.
    script = _console_script(name)
    if script is not None:
        return Classification(
            dep,
            Status.UNKNOWN,
            f"not imported, but provides console script '{script}'; "
            "cannot statically confirm CLI usage",
            (),
        )

    # 4c. Installed but exposes no importable top-level module at all -> we
    #     cannot reason about it statically.
    if not provided:
        return Classification(
            dep,
            Status.UNKNOWN,
            "installed but provides no importable top-level module",
            (),
        )

    # 5. Genuinely unused.
    return Classification(
        dep,
        Status.UNUSED,
        f"provides {', '.join(sorted(provided))} but none are imported",
        (),
    )


def _console_script(name: str) -> str | None:
    """Return one console-script name the distribution registers, if any."""
    try:
        dist = distribution(name)
    except PackageNotFoundError:
        return None
    try:
        eps = dist.entry_points
    except Exception:
        return None
    for ep in eps:
        if ep.group in ("console_scripts", "gui_scripts"):
            return ep.name
    return None
