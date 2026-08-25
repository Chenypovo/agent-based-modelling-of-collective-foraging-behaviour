# Agent-Based Modelling of Collective Foraging Behaviour

This repository implements Stage 1 single-ant walks and a **provisional Stage 2A** CPU-only colony model based on Zhang & Yong (2023).

Stage 2A adds a finite square, reflective boundaries, multiple ants, one nest, one inexhaustible food source, forager/transporter/follower roles, positional memory, and a replaceable discrete non-decaying pheromone field. It does not add ODE fitting, parameter optimisation, LLM agents, AutoDL, or GPU work. The original proposal, assessment template, briefing, similarity report, bibliography, and `results/stage1/` are not modified by the Stage 2 command.

Stage 2A is paper-informed but provisional because the authors' exact implementation details and source code are not available. It must not be described as an exact reproduction of Fig. 4. Read [docs/STAGE2_SPEC.md](docs/STAGE2_SPEC.md) for the explicit/provisional rule boundary.

## Mathematical specification

Read [docs/STAGE1_SPEC.md](docs/STAGE1_SPEC.md) before treating the results as a paper reproduction. It separates:

- rules stated explicitly in Sections II–III;
- conservative implementation choices;
- inconsistencies or missing details in the paper;
- the provisional branch-conditional interpretation of ZW equations (5)–(7);
- questions that still need later supervisor confirmation.

The implementation uses fixed-length 2D steps and `theta_i = U_i V_i`, with `V_i` uniform on `[0, Theta]`. FCRW repeats the previous turn sign with probability `gamma`. The ZW implementation follows the `gamma`, `gamma^2`, and `gamma^3` branch probabilities shown in Fig. 1(d).

## Environment

The existing Mac Python environment already contains the required lightweight packages. To create an isolated environment elsewhere:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Dependencies are NumPy, Matplotlib, Pandas, and Pytest. No GPU dependency is used.

## Run all Stage 1 experiments

```bash
./run_stage1.sh
```

The default run uses all three models, 2,000 movement steps, step size/speed 0.6, `Theta=60` degrees, `gamma=0.2`, seed `20260824`, and 50 repetitions per model.

All requested controls are available:

```bash
./run_stage1.sh \
  --model all \
  --steps 2000 \
  --step-size 0.6 \
  --theta-deg 60 \
  --gamma 0.2 \
  --seed 20260824 \
  --repetitions 50
```

Use `--speed 0.6` instead of `--step-size 0.6` if preferred. Stage 1 fixes the time step to one, so speed and step size have the same numerical value. Use `--cell-size` to change the visited-site grid resolution and `--output-dir` to redirect results.

## Run tests

```bash
MPLCONFIGDIR="${TMPDIR:-/tmp}/ant-walks-matplotlib" \
XDG_CACHE_HOME="${TMPDIR:-/tmp}/ant-walks-cache" \
python3 -m pytest -q
```

Tests cover deterministic seeds, fixed step length, angle bounds, SRW left/right balance, FCRW same-turn probability, the provisional ZW probability update, coverage binning, and isolation of model state.

## Run Stage 2A

The default command first runs all tests, then the fixed `N=10`, 1,000-step pilot, and only after that passes runs the fixed `N=100`, `L=300`, 10,000-step CPU experiment:

```bash
./run_stage2.sh
```

Run only one preset if needed:

```bash
./run_stage2.sh --preset pilot
./run_stage2.sh --preset paper
```

The default paper-scale run uses provisional ZW, `gamma=0.1`, `Theta=50` degrees, step/speed `0.6`, sensing range `0.6`, and snapshots at `t=1000`, `4000`, and `10000`. All unpublished numerical choices are centralised in `ColonyConfig` and documented in `docs/STAGE2_SPEC.md`.

Paper-scale outputs are written to `results/stage2_provisional/`; pilot outputs are written to its `pilot/` subdirectory. The command is CPU-only and does not perform parameter scans.

## Results

The default command writes a compact result set to `results/stage1/`:

- `REPORT.md`: configuration, aggregate values, interpretation, runtime, and claim boundary;
- `config.json`: exact input parameters;
- `metrics_per_run.csv`: one row per model and repetition;
- `summary.csv`: means and uncertainty estimates;
- `trajectories.png`: example SRW, FCRW, and ZW paths;
- `turning_statistics.png`: turn-sign correlations;
- `spatial_statistics.png`: straightness and cumulative visited sites;
- `runtime.json`: CPU/platform timing record.

These outputs show the implemented rule differences. They are **not** labelled as an exact numerical reproduction of Zhang & Yong Figs. 1–3 because the paper does not provide all seeds, run counts, rasterisation details, fitting windows, and error definitions required for that claim.
