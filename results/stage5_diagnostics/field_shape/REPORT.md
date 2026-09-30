# Stage 5 diagnosis: why the pheromone field is not radial

Status: **exploratory diagnosis**, 5 diagnostic seeds (2026093001-05) per condition, static food A only,
no relocation, 24,000 steps. Not confirmatory evidence; frozen Stage 3C/3D decisions are unchanged.
Scripts: `scripts/stage5_diagnose_field.py`, `scripts/stage5_summarise_field.py`.
Model change: `src/stage5_navigation/model.py` (waypoint spacing 1 reproduces the validated exact retrace;
tested in `tests/test_stage5_coarse_return.py`).

## Findings

1. **Ant exploration is close to radial; the pheromone is not.** Occupancy of all ants has direction bias
   R = 0.04-0.17 and about 24% in the lower-left quadrant (even = 25%). Time-mean pheromone has R about
   0.4-0.7 and only 0-26% in the lower-left. Only transporters deposit, so the field is a map of the
   searches that happened to end at food A, not of colony activity.
2. **Exact retrace makes each trip as long as the search that found food.** In seed 2026093002, 15 pickups
   had outbound paths of 487-11,948 steps; exact return took the same number of steps, versus about 151 for
   a straight line. Returns therefore deposit long, tortuous, food-side traces and deliveries stay rare
   (median 5 per 12,000 steps with 100 ants).
3. **Larger cells or a larger arena do not fix the shape or the delivery rate.** Cell size 3 gives wider,
   denser traces but similar deliveries; arena 600 removes wall effects but does not raise deliveries.
   Longer runs raise deliveries slowly (median 4, 5, 14 by 6k/12k/24k).
4. **Coarse-grained return only helps at large spacing.** The walk is persistent: using every 10th/50th/200th
   outbound vertex shortened the same returns by about 12%/45%/70%. Straight homing (idealised,
   noise-free path integration) raised deliveries by 12,000 to a median of 64 (39-76) and produced one
   nest-food trail.

## Interpretation limits

Straight homing is an upper bound: it has no path-integration error. Five seeds and one geometry.
The table's median return-trip column is biased by which trips complete inside the window; use finding 2
for return-length comparison.
