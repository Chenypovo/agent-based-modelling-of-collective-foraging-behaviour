# Task brief: navigation baseline + H1a

Written 2026-09-30, before the supervisor meeting (moved to 2 Oct). Amended 2026-09-30 with user decisions (see "Amendments"). If the meeting changes the direction,
the user will say so; otherwise execute as below. Read `docs/HANDOFF.md` first.

## Amendments (2026-09-30, user decisions)

- Half-life list changed to {250, 500, 1000, 2000, 4000}; runs lengthened (relocation 12,000, total 36,000).
- No pheromone deposit during spiral search; static efficiency uses all of [0, t_r); fallback rule for Step 2.
- H1a support criterion to be set after results (disclosed in the report).
- Scope: all of H1a, H1b, H2 by 15 Oct.

## Goal

Finish proposal hypothesis **H1a** on a repaired model, for the final report (due 15 Oct 2026).

> H1a (proposal): an intermediate pheromone decay rate reduces median recovery time after food
> relocation relative to lower and higher decay rates, while retaining at least 80% of the
> baseline's static food-retrieval efficiency.

Why a new baseline: the old model (exact retrace home) delivers ~5 times per 12,000 steps, so it
fails the proposal's own adequacy criterion (Section 5.1: "consistently produces ... transport to
the nest"), and earlier endpoints rested on too few events. Stage 5 (exploratory) showed that path
integration fixes this. H1b and H2 (LLM search) are out of scope: report them as future work.

## Fixed decisions (user-approved; do not change)

- Baseline homing = **path integration + landmark correction** (`src/stage5_navigation/path_integration.py`).
  Justification in the report = biology (Collett, Chittka & Collett 2013; Peleg & Mahadevan 2016,
  `from_prof/rsos.160128.pdf`) + our navigation ablation (Step 3). Describe it as "egocentric vs
  egocentric + landmark correction", not "egocentric vs geocentric": there is no landmark-only mode.
- Decay = exponential (proposal Eq. 1), expressed as half-life. **Baseline reference half-life =
  1000 steps** (the validated value). It is NOT tuned; H1a sweeps around it. Ignore Zhang & Yong
  2023's decay setting.
- Diffusion (and detection threshold if needed) IS chosen by calibration (Step 2), using
  model-validity rules written before running, never "which gives the best H1a result".
  Fallback if no D meets every rule: choose the D with the highest follower fraction among those
  where the thin-trail artefact is weakest, and say so in the report.
- Loaded ants do **not** deposit pheromone during the spiral nest search (new option with a test;
  the "off" setting reproduces the current code). The new baseline uses "no deposit during search".
- Static efficiency = all food-A deliveries in [0, t_r), relative to the half-life 1000 condition
  on the same seeds.
- Arena stays 300 × 300 (a 600 × 600 arena was tested and changed nothing), cell size 1,
  100 ants, nest/food geometry as in `scripts/stage5_navigation_experiment.py`.
- Stage 3C (Mechanism FAIL) and 3D (NO_CLEAR_INTERACTION) are closed. Do not rerun or reinterpret.

## Rules for every step

- Write the plan for a step (conditions, seeds, selection rule or test) into the analysis plan
  file BEFORE running it. Do not change it after seeing results; if something must change, record
  the change and the reason.
- Use fresh seed blocks per step. Do not reuse diagnostic seeds 2026093001–2026093010.
  Calibration seeds and H1a seeds must be different blocks.
- New mechanisms are options whose "off" setting reproduces the old behaviour exactly, with a test.
- `python3 -m pytest -q` must pass. Commit on a new branch; do not push or merge without the user.
- Label results honestly: calibration/robustness = exploratory; Step 4 H1a test = the main result.

## Steps

### Step 0 — Analysis plan (short, one file)
`docs/H1A_ANALYSIS_PLAN.md`: everything below with the exact numbers filled in.
Endpoint = proposal Eq. (2) recovery time (use the existing implementation and the Stage 4
amendment: `R_pre = 0` → τ = T_post, non-recovery; T_post = 24,000 in Step 4). Static efficiency = food-A deliveries before
relocation, relative to the baseline half-life 1000 condition.

