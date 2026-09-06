# Stage 2C-E1: zero-step preflight repair

Status: implementation and engineering tests only. The current failed formal directory is read-only in this task. Master must separately authorise running repair and subsequently resuming the pilot. No scientific execution or repair of that directory is authorised by this document.

## Recorded failure

The first `./run_stage2c.sh --mode pilot` invocation ended on 6 September 2026 at **19:21:35 Asia/Shanghai** (11:21:35 UTC), with **exit code 1**. Engineering validation reported **127 passed, 1 failed**. The failing test was `tests/test_stage2c_multiseed.py::test_dry_run_no_simulation_or_initialisation`.

The runner correctly created its output directory and planned manifests before running the complete engineering suite. The test incorrectly asserted that the formal output directory must not exist, even when it already existed before that test's temporary dry-run. The test now records the formal directory's initial existence and top-level entries and verifies that both remain unchanged; it also checks the exact temporary output path. The constructor, step, run and endpoint-calculation prohibition remains in force. Separate temporary-project tests exercise both initially absent and initially present formal directories.

Both `20260901` rules remained `planned`, at `t=0`, with empty attempts, null initial identities and no checkpoint/shared artifact. All 40 run entries remained uninitialised. This is an engineering preflight failure, not an unfavourable scientific observation.

The old failure is bound to runner commit `b8ad6911fdcbf82489ba1753179b0f12006911bb`. Correcting the test changes the runner source identity, so ordinary `--resume` must continue to reject the old preflight. Removing a test assertion or deleting the failed engineering receipt alone is insufficient.

## Explicit engineering mode and admissibility

The new CLI mode is `./run_stage2c.sh --mode repair-preflight`. It has no science branch and rejects `--resume`. It never calls pilot, full execution, analysis, a simulation constructor, a dynamics step or an endpoint calculator. It builds only preflight metadata and the non-registered, zero-step storage fixture, then runs the full engineering suite.

Before the first write, repair checks all of the following while holding the existing runner lock, opened without creating or truncating it:

- An existing, recognised output directory, with the complete eight-file preflight set and existing lock. Unknown files/directories and symlinks are rejected, including an empty `runs/`, `completed/` or `analysis/` directory, summary or shared artifact.
- A complete failed engineering receipt: `passed=false`, `paper_scale_simulation_executed=false`, the full output, consistent failed test names and test counts, valid elapsed/temporary-storage evidence, and an identity consistent with the other preflight files. A passed, corrupt, missing or incomplete receipt is rejected.
- Exactly the preregistered 40 seed/rule records, in order, with the canonical `planned / time=0 / attempts=[]` record, zero elapsed run time and checkpoint generation, and null initial, checkpoint, history and shared-artifact references/hashes. All-zero checks also cover recorded resource-history snapshots.
- Canonical configurations, paired audits and uninitialised hash placeholders; exactly the two expected planned metric tables with no observed values; consistent storage/source identity and original 1.5, four-hour and 2 GB limits.
- A readable, complete old source hash map that matches its recorded Git commit. The old and current protected input, frozen model and preregistration identities must agree. Current code must be committed and the worktree clean outside the authorised output directory.

No failed scientific run, scientific checkpoint, changed seed/configuration, partially initialised simulation or ambiguous evidence can be admitted. This mode is deliberately limited to one E1 transaction, `attempt-01`; it does not automatically repair a second engineering failure or migrate scientific state.

## Evidence and interrupted publication

The future repair retains this structure inside the formal output directory:

```text
engineering_failures/attempt-01/
  intent.json
  files/
    config_manifest.json
    checkpoint/progress_manifest.json
    seed_manifest.json
    storage_preflight.json
    runtime.json
    engineering_validation.json
    per_seed_metrics.csv
    paired_comparison.csv
  failure_receipt.json
  replacement.zip
  complete.json
```

The existing `.runner.lock` stays at the root and is never truncated. The eight old preflight files are copied byte for byte; their sizes and SHA-256 values are recorded in immutable intent and failure receipts. The full old test output survives in the archived engineering receipt. Only after all copies have been verified does repair publish new root files and remove the archived old root engineering receipt so that fresh tests can produce a new one. No directory is deleted, moved aside or recreated to hide the failure.

