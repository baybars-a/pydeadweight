# Release Blockers — RC Hygiene Audit

Scope: dead code, duplicated logic, unreachable branches, unused imports, stale
tests, inconsistent error messages, undocumented behavior. **No behavior was
modified by this audit.** A "blocker" here is a shipped artifact that is
factually wrong or actively misleads a user — not a code-quality nit.

The test suite is green (52 passed, 1 skipped) and no behavioral defect, crash,
data-loss, or security issue was found in the audited categories. Both blockers
below are **documentation / user-message** inaccuracies introduced by the
earlier F6/F2 fixes that were never propagated to user-facing text. Each is a
sub-five-minute text edit with zero behavior change.

| ID | Severity | Location | Problem | Why it blocks | Recommended correction |
|----|----------|----------|---------|---------------|------------------------|
| B1 | **High** | `README.md:142–145` ("How it works", item 5) | States the convention layer rescues "console-script CLIs … before anything is finalized as **unused**", implying such deps are reported **used**. After fix F6, a console-script-only dep is classified **`unknown`**, not used (`classifier.py:126–138`). | The shipped README contradicts shipped behavior on a core classification rule. A user reading it will expect stale CLI tools to be hidden as "used"; instead they surface as "unknown". Directly misleads on what the tool reports. | Reword item 5: console-script / entry-point deps that are never imported are reported **`unknown`** (surfaced for review, never auto-deleted), not silently kept as used. |
| B2 | **Medium-High** | `cli.py:176–180` (the F2 skipped-file warning) | The warning tells the user to "use `--verbose` to list them", but `clean --verbose` never lists skipped files: `args.verbose` is consumed only in `_run_check` (`cli.py:154`) and is unused in `_run_clean`. | A shipped instruction points the user at a remedy that does nothing. The user runs `clean -v`, sees no list, and loses trust in the warning that is specifically guarding against deleting a still-used dependency. | Either drop the "use --verbose to list them" clause from the clean warning, or have `_run_clean` print the skipped-file list when `args.verbose` is set (mirroring `report.render_human`). Pick the doc-only option to honor "no behavior change". |

## Disposition

Neither blocker is a behavioral defect; both are ship-facing text that became
inaccurate when F6 and F2 landed. They block a *release candidate* because the
README and the safety warning are part of the shipped product and are currently
wrong/misleading. Correcting them requires no code-logic change and no new test
(B1 is README prose; B2 is a CLI string or a guarded print).

Everything else found in this audit is non-blocking and recorded in
`technical_debt.md` and `maintenance_notes.md`.
