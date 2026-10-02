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
