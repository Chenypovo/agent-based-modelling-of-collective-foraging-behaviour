# Stage 3A — scalar pheromone B0 engineering acceptance

**Engineering PASS.** B0 is eligible to be submitted for master acceptance before
any next-stage work. This is not permission to start Stage 3B. No recovery C was
implemented. No formal multi-seed experiment was run. Exponential and hard-cutoff
decay received engineering validation only: no decay-law, recovery or SOTA
scientific conclusion follows.

## Scope and identity

- Live starting branch: `codex/stage2c-multiseed-confirmation`.
- Verified starting HEAD: `36ab78a32b7ea22f2902574fdb517a5e4b20e4e3`.
- Tracked workspace was clean before work; the four existing untracked material
  trees were preserved.
- New branch: `codex/stage3-scalar-decay-baseline`.
- All implementation is isolated in `src/scalar_baseline/`; no existing tracked
  source, test, default, report or result file was edited.
- Specification was written before implementation:
  `docs/STAGE3A_SCALAR_DECAY_BASELINE_SPEC.md`.
- Stage 2A remains a legacy baseline. New experiments use B0 as their fair main
  control. This independent, paper-informed model is not an exact reproduction
  of Zhang–Yong (2023). The ground scalar field is not an airborne plume model.

## Acceptance evidence

| Gate | Result and durable evidence |
|---|---|
| New and old tests | **313 passed**, zero failures/skips; `test_results.txt` and `test_runtime.json`. Includes 267 legacy tests and 46 Stage 3A tests. Final suite elapsed 192.739 s including process overhead. |
| Scalar-only | `ScalarField.__slots__` contains concentration, optional cutoff timestamps, time and geometry/decay metadata only. No cell direction, food identity or source/target direction. `config_audit.json`. |
| Food-coordinate isolation | Pure `navigate` accepts heading, two scalar samples, role/timer, independent noise and frozen FCRW turn only. Two-query sensor test, food-location perturbation test and poisoned-environment movement test pass. `food_coordinate_isolation_audit.json`. |
| Diffusion=0 | Nonzero diffusion is rejected at both simulation config and field construction. Empty neighbouring cells remain exactly zero under both decay modes. One containing cell per deposit. |
| Half-life/rate | Bidirectional conversion, inconsistent-input rejection and exactly equal step-by-step fields for equivalent inputs pass. This is parameter equivalence, not an ablation. |
| Exponential | Analytic decay, repeated deposits and decay-before-deposition pass. |
| Hard cutoff | Named `hard_cutoff_cell_timer`; pre-expiry hold, expiry clearing, positive-deposit timer refresh and zero-deposit non-refresh pass. This is a cell timer, not a molecular lifetime. |
| Navigation | Left/right signs, deterministic zero on ties, independent symmetric noise, maximum turn, threshold equality/hysteresis and immediate loss-to-FCRW pass. No recovery/casting role or recovery-duration parameter exists. |
| Food relocation | A removal/B addition, no relocation mutation of agents/field, carried-A snapshot and separate A/B delivery bookkeeping pass. |
| State validity | Per-step population, role/cargo conservation, position bounds, finite headings/concentration and bounded self-path memory pass. Fixed-seed repeatability passes for both modes on tiny engineering fixtures. |
| Legacy preservation | **646/646 protected SHA-256 hashes match**, no missing/changed files and no additions in protected material/result trees. Includes 415 files under Stage 2C. `protected_sha256_before.json` and `protected_sha256_check.json`. |
| Output protection | Pilot CLI rejects protected output directories and existing output directories before simulation. `cli_output_guard_audit.json`. |
| Runtime/storage | Actual pilot timings and file sizes in `pilot/runtime.json`; final artifact inventory in `storage_measurement.json`. |

The static identifier checks are scoped structural evidence, not a formal
information-flow proof. Dynamic perturbation and denied-environment tests
support them. Full source identities are recorded in `stage3a_source_sha256.json`.
An initial development test collection exposed Python 3.9 annotation evaluation;
postponed annotations corrected it in the new package. Final tests pass on the
available runtime, with no legacy compatibility edits.

## Bounded pilot observations

All fixtures are deterministic engineering checks. No parameter was selected
using a full foraging outcome.

