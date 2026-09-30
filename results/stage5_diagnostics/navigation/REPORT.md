# Stage 5 exploratory study: how ants find their way home

Status: **exploratory**. Diagnostic seeds 2026093001-10 (10 per condition), not confirmatory evidence.
Frozen Stage 3C/3D decisions are unchanged. Code: `src/stage5_navigation/path_integration.py`
(tests: `tests/test_stage5_path_integration.py`); runner `scripts/stage5_navigation_experiment.py`;
tables/figures `scripts/stage5_summarise_navigation.py` -> `summary_tables.md` and PNG files here.

## Question

The validated model makes a loaded ant retrace its own outbound search path exactly. Real foragers
home with path integration (an egocentric home vector that accumulates error) and correct it with
familiar landmarks (geocentric information). Does the homing strategy change colony foraging and
adaptation after the food is moved, and how does terrain (landmark density) change the answer?

## Model

Everything else is the validated scalar model (100 ants, 300 x 300, nest (150,150), food A (240,150),
food B (150,240), step 0.6, exponential half-life 1000, deposit only by loaded ants).

- **Exact retrace** (current model, control).
- **Path integration**: each step the ant adds its displacement to a position estimate after rotating
  it by Gaussian compass noise (SD = "error", radians per step). A loaded ant walks toward its estimated
  nest. The nest is perceived only within 3 units; if the ant believes it is home but cannot perceive
  the nest, it runs an Archimedean spiral search (loop spacing 4). Delivery re-anchors the estimate.
- **Landmarks**: fixed random points visible within 8 units. Each ant remembers, per landmark, the
  landmark position implied by its least-uncertain sighting (uncertainty = path length since last anchor);
  a later, more uncertain sighting resets its estimate to that memory. During a committed spiral search
  landmarks are ignored (otherwise a biased memory trapped ants in a restart loop; found and fixed with a
  regression test before these results).

## Results on default settings (static food, 12,000 steps; median [range] over 10 seeds)

| Strategy | Deliveries | Return trip (steps) | Homing error at "home" |
|---|---|---|---|
| Exact retrace | 6 [3-13] | 2813 | - |
| Path integration, no error | 60 [32-109] | 148 | 0 |
| Error 0.1 | 312 [227-579] | 149 | 1.0 |
| Error 0.3 | 326 [76-548] | 152 | 3.5 |
| Error 0.6 | 55 [21-272] | 465 | 18.8 |
| Error 1.0 | 18 [13-29] | 1218 | 41.2 |
| Error 0.6 + 300 landmarks | 232 [45-349] | 149 | 0.6 |
| Error 1.0 + 300 landmarks | 205 [38-513] | 150 | 1.0 |

1. Any form of homing vector beats exact retrace: a return takes ~150 steps instead of as long as the
   search that found the food.
2. Landmarks rescue large error: at error 0.6 or 1.0, 300 landmarks cut homing error to about 1 unit and
   raised deliveries from 55 / 18 to 232 / 205.
3. On these default settings small error (0.1-0.3) gave more deliveries than zero error, and with small
   error landmarks *lowered* deliveries. Both effects run through pheromone recruitment and are **not
   robust** (see robustness check below): with zero error every return lays pheromone on the same
   one-cell line, and only 1.2% of ant-steps were trail following versus 6.5% at error 0.1.

## Robustness check: trail physics (median deliveries by 12,000, 10 seeds)

Trail width was changed three ways: 3-unit cells, and pheromone diffusion D = 0.01 or 0.05 per step
(proposal Eq. 1, `src/stage5_navigation/diffusion.py`, absorbing edge; D = 0 reproduces the validated field).

| Strategy | Default (D=0, cell 1) | Cell 3 | D = 0.01 | D = 0.05 |
|---|---|---|---|---|
| Exact retrace | 6 | 6 | 6 | 6 |
| Path integration, no error | 60 | 22 | 108 | 14 |
| Error 0.1 | 312 | 21 | 334 | 14 |
| Error 0.6 | 55 | 12 | 64 | 12 |
| Error 1.0 | 18 | 9 | 22 | 8 |
| Error 0.1 + 300 landmarks | 74 | 20 | 102 | 14 |
| Error 0.6 + 300 landmarks | 232 | 22 | 206 | 13 |
| Error 1.0 + 300 landmarks | 205 | 22 | 262 | 12 |

Trail following share of ant-steps under D = 0.05 fell to about 0.001-0.08: diffusion dilutes the trail
below the detection threshold (signal_on 0.5), so recruitment nearly stops and deliveries reflect
individual foraging only. On 3-unit cells both sensors (1 unit out) often read the same cell, so ants
cannot steer along the trail.

**Robust in all four settings:** a homing vector beats exact retrace, and landmarks restore performance
when path integration is noisy. **Setting-dependent:** the size of the advantage, whether small error
beats zero error, and whether landmarks help or hurt precise ants. These depend on whether pheromone
recruitment works, which depends on trail width relative to sensor spacing and detection threshold.

## Results (food moved at step 6,000; 18,000 steps)

| Strategy | A deliveries before move | B deliveries after move | First B delivery after move |
|---|---|---|---|
| Exact retrace | 6 | 3 | 6820 steps (2/10 never) |
| Path integration, no error | 28 | 66 | 793 |
| Error 0.6 | 18 | 12 | 2116 |
| Error 0.6 + 300 landmarks | 56 | 124 | 862 |

Better homing both strengthens foraging before the move and speeds adaptation after it; the strong
nest-food trail did not trap the colony at the old food in these runs.

## Terrain sweep (error x landmark count, default settings)

See `terrain_heatmaps.png` and `summary_tables.md`. Landmarks cut homing error at every error level
(e.g. error 1.0: 41 -> 1.0 units from 0 to 300 landmarks). Deliveries rise with landmarks when error is
large (error 1.0: 18 -> 205) but fall when error is small (error 0.1: 312 -> 74); the latter is the
non-robust recruitment effect above.

## Answer to the supervisor's slide-3 question

The ants' own movement is close to radial around the nest (occupancy direction bias R about 0.1). The
pheromone is not, because only loaded ants deposit, and under exact retrace they re-lay their whole
tortuous search path on the food side. With a homing vector the pheromone becomes a nest-food trail,
and with large homing error it fans out around the nest from local searches.

## Limits

Ten seeds with wide spread; one arena and food geometry; nest-perception radius, spiral spacing,
landmark view radius and per-ant perfect landmark recognition are assumptions, not calibrated values.
Ants carry no food-vector memory: after delivery they search again and rely on pheromone. Loaded ants
also deposit during spiral search, which creates rings around the nest; whether real ants do so is open.
