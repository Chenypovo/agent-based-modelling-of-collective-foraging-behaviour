# Stage 2A specification: provisional colony foraging model

Status: implementation specification written before the Stage 2A colony code.

Primary source: Zhang, N. & Yong, E. H. (2023), *Dynamics, statistics, and task allocation of foraging ants*, Physical Review E 108, 054306. DOI: https://doi.org/10.1103/PhysRevE.108.054306. The paper was checked directly, with particular attention to Section IV, Eqs. (15)--(17), and Fig. 4.

## 1. Claim and scope gate

Stage 2A is an independent, paper-informed colony model. It is **not** the authors' source code and **not** an exact reproduction of Fig. 4. The implementation details listed as provisional below remain replaceable pending a reply from the supervisor/authors.

Included: a finite two-dimensional square, reflective boundaries, multiple ants, one nest, one inexhaustible food source, forager/transporter/follower roles, positional memory, a discrete non-decaying pheromone field, colony counts, orientation and nematic order, deterministic tests, and bounded CPU runs.

Excluded: pheromone diffusion or decay, food depletion, environmental change, random search, Optuna, an LLM scientific agent, Fig. 5 parameter sweeps, AutoDL/GPU work, ODE fitting, and any exact-reproduction claim.

## 2. Paper-explicit model content

### 2.1 Environment and movement

- Ants are self-propelled point particles in continuous two-dimensional space.
- The speed is `v0 = 0.6` length units per unit time. With the model's unit time step, the commanded path length per update is `0.6`.
- The interaction/vision range is `delta = 0.6` length units.
- Fig. 4 uses `N = 100`, a square of side `L = 300`, and reflective boundaries.
- Fig. 4 uses `gamma = 0.1` and `Theta = 50 degrees`.
- There is one inexhaustible food source.
- The nest-food line makes an angle `pi/4` with the horizontal axis.
- At `t = 0`, all ants are foragers at the nest and depart in different random directions.
- The movement law is one selected Stage 1 model (SRW, FCRW, or provisional ZW). Stage 2A calls the existing `ant_walks.generate_trajectory` implementation to generate forager turning schedules; it does not copy the Stage 1 walk rules.

### 2.2 Roles and allowed transitions

The paper defines three roles:

- `forager` (`F`): searches for food;
- `transporter` (`T`): returns from food to nest and deposits pheromone;
- `follower` (`f`): follows a pheromone trail toward food.

Only these role transitions are allowed:

| From | Trigger | To | Status |
|---|---|---|---|
| forager | finds food | transporter | paper-explicit |
| forager | encounters pheromone | follower | paper-explicit |
| transporter | deposits food at nest | follower | paper-explicit |
| follower | reaches food | transporter | paper-explicit |

The transporter-to-follower transition is important: Section IV states that a transporter becomes a follower after depositing food at the nest. Stage 2A therefore does not introduce a transporter-to-forager transition.

### 2.3 Memory and pheromone

- A search path is written as `{x0, x1, ..., xt}`, with nest and food at its endpoints.
- The paper states that an ant remembers one third of its positional information and illustrates the retained path as `{x0, x3, ..., xk, x(k+3), ..., xt}`.
- A transporter retraces this coarser path toward the nest, shortening the route by removing meanders.
- A transporter deposits pheromone while returning.
- The study uses a single pheromone kind because it has one limitless food source.
- Pheromone density represents route credibility. When several trails are present, an ant chooses the trail with the largest pheromone concentration.
- No pheromone diffusion or decay rule is specified or added in the Stage 2A baseline.

### 2.4 Observables

For ant `alpha` at time `i`, Eq. (15) maps its velocity to an unoriented angle in `[-pi/2, pi/2)`, identifying opposite velocities. Eq. (16) defines the orientation order `phi_i` as the arithmetic mean of those angles. Eq. (17) defines the nematic order `psi_i` as the magnitude of the mean folded unit-velocity vector. A uniform distribution in the folded half-plane gives `psi` near `2/pi`, while alignment along the nest-food axis gives `psi` near one.

## 3. Provisional assumptions implemented in Stage 2A

Every value below is held in `ColonyConfig` (including nested site, movement, and pheromone configuration). None is scattered as a simulation constant.

