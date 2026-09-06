# Stage 2B specification: local trail geometry single-rule ablation

Status: pre-registered specification written before the Stage 2B behaviour change.

Stage 2B is an independent single-rule ablation, not an exact reproduction of Zhang and Yong Fig. 4.

Every Stage 2B report and figure must contain this notice:

> Stage 2B single-rule ablation — not an exact reproduction of Fig. 4.

## 1. Frozen baseline

- branch at intake: `main`
- frozen commit: `02a953af132a44aabcf8be92a873de7694d4a5fb`
- frozen commit message: `chore: establish Stage 2A diagnostic baseline`
- accepted pre-change tests: `43 passed`
- fixed run: `N = 100`, `L = 300`, `t = 10,000`, seed `20260824`
- movement: provisional ZW, `gamma = 0.1`, `Theta = 50 degrees`, step size `0.6`
- final baseline `phi = -0.032578`, `psi = 0.640075`
- baseline deliveries: `363`
- baseline follower hit-step mean nest-food-axis error: `43.01 degrees`
- baseline active pheromone cells: `102,737`

The accepted Stage 1, Stage 2A, and Stage 2A-Diagnostic artifacts are read-only inputs. Stage 2B writes only below `results/stage2b_local_geometry/`.

## 2. Scientific question

Does a follower direction inferred from the local spatial geometry of nearby active pheromone cells produce more ordered nest-food-axis motion than directly adopting the direction stored in one maximum-concentration cell?

This is a one-seed mechanism test. It does not identify the unpublished Zhang-Yong implementation and does not estimate a parameter distribution.

## 3. Single changed rule

The configuration field `follower_direction_rule` has exactly two allowed values:

- `stored_cell_direction`: the frozen Stage 2A baseline and the default;
- `local_weighted_pca_tangent`: the Stage 2B ablation.

For `local_weighted_pca_tangent`:

1. Read every active pheromone grid cell within the existing sensing range `delta`.
2. Use only each cell centre and its current pheromone concentration.
3. Compute the concentration-weighted mean of the centres.
4. Compute the concentration-weighted `2 x 2` covariance matrix around that mean.
5. Use the eigenvector of the largest eigenvalue as the local trail tangent.
6. Treat the tangent as an unoriented axis and select the sign with the smaller angular difference from the follower's current heading.
7. Preserve the current heading when fewer than two distinct cells are available, the covariance is zero, the principal direction is not numerically unique or finite, or the tangent sign is exactly tied relative to the current heading.

The rule has no adjustable threshold, smoothing coefficient, random tie-break, or noise term. Numerical validity checks use finite arithmetic and exact degeneracy checks; they are not experiment parameters.

The PCA inference is forbidden from reading food coordinates, nest coordinates, a cell's stored `direction_to_food`, a global path, or hidden state from another ant. It may support bidirectional travel along the same local trail axis.

The same configured direction entry point is used when an existing follower moves, when a forager is recruited to follower, and when a transporter becomes a follower at the nest. This prevents the Stage 2B sign choice from being initialised indirectly by the baseline stored-cell direction. Role-transition triggers and event timing are unchanged.

## 4. Rules held unchanged

- SRW, FCRW, and provisional ZW movement implementations;
- random seed, initial headings, and pre-generated turn schedules;
- ant speed, follower step length, and sensing range;
- nest and food coordinates and radii;
- forager, transporter, and follower transition triggers;
- transporter one-third memory and reversed interpolated return route;
- pheromone grid, deposition amount, stored direction, persistence, and tie-breaking used by the baseline rule;
- zero pheromone diffusion and zero decay;
- reflective boundary calculation;
- coordinate conventions, site detection, within-step event order, snapshots, and state-record intervals;
- population size and paper-scale horizon.

The stored direction remains in the pheromone field for baseline compatibility and is not read by the PCA rule.

## 5. Protected artifacts and SHA-256 gate

Before Stage 2B execution, record SHA-256 for every file under:

- `results/stage1/`
- `results/stage2_provisional/`
- `results/stage2_diagnostic/`

Also protect:

- `docs/STAGE1_SPEC.md`
- `docs/STAGE2_SPEC.md`
- `Project Proposal.pdf`
- `_PH6780 Templates.docx`
- `_AY2627_T1_Briefing_updated.pdf`
- `references.bib`

Recompute the same manifest after all Stage 2B outputs are complete. Every path must still exist and every digest must match. The ignored local files `similarity check.pdf` and `results/stage2_diagnostic/sensing_diagnostics.csv` must not be deleted, moved, or added to Git.

## 6. Pre-registered metrics

