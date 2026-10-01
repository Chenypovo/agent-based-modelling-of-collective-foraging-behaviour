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
| 2 Main test | 2026260001 – 2026260230 (n = 230; user decision, see Step 1 and Deviations) |
| 3 Robustness | 2026270001 – 2026270230 |
| 4 Spread sweep / 4b control | the first 40 Step 2 seeds, 2026260001 – 2026260040 (reuses their homogeneous and 120° runs) |

## Step 1 — number of seeds from existing data (no new runs)

Code: `scripts/h1b_power.py`; output `results/h1b_heterogeneity/power/` (`power.md` for n = 20–100,
`power_extended.md` for n = 150–300).

### How the detection rate is estimated

The question is: "if heterogeneity really made median τ 20% shorter, how often would an experiment
with n paired seeds pass parts (a) and (b) of the verdict rule?" We cannot run H1b to find out, so we
borrow the noise from H1a.

1. **Noise pool.** H1a Step 4 (D = 0.01, 20 seeds) τ for half-life 1000 paired by seed with each of its
   neighbours, 500 and 2000: 40 pairs (τ at 1000, τ at neighbour) from the same seed. Each pair is
   "two slightly different colonies run on the same seed", which is what homo vs het120 is.
2. **Remove any real difference.** For each drawn pair, a coin flip decides which member is "homo" and
   which is "hetero". The pool then has no systematic difference but keeps the real seed-to-seed
   scatter and the real within-seed pairing.
3. **Insert the effect.** Hetero τ × 0.8 for runs that recovered; runs censored at 24,000 stay at
   24,000 (the effect cannot rescue a run that never recovers).
4. **Run the analysis.** Draw n pairs with replacement, apply 2–3, compute Δ = median τ(hetero) −
   median τ(homo) and its paired bootstrap 95% CI (1,000 resamples). "Detected" = Δ < 0 and the CI
   excludes 0. Repeat 1,000 times per n (`default_rng(20261001)`; extension `default_rng(20261002)`).
   The detection rate is the share of the 1,000 that were detected (Monte Carlo error about ±0.03).
5. **Check.** With no effect (step 3 skipped) the false detection rate is ≤ 0.02 at n = 20–100.

### Result

| Data used for the noise pool | n = 20 | 50 | 100 | 150 | 200 | **230** | 250 | 300 |
|---|---|---|---|---|---|---|---|---|
| D = 0.01 (H1a Step 4; used) | 0.12 | 0.29 | 0.46 | 0.63 | 0.76 | **0.82** | 0.85 | 0.91 |
| D = 0.02 (H1a Step 5; sensitivity only) | 0.08 | 0.17 | 0.23 | 0.29 | 0.35 | 0.40 | 0.44 | 0.47 |

Why so many seeds: within-seed differences between neighbouring conditions are large (paired
difference IQR −4,802 to +1,174 steps at D = 0.01; −4,280 to +9,735 at D = 0.02) and 25% of runs
are censored at 24,000, so a 20% shift of the median is small relative to the scatter.

### Assumptions that drive the number (to be repeated in the report)

- **Noise borrowed from half-life pairs.** We assume homo vs het120 on the same seed differ as much as
  half-life 1000 vs 500/2000 on the same seed. If het120 tracks homo more closely (its turns are
  rescaled copies of homo's), the true detection rate is higher; if the two colonies diverge more
  (they likely do after a few hundred steps, because trajectories are chaotic), it is lower.
- **Only 40 pairs from 20 seeds** define the noise shape; a different 20 seeds could give a noticeably
  different number. The D = 0.02 pool, with wider differences, gives 0.40 at n = 230.
- **Effect model:** a 20% shorter τ for recovered runs only, no change in the non-recovery rate. An
  effect that also rescues censored runs would be easier to detect.
- **Only parts (a) and (b) of the verdict rule** are simulated; part (c) (efficiency ratio ≥ 0.8) is
  assumed to pass.
- 20% is a planning value chosen in the brief, not a prediction of the effect size.

### Chosen n

The pre-set rule (smallest n with detection rate ≥ 0.8, capped at 100) gave n = 100 (rate 0.46).
**The user then set n = 230 per condition** (2026-10-01, before any H1b simulation run, having seen
only the Step 1 table above): the smallest n in the extended table with an estimated detection rate
≥ 0.8 (0.82) on the D = 0.01 pool. This exceeds the brief's cap of 100; listed under Deviations.
Step 3 uses the same n.

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
Confirmed by the user on 2026-10-01 before Step 2 ran. Any later change is disclosed in the report.

## Step 3 — robustness at D = 0.02 (exploratory)

Same as Step 2 at D = 0.02, thresholds 0.25 / 0.125, seeds 2026270001 – 2026270230.
"Conclusion holds" if Δ has the same sign as in Step 2 and the verdict rule gives the same verdict;
otherwise the report says the result depends on the diffusion setting.

## Step 4 — spread sweep (exploratory, only if time)

20 / 80 split, matched mean, D = 0.01: θ_scout ∈ {80°, 100°} → θ_recruit = 54.20°, 46.75°
(plus 120° / 37.43° from Step 2 and 60° / 60° = homogeneous). First 40 Step 2 seeds.
Report median τ, Δ vs homo with CI, efficiency ratio. No verdict (40 seeds: low power, descriptive only).

**4b — control for colony spread (exploratory, only if time):** homogeneous colony at 37.432°
(all ants recruit-like), same seeds. If it recovers as fast as or faster than `het120`, an advantage
of `het120` cannot be attributed to heterogeneity itself.

## Output and cost

- Runner `scripts/h1b_run.py` (save per run, resume, ≤ 4 workers, `nice 10`); summary
  `scripts/h1b_summarise.py`; results in `results/h1b_heterogeneity/<step>/`; write-up
  `results/h1b_heterogeneity/REPORT.md`.
- Cost: ~55–75 s per 36,000-step run (H1a Steps 4–5 median 66–77 s; reproduction check 53 s). With
  4 workers, Step 2 with n = 230 is 460 runs ≈ 2–2.5 h; Step 3 the same; Step 4 + 4b ≈ 120 runs
  ≈ 35 min.

## Deviations and post-result decisions

- 2026-10-01, **after Step 1, before any H1b simulation run** (only the H1a-based detection-rate table
  had been seen): the user confirmed the default verdict rule and raised n from 100 (cap in the brief)
  to **230 per condition**, the smallest n with estimated detection rate ≥ 0.8 (0.82 on the D = 0.01
  pool; `power_extended.md`). Step 2 seeds 2026260001–230, Step 3 seeds 2026270001–230.
- 2026-10-01: before Step 2, the homogeneous condition of `scripts/h1b_run.py` was run once on H1a
  seed 2026240001 (half-life 1000) and reproduced the stored H1a delivery times and τ exactly
  (`results/h1b_heterogeneity/check/`). Not an H1b data run.
