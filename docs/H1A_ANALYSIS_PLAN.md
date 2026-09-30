# H1a analysis plan (navigation baseline + pheromone decay)

Written 2026-09-30, before any Step 1–5 run. Source brief: `docs/TASK_BRIEF_H1A_BASELINE.md`.
Rule: nothing below changes after results are seen. Any change goes in "Deviations" at the bottom
with the date and reason.

Known before writing (disclosed): the Stage 5 exploratory runs (seeds 2026093001–10) already showed,
without the "no deposit during search" change, that D = 0.01 still had the thin-trail artefact
(error 0.1 gave ~3x the deliveries of error 0) and D = 0.05 almost stopped trail following
(follower share ~0.001–0.08). The Step 2 rules were written knowing this.

## Common settings (all steps unless stated)

| Setting | Value |
|---|---|
| Arena, cell size | 300 × 300, cell 1 |
| Ants | 100, step 0.6, contact radius 0.75, deposit q = 1 (loaded ants only) |
| Nest / food A / food B | (150,150) / (240,150) / (150,240) |
| Decay | exponential, half-life 1000 steps unless the step sweeps it |
| Homing (baseline) | path integration, `compass_noise = 0.5`, 100 landmarks, view radius 8, nest cue radius 3, spiral spacing 4 |
| Landmark placement | uniform random, `SeedSequence([seed, 99])` (same as Stage 5 runner) |
| Deposit during spiral search | **off** (new option; "on" reproduces current code) |
| Sensor distance | 1 (= cell size) |
| Detection thresholds | on 0.5 / off 0.25 unless Step 2 selects the lower pair |

`compass_noise = 0.5` is a fixed modelling assumption (user decision), not calibrated to data and not
tuned on results. Nest cue radius, spiral spacing, view radius and landmark count 100 are also fixed
assumptions and will be listed as such in the report.

## Seed blocks (fresh, non-overlapping; checked against all earlier stages)

| Step | Seeds |
|---|---|
| 2 Calibration | 2026210001–2026210010 (10) |
| 3 Navigation ablation | 2026230001–2026230020 (20) |
| 4 H1a main test | 2026240001–2026240020 (20) |
| 5 Robustness | 2026250001–2026250020 (20) |

Diagnostic seeds 2026093001–10 and Stage 4 seeds (2026100101–05, 2026100201–10, 2026101001–05)
are not used.

## Step 1 — Navigation settings (no runs of its own)

Settings as in the table above. Code changes before any run:
1. `NavigationConfig.deposit_during_search` (default `True` = current behaviour). Test: with `True`,
   a seeded run is identical to the current code; with `False`, no deposit happens while a
   transporter is in spiral-search mode.
2. Per trip, record the outbound path length (steps walked since leaving the nest, × step size) at
   pickup, next to the existing arrival error. No effect on dynamics (test: identical trajectories).

Homing-error description (reported, no decision depends on it): from the Step 3 baseline condition
(error 0.5, 100 landmarks) and Step 4 half-life 1000, report median arrival error, and median arrival
error per tertile of outbound path length. Also the same for error 0.5 with 0 landmarks, so the report
can say what 0.5 means with and without landmarks.

## Step 2 — Diffusion calibration

- Grid: D ∈ {0, 0.01, 0.02, 0.05} × threshold pairs {(0.5, 0.25), (0.25, 0.125)} = 8 cells. All D are
  within the explicit-scheme stability limit D·dt/dx² ≤ 0.25. Both threshold pairs are run up front so
  the choice to use the lower pair does not depend on a look at results.
- Per cell, 3 conditions: C1 = error 0, 0 landmarks; C2 = error 0.1, 0 landmarks; C3 = baseline
  (error 0.5, 100 landmarks). Static food A, half-life 1000, 12,000 steps, 10 seeds.
  Total 8 × 3 × 10 = 240 runs.
- Metrics per run: food-A deliveries, follower fraction (share of ant-steps in "follower" role).

Rules (a cell must pass all three):
1. **Recruitment**: median follower fraction in C3 ≥ 0.02.
2. **Thin-trail artefact gone**: A = median over seeds of ln((C2 deliveries + 1)/(C1 deliveries + 1))
   ≤ ln(1.25), i.e. adding small error (0 → 0.1) raises deliveries by at most 25% (paired by seed).
3. **Stable**: D ≤ 0.25 and no run fails the model's validity checks (finite, non-negative field).

