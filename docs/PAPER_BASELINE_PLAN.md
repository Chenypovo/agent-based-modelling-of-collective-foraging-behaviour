# Paper baseline plan: Zhang & Yong (2023) rules + Eq. (1) field + five static checks

Written 2026-10-02, before any run. Implements `docs/TASK_BRIEF_PAPER_BASELINE.md`; where this file
adds detail the brief left open, it is marked **(clarification)**. Branch `paper-baseline` (from
`h1b-heterogeneity`). Nothing here is pushed or merged without the user.

## 1. Model

New module `src/paper_baseline/` with `PaperSimulation(scalar_baseline.simulation.Simulation)`.
`src/scalar_baseline/` is not edited. Every new rule is an option; with all options at "off" the
class must reproduce `Simulation` exactly (test: identical positions, roles, field, ledger).

| Option | Off (current) | On (paper baseline) |
|---|---|---|
| `walk` | `fcrw` | `fcrw` (baseline) or `zw` (comparison arm) |
| `boundary` | `clamp` | `reflect` (specular, reusing `colony.environment.SquareEnvironment.reflect_move`) |
| `return_stride` | `1` exact retrace, one vertex per step | `3`: keep vertices 0, 3, 6, …, last (`colony.agents.coarse_grain_path`), walk the reversed route at 0.6 path length per step (`colony.agents.advance_transporter_route`, interpolated; a step can pass a waypoint) |
| `after_delivery` | `forager` | `follower`, heading turned by 180° |
| `deposit` | on | on, or `off` for the pheromone-off control |
| field | `ScalarField` | `DiffusingField` (Eq. 1); a no-decay variant (decay rate 0) for Step 2 only |

Fixed settings (all from the brief or the validated B0 defaults): N = 100; step 0.6; γ = 0.1,
Θ = 50°; q = 1 per transporter step (deposited at the position after the move, as now); cell size 1;
field edge P = 0; sensing = existing bilateral sensors (distance 1, ±45°), max turn 60°, follower
noise ±0.05 rad; contact radius 0.75 for nest and food; food inexhaustible; all ants start at the
nest as foragers with uniform random headings.

**(clarification)** Rules in detail:
- Forager (`fcrw` role): FCRW/ZW turn sequence pre-generated per ant (as now); becomes follower
  when max(left, right) ≥ on-threshold; becomes transporter on food contact.
- Path memory = every vertex since the ant last left the nest (reset at delivery to the ant's
  position, which is within the 0.75 nest radius — existing behaviour; corrected wording, Step 1). It is kept unchanged through forager ↔ follower switches. On food pickup the route is
  coarse-grained from this memory, so repeated trips straighten the route.
- Transporter: follows the route, ends exactly at the nest vertex; on nest contact it delivers,
  memory resets, heading += 180°, role = follower, loss counter = 0. Transporters do not sense.
- Follower: existing scalar trail following; on food contact → transporter. If the signal stays
  below the off-threshold for `loss_steps` = 2 consecutive steps (the existing B0 value) it reverts
  to forager (our addition, not in the paper). Nest contact by a follower changes nothing.
- Order parameters (Eqs. 15–17) use each ant's displacement direction over the last step
  (Eq. 15), folded to [−π/2, π/2) (`colony.metrics.compute_order_parameters`), over all N ants,
  every step. A zero displacement (cannot normally happen) falls back to the heading.

## 2. Five static checks (as in the brief; operational details)

A condition passes a check if the **median meets it and ≥ 80% of seeds meet it** (16/20 in
validation; **(clarification)** 8/10 in Steps 2–3, which use 10 seeds).

| Check | Exact measurement | Pass |
|---|---|---|
| 1 Discovery | time of first food pickup (no pickup → 12,000) | ≤ 4,000 |
| 2 Recruitment | pickups in [4,000, 12,000) where the ant's role just before contact was follower ÷ all pickups in that window (no pickups → 0) | ≥ 50% |
| 3 Trail | pheromone in cells whose centre is ≤ 5 units from the nest–food segment ÷ total pheromone, at t = 10,000 (total 0 → 0) | ≥ 50% |
| 4 Transport | deliveries in [6,000, 12,000); R² of a straight-line fit to cumulative deliveries vs time in that window | ≥ 100 and **(clarification)** R² ≥ 0.95 |
| 5 full | means over [10,000, 12,000): ψ, φ, foragers | ψ ≥ 0.9, \|φ − π/4\| ≤ 0.1, foragers ≤ 10 |
| 5 basic | same | ψ ≥ 0.8 and ψ ≥ ψ_off(same seed) + 0.1; \|φ − π/4\| ≤ 0.1; foragers ≤ 25 |