The frozen Stage 2A output is the only baseline. Compare it with the single fixed Stage 2B run using:

1. final global `phi` and `psi`;
2. mean global `phi` and `psi` over inclusive times `9,000` through `10,000`;
3. follower-specific and transporter-specific `phi` and `psi`, including the same final and late-window summaries;
4. mean follower movement axis error on pheromone-hit steps;
5. local direction continuity, defined as the mean axial angle change between selected directions on consecutive hit steps for the same follower; opposite directions on one axis are equivalent;
6. follower sensing miss rate;
7. cumulative successful deliveries;
8. first food discovery, first successful delivery, and first pheromone recruitment times;
9. final active pheromone area and the intensity-weighted 90% main-channel width;
10. completed transporter endpoint path efficiency;
11. forager/transporter/follower counts through time.

`phi` is a folded signed mean and can cancel across roles. `psi` and axial errors are the main order measures. Empty or very small role samples must be labelled unavailable or insufficient rather than imputed.

Raw follower step records are not an output. Sensing statistics must be aggregated online or reduced before writing so that no new raw diagnostic file exceeds 100 MB.

## 7. Acceptance gates

### 7.1 Engineering gate

All items must pass:

- all original and new automated tests pass;
- population is conserved and positions remain inside the arena;
- all recorded numerical state is finite;
- repeated fixed-seed runs are exactly reproducible at the tested scale;
- all protected SHA-256 values match;
- a fieldwise configuration audit finds `follower_direction_rule` as the only behavioural difference from the frozen baseline.

### 7.2 Mechanism-improvement gate

All items must pass simultaneously:

- late-window mean `psi` improves by at least `0.10` over the baseline late-window mean;
- follower hit-step mean axis error is at most `35 degrees`;
- cumulative deliveries are at least `291` (80% of 363);
- PCA direction inference does not depend on global food or nest coordinates.

The `0.10` comparison uses the actual Stage 2A mean over `t = 9,000..10,000`, calculated from the frozen CSV, not the Stage 2A final value.

### 7.3 Fig. 4 candidate gate

This gate is only a reason to consider later multi-seed validation:

- late-window mean `psi >= 0.90`;
- late-window mean `phi` differs from `pi/4` by no more than `0.15 rad`;
- transport and role cycling do not collapse.

If all conditions pass, the strongest allowed wording is `fixed-seed Fig. 4-like candidate`. The wording `Fig. 4 reproduced` is prohibited.

## 8. Execution protocol

1. Run the original 43 tests before implementation.
2. Add focused PCA, isolation, compatibility, reproducibility, population, boundary, finite-state, protection, and single-change tests.
3. Run one CPU pilot with `N = 10`, `t = 1,000`, and `local_weighted_pca_tangent`.
4. If the pilot is stable, run exactly one paper-scale CPU experiment with `N = 100`, `L = 300`, `t = 10,000`, seed `20260824`, provisional ZW, `gamma = 0.1`, and `Theta = 50 degrees`.
5. Do not scan parameters, change seed, use a GPU/AutoDL, or select a visually preferable run.

## 9. Required outputs

The paper-scale directory `results/stage2b_local_geometry/` must contain at least:

- `config.json`
- `baseline_comparison.json`
- `single_change_audit.json`
- `metrics.csv`
- `role_specific_order.csv`
- `axis_alignment.csv`
- `transition_counts.json`
- `runtime.json`
- `REPORT.md`

Required figures compare baseline and Stage 2B `phi/psi`, role-specific `phi/psi`, follower hit-step axis error, role counts, cumulative deliveries, and the final pheromone channel. Every figure and report carries the Stage 2B notice.

## 10. Scientific limitations

- One fixed seed cannot establish robustness or estimate uncertainty.
- PCA can recover only local geometric anisotropy present inside the existing sensing radius; it cannot identify causality upstream in transporter route generation.
- A broad non-decaying historical field can remain ambiguous even when local PCA is implemented correctly.
- The nest-food axis is used only for evaluation, never for the PCA movement decision.
- Passing an engineering gate does not imply mechanism improvement; passing the candidate gate does not imply reproduction.

## 11. Questions still awaiting professor confirmation

1. What exact local information and direction-selection rule did the original follower use?
2. How were pheromone width, deposition, concentration, and direction represented?
3. How were equal-concentration or geometrically ambiguous local trails resolved?
4. What exact one-third-memory endpoint and transporter interpolation rules were used?
5. What coordinates, radii, initialisation, food detection, boundary numerics, seed, event order, and order-parameter sampling produced Fig. 4?

No answer is inferred while the professor has not replied.
