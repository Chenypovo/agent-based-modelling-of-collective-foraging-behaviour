# Stage 2A provisional colony results

Stage 2 provisional implementation — not an exact reproduction of Fig. 4.

## Direct verdict

**Stage 2A implementation acceptance: PASS.** The fixed seeded run completed the required causal chain and all stated engineering gates.

**Fig. 4 endpoint diagnostic: not reproduced.** The final phi and psi remain far from the paper's approximately pi/4 and 1 endpoint. This is a scientific limitation, not hidden by the implementation acceptance verdict.

This is a paper-informed independent implementation. It is not the authors' source code and is not evidence of an exact Fig. 4 reproduction.

## Paper-scale fixed run

- ants / arena / horizon: N = 100, L = 300, t = 10,000
- movement: ZW, step = 0.6, gamma = 0.1, Theta = 50 degrees
- nest / food: (90.0, 90.0) / (240.0, 240.0) (provisional coordinates)
- first food discovery: 913
- first successful delivery: 1583
- first forager-to-follower pheromone recruitment: 1168
- final F / T / f: 0 / 19 / 81
- final phi / psi: -0.032578 / 0.640075
- cumulative deliveries: 363
- active pheromone cells / total intensity: 102737 / 331588.0

### Required snapshot metrics

| time | F | T | f | phi | psi | deliveries |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 99 | 1 | 0 | 0.219135 | 0.628199 | 0 |
| 4,000 | 0 | 61 | 39 | 0.067140 | 0.647407 | 57 |
| 10,000 | 0 | 19 | 81 | -0.032578 | 0.640075 | 363 |

### Transition totals

- `forager_to_transporter`: 1
- `forager_to_follower`: 99
- `transporter_to_follower`: 363
- `follower_to_transporter`: 381

## Acceptance checks

- PASS: `stage1_preservation_hashes_match`
- PASS: `automated_tests_passed`
- PASS: `configured_horizon_completed`
- PASS: `population_conserved`
- PASS: `finite_metrics`
- PASS: `food_discovered`
- PASS: `food_delivered`
- PASS: `pheromone_deposited`
- PASS: `forager_recruited_to_follower`
- PASS: `transporter_became_follower`

## Scientific interpretation limit

The final order parameters are phi = -0.032578 and psi = 0.640075; the paper reports approximately phi = pi/4 and psi = 1 for its FCRW/ZW endpoints. The current fixed provisional rules therefore demonstrate role cycling, recruitment, transport, and a visible nest-food corridor, but do not demonstrate the paper's disorder-order endpoint. Because pheromone does not decay, all historical route cells remain active; the final field contains 102737 active cells and is much broader than a single clean trail. Resolving this requires the missing author/supervisor implementation details, not an unapproved parameter scan.

## Small pilot

- configuration: N = 10, L = 45.0, t = 1000
- runtime: 0.819 s simulation; 1.810 s through outputs
- first discovery / delivery: 49 / 91
- final F / T / f: 0/4/6
- cumulative deliveries: 87

## Runtime and hardware

- simulation: 88.971 s
- end-to-end through figures/report inputs: 92.304 s
- platform: macOS-27.0-x86_64-i386-64bit
- Python: 3.9.4
- CPU-only; GPU and AutoDL were not used
- automated tests before runs: 32 passed in 2.20s

## Provisional assumptions used

- nest and food coordinates and physical radii
- point initialisation at the nest centre and IID uniform heading sampling
- food radius plus sensing range as the food-detection condition
- grid-cell pheromone representation, deposit amount, and one-cell trail width
- stored concentration-weighted direction toward food
- follower local-maximum selection and deterministic tie-breaking
- continuing the previous heading after temporary signal loss
- retaining indices 0, 3, 6, ... and appending the final path vertex
- linear interpolation while retracing the reversed coarse path
- overshoot reflection and the within-step update/event order

## Awaiting supervisor confirmation

The exact coordinates/radii, initialisation, food detection, pheromone representation and increment, trail width/direction choice, equal-concentration handling, memory endpoint rule, transporter interpolation, nest reset timing, boundary numerics, seeds, and event ordering remain unresolved. See `docs/STAGE2_SPEC.md` for the complete question list.

## Output files

- `config.json`: complete centralised configuration
- `metrics.csv`: one row per time step with F/T/f, phi, psi, deliveries, and pheromone summaries
- `agent_states.csv`: every ant at the configured recording interval and required snapshots
- `final_agents.csv`: final position, heading, orientation, and role for every ant
- `events.csv` and `transition_counts.json`: complete role-transition evidence
- `snapshot_t*.csv` and `snapshot_t*.png`: required spatial snapshots
- `role_counts.png`, `order_parameters.png`, and `cumulative_food_transport.png`: requested time-series figures
- `runtime.json`: CPU/platform timing
- `stage1_sha256.json`: preservation readback against the pre-Stage 2A hashes

No Stage 2B, Stage 3, optimisation, or LLM experiment was run.
