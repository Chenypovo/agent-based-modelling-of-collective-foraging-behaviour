# Stage 1 results

This directory contains an independent single-ant implementation of SRW, FCRW, and the provisional branch-conditional ZW interpretation documented in `docs/STAGE1_SPEC.md`.

## Run configuration

- steps per trajectory: 2000
- repetitions per model: 50
- step size / speed: 0.6
- Theta: 60 degrees
- gamma: 0.2
- base random seed: 20260824
- coverage cell size: 0.6

## Aggregate results

Values are mean +/- normal-approximation 95% Monte Carlo half-width across repetitions.

| model | metric | mean +/- error |
|---|---|---:|
| SRW | same-turn fraction | 0.501341 +/- 0.0027 |
| SRW | lag-one sign product | 0.00268134 +/- 0.0053 |
| SRW | paper-style rho | 0.82585 +/- 0.00088 |
| SRW | straightness | 0.0642306 +/- 0.01 |
| SRW | visited sites | 1715.74 +/- 14 |
| FCRW | same-turn fraction | 0.201751 +/- 0.0024 |
| FCRW | lag-one sign product | -0.596498 +/- 0.0048 |
| FCRW | paper-style rho | 0.826616 +/- 0.00085 |
| FCRW | straightness | 0.0968731 +/- 0.012 |
| FCRW | visited sites | 1835.1 +/- 6.9 |
| ZW (provisional) | same-turn fraction | 0.172336 +/- 0.0018 |
| ZW (provisional) | lag-one sign product | -0.655328 +/- 0.0037 |
| ZW (provisional) | paper-style rho | 0.826821 +/- 0.00099 |
| ZW (provisional) | straightness | 0.100641 +/- 0.017 |
| ZW (provisional) | visited sites | 1853.88 +/- 7.3 |

## Interpretation boundary

- SRW should have a same-turn fraction near 0.5. FCRW should have a same-turn fraction near gamma by construction.
- FCRW and ZW favour alternating turn signs, which cancels successive angular changes and can produce greater directional persistence than SRW.
- The paper-style rho is expected to be similar across models at fixed Theta because all three use the same uniform turn-magnitude distribution; gamma changes sign ordering rather than the marginal magnitude distribution.
- Visited-site and displacement differences apply only to the stated trajectory length, cell resolution, and parameter values.
- These outputs are not an exact numerical reproduction of Figs. 1–3. The paper does not supply all seeds, run counts, rasterisation details, fitting windows, and error definitions needed for that claim.

## Runtime and hardware

The measured end-to-end Python process through figure generation finished in 1.995 seconds, including dependency import, simulation, CSV/JSON output, and plotting. The simulation and metric pass took 0.450 seconds. Final timing/report serialisation occurs immediately after this measurement. The run used macOS-27.0-x86_64-i386-64bit (x86_64) with CPU-only NumPy/Matplotlib/Pandas code. No GPU or AutoDL resource was used. This runtime is sufficient for the bounded Stage 1 workload.

## Files

- `config.json`: exact run parameters
- `metrics_per_run.csv`: one row per model and repetition
- `summary.csv`: means, standard deviations, standard errors, and 95% error half-widths
- `trajectories.png`: one example path per model
- `turning_statistics.png`: turn-sign correlation comparison
- `spatial_statistics.png`: straightness and cumulative visited-site comparison
- `runtime.json`: wall-clock and platform information