ψ_off is the pheromone-off run on the same seed and layout. "Full pass" = checks 1–4 + 5 full;
"basic pass" = checks 1–4 + 5 basic. Pheromone-off must **fail** checks 2, 3 and 5 (basic).
For the paper-layout arm (20,000 steps) the same windows are used, plus ψ, φ over [18,000, 20,000)
reported for comparison with Fig. 4.

## 3. Runs and seeds

Fresh seed blocks (prefixes 202628–202630 appear nowhere in the repo). Within a step, every
condition uses the same seeds (paired comparisons). Runs save one JSON each and resume.
≤ 4 workers, `nice` 10.

| Step | Conditions | Seeds | Runs |
|---|---|---|---|
| 2 Paper-faithful (exploratory) | no decay, D = 0, FCRW, thresholds 0.5/0.25 **(clarification)**; + pheromone-off | 2026280001–010 | 20 |
| 3 Calibration (exploratory) | half-life {500, 1000, 2000} × D {0, 0.01, 0.02} × thresholds {0.5/0.25, 0.25/0.125} = 18 cells; + one pheromone-off **(clarification: with no deposit the field is always 0, so one off-run per seed serves every cell)** | 2026290001–010 | 190 |
| 4 Validation | chosen cell; ZW; arena 600 (nest (300, 300), food at 90 on 45°); paper layout (nest (90, 90), food (240, 240), 20,000 steps); each with its own pheromone-off control | 2026300001–020 | 160 |

Layouts: standard nest (150, 150), food A (150 + 90/√2, 150 + 90/√2), food B (150 − 90/√2,
150 + 90/√2) (B unused here: no relocation). Arena 600: same offsets from (300, 300). Paper layout:
food A (240, 240), distance 212.13; food B is required by the config but unused, placed at the
same distance on the 30° axis, (273.71, 196.07).

Selection rule (brief): among full-pass cells, most median deliveries in [6,000, 12,000); if none,
among basic-pass cells; ties within 5% → smaller D, then half-life 1000 (then, if still tied,
**(clarification)** thresholds 0.5/0.25). No basic-pass cell → stop and report.

## 4. Saved per run

Summary (check metrics, pickups by role, deliveries, first pickup time); time series every 10 steps
of ψ, φ, F/T/f counts and cumulative deliveries; ant positions + roles at t = 1,000 / 4,000 /
10,000; field array at t = 10,000 for the first 3 seeds of each condition only (storage).

## 5. Tests (Step 1)

All-off reproduces `Simulation`; stride-3 coarse-graining keeps 0, 3, 6, …, last and the transporter
moves 0.6 per step along it and ends at the nest; T → f with a 180° turn on delivery; reflective
boundary keeps ants inside and mirrors the heading; pheromone-off leaves the field at zero; no-decay
field keeps mass; ψ = 1 for aligned headings, ψ ≈ 2/π for uniform headings; check-metric functions
on hand-made inputs.

## 6. What is decided by the user, not by results

Thresholds above can change only before Step 3. If no calibration cell reaches basic pass, the
user decides what to relax. Step 2 and 3 are exploratory; only Step 4 is the validation.

## 7. Amendment A (2026-10-02, user decision after Step 3 failed; written before any Step 3b run)

**What happened.** Step 2 (paper-faithful, no decay) and Step 3 (18 Eq. (1) cells, stride-3
coarse-grained return) both failed: no cell reached basic pass; ψ ≈ 0.64 in every cell (= random
headings), trail share ≤ 5%, ≤ 22 deliveries in [6,000, 12,000). Diagnosis (seed 2026280001): the
stride-3 return removes only small zigzags, so the return is ~95% as long as the outbound search
(e.g. 823 vs 149 steps for a straight line); within 12,000 steps each ant makes too few trips for
repeated coarse-graining to straighten anything, and the meandering returns lay pheromone over
the arena (slow decay: 67% of the arena above the on-threshold) or too faintly (fast decay: < 1%).
Step 2 and Step 3 results are kept and reported as failed (`results/paper_baseline/{paper,calib}/`).

**Change (user, 2026-10-02).** Transporters return by **path integration**: each ant integrates its
own displacement every step with Gaussian compass noise of SD σ (radians per step); a transporter
walks straight toward its estimated nest. No landmarks. Implementation as Stage 5 / H1a
(`stage5_navigation.path_integration`): the nest is perceived within 3 units; if the estimate says
"home" but the nest is not perceived, the ant spiral-searches (spacing 4) and lays no pheromone
while searching; on delivery the seen nest resets the estimate. All other rules unchanged
(T → f with 180° turn, FCRW γ = 0.1 Θ = 50°, reflective walls, Eq. (1) field, bilateral sensing,
follower → forager after 2 low steps). Implemented as option `homing="vector"`; "off" unchanged.