| Topic | Stage 2A rule/default | Status |
|---|---|---|
| nest coordinate | `(90, 90)` for the paper-scale run, estimated from Fig. 4 | provisional assumption; awaiting supervisor confirmation |
| food coordinate | `(240, 240)` for the paper-scale run, estimated from Fig. 4; this preserves the explicit `pi/4` axis | provisional assumption; awaiting supervisor confirmation |
| nest radius | `3.0` length units | provisional assumption; awaiting supervisor confirmation |
| food radius | `3.0` length units | provisional assumption; awaiting supervisor confirmation |
| initial position | every point ant starts exactly at the configured nest centre | provisional numerical interpretation of the paper statement; awaiting supervisor confirmation |
| initial heading | independent uniform draws on `[0, 2*pi)` from a seeded NumPy generator | provisional numerical interpretation of "random directions"; awaiting supervisor confirmation |
| initial role | all ants are `forager`, as stated in Fig. 4 | paper-explicit; exact author initialisation remains awaiting confirmation |
| food detection | detected after a movement when the ant centre is within `food_radius + delta` of the food centre | provisional assumption; awaiting supervisor confirmation |
| nest arrival | detected when the ant centre is within `nest_radius` of the nest centre | provisional assumption; awaiting supervisor confirmation |
| memory thirds | keep vertices with indices `0, 3, 6, ...`; append the final vertex once if its index is not divisible by three | provisional disambiguation of the paper's one-third example; awaiting supervisor confirmation |
| transporter route | reverse the retained waypoint list and advance along its line segments at the configured speed; deposit once after each movement update | provisional numerical rule; awaiting supervisor confirmation |
| transporter after nest | record one delivery, then switch to follower as stated in Section IV; start a new nest-to-food travel record | role change is paper-explicit; exact arrival/reset timing is provisional and awaiting confirmation |
| pheromone structure | square grid with cell side `0.6`; each cell stores concentration and a concentration-weighted direction toward food | provisional assumption; awaiting supervisor confirmation |
| deposit amount | add `1.0` to the current grid cell per transporter update | provisional assumption; awaiting supervisor confirmation |
| pheromone width | one occupied grid cell per deposit; perception uses the configured `delta` around the ant | provisional assumption; awaiting supervisor confirmation |
| follower choice | among sensed active cells, choose the highest concentration and use its stored direction toward food | paper gives the concentration rule; discretisation and direction storage are provisional and awaiting confirmation |
| equal concentration | prefer the candidate whose stored direction has the largest projection toward the configured food, then use lexicographic cell order | provisional assumption; awaiting supervisor confirmation |
| follower loses signal | continue its last heading and look again after the next update | provisional assumption; awaiting supervisor confirmation |
| repeated trail visits | concentrations add; direction vectors are concentration-weighted | additive credibility is consistent with the paper but the exact increment is provisional and awaiting confirmation |
| boundary reflection | reflect the overshoot coordinate across the crossed wall and flip the corresponding velocity component; repeat if needed | provisional numerical rule; awaiting supervisor confirmation |
| within-step events | role changes are evaluated after the movement/deposit phase and take effect immediately for the stored end-of-step state | provisional assumption; awaiting supervisor confirmation |

## 4. Configuration presets

### 4.1 Paper-scale CPU run

| Parameter | Value | Source/status |
|---|---:|---|
| ants | 100 | paper-explicit |
| square side `L` | 300 | paper-explicit |
| time steps | 10,000 | paper-explicit Fig. 4 snapshot horizon |
| speed / step size | 0.6 | paper-explicit |
| sensing range `delta` | 0.6 | paper-explicit |
| `gamma` | 0.1 | paper-explicit Fig. 4 |
| `Theta` | 50 degrees | paper-explicit Fig. 4 |
| movement model | provisional ZW | Stage 2A bounded-run choice; ZW interpretation remains provisional from Stage 1 |
| snapshots | 1,000; 4,000; 10,000 | paper-explicit Fig. 4 times |
| seed | 20,260,824 | provisional reproducibility choice |
| state-record interval | 100 steps plus all required snapshots and final state | provisional output-size choice |

### 4.2 Small pilot

The pilot uses `N = 10`, `L = 45`, nest `(12, 12)`, food `(27, 27)`, 1,000 steps, and snapshots at 250, 500, and 1,000. It deliberately shortens the nest-food separation while preserving the same movement, transition, pheromone, and metric code.

## 5. Numerical update order

At each unit time step:

1. Foragers consume the next pre-generated Stage 1 turning angle and make one reflected fixed-speed move. Their realised position is appended to their current nest-to-food path.
2. Followers sense the local field, select a direction under the configured rule, make one reflected fixed-speed move, and append the realised position to their current path.
3. Transporters advance along their reversed coarse-grained waypoint path at the same speed and deposit pheromone at the resulting position.
4. Post-movement events are evaluated through the central transition function. Food arrival has priority over pheromone recruitment for a forager.
5. Counts, deliveries, order parameters, pheromone summary, and transition totals are recorded.

All ants are updated from their own state. Random number generators, ant arrays, path lists, and pheromone arrays are instance-local.

## 6. Outputs and claim label

The paper-scale run writes to `results/stage2_provisional/`; the small pilot writes to its `pilot/` subdirectory. Outputs include configuration, metrics, sampled agent states, final agents, event log, transition counts, runtime, snapshots, time-series figures, a Stage 1 hash manifest, and `REPORT.md`.

Every generated figure and report must contain this exact notice:

> Stage 2 provisional implementation — not an exact reproduction of Fig. 4.

