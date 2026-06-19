# Maintenance Notes — RC Hygiene Audit

Lower-severity observations: message inconsistencies and documentation that
lags implemented behavior. None blocks release; none requires a behavior change.
Grouped by category 6 (inconsistent error messages) and category 7 (missing/
inaccurate documentation of implemented behavior).

## 6. Inconsistent error / warning messages

| ID | Location | Finding | Suggested alignment |
|----|----------|---------|---------------------|
| E1 | `manifest.py` (`ManifestError: "no manifest found in … (looked for pyproject.toml and requirements*.txt)"`) vs `writer.py:82` (`FileNotFoundError(f"no manifest found in {project_path}")`) | The same logical condition ("no manifest") is reported as two different exception types with two different messages from two modules. The writer path is nearly unreachable (it runs only after `analyze` already parsed a manifest), but the divergence is real. | Reuse `ManifestError` and the fuller message, or have `_run_clean` never reach the writer's variant. Cosmetic until the unreachable path is hit. |
| E2 | `report.py:79` ("**WARNING:** …") vs `cli.py:175` ("**warning:** …") | Warning prefix capitalization is inconsistent across the two places the tool warns. | Pick one casing for all user-facing warnings. |
| E3 | `cli.py:176–180` | Skipped-file warning instructs "use `--verbose` to list them", but `clean --verbose` does not list them (see B2 in `release_blockers.md`). | Tracked as **B2** — promoted to a blocker because it actively misleads. Listed here for cross-reference. |

## 7. Documentation lagging implemented behavior

| ID | Location | Finding | Suggested fix |
|----|----------|---------|----------------|
| DOC1 | `README.md:142–145` | Convention-layer description still says console-script CLIs are rescued and "finalized as used"; F6 changed them to `unknown`. | Tracked as **B1** in `release_blockers.md` (user-facing). |
| DOC2 | `classifier.py:6–12` (module docstring) | (a) The `unknown` bucket description lists only "not installed" and "no importable top-level module" — it omits the F6 case (installed, provides a console script, not imported). (b) "Any match downgrades it to `used`" is now false: a console-script match downgrades to `unknown`, not `used`. | Update the docstring's bucket list and the "downgrades to used" sentence to reflect F6. Internal doc only. |
| DOC3 | `extractor.py:50–58` docstring + `models.py:35–39` | Both describe import provenance "with provenance (which file each came from, for `--verbose`)", but no output surfaces it (see D2). The CLI `--verbose` help (`cli.py:78`) is *correctly* narrower ("Show per-dependency reasoning"), so only the lower-level docstrings overpromise. | Either implement provenance display (feature, out of scope) or soften the docstrings to match reality. |
| DOC4 | `README.md` (clean section) | New behaviors from the prior fix round are undocumented: `--no-lockfile` now suppresses the lockfile hint (F12); `clean` emits a skipped-file safety warning (F2); manifest writes are atomic (F5); dynamic-dependency manifests raise a clear error (F7). | Add a short "clean safety behaviors" note to the README so the shipped feature set is documented. |

## General observations (informational, no action required to ship)

- **Source package is import-clean** (pyflakes: 0 unused imports in
  `pydeadweight/`). Only test files carry stale imports (UI1/UI2).
- **`_detect_newline` (`writer.py:61`)** treats a file as CRLF if *any* `\r\n`
  is present, normalizing mixed-ending files to CRLF on write. This is a
  deliberate, acceptable simplification — note it if mixed-ending inputs ever
  matter.
- **Two `--no-lockfile` truths**: the flag is now honestly wired (suppresses the
  hint) and the writer never touches lockfiles regardless, so the flag's name
  slightly overstates its scope. Acceptable; just keep the README accurate.
- The earlier critical-fix round (F1–F8, F12, F13) is intact and covered by
  `tests/test_audit_regressions.py`; this audit found no regressions in it.
