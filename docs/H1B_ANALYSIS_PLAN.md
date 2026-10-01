# H1b analysis plan (movement heterogeneity)

Written 2026-10-01, before any H1b simulation run. Source brief: `docs/TASK_BRIEF_H1B.md`.
Rule: nothing below changes after results are seen. Any change goes in "Deviations" at the bottom
with the date and reason.

> **H1b** (proposal): with mean movement persistence held constant, a colony with bounded scout-like
> and recruit-like movement heterogeneity has a shorter median recovery time than a homogeneous colony.

## Common settings (= H1a baseline, `docs/H1A_ANALYSIS_PLAN.md`, Step 4)

| Setting | Value |
|---|---|
| Arena, cell, ants | 300 × 300, cell 1, 100 ants, step 0.6, contact radius 0.75, deposit q = 1 |
| Nest / food A / food B | (150,150) / (240,150) / (150,240); A removed and B opened at step 12,000 |
| Horizon | 36,000 steps |
| Homing | path integration, compass noise 0.5, 100 landmarks (`SeedSequence([seed, 99])`), view radius 8, nest cue radius 3, spiral spacing 4, no deposit during spiral search |
| Trail physics | D = 0.01, thresholds on 0.25 / off 0.125 (halved from 0.5 / 0.25 by the H1a Step 2 rule) |
| Decay | exponential, half-life 1000 |
| FCRW | gamma 0.2, `theta_max` 60° (homogeneous) |
| Endpoint | τ = Eq. (2), `amended_endpoint(relocation=12000, post_horizon=24000, window=1200)`; R_pre = 0 → τ = 24,000 non-recovery (Stage 4 amendment); non-recovery counted as 24,000 in medians |

## What changes: per-ant FCRW turning amplitude only

Code: `src/stage5_navigation/heterogeneity.py`, class `HeterogeneousPISimulation`
(subclass of the H1a `PathIntegrationSimulation`). Only `theta_max` of the FCRW turn generator differs
between ants; sensing, pheromone response (follower steering), homing and contacts are identical.
FCRW turns are used only while an ant is searching (role "fcrw"); followers and transporters are
unaffected. Each ant's turns are regenerated from the same random stream as in the homogeneous colony,
so ant i's turns are exactly (θ_i / 60°) × its homogeneous turns (common random numbers).

Tests (`tests/test_stage5_heterogeneity.py`): with all θ = 60° (or no per-ant list) the run is
identical to `PathIntegrationSimulation` (events, positions, field); turns rescale as stated;
persistence formula matches the generator; matched-mean solution. Before Step 2, one extra check:
the H1b runner's homogeneous condition on H1a seed 2026240001 (half-life 1000) must reproduce the
stored H1a delivery times exactly.

### Mean persistence held constant

FCRW turn = random sign × magnitude, magnitude ~ U(0, θ). Per-step persistence
c(θ) = E[cos(turn)] = sin θ / θ (sign does not matter). Checked against the generator
(2,000,000 turns each): c(60°) = 0.82699 (generator 0.82701), c(120°) = 0.41350 (0.41357).

Matched mean: 0.2 c(θ_scout) + 0.8 c(θ_recruit) = c(60°) = 0.82699.

Largest spread with both values in [20°, 120°]:
- θ_scout = 120° → c(θ_recruit) = (0.82699 − 0.2 × 0.41350) / 0.8 = 0.93037 → **θ_recruit = 37.432°**
  (bisection on sin θ / θ; generator check 0.93038).
- The other end is not feasible: θ_recruit = 20° (c = 0.97980) would need c(θ_scout) = 0.21570,
  i.e. θ_scout = 146.5° > 120°.

So the primary contrast is **20 ants at 120° ("scout-like") + 80 ants at 37.432° ("recruit-like")**
vs **100 ants at 60°**. The runner computes θ_recruit with `matched_theta` (not a rounded number).
Which 20 ants are scouts is drawn per seed with `SeedSequence([seed, 77])`, independent of every
simulation stream.

Labels: Fernández-López et al. (2025) is cited in the proposal but the paper is not in `from_prof/`
or `reports/`, so "wide turns = scout-like, narrow turns = recruit-like" is **our assumption**, not a
mapping checked against that study.

### Known limitation, written before running

Matching mean per-step persistence does **not** match how far the colony spreads. From the FCRW
generator (gamma 0.2, 200 walks of 2,000 steps, free space), RMS displacement is 207 at 37.4°,
133 at 60°, 58 at 120°; the heterogeneous colony's mean squared displacement corresponds to an RMS
of ~187 vs 133 for the homogeneous one. A difference between the colonies may therefore come from
"most ants walk straighter" rather than from heterogeneity itself. The optional control in Step 4b
addresses this; it is exploratory and does not change the verdict rule.

## Seed blocks (fresh; no overlap with any earlier stage — checked by grep of the repository)

| Step | Seeds |
|---|---|
| 2 Main test | 2026260001 – 2026260100 (n = 100, Step 1) |
| 3 Robustness | 2026270001 – 2026270100 |
| 4 Spread sweep / 4b control | the first 40 Step 2 seeds, 2026260001 – 2026260040 (reuses their homogeneous and 120° runs) |

