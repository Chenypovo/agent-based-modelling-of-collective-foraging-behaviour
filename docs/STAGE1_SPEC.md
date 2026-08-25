# Stage 1 specification: single-ant discrete walks

Status: implementation specification, written before Stage 1 code.

Primary source: Zhang, N. & Yong, E. H. (2023), *Dynamics, statistics, and task allocation of foraging ants*, Physical Review E 108, 054306. DOI: https://doi.org/10.1103/PhysRevE.108.054306. This specification covers only Sections II–III and Figs. 1–3.

## 1. Scope gate

Stage 1 contains one ant moving in unbounded two-dimensional continuous space. It implements and compares SRW, FCRW, and ZW trajectories and their single-walker statistics.

It does **not** contain a nest, food, pheromone, ant roles, task allocation, colony-level foraging, ODEs, an LLM agent, random search, Optuna, AutoDL, or GPU work. Passing Stage 1 does not mean that the whole Zhang–Yong paper has been reproduced.

## 2. Common kinematics

### Paper-explicit content

- A path with `t` temporal steps has `t + 1` vertices in two-dimensional real space.
- Consecutive vertices are separated by a fixed step length `ell`:

  `|r_i - r_(i-1)| = ell`.

- The turning angle is

  `theta_i = U_i V_i`,

  where `U_i` is a sign and `V_i` is uniform on `[0, Theta]`. `Theta` is the maximum directional deviation.
- The paper uses constant speed `v0 = 0.6` length units per time unit. With one time unit per simulation step, this is a step length of `0.6`.

### Stage 1 implementation

- The initial position is `(0, 0)` and the initial heading is `0` radians (the positive x-axis).
- For each requested movement step, sample `U_i` and `V_i`, update the heading by `theta_i`, and then move exactly `ell` along the updated heading.
- `V_i` values are independent of all turn signs and of each other.
- Internally, angles are radians. The command-line interface accepts `Theta` in degrees.
- A user may specify either step size or speed. The Stage 1 time step is fixed to one, so the numerical values are identical.

### Unspecified or inconsistent details

- The paper does not state how the initial heading is sampled. Fixing it to zero is harmless for rotation-invariant statistics and makes runs easier to compare.
- The paper does not state whether the first movement occurs before or after the first sampled turn. Stage 1 uses “turn, then move” and records one turn angle per requested movement step.
- Equations (1)–(2) identify `U=+1` as left and `U=-1` as right, while the Fig. 1 caption calls negative `theta` a left turn and positive `theta` a right turn. Stage 1 follows the equations: `U=+1` is called left. Positive angles use the standard counter-clockwise mathematical rotation. Statistical comparisons depend on equality/opposition of signs, not on these names.
- The text calls the turning angles i.i.d. For FCRW and ZW, only their magnitudes are independent; the signs, and therefore the signed angles, are correlated.

## 3. SRW: simple random walk

### Paper rule

Equations (1)–(2) define a step-independent turn sign:

- `P(U_i = +1) = p`
- `P(U_i = -1) = 1 - p`

The paper uses the unbiased case `p = 1/2`.

### Stage 1 implementation

Every `U_i` is sampled independently, with equal probability for `+1` and `-1`. There is no persistent model state.

## 4. FCRW: first-order correlated random walk

### Paper rule

Equations (3)–(4) define a time-homogeneous first-order Markov chain:

- `P(U_(i+1) = U_i | U_i) = gamma`
- `P(U_(i+1) = -U_i | U_i) = 1 - gamma`

The initial sign is unbiased: `P(U_1 = +1) = P(U_1 = -1) = 1/2`. The paper uses `0 < gamma <= 1/2` in the text; the Fig. 1 caption includes the boundary `gamma = 0`.

Thus `gamma` is the probability that two consecutive turns have the same sign. Smaller `gamma` creates stronger alternation of left and right turns. At `gamma = 1/2`, FCRW reduces to SRW in its sign statistics.

### Stage 1 implementation

The first sign is sampled with probability `1/2`. Each later sign repeats the immediately previous sign with probability `gamma`; otherwise it flips. Stage 1 accepts `0 <= gamma <= 1/2` so that the probability-tree boundary shown in Fig. 1 can be tested.

## 5. ZW: zigzag walk

### Paper rule

For the realised sign `U_i`, equations (5)–(7) state:

If `P(U_i) >= 1/2`:

- `P(U_(i+1) = U_i) = gamma`
- `P(U_(i+1) = -U_i) = 1 - gamma`

If `P(U_i) < 1/2`:

