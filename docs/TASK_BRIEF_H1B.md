# Task brief: H1a housekeeping + H1b (movement heterogeneity)

Written 2026-10-01 by the master session. Read `docs/HANDOFF.md` first. Same process as H1a:
plan file before runs, fresh seed blocks, ≤ 4 workers at low priority, save per run, commit on a
new branch from `h1a-baseline`, do not push or merge without the user. Deadline for everything
(H1b, then H2): 15 Oct 2026, so aim to finish H1b by about 7 Oct.

## Part A — H1a housekeeping (no reruns, no change to any H1a number or verdict)

The master session independently recomputed all 40 H1a/robustness endpoints from the stored delivery
times: 0 mismatches. H1a stays as it is. Only:

1. `results/h1a_baseline/REPORT.md`: state explicitly that the detection thresholds were **halved**
   from the original 0.5 / 0.25 to 0.25 / 0.125, and that the Step 2 rule selected this.
2. `docs/HANDOFF.md`: remove the stale "loaded ants deposit during spiral search" (the baseline does not).
3. Optional, descriptive only: from the stored `runs.json` (no new simulation), add per half-life
   the time to first food-B delivery after relocation and the number of B deliveries in
   [12,000, 18,000). Label it "post-hoc description; not used for the H1a verdict".

## Part B — H1b

> H1b (proposal): with mean movement persistence held constant, a colony with bounded scout-like and
> recruit-like movement heterogeneity has a shorter median recovery time than a homogeneous colony.

### Fixed decisions

- Baseline = the H1a baseline exactly: path integration (compass noise 0.5) + 100 landmarks, no
  deposit during spiral search, D = 0.01, thresholds 0.25 / 0.125, half-life 1000, 300 × 300,
  100 ants, relocation at 12,000, 36,000 steps, Eq. (2) with T_post 24,000, w 1,200 (Stage 4
  R_pre = 0 amendment).
- Movement heterogeneity = **only** the FCRW turning amplitude (`theta_max`, currently 60°) differs
  between two groups of ants; everything else (sensing, pheromone response, homing) is identical.
  Implement as an option (per-ant `theta_max`) whose homogeneous setting reproduces the H1a baseline
  exactly, with a test.
- "Mean persistence held constant": choose the two group values so the colony mean of the per-step
  persistence c = E[cos(turn)] (measured from the FCRW generator, not from the simulation outcome)
  equals that of the homogeneous 60° colony. Show the calculation in the plan.
- Primary contrast, fixed before running: 20% low-persistence ants ("scout-like": wider turns) and
  80% high-persistence ants ("recruit-like"), with the spread chosen as the largest that keeps every
  `theta_max` within [20°, 120°] under the matched mean. If Fernández-López et al. (2025) is available
  in `from_prof/` or `reports/`, check whether its scout/recruit mapping agrees; if not available,
  call the labels an assumption.

### Steps

0. **Plan** `docs/H1B_ANALYSIS_PLAN.md` with all numbers, written and committed before any run.
1. **Seed count from existing data (no new runs).** Use the stored H1a runs (half-life 1000 and its
   neighbours) to estimate the spread of paired differences in τ, then pick the number of seeds per
   condition that gives a reasonable chance of detecting a 20% change in median τ (bootstrap or
   simulation; show the method). Cap at 100 seeds per condition. Record the chosen n in the plan.
2. **Main test.** Homogeneous vs heterogeneous, same seeds (paired), n from Step 1.
3. **Robustness (exploratory).** Repeat at D = 0.02 with the same thresholds, as in H1a.
4. **Exploratory spread sweep** (only if time): a few spreads at the same 20/80 split and matched mean.
5. **Write-up** `results/h1b_heterogeneity/REPORT.md` + update `docs/HANDOFF.md`.

### Outcomes

- Primary: median τ (Eq. 2) per condition; paired bootstrap 95% CI of Δ = median τ(hetero) −
  median τ(homo); non-recovery counts (and how many are R_pre = 0).
- Static efficiency: food-A deliveries in [0, 12,000), median per-seed ratio hetero / homo.
- Secondary, descriptive, fixed in the plan before running (never used for the verdict): time to
  first B delivery after relocation; B deliveries in [12,000, 18,000).

### Verdict rule (default; written before running)

H1b is supported only if median τ(hetero) < median τ(homo), the 95% CI of Δ excludes 0, and the
median static-efficiency ratio is ≥ 0.8. Otherwise "not supported". If the user wants a different
rule, the user must say so **before Step 2 runs**; any later change must be disclosed in the report.

## Needs the user

- Confirm or change the verdict rule before Step 2 runs.
- Any change from the 2 Oct supervisor meeting.

## Out of scope

H2 (separate brief after H1b), changes to H1a numbers, new navigation mechanisms, obstacles.
