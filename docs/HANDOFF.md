# Handoff

New session: read this file first, then do **Next task** only. Keep process light: code + tests + a
short REPORT.md, no new preregistration or receipt machinery unless the task says so.

Last updated: 2026-09-30 evening (H1a done; supervisor meeting moved to 2 Oct).

## Project in one paragraph

NTU PH6780 supervised research (student Yipeng Chen, supervisor Dr Yong Ee Hou). Agent-based model of
ant collective foraging with a scalar pheromone field. After the Sep 2026 meeting the focus moved to
**how ants get home**: egocentric path integration versus geocentric landmark correction, across
terrains, and the effect on colony foraging and adaptation after food relocation. The LLM
search-benchmark layer (Stage 4) is **paused** until the physics model is settled.

## Where things are

| Item | Location |
|---|---|
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

## Supervisor feedback from 2 Oct meeting

_To fill in after the meeting._

## Next task

Do `docs/TASK_BRIEF_H1B.md` (Part A: small H1a text fixes; Part B: H1b movement heterogeneity).
Then H2 (LLM search) after fixing the five Stage 4 issues and getting the user's API choice. Deadline 15 Oct.

**Done means:** tests pass (`python3 -m pytest -q`), results + REPORT.md written, committed on a branch,
this file updated (status, what changed, next task).