| Pilot | Executed fixture and observation | Compute time |
|---|---|---|
| Single cell | 8 updates, initial q=1 and another deposit at t=2. Exponential half-life=2; cutoff timer=4. Analytic decay, refresh and expiry assertions pass. These are fixed implementation fixtures, not a scientific matched comparison. | 0.000194 s |
| Artificial straight trail | One follower, 8 steps, two-cell-wide trail; zero fixture noise and FCRW turn magnitude. Equal sensor readings preserve straight heading. | 0.000704 s |
| Local gap | One follower, 24 steps; empty x cells 10–13. First low sample at step 11, FCRW on step 12. Later signal contact can recruit it again normally; no special recovery search was used. | 0.000911 s |
| Population smoke | N=10, 100 steps, default exponential configuration. Population stays 10 and states remain valid. **No food was discovered and no pheromone was deposited in this short smoke test.** It therefore checks state integrity, not successful colony foraging. | 0.015878 s |
| Relocation integrity | N=2, 10 steps, relocation at step 5. A pickup at 4; ant 0 carries A at relocation; B pickup at 6; A delivery at 8; B delivery at 10. Final A/B discoveries=1/1 and deliveries=1/1. | 0.001027 s |

Total fixed-pilot runtime including JSON output: **0.023459 s**. Pilot output is
**104,616 bytes including its runtime record** (103,949 bytes of fixture data).
These timings exclude Python process startup and are machine-specific; they
are not a projection for a formal experiment. The legacy test suite includes
its existing synthetic/storage fixtures; it did not resume Stage 2C results.

The relocation fixture uses straight trajectories, zero turn/noise, on/off
thresholds of 100 to isolate bookkeeping, and a declared short own-path prefix
for ant 1. This is an artificial contact fixture. Exact settings, initialisation
and step traces are recorded in each pilot JSON.

## Rules that remain provisional

All new behavioural and numeric assumptions remain provisional: arena/nest/food
geometry, endpoint contact detection, population/horizon, movement settings,
sensor spacing/angle, grid width, one-cell deposition footprint, deposit amount
and transporter-only deposition, on/off thresholds, loss streak length, epsilon,
steering gain/turn cap/noise, default half-life, step event order, clipped
boundaries, FCRW schedule consumption at global step indices, unlimited food,
role transitions after contacts, self-path memory capacity/reversal and its
reset after delivery. Every fixture override is provisional too. The entire
default table and evidence labels appear in the specification.

Engineering choices include the independent package, float64 grid, integer cell
timers, nearest-cell lookup, random stream separation, source-provenance ledger
and horizon-bounded storage. They do not establish biological facts. The frozen
FCRW code and mathematical decay identities are confirmed; biological sensor
calibration, empirical lifetime law and scientific performance remain unresolved.

For a future single-deposit match, use
`T_detect = ln(q / threshold) / lambda`, then `ceil(T_detect)` with the specified
1e-12 integer snap. The audit example uses q=1, the on-threshold=0.5 and half-life
20, yielding cutoff_steps=20. Threshold equality remains detectable for the
exponential field while cutoff clears at expiry; this endpoint difference must
be reported. Repeated deposit addition/refresh prevents general equivalence.

## Reproduction and handoff

From the repository root, run tests with no pytest cache, no Python bytecode and
the noninteractive plotting backend:

```sh
PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg python3 -B -m pytest -p no:cacheprovider -q
```

The pilot runner exposes only the fixed tiny fixtures. Use a fresh output path
(the committed pilot directory is intentionally refused):

```sh
PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg python3 -B scripts/run_stage3a_pilot.py --output-dir /tmp/ph6780-stage3a-pilot-review
PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg python3 -B scripts/audit_stage3a.py
```

The protection audit applies to this workspace snapshot, including local-only
protected materials; a fresh clone cannot recreate those untracked files from
Git. It fails rather than silently skipping missing protection inputs.

Delivery is limited to the Stage 3A source, tests, specification, audit scripts
and small engineering evidence. Requested local commit message:
`feat: add Stage 3A scalar decay baseline`. No push, no merge, no Stage 3B,
no recovery C, no formal 20-seed/N=100×12000 experiment, no decay scan/scientific
ablation, no diffusion experiment, no LLM/random/TPE search, no GPU or AutoDL.
**Stop for master acceptance.**