- `P(U_(i+1) = U_i) = gamma P(U_i)`
- `P(U_(i+1) = -U_i) = 1 - gamma P(U_i)`

The paper states that this rule penalises long runs in the same direction and promotes alternating left/right sequences. Fig. 1(d) shows branch probabilities containing `gamma`, `gamma^2`, and `gamma^3`.

### Provisional Stage 1 interpretation

The notation `P(U_i)` is not fully defined for the path-dependent update. Stage 1 uses the interpretation most closely matching the Fig. 1(d) probability tree:

1. Let `q_i` be the conditional probability, on the current realised branch, of the sign that was actually selected for `U_i`.
2. Initialise `q_1 = 1/2` after sampling the unbiased first sign.
3. Compute the probability of repeating the current sign:
   - `p_same = gamma` when `q_i >= 1/2`;
   - `p_same = gamma q_i` when `q_i < 1/2`.
4. Sample the next sign. If it repeats, set `q_(i+1) = p_same`; if it flips, set `q_(i+1) = 1 - p_same`.

This produces the `gamma`, `gamma^2`, and `gamma^3` branch probabilities drawn in Fig. 1(d). The implementation is deliberately labelled `provisional`; no additional reset, run-length, or hidden-memory rule is introduced.

An alternative “global marginal probability” reading is not implemented because the paper does not give the ensemble-level recursion needed to resolve it unambiguously and the published probability tree supports the branch-conditional reading.

## 6. Parameters and defaults

| Parameter | Stage 1 default | Source/status |
|---|---:|---|
| model | all three | Stage 1 comparison choice |
| steps | 2,000 | Stage 1 runtime/statistics choice |
| step size / speed | 0.6 | paper-explicit speed with unit time step |
| Theta | 60 degrees | value used in Figs. 2–3; not a unique paper-wide default |
| gamma | 0.2 | value used in spatial examples in Fig. 3; not a unique paper-wide default |
| random seed | 20260824 | Stage 1 reproducibility choice |
| repetitions | 50 | Stage 1 uncertainty-estimation choice |
| coverage cell size | step size (0.6 by default) | matches `a=0.6`, equivalently `R=5/3`, used in parts of Fig. 3 |

Fig. 2 also uses `Theta=60 degrees` and several `gamma` values: FCRW uses 0.45, 0.25, and 0.1; ZW uses 0.49, 0.3, and 0.1. These are examples rather than a single calibrated parameter set.

## 7. Stage 1 statistics

For every trajectory, Stage 1 records:

- fraction of adjacent turn signs that are the same;
- lag-one sign product, `mean(U_i U_(i+1))`, which is positive for same-sign preference and negative for alternating-sign preference;
- paper-style mean resultant statistic `rho_hat = mean(cos(theta_i))`, corresponding to Eq. (9) under a symmetric turning-angle distribution;
- net displacement from the origin;
- straightness, defined as net displacement divided by total path length;
- distinct visited grid cells and covered area.

For coverage, the continuous plane is tiled with squares of side `a`, centred so that the origin lies at the centre of a cell, following Section III. A recorded vertex `(x, y)` is assigned to cell indices `floor(x/a + 1/2), floor(y/a + 1/2)`. Stage 1 counts cells containing recorded vertices; it does not invent sub-step interpolation along line segments. This endpoint convention is an implementation assumption because the paper does not specify its numerical rasterisation algorithm.

Repeated runs report the mean, sample standard deviation, standard error, and a normal-approximation 95% error half-width (`1.96 * standard error`). These intervals describe Monte Carlo uncertainty for this run configuration; they are not fitted confidence intervals for the paper’s figures.

## 8. Verification and claim boundary

Automated tests must verify seed reproducibility, fixed step length, turn-angle bounds, SRW balance, FCRW same-sign probability, the provisional ZW update, and model-state isolation.

The generated results are an independent Stage 1 implementation check. They may be compared qualitatively with the paper’s stated movement behaviour, but they must not be labelled an exact reproduction of Figs. 1–3 without matching the paper’s full simulation sizes, sampling details, fitting procedures, and numerical values.

## 9. Items for later supervisor confirmation

These questions do not block Stage 1, but should be confirmed before using this code as a calibrated baseline for later stages:

1. Should the ZW probability in equations (5)–(7) be interpreted as the current branch’s realised-sign probability, as in this provisional implementation?
2. Which left/right sign convention was used in the authors’ source code?
3. Was the first movement performed before or after the first turn was sampled?
4. For visited sites, were only time-step positions binned, or were all grid cells crossed by each continuous step counted?
5. What exact trajectory counts, durations, seeds, fitting windows, and error definitions produced Figs. 1–3?