Selection:
- Default threshold pair first: choose the smallest D passing all rules.
- If none, the lower threshold pair: smallest D passing all rules.
- Fallback (brief's rule, made exact): among cells passing rules 1 and 3, take those with A within
  ln(1.1) of the lowest A; choose the one with the highest C3 follower fraction (ties: default pair,
  then smaller D). Rule 1 is kept as a gate because a model without trail following cannot test a
  pheromone-decay hypothesis. If no cell passes rule 1, choose the cell with the highest C3 follower
  fraction and flag this to the user before Step 3. The report states that the fallback was used.

Neighbouring D for Step 5 (same threshold pair): of the adjacent grid values, the one that passes
rule 1; if both pass, the larger; if neither, the larger (and Step 5 will say recruitment was absent).

## Step 3 — Navigation ablation (exploratory; justifies the baseline)

- Chosen D and thresholds from Step 2, half-life 1000, static food, 12,000 steps, 20 seeds.
- Conditions: exact retrace + path integration error {0.1, 0.3, 0.5, 0.6, 1.0} × landmarks
  {0, 10, 30, 100, 300} = 26 conditions, 520 runs.
- Outcomes: food-A deliveries, median arrival error, return-trip median, follower fraction.
- Baseline adequacy (stop-and-ask rule): the baseline (0.5, 100 landmarks) must have
  (a) median deliveries ≥ 5 × the exact-retrace median, and (b) ≥ 20 deliveries on every seed.
  If either fails, stop and tell the user; do not start Step 4.
- Descriptive only (no pass/fail): whether landmarks lower arrival error at each error level, and
  the max/min ratio of median deliveries across the five error levels at each landmark count
  (smaller = less sensitive to path-integration error).

## Step 4 — H1a main test

- Half-lives {250, 500, 1000, 2000, 4000} steps. Food A removed and food B opened at step 12,000;
  36,000 steps total. Same 20 seeds for every half-life (paired). 100 runs.
- Recovery time τ = proposal Eq. (2), existing `amended_endpoint(events, relocation=12000,
  post_horizon=24000, window=1200)`. That gives: reference window [9,600, 12,000) for food-A
  deliveries (R_pre); recovery when food-B delivery rate over every window of length w = 1,200 inside
  [t, t + w] stays ≥ 0.8 × R_pre; non-recovery τ = 24,000 (included in medians as 24,000).
  R_pre = 0 → τ = 24,000, non-recovery (Stage 4 amendment); counted separately.
- Static efficiency: E(h, seed) = food-A deliveries in [0, 12,000). Ratio r(h, seed) =
  E(h, seed) / E(1000, seed). Reported per half-life as the median over seeds of r, with a bootstrap
  CI. Seeds with E(1000, seed) = 0 are excluded from the ratio and counted.
- Per half-life report: median τ, number of non-recoveries, of which R_pre = 0, median E, median r.
- Comparisons: intermediate i ∈ {500, 1000, 2000} vs extreme e ∈ {250, 4000} (6 pairs).
  Δ = median τ(i) − median τ(e); 95% percentile CI from a paired bootstrap over seeds
  (10,000 resamples, numpy `default_rng(20261015)`; each resample draws seed indices once and uses
  them for both half-lives). No multiplicity correction; stated in the report.
- Support criterion: **set by the user after seeing these results**. The report says so plainly.

## Step 5 — Robustness at neighbouring D

- Same as Step 4 at the Step 2 neighbouring D (same thresholds), seeds 2026250001–020.
- "H1a conclusion holds" if, for every Step 4 comparison whose CI excluded 0, the Step 5 Δ has the
  same sign, and the user's support criterion gives the same verdict. Otherwise the report says the
  conclusion depends on the diffusion setting.

## Labels and output

- Steps 2, 3, 5 exploratory; Step 4 is the main result.
- Code: new runner `scripts/h1a_run.py` (Stage 5 runner left unchanged); results in
  `results/h1a_baseline/<step>/`; write-up `results/h1a_baseline/REPORT.md`.
- Rough cost: ~30 s per 12,000-step run, ~90 s per 36,000-step run, 8 workers:
  Step 2 ≈ 15 min, Step 3 ≈ 35 min, Steps 4 and 5 ≈ 20 min each.

## Deviations and post-result decisions

- 2026-09-30, **after Step 4 results were seen**: the user set the H1a support criterion to the
  strict rule: H1a is supported only if some intermediate half-life i ∈ {500, 1000, 2000} has
  (a) median τ below both extremes (250 and 4000), (b) paired 95% bootstrap CIs of Δ excluding 0
  for both comparisons, and (c) median static-efficiency ratio ≥ 0.8. Chosen after the results were
  known; the report states this.
- 2026-09-30: runner changed to save each run on completion and resume, 4 workers at low priority
  (first calibration attempt with 9 workers froze the machine and was stopped; no results from it
  were kept or looked at beyond the first ~20 progress lines). No change to conditions or seeds.
