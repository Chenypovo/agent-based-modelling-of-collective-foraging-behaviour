# Stage 2A-Diagnostic report

Stage 2A diagnostic only — no model rules or parameters changed.

## Direct verdict

**Diagnostic acceptance: PASS.** The fixed-seed run is byte-for-byte compatible for the required Stage 2A outputs, all protected inputs retained their pre-diagnostic SHA-256 hashes, and no model rule or parameter changed.

- tests: 43 passed in 2.31s
- fixed configuration: N = 100, L = 300, t = 10,000, seed = 20260824
- first discovery / delivery / recruitment: 913 / 1583 / 1168
- final F / T / f: 0 / 19 / 81
- final global phi / psi: -0.032578 / 0.640075
- deliveries / pheromone active cells / total intensity: 363 / 102,737 / 331588.0

## Role-specific order at t = 10,000

- forager: n = 0; phi/psi unavailable and not interpreted
- transporter: n = 19; phi = 0.349730; psi = 0.593624
- follower: n = 81; phi = -0.122255; psi = 0.676763

Counts below five are explicitly marked in the CSV and are not interpreted.

## Axis alignment

The nest-food axis is pi/4. Errors are axial: opposite directions along the same line have zero error.

| role | n | mean error (deg) | mean abs along speed | mean abs perpendicular speed |
|---|---:|---:|---:|---:|
| forager | 0 | unavailable | unavailable | unavailable |
| transporter | 19 | 31.650 | 0.4863 | 0.2983 |
| follower | 81 | 48.220 | 0.3613 | 0.4031 |

## Pheromone field

- active area: 41.09% (102,737/250,000 cells)
- top 1% / 5% / 10% of all grid cells carry 38.18% / 57.92% / 69.35% of total pheromone
- all-history weighted mean distance to axis / 90% channel width: 34.043 / 190.070
- top-1%-active weighted mean distance / width / connectivity: 9.564 / 37.335 / False
- top-5%-active weighted mean distance / width / connectivity: 10.650 / 39.881 / True
- top-10%-active weighted mean distance / width / connectivity: 14.789 / 62.791 / True

`all_active_history` is the union of every deposited historical route. Top-active masks are tie-inclusive high-concentration main-trajectory candidates; they are not treated as equivalent evidence.

## Follower sensing

- sensing steps / hits / misses: 472,415 / 460,954 / 11,461
- miss rate / no-signal continue-heading count: 2.43% / 11,461
- maximum-concentration tie steps: 83,813 (18.18% of hits)
- median candidate cells per step: 8.0
- longest consecutive miss streak: 315
- mean / median selected direction error relative to food on hits: 68.746 / 56.923 degrees
- mean movement axis error on hits / misses: 43.011 / 37.804 degrees
- per-follower summaries: 100 ants in `sensing_per_follower.csv`

## Transport path efficiency

- transport legs: 382 total; 363 completed; 19 active at horizon
- median one-third-memory shortening: 1.45%
- mean / median completed endpoint efficiency: 0.617 / 0.781
- median completed transport time: 444.0 steps
- anomalously long / possible looping / far-from-axis completed legs: 117 / 11 / 316

Endpoint efficiency uses departure-to-arrival displacement divided by actual travelled return distance and is bounded by one. The separate nest-food-centre distance is reported but can exceed the endpoint displacement because detection occurs within finite site radii.

## 1. Confirmed causes

- Follower trail-directed motion itself is disordered. On 460,954 signal hits, the selected direction had mean/median food-direction error 68.75°/56.92° and the realised movement had mean axial error 43.01°, close to the uniform-direction value 45°.
- The one-third-memory transporter route barely shortens the outbound path for the typical leg (median shortening 1.45%). 316/363 completed returns were flagged far from the main axis and 117/363 exceeded 1.5 times the nest-food centre distance, so off-axis geometry is directly deposited as pheromone.
- The non-decaying field retained 102,737 active cells (41.09% of the arena grid). The all-history 90% width was 190.070; the strongest 1%-of-active mask was not nest-food connected.

## 2. Likely causes

- The provisional follower direction-inference rule is the most likely rule-level mismatch: a hit deterministically sets the heading to one stored cell direction, yet those selected directions are usually not toward the food or along the nest-food axis.
- The provisional memory stride plus linear interpolation is likely upstream of the broad field: it removes only 1.45% of path length at the median and retains substantial off-axis geometry.
- Because decay is frozen at zero, every off-axis historical deposit remains selectable. This likely amplifies early and long-path errors, but a causal counterfactual was intentionally not run.

## 3. Ruled-out causes

- A diagnostic-instrumentation behaviour change: all required original outputs, scalars, and protected-file hashes match.
- A simple phi/psi implementation failure: synthetic aligned and bidirectionally aligned fields give psi = 1, while a uniform direction field gives psi approximately 2/pi.
- Role mixing as the main explanation: the sample-weighted mean of populated-role magnitudes is 0.660966, versus global psi 0.640075; mixing reduces psi by only 0.020892. Follower psi is 0.676763 and transporter psi is 0.593624.
- Frequent signal loss as the dominant cause: misses are only 2.43% of follower steps, and hit steps are at least as disordered by axis error (43.01° on hits versus 37.80° on misses).
- Widespread literal looping as the dominant transporter failure: only 11/363 completed legs crossed the stated repeated-cell diagnostic threshold.

## 4. Unresolved

- The authors' exact follower trail-inference and signal-reacquisition rule.
- The authors' exact pheromone grid/width/deposit representation and equal-concentration handling.
- The exact one-third-memory endpoint rule and transporter interpolation/controller.
- Whether the paper's plotted order parameters used precisely the same sampling population and within-step timing.
- The Stage 1 ZW branch-conditional interpretation remains provisional.

## Evidence-ranked explanation

1. Follower direction selected on signal hits is poorly aligned (mean food-direction error 68.75°; mean axis error 43.01°).
2. The provisional one-third-memory return geometry leaves off-axis paths (median shortening 1.45%; 316/363 completed legs far from axis).
3. The broad, non-decaying historical field retains those paths (active area 41.09%; all-history width 190.070).
4. Signal misses are secondary overall (2.43%), although rare streaks reach 315 steps.

These are observational rankings. Only the first-order mechanisms are measured directly; counterfactual causality remains outside Stage 2A-Diagnostic.

## Single Stage 2B rule worth validating next

Validate the follower local trail-direction inference rule: after selecting a concentration, determine how the authors derived the next movement direction from neighbouring trail geometry rather than assuming one stored per-cell vector. Do not change it in Stage 2A-Diagnostic.

No modification was implemented.

## Runtime and scope

- simulation: 133.488 s
- diagnostic analysis and outputs after simulation: 9.203 s
- total: 142.692 s
- platform: macOS-27.0-x86_64-i386-64bit
- Python: 3.9.4
- Mac CPU only; no GPU or AutoDL
- no Stage 2B, Stage 3, random search, Optuna, or LLM experiment

## Output inventory

- `role_specific_order.csv`, `axis_alignment.csv`
- `pheromone_concentration.csv`
- `sensing_diagnostics.csv`, `sensing_per_follower.csv`, `sensing_miss_streaks.csv`
- `transport_path_efficiency.csv`
- `metric_validation.csv`
- `baseline_compatibility.json`, `pre_diagnostic_sha256.txt`, `runtime.json`
- six diagnostic PNG figures

Stage 2A diagnostic only — no model rules or parameters changed.
