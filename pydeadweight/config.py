"""Load and merge configuration.

Precedence (highest first): CLI flags > config file > built-in defaults.
CLI overrides are applied by the caller after ``load_config`` returns; this
module only handles file + defaults.

Config is read from ``[tool.pydeadweight]`` in ``pyproject.toml``, falling
back to a standalone ``.pydeadweight.toml`` (whose keys live at the top level).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Config:
    ignore: tuple[str, ...] = ()
    """Distribution names always treated as used."""

    exclude: tuple[str, ...] = ()
    """Glob patterns excluded from source discovery."""

    runtime_only: tuple[str, ...] = ()
    """User additions to the built-in runtime-only list."""

    include_dev: bool = True
    """Whether dev/optional dependency groups are analyzed."""

    source_path: str | None = None
    """Path of the config file that supplied these values, for reporting."""


def _coerce_str_list(value: object, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"[tool.pydeadweight] {key} must be a list of strings")
    return tuple(value)


def _from_table(table: dict, source_path: Path) -> Config:
    include_dev = table.get("include_dev", True)
    if not isinstance(include_dev, bool):
        raise ValueError("[tool.pydeadweight] include_dev must be a boolean")
    return Config(
        ignore=_coerce_str_list(table.get("ignore"), "ignore"),
        exclude=_coerce_str_list(table.get("exclude"), "exclude"),
        runtime_only=_coerce_str_list(table.get("runtime_only"), "runtime_only"),
        include_dev=include_dev,
        source_path=str(source_path),
    )


def load_config(project_path: Path, explicit_config: Path | None = None) -> Config:
    """Discover and read configuration.

    If ``explicit_config`` is given it is read directly: a ``pyproject.toml``
    uses its ``[tool.pydeadweight]`` table, anything else is read as a
    top-level table. Otherwise we look for ``pyproject.toml`` then
    ``.pydeadweight.toml`` under ``project_path``.
    """
    if explicit_config is not None:
        return _read_file(explicit_config)

    pyproject = project_path / "pyproject.toml"
    if pyproject.is_file():
        cfg = _read_file(pyproject)
        if cfg.source_path is not None:
            return cfg

    standalone = project_path / ".pydeadweight.toml"
    if standalone.is_file():
        return _read_file(standalone)

    return Config()


def _read_file(path: Path) -> Config:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"could not read config file {path}: {exc}") from exc

    if path.name == "pyproject.toml":
        table = data.get("tool", {}).get("pydeadweight")
        if table is None:
            # pyproject exists but declares no config; signal "not found here"
            # so the caller can fall through to .pydeadweight.toml.
            return Config(source_path=None)
        return _from_table(table, path)

    # Standalone config: support both a bare top-level table and a nested
    # [tool.pydeadweight] table for people who copy-paste from pyproject.
    table = data.get("tool", {}).get("pydeadweight", data)
    return _from_table(table, path)


def merge_cli_overrides(
    config: Config,
    *,
    include_dev: bool | None = None,
    extra_ignore: tuple[str, ...] = (),
) -> Config:
    """Apply CLI overrides on top of file/default config."""
    merged_ignore = tuple(dict.fromkeys((*config.ignore, *extra_ignore)))
    return replace(
        config,
        ignore=merged_ignore,
        include_dev=config.include_dev if include_dev is None else include_dev,
    )
