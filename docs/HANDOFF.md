# Handoff

New session: read this file first, then do **Next task** only. Keep process light: code + tests + a
short REPORT.md, no new preregistration or receipt machinery unless the task says so.

Last updated: 2026-10-03 (paper baseline done on branch `paper-baseline`; next: H1a/H1b reruns on it).

## Project in one paragraph

NTU PH6780 supervised research (student Yipeng Chen, supervisor Dr Yong Ee Hou). Agent-based model of
ant collective foraging with a scalar pheromone field. After the Sep 2026 meeting the focus moved to
**how ants get home**: egocentric path integration versus geocentric landmark correction, across
terrains, and the effect on colony foraging and adaptation after food relocation. The LLM
search-benchmark layer (Stage 4) is **paused** until the physics model is settled.

## Where things are

| Item | Location |
|---|---|
| **Paper baseline (current model)** | `src/paper_baseline/` (`model.py` options, `checks.py` five checks); plan `docs/PAPER_BASELINE_PLAN.md`; report `results/paper_baseline/REPORT.md`; scripts `scripts/paper_baseline_{run,summarise,figures}.py` |
| Validated scalar model (do not edit) | `src/scalar_baseline/` |
| Stage 5 navigation code | `src/stage5_navigation/` (`model.py` coarse return, `path_integration.py`, `diffusion.py`) |
| Stage 5 tests | `tests/test_stage5_*.py` |
| Stage 5 experiment / summary scripts | `scripts/stage5_navigation_experiment.py`, `scripts/stage5_summarise_navigation.py` |
| Stage 5 results and write-up | `results/stage5_diagnostics/navigation/REPORT.md` (field-shape diagnosis: `.../field_shape/REPORT.md`) |
| H1a plan / results / report | `docs/H1A_ANALYSIS_PLAN.md`, `results/h1a_baseline/REPORT.md`, runner `scripts/h1a_run.py`, rules+stats `scripts/h1a_summarise.py` |
| Meeting deck 1 Oct | `meeting_materials/2026-10-01/` (untracked) |
| Stage 4 LLM harness (paused) | `src/scalar_baseline/stage4_*.py`, `docs/STAGE4_*.md` |

Git: H1a work on branch `h1a-baseline` (not pushed/merged); Stage 5 on `stage5-navigation-diagnosis`; `main` on GitHub includes everything up to the Stage 5
commit. Local `git push` over HTTPS is unreliable; large pushes may need to go commit by commit.

## Fixed decisions (do not change)

- Stage 3C = Mechanism FAIL, Stage 3D = NO_CLEAR_INTERACTION. Closed; no extra seeds or reruns.
- Negative results are kept and reported as such.
- Stage 5 results so far are exploratory (diagnostic seeds 2026093001-10), not confirmatory.
- The validated model must stay reproducible: new mechanisms are subclasses/options whose "off" setting
  reproduces the old behaviour exactly, with a test proving it.

## What we know (Stage 5, exploratory)

- Robust: a home vector (path integration) beats exact retrace; landmarks rescue noisy path integration.
- Not robust: "small error beats zero error" and "landmarks hurt precise ants" depend on trail width
  vs sensor spacing (1 unit) and detection threshold; they change with cell size and diffusion.
- Open issues: trail physics (diffusion, threshold) not yet justified; path-integration error, nest
  perception radius (3), spiral spacing (4), landmark view radius (8) are assumptions; ants have no
  food-vector memory.

## H1a status (done 2026-09-30)

- New baseline: path integration (compass noise 0.5) + 100 landmarks, no deposit during spiral search,
  diffusion D = 0.01 with thresholds 0.25/0.125 (only 1 of 8 calibration settings passed the rules).
- Step 3: baseline forages (median 692 vs 10 for exact retrace). Thin-trail artefact persists between
  error 0.1 and 0.3; landmarks make homing accurate/stable but lower deliveries.
- **H1a not supported** (strict criterion, chosen by the user after results). Only 2000 < 4000 was
  clear at D = 0.01, and it shrank to nothing at D = 0.02. Half-life 250 costs static efficiency badly.
- Runs: max 4 workers, low priority (9 workers froze the Mac). Runner saves per run and resumes.

## H1b status (in progress, 2026-10-02 00:20)

Branch `h1b-heterogeneity` (from `h1a-baseline`, not pushed). Plan `docs/H1B_ANALYSIS_PLAN.md`
(n = 230 per condition, user decision before Step 2; verdict rule = brief default, user-confirmed).
- Part A done (commit 7afc6c8). Step 0/1 done. Runner `scripts/h1b_run.py`, stats `scripts/h1b_summarise.py`.
- Step 2 (D = 0.01): **not supported, opposite direction**: median τ het120 13,184 vs homo 10,844,
  Δ = +2,341 [721, 4,148]; static efficiency ratio 1.09 [1.02, 1.17]. `results/h1b_heterogeneity/main/summary.md`.
- Step 3 (D = 0.02, exploratory): same direction, Δ = +2,389 [321, 4,694]; efficiency 1.19 [1.09, 1.36].
  `results/h1b_heterogeneity/robust/summary.md`.
- Remaining: Step 4 (`python3 scripts/h1b_run.py sweep`, 120 runs ~35 min, then `h1b_summarise.py sweep`;
  includes the homo-37.43° control for the colony-spread confound) — user to decide; Step 5 REPORT.md
  + this file.

## Paper baseline status (done 2026-10-03, branch `paper-baseline`, not pushed)

- Paper rules (stride-3 return) did not organise the colony with or without Eq. (1) decay/diffusion
  (Steps 2–3, ψ = 0.64). User decisions after failures, recorded before the next run: Amendment A =
  path-integration homing (no landmarks); Amendment B = 20,000-step runs, late windows +8,000.
- **Baseline:** FCRW γ 0.1 Θ 50°, home vector with compass noise 0.1, T → f with 180° turn, half-life
  2000, D = 0.01, thresholds 0.25/0.125, 300 × 300 reflective, nest (150, 150), food 90 away on 45°.
  Chosen by the fallback rule (no cell reached basic pass in calibration).
- **Validation (20 seeds):** checks 1–4 pass 20/20; check 5 medians at full level (ψ 0.940, φ 0.704,
  5.9 foragers) but only 14/20 seeds (16 needed) → **check 5 formally not passed**. Pheromone-off
  fails 2, 3, 5 (order comes from pheromone). ZW arm: full pass (16/20). Arena 600: check 5 fails
  (depends on arena size). Paper layout: check 5 20/20, check 1 fails (food twice as far).
- Basic tier has a design flaw (φ line needs ≲ 13 foragers, tier allows 25); reported, not changed.
- Per-run JSON files are untracked (~230 MB); summaries, plan and report are committed.

## Supervisor feedback from 2 Oct meeting

_To fill in after the meeting._

## Next task

Paper baseline is done (`results/paper_baseline/REPORT.md`). Next: rerun **H1a/H1b on the paper
baseline** (brief to be written by the master session), then H2. Deadline 15 Oct. Constraints from
the baseline: relocate food at 20,000 steps (not 12,000); start from σ = 0.1 home vector without
landmarks; report that the baseline did not formally pass check 5 (14/20 seeds). Supervisor asked
for self-explanatory figures (line plots, one sentence each).

**Done means:** tests pass (`python3 -m pytest -q`), results + REPORT.md written, committed on a branch,
this file updated (status, what changed, next task).
