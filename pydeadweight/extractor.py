"""Stage 8: the static-analysis core — extract imported module names.

Parses every source file with the stdlib ``ast`` module (never regex) and
collects the top-level package of each absolute import. Relative imports are
skipped because they reference first-party code, never a third-party
dependency. ``ast.walk`` is used so imports inside functions, classes,
``try``/``except``, and ``if TYPE_CHECKING:`` blocks are all captured.

What this stage cannot see — dynamic imports (``importlib.import_module``,
``__import__``), plugin loaders, and packages required at runtime but never
imported — is by definition out of reach for static analysis and is handled
downstream by the convention layer, not by heuristics bolted on here.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .models import ImportName, SkippedFile


def extract_imports_from_source(
    source: str | bytes, filename: str = "<unknown>"
) -> set[str]:
    """Return the set of top-level module names imported by one source.

    Accepts ``str`` or ``bytes``. Passing ``bytes`` lets ``ast.parse`` honor a
    UTF-8 BOM and PEP 263 coding declarations, exactly as the interpreter does;
    that is why the file layer (:func:`extract_imports`) reads raw bytes.

    Raises ``SyntaxError`` if the source cannot be parsed; callers that walk a
    tree of files should use :func:`extract_imports` which handles that.
    """
    tree = ast.parse(source, filename=filename)
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # import foo, bar.baz  ->  foo, bar
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top:
                    modules.add(top)
        elif isinstance(node, ast.ImportFrom):
            # from foo.bar import baz  ->  foo
            # node.level > 0 is a relative import (from . import x) -> skip.
            if node.level == 0 and node.module:
                top = node.module.split(".")[0]
                if top:
                    modules.add(top)

    return modules


def extract_imports(
    files: list[Path],
) -> tuple[list[ImportName], list[SkippedFile]]:
    """Extract imports across many files.

    Returns ``(import_names, skipped_files)``. A file with a ``SyntaxError``
    (or that cannot be read) is recorded as skipped and analysis continues;
    callers decide whether an all-skipped run is fatal.
    """
    imports: list[ImportName] = []
    skipped: list[SkippedFile] = []

    for path in files:
        try:
            # Read bytes, not text: ast.parse then handles the BOM and any PEP
            # 263 coding declaration itself, instead of us assuming UTF-8 and
            # skipping files a Windows editor saved with a BOM.
            source = path.read_bytes()
        except OSError as exc:
            skipped.append(SkippedFile(path=str(path), error=f"read error: {exc}"))
            continue
        try:
            modules = extract_imports_from_source(source, filename=str(path))
        except (SyntaxError, ValueError) as exc:
            # ValueError covers e.g. null bytes / bad coding cookies.
            skipped.append(SkippedFile(path=str(path), error=f"parse error: {exc}"))
            continue
        for module in sorted(modules):
            imports.append(ImportName(module=module, source_file=str(path)))

    return imports, skipped