The figures are diagnostic outputs from one fixed seeded run. They are not parameter estimates and are not evidence that the unpublished author implementation has been recovered.

## 7. Verification requirements

Automated tests cover:

- unchanged Stage 1 tests;
- seed reproducibility and instance isolation;
- reflective bounds and commanded step length;
- population conservation and allowed transitions;
- deterministic forager food discovery, transporter return, and follower arrival;
- no spontaneous pheromone decrease with decay disabled;
- the provisional one-third memory rule;
- known orientation/nematic arrangements;
- a small long run with no NaN, out-of-bounds position, or missing state.

The paper-scale acceptance run must additionally complete on Mac CPU and demonstrate the causal chain from food discovery to return, trail deposition, and follower activity. If a fixed seed does not show that chain, it is reported as a failed scientific/behavioural gate rather than hidden by a parameter scan.

## 8. Stage 1 baseline SHA-256 (recorded before Stage 2A edits)

| File | SHA-256 |
|---|---|
| `docs/STAGE1_SPEC.md` | `38c741d14ab0adbdc448a24424b08042679eaed8db645ed5c6fc7ea9626da3f3` |
| `run_stage1.sh` | `b2d5540708cb73ce54fa4016d5005b79b2bae74e34b8683de5e2e906bf7569a5` |
| `scripts/run_stage1.py` | `a4e09cd333c98b12c9d989343008cee6f06b5004e4585b235fc1456d6a7301e3` |
| `src/ant_walks/__init__.py` | `cc4cd63987bb28137859c7debab8f67d5487602e760478778e4d8fcbe5bd56fc` |
| `src/ant_walks/cli.py` | `b099b9d3d18789ab70f0b79fae4d1e2097fb03cf75f4778ba78d18729b93b710` |
| `src/ant_walks/experiment.py` | `c950a3eefaad950ec1455632654efb434225d69159c14d575fd7ad3470e2e1d7` |
| `src/ant_walks/metrics.py` | `1d898636fa74ec76f22011cd57b288eb3b9eccc4d2a9ff675dcdc41291cac14b` |
| `src/ant_walks/models.py` | `96589d8fd545cc98d3434f7d34201d537905fa3a561460f7f3e037f28915f0c4` |
| `tests/conftest.py` | `0a586e159d2b7889ffda8fb3d1b225d142b8f33875da9ab061d94b8fc6fea09c` |
| `tests/test_metrics.py` | `d33b90c224dd0bb36317d105cc1a92a27e86d0a1b8c06af443b6f614270e2691` |
| `tests/test_models.py` | `f1929b4f061286043c19bd976d300294c6fcdbef911dd57acacf9613a809256c` |
| `results/stage1/REPORT.md` | `dba514b3c150730a7618d428635beee02e5cbcdc96fee7079ef01ee2ecf33075` |
| `results/stage1/config.json` | `94a878200da36e427e140809bc52467e0e539e8df7ed636b61d99adaef8e11c6` |
| `results/stage1/metrics_per_run.csv` | `1eb4f8f270813281f77bc853bba16035466747da8d4dddcf6e41d51a3db554ed` |
| `results/stage1/runtime.json` | `35ea816e6a1e04bc9e13641d6b1d5234b82d6c81c1fb973d781ec96c393e93bf` |
| `results/stage1/spatial_statistics.png` | `1708cbda1b1ef9a8818b3a94abef05f89a0a2fd339ea94c2a8bb1c6ade819dc3` |
| `results/stage1/summary.csv` | `493a7bb85c78331f30b74eac6aa3195d433d445fec51991bb600bcbbb352b644` |
| `results/stage1/trajectories.png` | `8e9bcaa8577bd3cda1345099cc0a0f701cb5ccf5b4de1e6ce4e24fc0430a9cc0` |
| `results/stage1/turning_statistics.png` | `6a3066da12687f5dc8b66132d2dc15f2399512fe6889c877b3eff99c41a723dc` |

These files are treated as the Stage 1 preservation set. Stage 2A must not modify them, and the generated hash manifest checks them again after the Stage 2 runs.

## 9. Questions awaiting supervisor confirmation

1. What exact nest and food coordinates and physical radii were used for Fig. 4?
2. Were all ants placed at one point, uniformly inside a nest disk, or by another initialisation rule? How exactly were initial headings sampled?
3. Was food detection point-based, radius-based, segment-intersection-based, or tied only to `delta`?
4. How was pheromone represented, what was deposited per step, and what spatial width did a trail have?
5. How did a follower infer the next trail segment, and how were equal concentrations resolved?
6. How exactly was `{x0, x3, ..., xt}` constructed when the final index was not divisible by three?
7. Did a transporter interpolate continuously between retained vertices, jump between them, or use another controller?
8. At what exact point within an update was a transporter counted at the nest and converted to a follower?
9. What numerical reflection method was used for an update crossing a boundary?
10. What random seeds, event ordering, and output sampling produced Fig. 4?