**Why.**
1. The paper itself (p. 6, Sec. IV) states that foraging ants can memorise the nest location "using
   landmarks and path integration" and so travel home from the food "with little difficulty"; the
   stride-3 memory is its simplification.
2. The paper's own argument for the coarse-grained memory is its limit: repeated coarse-graining of a
   path eventually leaves "a straight path connecting the nest and the food source". A straight home
   vector is that end state reached directly; Step 2–3 show the limit is not reached in 12,000 steps.
3. Supervisor: the Sep 2026 sketch shows a return path much straighter than the outbound search; his
   teaching MATLAB model has transporters walk straight to the nest; and he asked us to study
   egocentric (path integration) vs geocentric navigation, for which this is the egocentric baseline.

**Step 3b calibration** (exploratory; replaces Step 3 for the selection): σ ∈ {0, 0.1, 0.3} ×
the same 18 Eq. (1) cells = 54 cells, plus a pheromone-off run per σ (ψ_off for the basic tier is
taken from the off-run with the same σ and seed), seeds **2026310001–010** (fresh), 570 runs.
Checks, tiers and selection rule unchanged (full pass first, then basic; most median deliveries in
[6,000, 12,000); ties within 5% → smaller D, then half-life 1000, then thresholds 0.5/0.25, then
most deliveries). If no cell reaches basic pass: stop and report. Step 4 then uses the chosen
(σ, half-life, D, thresholds) with seeds 2026300001–020 as planned.

## 8. Amendment B (2026-10-03, user decision after Step 3b; written before any Step 3c run)

**What happened (Step 3b, `results/paper_baseline/calib2/`).** With path-integration homing, checks
1–4 passed in about 30 of 54 cells (best: ~1,300 deliveries in [6,000, 12,000), trail share
0.55–0.87, ψ up to 0.88), but **no cell passed check 5 at either tier**. The binding criterion was φ:
no cell median and no single run reached |φ − π/4| ≤ 0.1 (best median 0.616, best run 0.666; need
≥ 0.685). ψ ≥ 0.8 was met by 16 cells and foragers ≤ 25 by 12. Step 3b is kept and reported as failed.

**Two reasons, both recorded.**
1. *Horizon.* The colony was still organising at 12,000 steps. Best cell (σ = 0, half-life 2000,
   D = 0.01, 0.25/0.125), medians per 2,000-step block from 4,000 to 12,000: foragers 54 → 37 →
   24 → 18, φ 0.33 → 0.46 → 0.57 → 0.62. Paper Fig. 4(d, e) runs to 20,000 steps.
2. *Design flaw in the basic tier (our standard, not the model).* φ is the mean folded heading of all
   N ants; searching foragers have random headings and pull φ toward 0, so φ ≈ (share of ants on the
   trail) × π/4. |φ − π/4| ≤ 0.1 therefore needs roughly ≥ 87% of ants on the trail (≲ 13 foragers),
   which is inconsistent with the basic tier's "foragers ≤ 25". The thresholds are **not** changed;
   the inconsistency is reported.

**Change (user).** All Step 3c and Step 4 runs last **20,000 steps**; every late window moves by
+8,000 steps; pass thresholds unchanged:

| Check | 12,000-step version | 20,000-step version |
|---|---|---|
| 1 discovery | first pickup ≤ 4,000 | unchanged |
| 2 recruitment window | [4,000, 12,000) | [4,000, 20,000) |
| 3 trail share at | t = 10,000 | t = 18,000 |
| 4 transport window | [6,000, 12,000) | [14,000, 20,000) |
| 5 order / role means | [10,000, 12,000) | [18,000, 20,000) |

**Step 3c calibration**: the full Step 3b grid (σ {0, 0.1, 0.3} × half-life {500, 1000, 2000} ×
D {0, 0.01, 0.02} × thresholds {0.5/0.25, 0.25/0.125} = 54 cells, + pheromone-off per σ), 20,000
steps, fresh seeds **2026320001–010**, 570 runs. Selection rule unchanged (full pass, then basic
pass, most median deliveries in the transport window, same tie-breaks).

**Fallback, fixed now (user).** If no cell reaches basic pass, choose among cells passing checks 1–4
the one with the most median deliveries in [14,000, 20,000) (same tie-breaks), continue to Step 4,
and state in the report that check 5 was **not passed**, with the actual ψ, φ and forager values.

Step 4 (validation, seeds 2026300001–020) uses 20,000 steps and the same shifted windows for every
arm; the paper-layout arm therefore uses the same windows as the others. Snapshots are saved at
t = 1,000 / 4,000 / 10,000 / 18,000. Consequence for later briefs: H1a/H1b relocation must happen
after the colony is organised, i.e. at 20,000 rather than 12,000 (to be fixed in those briefs).
