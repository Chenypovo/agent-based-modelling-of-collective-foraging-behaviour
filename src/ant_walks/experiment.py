"""Repeated Stage 1 experiments, summaries, figures, and report output."""

from __future__ import annotations

import json
import platform
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .metrics import compute_trajectory_metrics, cumulative_visited_sites
from .models import ModelName, Trajectory, generate_trajectory

MODEL_ORDER: tuple[ModelName, ...] = ("srw", "fcrw", "zw")
MODEL_CODES = {"srw": 11, "fcrw": 23, "zw": 37}
MODEL_LABELS = {"srw": "SRW", "fcrw": "FCRW", "zw": "ZW (provisional)"}
MODEL_COLOURS = {"srw": "#D55E00", "fcrw": "#E69F00", "zw": "#7B2CBF"}
METRIC_COLUMNS = (
    "same_turn_fraction",
    "lag1_sign_product",
    "paper_rho_mean_cos_turn",
    "circular_turn_resultant_length",
    "net_displacement",
    "straightness",
    "visited_sites",
    "covered_area",
)


@dataclass(frozen=True)
class ExperimentConfig:
    models: tuple[ModelName, ...] = MODEL_ORDER
    steps: int = 2_000
    step_size: float = 0.6
    theta_deg: float = 60.0
    gamma: float = 0.2
    seed: int = 20_260_824
    repetitions: int = 50
    cell_size: float = 0.6
    output_dir: str = "results/stage1"


@dataclass(frozen=True)
class ExperimentResult:
    metrics: pd.DataFrame
    summary: pd.DataFrame
    runtime_seconds: float
    output_dir: Path


def _derived_seed(base_seed: int, model: ModelName, repetition: int) -> int:
    seed_sequence = np.random.SeedSequence([base_seed, MODEL_CODES[model], repetition])
    return int(seed_sequence.generate_state(1, dtype=np.uint64)[0])


def _summarise(metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for model in MODEL_ORDER:
        model_rows = metrics.loc[metrics["model"] == model]
        if model_rows.empty:
            continue
        for metric in METRIC_COLUMNS:
            values = model_rows[metric].dropna().to_numpy(dtype=float)
            n = len(values)
            mean = float(np.mean(values))
            std = float(np.std(values, ddof=1)) if n > 1 else 0.0
            standard_error = std / np.sqrt(n) if n else float("nan")
            rows.append(
                {
                    "model": model,
                    "metric": metric,
                    "mean": mean,
                    "std": std,
                    "standard_error": standard_error,
                    "ci95_half_width": 1.96 * standard_error,
                    "n": n,
                }
            )
    return pd.DataFrame(rows)


def _summary_value(summary: pd.DataFrame, model: str, metric: str, column: str) -> float:
    match = summary.loc[(summary["model"] == model) & (summary["metric"] == metric), column]
    return float(match.iloc[0])


def _plot_trajectories(samples: dict[ModelName, Trajectory], output_dir: Path) -> None:
    fig, axes = plt.subplots(1, len(samples), figsize=(12, 4), constrained_layout=True)
    axes_array = np.atleast_1d(axes)
    for axis, model in zip(axes_array, samples):
        trajectory = samples[model]
        position = trajectory.positions
        axis.plot(position[:, 0], position[:, 1], color=MODEL_COLOURS[model], linewidth=1.0)
        axis.scatter(position[0, 0], position[0, 1], color="black", s=24, marker="o", label="start")
        axis.scatter(position[-1, 0], position[-1, 1], color=MODEL_COLOURS[model], s=30, marker="x", label="end")
        axis.set_title(MODEL_LABELS[model])
        axis.set_xlabel("x (length units)")
        axis.set_ylabel("y (length units)")
        axis.set_aspect("equal", adjustable="datalim")
        axis.legend(frameon=False, fontsize=8)
    fig.suptitle("Stage 1 example trajectories (same configuration, model-specific seeds)")
    fig.savefig(output_dir / "trajectories.png", dpi=180)
    plt.close(fig)


def _plot_turning_statistics(summary: pd.DataFrame, config: ExperimentConfig, output_dir: Path) -> None:
    models = [model for model in MODEL_ORDER if model in config.models]
    x = np.arange(len(models))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)

    for axis, metric, title, ylabel in (
        (axes[0], "same_turn_fraction", "Adjacent turns with the same sign", "fraction"),
        (axes[1], "lag1_sign_product", "Lag-one turn-sign product", "mean($U_i U_{i+1}$)"),
    ):
        means = [_summary_value(summary, model, metric, "mean") for model in models]
        errors = [_summary_value(summary, model, metric, "ci95_half_width") for model in models]
        colours = [MODEL_COLOURS[model] for model in models]
        axis.bar(x, means, yerr=errors, color=colours, capsize=4, alpha=0.9)
        axis.set_xticks(x, [MODEL_LABELS[model] for model in models])
        axis.set_title(title)
        axis.set_ylabel(ylabel)
        axis.axhline(0.0, color="black", linewidth=0.8)
    axes[0].axhline(0.5, color="grey", linewidth=1.0, linestyle="--", label="SRW expectation")
    axes[0].axhline(config.gamma, color=MODEL_COLOURS["fcrw"], linewidth=1.0, linestyle=":", label="FCRW expectation")
    axes[0].legend(frameon=False, fontsize=8)
    axes[0].set_ylim(0.0, max(0.6, float(axes[0].get_ylim()[1])))
    axes[1].set_ylim(-1.0, 1.0)
    fig.suptitle("Turning-sign correlations (error bars: 95% Monte Carlo half-width)")
    fig.savefig(output_dir / "turning_statistics.png", dpi=180)
    plt.close(fig)


