# pydeadweight v1.0.0

First production release. `pydeadweight` detects — and optionally removes —
declared Python dependencies a project no longer imports. It runs a pure
static-analysis pipeline (it never executes your code), defaults to a read-only
report, and gates every mutation behind an explicit confirmation flag.

## Highlights

- **`check`** — classify every declared dependency as `used`, `unused`, or
  `unknown`, with human or `--json` output and a `--fail-on-unused` CI gate.
- **`clean`** — remove unused dependencies from the manifest, preserving
  comments, ordering, and line endings. Refuses to write without `--dry-run`,
  `--interactive`, or `--yes`. Manifest writes are atomic.
- **Correct distribution↔import resolution** from installed package metadata
  (`Pillow`→`PIL`, `PyYAML`→`yaml`, …) — no hardcoded table.
- **Convention layer** keeps static-analysis blind spots from becoming wrongful
  `unused` verdicts: a built-in runtime-only list (DB drivers, WSGI/ASGI
  servers, build backends) and your allowlist are treated as `used`; never-
  imported CLI/entry-point packages are reported `unknown` (surfaced, never
  auto-deleted).
- Supports `pyproject.toml` (PEP 621 and Poetry) and `requirements*.txt`.

## Operating requirement

Run `pydeadweight` **inside the project's installed environment** (the venv
where its dependencies are installed). Name resolution reads installed package
metadata; a dependency that isn't installed is reported `unknown`, never
`unused`. See the README for the full rationale.

## Robustness fixed for 1.0.0

The following correctness, data-integrity, and stability issues were fixed and
are covered by regression tests (`tests/test_audit_regressions.py`):

- BOM / PEP 263-encoded source files are now parsed instead of silently skipped
  (previously a Windows-saved file could cause a false `unused` verdict).
- `clean` warns when any source file could not be parsed, so a skipped file's
  imports can't lead to a silent deletion.
- `clean` removes unused deps from **all** `requirements*.txt` files, not just
  the primary one.
- Manifest writes preserve original line endings (no whole-file CRLF/LF churn)
  and are atomic (a failed write leaves the original intact).
- Never-imported console-script packages are classified `unknown`, not `used`.
- Manifests declaring PEP 621 dynamic dependencies raise a clear error instead
  of silently analyzing an empty dependency set.
- Directory-symlink cycles in the source tree no longer hang discovery.
- `--no-lockfile` has an observable effect; unexpected `clean`/write errors map
  to a clean exit code instead of a traceback.

## Known limitations

All known limitations fail in the **safe direction** — they may *miss* an unused
dependency (false negative), never *wrongly delete a required one* (false
positive). Each is a candidate for a future release.

| Ref | Limitation | Effect | Workaround |
|-----|------------|--------|------------|
| F9 | **Namespace packages** are matched only at the top-level import name. Distributions sharing a namespace (e.g. `azure-storage-blob` + `azure-identity`, both providing `azure`) are conflated: importing one marks all as `used`. | An unused namespace-sibling dependency may not be flagged. | Review namespace-package families manually. |
| F10 | **`.gitignore` handling reads the project-root file only.** Nested `.gitignore` files, negation precedence, and the global excludes file are not composed. | Source under a directory excluded by a nested `.gitignore` is still scanned (occasionally the reverse), so verdicts can be slightly off. | Use `[tool.pydeadweight] exclude = [...]` to express exclusions explicitly. |
| F11 | **`requirements*.txt` `-r`/`-c` includes are not followed**, and backslash line-continuations are not joined. | Dependencies declared only in an included file (not matching `requirements*.txt`) are invisible; a continued requirement line is dropped. | Point analysis at a flattened requirements file, or use `pyproject.toml`. |
| F14 | **Poetry edge-case grouping.** List-valued (multi-constraint) dependencies and `optional = true` extras are recorded under the `main` group. | `--no-include-dev` filtering can be inexact for these entries; no crash, no wrong deletion. | Verify Poetry extras/multi-constraint deps manually when using `--no-include-dev`. |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (no unused, or unused found without `--fail-on-unused`) |
| 1 | Unused dependencies found **and** `--fail-on-unused` set |
| 2 | Usage error |
| 3 | Project error (no/unparseable manifest, dynamic dependencies, all source unparseable) |

## Tooling dependencies

`packaging`, `tomlkit`, `pathspec`, and the standard library. Python 3.11+.
