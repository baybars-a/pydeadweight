# Technical Debt — RC Hygiene Audit

Non-blocking findings. None changes behavior; none needs to be fixed to ship.
Recorded so they are paid down deliberately, not rediscovered. Ordered by
category as requested.

## 1. Dead code

| ID | Location | Finding | Notes / recommended action |
|----|----------|---------|----------------------------|
| D1 | `writer.py:52–58` | `WriteResult.manifest_path` and `WriteResult.new_content` properties are referenced **nowhere** (grep of `pydeadweight/` + `tests/` finds no `.manifest_path` reads, and `.new_content` only matches `FileEdit.new_content` at `writer.py:93`). Added as "backwards-compatible convenience views" during the F3 multi-file refactor, but no caller — production or test — uses them. | Remove both properties (pure dead-code deletion, no behavior change). Keep `WriteResult.removals`, which *is* used (`cli.py`, `tests/test_writer.py`). |
| D2 | `models.py:35–39`, written at `extractor.py:84` | `ImportName.source_file` (import provenance) is collected for every import but never read by any production code path. The PRD/extractor docstring promise it "for `--verbose`", yet no output surfaces it (`report.render_human` prints only `c.reason`). Only `tests/test_extractor.py:83` reads it. | Either surface provenance in `--verbose` output (a *feature* — out of scope now) or drop the field and its test assertion. Until then it is dead data with a test pinning it in place. |

## 2. Duplicated logic

| ID | Location | Finding | Recommended action |
|----|----------|---------|--------------------|
| DL1 | `manifest.py:223–236` (`_clean_requirement_line`) vs `writer.py:232–238` (`_requirement_line_name`) | Two independent implementations of requirements-line parsing: both strip `# ` inline comments, skip blank/`#`/`-` lines, and derive a name. They can drift (e.g. manifest also skips `git+`/URLs; writer does not). | Extract one shared helper (e.g. in `manifest.py`) and import it into `writer.py`. Mechanical, behavior-preserving if the union of rules is kept. |
| DL2 | `cli.py:135–140` | Two `except` blocks (`ManifestError`, `ProjectError`) with byte-identical bodies. | Collapse to `except (ManifestError, ProjectError) as exc:`. |
| DL3 | `cli.py:69–79` vs `cli.py:100–107` | `--config`, `--ignore`, `--include-dev/--no-include-dev`, `-v/--verbose` are redefined verbatim on both the `check` and `clean` subparsers. | Define a shared parent `ArgumentParser(add_help=False)` and pass via `parents=[...]`. Structural only. |

## 3. Unreachable branches

| ID | Location | Finding | Recommended action |
|----|----------|---------|--------------------|
| U1 | `cli.py:146–147` | `parser.error("unknown command")` then `return EXIT_USAGE`. The subparser is created with `required=True` (`cli.py:44`), so `args.command` is always `"check"` or `"clean"`; this tail is unreachable. Line 146 carries `# pragma: no cover`, but line 147 is dead too. | Delete the two lines, or keep as a defensive guard but drop the unreachable `return`. |
| U2 | `manifest.py` `_build_records` (`raw_specs.get(name, name)`) | `raw_specs[name]` is always set wherever `accum[name]` is set, so the `, name` default never fires. | Harmless; leave or simplify to `raw_specs[name]`. |

## 4. Unused imports

| ID | Location | Finding | Recommended action |
|----|----------|---------|--------------------|
| UI1 | `tests/test_audit_regressions.py:8` | `import sys` — unused (pyflakes-confirmed). | Remove the import. |
| UI2 | `tests/test_extractor.py:5` | `import pytest` — unused (pyflakes-confirmed). | Remove the import. |

The `pydeadweight/` package itself is **clean** of unused imports (pyflakes
reports zero). Both findings are in test scaffolding only.

## 5. Stale tests

| ID | Location | Finding | Recommended action |
|----|----------|---------|--------------------|
| ST1 | `tests/test_extractor.py:80–83` (`test_provenance_recorded`) | Asserts `ImportName.source_file` is populated — i.e. it pins down dead data (see D2). The test passes, but it guards a field no shipping code consumes, so it gives false confidence that provenance "works". | If D2 is resolved by surfacing provenance, strengthen this test to assert it appears in `--verbose`. If D2 is resolved by deletion, remove this test. |
| ST2 | UI1, UI2 above | Leftover imports in test files. | Covered by §4. |

No test references a removed/renamed API; the suite is internally consistent
with current code.