## Step 1 — number of seeds from existing data (no new runs)

Data: H1a Step 4 (D = 0.01) τ for half-life 1000 and its neighbours 500 and 2000, paired by seed:
pairs (1000, 500) and (1000, 2000), 40 pairs. These stand in for "two different conditions on the
same seeds".

Simulation (`scripts/h1b_power.py`, `default_rng(20261001)`):
1. For n ∈ {20, 30, 40, 50, 60, 70, 80, 90, 100}, repeat 1,000 times: draw n pairs with replacement
   from the pool; randomly swap the two members of each pair (so the two "conditions" have no built-in
   difference); call one member homo, the other hetero.
2. Effect: hetero τ × 0.8 for recovered runs; non-recovered runs stay at 24,000 (conservative: the
   effect cannot rescue a censored run).
3. Paired bootstrap 95% CI of Δ = median τ(hetero) − median τ(homo), 1,000 resamples.
   "Detected" = Δ < 0 and the CI excludes 0.
4. Also with no effect (check that false detections ≈ 2.5%).

Choice: the smallest n whose detection rate is ≥ 0.8; if none reaches 0.8, n = 100 (cap) and the
report states the expected detection rate. Sensitivity (reported, not used for the choice): the same
calculation on the H1a Step 5 (D = 0.02) data.

**Chosen n = 100 per condition** (filled in 2026-10-01 by Step 1, before any simulation run;
`results/h1b_heterogeneity/power/power.md`). No n reached 0.8: the estimated detection rate for a 20%
shorter median τ is 0.12 at n = 20, 0.29 at n = 50 and **0.46 at n = 100** (D = 0.02 data: 0.23 at
n = 100). False detections with no effect: ≤ 0.02. Reasons: paired τ differences are very wide
(IQR −4,802 to 1,174 steps) and 25% of runs are censored at 24,000. Consequence for reading Step 2:
a "not supported" verdict at n = 100 is weak evidence that heterogeneity has no effect.

## Step 2 — main test (paired)

- Conditions: `homo` (100 × 60°) and `het120` (20 × 120° + 80 × 37.432°); same n seeds.
- Outcomes per run: τ, non-recovery, R_pre, food-A deliveries in [0, 12,000), B delivery times,
  follower fraction, and descriptive per-group counts (pickups by scouts / recruits, group of the first
  B discoverer).
- Primary: median τ per condition; Δ = median τ(het) − median τ(homo) with a paired bootstrap 95%
  percentile CI (10,000 resamples, `default_rng(20261007)`, same seed indices for both conditions).
  Non-recovery counts and how many have R_pre = 0.
- Static efficiency: E = food-A deliveries in [0, 12,000); per-seed ratio E(het) / E(homo); median
  ratio with bootstrap CI. Seeds with E(homo) = 0 are excluded from the ratio and counted.
- Secondary, descriptive, never used for the verdict: time from 12,000 to the first B delivery; number
  of B deliveries in [12,000, 18,000) (median [IQR] per condition, and paired median difference).

### Verdict rule (brief's default, written before running)

H1b is **supported** only if (a) median τ(het) < median τ(homo), (b) the 95% CI of Δ excludes 0, and
(c) the median static-efficiency ratio is ≥ 0.8. Otherwise "**not supported**".
The user must confirm or change this rule before Step 2 runs; any later change is disclosed in the report.

## Step 3 — robustness at D = 0.02 (exploratory)

Same as Step 2 at D = 0.02, thresholds 0.25 / 0.125, seeds 2026270001 – 2026270100.
"Conclusion holds" if Δ has the same sign as in Step 2 and the verdict rule gives the same verdict;
otherwise the report says the result depends on the diffusion setting.

## Step 4 — spread sweep (exploratory, only if time)

20 / 80 split, matched mean, D = 0.01: θ_scout ∈ {80°, 100°} → θ_recruit = 54.20°, 46.75°
(plus 120° / 37.43° from Step 2 and 60° / 60° = homogeneous). First 40 Step 2 seeds.
Report median τ, Δ vs homo with CI, efficiency ratio. No verdict.

**4b — control for colony spread (exploratory, only if time):** homogeneous colony at 37.432°
(all ants recruit-like), same seeds. If it recovers as fast as or faster than `het120`, an advantage
of `het120` cannot be attributed to heterogeneity itself.

## Output and cost

- Runner `scripts/h1b_run.py` (save per run, resume, ≤ 4 workers, `nice 10`); summary
  `scripts/h1b_summarise.py`; results in `results/h1b_heterogeneity/<step>/`; write-up
  `results/h1b_heterogeneity/REPORT.md`.
- Cost: ~70 s per 36,000-step run (H1a Steps 4–5 median 66–77 s). With 4 workers, Step 2 with
  n = 100 is 200 runs ≈ 1 h; Step 3 the same; Step 4 + 4b ≈ 120 runs ≈ 35 min.

## Deviations and post-result decisions

_None yet._
