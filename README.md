# pydeadweight

Detect — and optionally remove — declared Python dependencies that your project
no longer imports.

Dependency lists rot. Packages get added during experiments, refactors leave
imports behind, and nothing prunes the manifest. Stale dependencies inflate
install time, widen the security surface, and mislead new contributors about
what the project actually relies on. `pydeadweight` finds the dead weight.

It runs a **static-analysis** pipeline — it never executes your project's code.
It defaults to a read-only report and only mutates files when you explicitly
ask, behind a confirmation flag. Correctness is the point: it biases toward
**false negatives over false positives**, so it would rather miss an unused
dependency than wrongly tell you to delete one you need.

---

## ⚠️ Run it inside your project's environment

**This is the single biggest correctness requirement.** `pydeadweight` resolves
the mismatch between distribution names and import names (you `pip install
Pillow` but `import PIL`) by reading installed package metadata
(`importlib.metadata.packages_distributions`). That metadata only exists for
**installed** packages.

So run `pydeadweight` inside the virtualenv where your project's dependencies
are installed:

```console
$ source .venv/bin/activate      # or your env of choice
$ pydeadweight check
```

If a declared dependency is **not installed**, its import name is unknowable and
it is reported as `unknown` — never `unused`. You'll get a warning telling you
to run inside the project venv. This is by design: better to say "I don't know"
than to confidently flag a needed package for deletion.

---

## Install

```console
$ pip install pydeadweight        # once published
# or, from a checkout:
$ pip install -e .
```

Python 3.11+ required. The tool keeps its own dependency list short — `packaging`,
`tomlkit`, `pathspec`, and the standard library.

---

## Usage

### `check` — analyze and report (read-only)

```console
$ pydeadweight check [PATH]
```

| Flag | Default | Behavior |
|------|---------|----------|
| `--json` | off | Emit machine-readable JSON instead of human text |
| `--fail-on-unused` | off | Exit non-zero if any dependency is unused (for CI) |
| `--include-dev` / `--no-include-dev` | include | Include dev/optional dependency groups |
| `--config PATH` | auto | Config file; auto-discovers `pyproject.toml` / `.pydeadweight.toml` |
| `--ignore NAME` | — | Treat NAME as used for this run (repeatable) |
| `-v, --verbose` | off | Show per-dependency reasoning |

```console
$ pydeadweight check --verbose
Analyzed 18 source file(s); 4 declared dependencies.

Unused dependencies (1):
  [unused] click  (main)
      provides click but none are imported

Used (3):
  [used]   gunicorn - matches runtime-only package list
  [used]   pillow - imported as PIL
  [used]   requests - imported as requests
```

### `clean` — remove unused dependencies (mutating)

```console
$ pydeadweight clean [PATH]
```

| Flag | Behavior |
|------|----------|
| `--interactive` | Prompt y/n per unused dependency |
| `--yes` | Skip confirmation (required for non-interactive removal) |
| `--dry-run` | Show exactly what would change, write nothing |
| `--no-lockfile` | Edit the manifest but do not touch the lockfile (default-safe) |

`clean` **refuses to run** without one of `--dry-run`, `--interactive`, or
`--yes` — it will never silently rewrite your files. The `pyproject.toml` writer
preserves your comments, ordering, and formatting; only the removed entries
change. Lockfiles are not regenerated automatically — `pydeadweight` prints the
exact command to run (`uv lock`, `poetry lock`, `pip-compile`) instead.

```console
$ pydeadweight clean --dry-run
Changes to pyproject.toml:
  - "click"    (project.dependencies)

Dry run: no files were modified.
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (no unused, or unused found without `--fail-on-unused`) |
| 1 | Unused dependencies found **and** `--fail-on-unused` set |
| 2 | Usage error (bad flags, conflicting options, missing confirmation) |
| 3 | Project error (no manifest, unparseable manifest, all source unparseable) |

---

## How it works

```
manifest file ──► manifest parser ──┐
                                     ├──► classifier ──► convention layer ──► reporter
source tree ─────► import extractor ─┘                                    └─► cleanup writer
```

1. **Manifest parser** reads declared dependencies from `pyproject.toml`
   (PEP 621 or Poetry) or `requirements*.txt`, using `packaging` to parse
   specifiers and canonicalize names.
2. **Import extractor** walks every `.py` file with the `ast` module (never
   regex), collecting top-level imports. It captures imports inside functions,
   `try`/`except`, and `if TYPE_CHECKING:` blocks, and skips relative imports
   (first-party code).
3. **Name resolution** inverts `packages_distributions()` to map each
   distribution to the import names it provides, and filters out stdlib modules.
4. **Classifier** buckets each dependency as `used`, `unused`, or `unknown`.
5. **Convention layer** keeps static-analysis blind spots from becoming
   wrongful `unused` verdicts. A dependency on the built-in runtime-only list
   (DB drivers, WSGI/ASGI servers, build backends) or on your allowlist is
   treated as `used`. A dependency that is never imported but ships a
   console-script / entry-point CLI is reported as `unknown` — surfaced for
   review and never auto-deleted, since static analysis can't confirm whether
   the CLI is actually used.

### What it cannot see

Static analysis cannot detect dynamic imports
(`importlib.import_module(variable)`, `__import__`), framework plugins loaded by
name, or packages required only as a runtime backend. The convention layer and
your `ignore` allowlist exist to suppress exactly these cases.

---

## Configuration

Configure via `[tool.pydeadweight]` in `pyproject.toml`, or a standalone
`.pydeadweight.toml`. CLI flags override config; config overrides built-in
defaults.

```toml
[tool.pydeadweight]
ignore = ["gunicorn", "psycopg2-binary"]    # always treated as used
exclude = ["scripts/legacy/**", "docs/**"]  # globs excluded from discovery
runtime_only = ["my-internal-driver"]       # extend the built-in runtime-only list
include_dev = true
```

---

## CI integration

Block PRs that add a dependency nothing imports:

```yaml
# .github/workflows/deps.yml
jobs:
  pydeadweight:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e .          # install the project so deps resolve
      - run: pip install pydeadweight
      - run: pydeadweight check --json --fail-on-unused
```

Note the `pip install -e .` step: the project's dependencies must be installed
for analysis to be accurate.

---

## Development

```console
$ pip install -e ".[dev]"
$ pytest
```

The pipeline stages are pure-function-style modules tested in isolation; see
`tests/` for extractor edge cases, manifest layouts, classifier buckets, writer
round-trips, and CLI exit-code coverage.

---

## Scope (v1)

**In:** direct/declared dependencies, Python projects, `pyproject.toml` and
`requirements*.txt`. **Out:** outdated/vulnerable dependency detection, unused
*transitive* deps, rewriting source to remove unused imports, non-Python
ecosystems, and auto-committing or opening PRs.