def _plot_spatial_statistics(
    summary: pd.DataFrame,
    coverage_curves: dict[ModelName, list[np.ndarray]],
    config: ExperimentConfig,
    output_dir: Path,
) -> None:
    models = [model for model in MODEL_ORDER if model in config.models]
    x = np.arange(len(models))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True)

    straightness = [_summary_value(summary, model, "straightness", "mean") for model in models]
    straightness_error = [
        _summary_value(summary, model, "straightness", "ci95_half_width") for model in models
    ]
    axes[0].bar(
        x,
        straightness,
        yerr=straightness_error,
        color=[MODEL_COLOURS[model] for model in models],
        capsize=4,
    )
    axes[0].set_xticks(x, [MODEL_LABELS[model] for model in models])
    axes[0].set_ylabel("net displacement / path length")
    axes[0].set_title("Trajectory straightness")
    axes[0].set_ylim(bottom=0.0)

    plot_step = max(1, config.steps // 500)
    time_steps = np.arange(config.steps + 1)
    for model in models:
        curves = np.asarray(coverage_curves[model], dtype=float)
        mean = np.mean(curves, axis=0)
        if len(curves) > 1:
            sem = np.std(curves, axis=0, ddof=1) / np.sqrt(len(curves))
        else:
            sem = np.zeros_like(mean)
        selected = slice(None, None, plot_step)
        axes[1].plot(
            time_steps[selected],
            mean[selected],
            color=MODEL_COLOURS[model],
            label=MODEL_LABELS[model],
        )
        axes[1].fill_between(
            time_steps[selected],
            (mean - 1.96 * sem)[selected],
            (mean + 1.96 * sem)[selected],
            color=MODEL_COLOURS[model],
            alpha=0.15,
        )
    axes[1].set_xlabel("movement steps")
    axes[1].set_ylabel("distinct visited cells")
    axes[1].set_title(f"Spatial coverage (cell size = {config.cell_size:g})")
    axes[1].legend(frameon=False)
    fig.suptitle("Single-ant spatial statistics")
    fig.savefig(output_dir / "spatial_statistics.png", dpi=180)
    plt.close(fig)


def _write_report(
    config: ExperimentConfig,
    summary: pd.DataFrame,
    runtime: dict[str, object],
    output_dir: Path,
) -> None:
    metric_labels = (
        ("same_turn_fraction", "same-turn fraction"),
        ("lag1_sign_product", "lag-one sign product"),
        ("paper_rho_mean_cos_turn", "paper-style rho"),
        ("straightness", "straightness"),
        ("visited_sites", "visited sites"),
    )
    lines = [
        "# Stage 1 results",
        "",
        "This directory contains an independent single-ant implementation of SRW, FCRW, and the provisional branch-conditional ZW interpretation documented in `docs/STAGE1_SPEC.md`.",
        "",
        "## Run configuration",
        "",
        f"- steps per trajectory: {config.steps}",
        f"- repetitions per model: {config.repetitions}",
        f"- step size / speed: {config.step_size:g}",
        f"- Theta: {config.theta_deg:g} degrees",
        f"- gamma: {config.gamma:g}",
        f"- base random seed: {config.seed}",
        f"- coverage cell size: {config.cell_size:g}",
        "",
        "## Aggregate results",
        "",
        "Values are mean +/- normal-approximation 95% Monte Carlo half-width across repetitions.",
        "",
        "| model | metric | mean +/- error |",
        "|---|---|---:|",
    ]
    for model in MODEL_ORDER:
        if model not in config.models:
            continue
        for metric, label in metric_labels:
            mean = _summary_value(summary, model, metric, "mean")
            error = _summary_value(summary, model, metric, "ci95_half_width")
            lines.append(f"| {MODEL_LABELS[model]} | {label} | {mean:.6g} +/- {error:.2g} |")

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- SRW should have a same-turn fraction near 0.5. FCRW should have a same-turn fraction near gamma by construction.",
            "- FCRW and ZW favour alternating turn signs, which cancels successive angular changes and can produce greater directional persistence than SRW.",
            "- The paper-style rho is expected to be similar across models at fixed Theta because all three use the same uniform turn-magnitude distribution; gamma changes sign ordering rather than the marginal magnitude distribution.",
            "- Visited-site and displacement differences apply only to the stated trajectory length, cell resolution, and parameter values.",
            "- These outputs are not an exact numerical reproduction of Figs. 1–3. The paper does not supply all seeds, run counts, rasterisation details, fitting windows, and error definitions needed for that claim.",
            "",
            "## Runtime and hardware",
            "",
            f"The measured end-to-end Python process through figure generation finished in {float(runtime['process_seconds_through_figures']):.3f} seconds, including dependency import, simulation, CSV/JSON output, and plotting. The simulation and metric pass took {float(runtime['simulation_analysis_seconds']):.3f} seconds. Final timing/report serialisation occurs immediately after this measurement. The run used {runtime['platform']} ({runtime['machine']}) with CPU-only NumPy/Matplotlib/Pandas code. No GPU or AutoDL resource was used. This runtime is sufficient for the bounded Stage 1 workload.",
            "",
            "## Files",
            "",
            "- `config.json`: exact run parameters",
            "- `metrics_per_run.csv`: one row per model and repetition",
            "- `summary.csv`: means, standard deviations, standard errors, and 95% error half-widths",
            "- `trajectories.png`: one example path per model",
            "- `turning_statistics.png`: turn-sign correlation comparison",
            "- `spatial_statistics.png`: straightness and cumulative visited-site comparison",
            "- `runtime.json`: wall-clock and platform information",
            "",
        ]
    )
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_experiment(
    config: ExperimentConfig, *, process_start: float | None = None
) -> ExperimentResult:
    """Run all requested repetitions and write the compact Stage 1 result set."""

    if not config.models:
        raise ValueError("at least one model is required")
    if config.repetitions < 1:
        raise ValueError("repetitions must be positive")
    if not np.isfinite(config.cell_size) or config.cell_size <= 0:
        raise ValueError("cell_size must be finite and positive")

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    end_to_end_start = start if process_start is None else process_start
    rows: list[dict[str, float | int | str]] = []
    samples: dict[ModelName, Trajectory] = {}
    coverage_curves: dict[ModelName, list[np.ndarray]] = {model: [] for model in config.models}

    for model in config.models:
        for repetition in range(config.repetitions):
            derived_seed = _derived_seed(config.seed, model, repetition)
            trajectory = generate_trajectory(
                model,
                steps=config.steps,
                step_size=config.step_size,
                theta_max=np.deg2rad(config.theta_deg),
                gamma=config.gamma,
                seed=derived_seed,
            )
            if repetition == 0:
                samples[model] = trajectory
            coverage_curves[model].append(
                cumulative_visited_sites(trajectory.positions, config.cell_size)
            )
            row: dict[str, float | int | str] = {
                "model": model,
                "repetition": repetition,
                "derived_seed": derived_seed,
            }
            row.update(compute_trajectory_metrics(trajectory, config.cell_size))
            rows.append(row)

    simulation_analysis_seconds = time.perf_counter() - start
    metrics = pd.DataFrame(rows)
    summary = _summarise(metrics)
    metrics.to_csv(output_dir / "metrics_per_run.csv", index=False)
    summary.to_csv(output_dir / "summary.csv", index=False)

    serialised_config = asdict(config)
    serialised_config["models"] = list(config.models)
    (output_dir / "config.json").write_text(
        json.dumps(serialised_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _plot_trajectories(samples, output_dir)
    _plot_turning_statistics(summary, config, output_dir)
    _plot_spatial_statistics(summary, coverage_curves, config, output_dir)
    process_seconds_through_figures = time.perf_counter() - end_to_end_start
    runtime: dict[str, object] = {
        "simulation_analysis_seconds": simulation_analysis_seconds,
        "process_seconds_through_figures": process_seconds_through_figures,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "gpu_used": False,
        "autodl_used": False,
    }
    (output_dir / "runtime.json").write_text(
        json.dumps(runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_report(config, summary, runtime, output_dir)

    return ExperimentResult(metrics, summary, process_seconds_through_figures, output_dir)


def normalise_models(model: str) -> tuple[ModelName, ...]:
    """Convert one CLI model selection to the experiment model tuple."""

    lowered = model.lower()
    if lowered == "all":
        return MODEL_ORDER
    if lowered not in MODEL_ORDER:
        raise ValueError(f"unknown model {model!r}")
    return (lowered,)  # type: ignore[return-value]