The failure receipt records old runner commit/source hash, failed tests, failure time, exit code and every archived file hash. The legacy September 6 receipt has no structured exit time or exit code. For that legacy schema, repair explicitly labels file modification time as a timestamp proxy and exit code 1 as inferred from failed pytest followed by the runner's `RuntimeError`; it does not claim the timestamp is the exact process exit time. The exact observed failure time and exit code are recorded above and in the original external command log. Future engineering receipts now record start/end timestamps and subprocess exit code directly.

An immutable intent binds one old snapshot to one new identity. A complete immutable replacement ZIP is published before changing root manifests. Every root file during publication must match either its exact archived old bytes or this transaction's prepared new bytes. Partial archives resume copying from unchanged originals; existing archive files are checked and never overwritten. Atomic-write temporary leftovers are retained and counted. Unknown leftovers are rejected.

A repeated invocation may finish the same interrupted transaction, including interruption after the new tests passed but before final accounting. It does not rerun tests whose valid passing receipt already exists. Only canonical zero-state accounting may evolve during that finalisation. A new failed test receipt is preserved and refused on a subsequent invocation, requiring another explicit engineering decision. A completed transaction is verified and then refused for repeat repair. Its completion receipt binds the archive, replacement bundle, new identity and passing engineering receipt.

Normal `Study` construction verifies the repair archive and refuses an incomplete transaction, so `pilot`, `full` and `analyse` cannot bypass an unfinished repair. After repair, the root preflight and engineering receipt use the new identity, while all 40 scientific run records remain planned and uninitialised. The return value is `preflight_repaired` with `simulation_started=false`, `scientific_metrics_generated=false` and the current resource decision. A resource `pause` is not an authorisation to run anything.

## Accounting and scientific boundary

All files under `engineering_failures/` are retained evidence, including the replacement bundle and any interrupted atomic-write temporary files. They are explicitly counted before the usual transient checkpoint exclusions. The archived failed receipt's external engineering-test bytes are also charged on every later resource calculation, in addition to the new test evidence. Resource history is never used to reset the elapsed budget.

The new preflight carries at least the maximum old progress/runtime elapsed time plus the old engineering-test duration. It then adds repair wall time, conservatively including any interruption gap. This avoids losing the failed test cost that the original progress snapshot had not recorded. The final repair receipt itself is included by a final resource calculation.

The complete production storage/time formulas and safety factor remain in use. Registered seeds, rules, N=100, L=300, 10,000 steps, metrics, thresholds and the frozen scientific model are unchanged. The metric-table refactor merely exposes the existing exact serialised bytes for validation without writing files or calculating scientific outcomes.

Tests use temporary outputs and a two-ant, nine-step-shaped storage fixture with non-registered seed 991337 and **zero executed simulation steps**. Simulation constructors, steps, run and scientific analysis are trapped in the repair test module. Tests cover the exact 127-pass/one-failure planned-state scenario, byte-exact archives, identity rebinding, accounting, both dry-run directory states, refusal gates, repeated calls and interruption at intent/copy/bundle/publication/testing/accounting/completion boundaries. Nested full-suite execution is substituted with bounded engineering receipt fixtures in repair unit tests; the real complete suite is run separately in the unchanged real failed-directory context.

## Required next authorisation

This E1 implementation does not execute repair on the current failed study, alter its receipt/manifests or resume its pilot. After reviewing the new commit, master must separately authorise **repair-preflight**. Only after validating the repaired preflight and resource decision may master separately authorise **pilot --resume**. No remaining confirmation seed is authorised by this repair.

## E1 implementation acceptance

The final uncached suite passed **176 tests in 94.32 seconds** in the real workspace while the original failed formal directory still existed. The command used `PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `python3 -B -m pytest -q -p no:cacheprovider` and a fresh `/private/tmp/stage2c-e1-v3hjq32o/acceptance-tests` base directory. The log is `/private/tmp/stage2c-e1-v3hjq32o/acceptance-tests.log`.

Read-only before/after inventories preserve all **9 original failed-site files**, **110 protected files** and **26 frozen source files**. The actual site's legacy identity and strict zero-step payload were validated without invoking repair. The real directory has no `engineering_failures/` or `runs/`; all 40 records remain planned at zero with empty attempts. Inventory/hash records are under `/private/tmp/stage2c-e1-v3hjq32o/`. Only engineering source, tests and this document are submitted; the original failed directory remains untracked and unmodified.