### Step 1 — Fix the navigation settings (no calibration)
- Path-integration error: **`compass_noise = 0.5`** (user decision). It is a fixed modelling
  assumption, not calibrated to data and not tuned on results; state it as such in the report.
  Step 3 includes 0.5 in its error sweep, which serves as the sensitivity check for this choice.
- Landmark count for the baseline: a medium value fixed in advance (proposed: 100). Keep view
  radius 8, nest cue radius 3, spiral spacing 4, and list them as assumptions in the report.
- Record the homing error the baseline actually produces (median arrival error vs outbound
  distance), so the report can describe what 0.5 means in plain terms.

### Step 2 — Calibrate diffusion (trail physics)
- Grid: D ∈ {0, 0.01, 0.02, 0.05} (check the explicit-scheme stability limit), detection
  thresholds as now (on 0.5 / off 0.25) plus one lower pair if needed. Baseline homing from Step 1,
  half-life 1000, static food, 12,000 steps, ≥10 calibration seeds.
- Selection rule (write before running), e.g. choose the smallest D that satisfies all of:
  1. recruitment actually happens (follower fraction clearly above zero);
  2. the thin-trail artefact is gone: without landmarks, deliveries do not increase when
     path-integration error goes from 0 to a small value;
  3. numerically stable.
- Output: chosen D, and the neighbouring D for Step 5.

### Step 3 — Navigation ablation (justifies the baseline)
Rerun the terrain sweep (exact retrace; path integration at errors 0.1 / 0.3 / 0.5 / 0.6 / 1.0;
landmark counts 0 / 10 / 30 / 100 / 300) under the chosen D, 20 seeds. Report deliveries and homing
error. Expected basis for the choice: landmarks keep homing accurate and make foraging insensitive
to path-integration error. If the baseline does not forage properly here, stop and tell the user.

### Step 4 — H1a (main result)
- Half-lives {250, 500, 1000, 2000, 4000} steps (log-spaced around the 1000 reference; the old
  100 and 10000 extremes were dropped because very short trails risk R_pre = 0 artefacts).
- Longer runs so the pre-relocation reference window holds more deliveries: relocation at step
  **12,000**, **36,000** steps total. Eq. (2) scales with it: T_post = 24,000, reference window
  [9,600, 12,000), w = 0.05 × T_post = 1,200, non-recovery τ = 24,000. Call `amended_endpoint`
  with these constants (relocation, post_horizon, window), not its 6,000/12,000/600 defaults.
- ≥20 seeds, same seeds across half-lives (paired).
- Report separately, per half-life, how many seeds were non-recovery only because R_pre = 0.
- Outcomes: median recovery time (Eq. 2), non-recovery count, static efficiency ratio vs half-life
  1000. Paired bootstrap CIs for "intermediate vs each extreme".
- Support criterion: **the user decided to set it after seeing the results.** The report must state
  plainly that the criterion was chosen after the results were known. Minimum content to report
  regardless: medians, non-recovery counts, paired bootstrap CIs, static efficiency ratios.

### Step 5 — Robustness
Repeat Step 4 at the neighbouring D from Step 2. Report whether the H1a conclusion holds. If it
does not, say the conclusion depends on the diffusion setting.

### Step 6 — Write-up
`results/<new dir>/REPORT.md` with figures (recovery time vs half-life; static efficiency vs
half-life; ablation heatmap), plain limitations, and an update to `docs/HANDOFF.md`.

## Needs the user before or during execution

1. Any change from the supervisor meeting (2 Oct).
2. The H1a support criterion, after Step 4 results.

## Scope and deadline

All work (H1a, then H1b movement heterogeneity, then H2 LLM search) is to be finished by
**15 Oct 2026**. This brief covers H1a only; H1b and H2 get their own briefs after H1a. H2 must first
fix the five Stage 4 issues listed in memory/`docs/HANDOFF.md` and needs the user's API choice.

Not in any brief: obstacles, multiple food sources, landmark-only navigation, new Stage 3 analyses.
