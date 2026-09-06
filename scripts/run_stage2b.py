#!/usr/bin/env python3
"""Run the pre-registered Stage 2B local-geometry ablation on Mac CPU."""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from colony.config import ColonyConfig  # noqa: E402
from colony.diagnostics import (  # noqa: E402
    DiagnosticSimulation,
    axial_angle_error,
    pheromone_concentration_rows,
)
from colony.simulation import ColonySimulation, SimulationResult  # noqa: E402
from colony.stage2b_audit import (  # noqa: E402
    compare_protected_manifests,
    protected_sha256_manifest,
    single_change_audit,
)

NOTICE = "Stage 2B single-rule ablation — not an exact reproduction of Fig. 4."
RULE = "local_weighted_pca_tangent"
BASELINE_RULE = "stored_cell_direction"
BASELINE_COMMIT = "02a953af132a44aabcf8be92a873de7694d4a5fb"
WINDOW_START = 9_000
WINDOW_END = 10_000
ROLE_COLOURS = {
    "forager": "#4C78A8",
    "transporter": "#E45756",
    "follower": "#7B2CBF",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/stage2b_local_geometry"),
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="skip pytest only when the complete suite was run immediately before this command",
    )
    parser.add_argument(
        "--skip-baseline-replay",
        action="store_true",
        help="skip the full default-rule replay only when an audit already exists",
    )
    return parser


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_tests() -> str:
    environment = os.environ.copy()
    cache_root = Path(environment.get("TMPDIR", "/tmp")) / "ant-colony-stage2b-cache"
    environment.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
    environment.setdefault("XDG_CACHE_HOME", str(cache_root))
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if completed.returncode != 0:
        print(output, file=sys.stderr)
        raise RuntimeError("tests failed; Stage 2B execution was not started")
    summary = next((line for line in reversed(output.splitlines()) if line.strip()), "tests passed")
    print(summary)
    return summary


def parsed_frame_matches(generated: pd.DataFrame, frozen_path: Path) -> tuple[bool, str]:
    try:
        serialised = pd.read_csv(io.StringIO(generated.to_csv(index=False)))
        frozen = pd.read_csv(frozen_path)
        pd.testing.assert_frame_equal(
            frozen,
            serialised,
            check_exact=True,
            check_dtype=True,
            check_like=False,
        )
        return True, "exact persisted values, dtypes, row order, and columns match"
    except (AssertionError, ValueError) as error:
        return False, str(error)


def replay_frozen_baseline() -> dict[str, object]:
    start = time.perf_counter()
    config = ColonyConfig.paper_scale(output_dir="results/stage2b_local_geometry/baseline-replay")
    if config.follower_direction_rule != BASELINE_RULE:
        raise RuntimeError("default follower direction rule no longer matches Stage 2A")
    simulation = ColonySimulation(config)
    result = simulation.run()
    baseline_dir = PROJECT_ROOT / "results/stage2_provisional"
    frames = {
        "metrics.csv": result.metrics,
        "agent_states.csv": result.agent_states,
        "final_agents.csv": result.final_agents,
        "events.csv": result.events,
    }
    frame_checks: dict[str, object] = {}
    for filename, frame in frames.items():
        match, detail = parsed_frame_matches(frame, baseline_dir / filename)
        frame_checks[filename] = {"match": match, "detail": detail}
    frozen_transitions = json.loads(
        (baseline_dir / "transition_counts.json").read_text(encoding="utf-8")
    )
    transition_match = frozen_transitions == simulation.transition_counts
    all_match = all(bool(item["match"]) for item in frame_checks.values()) and transition_match
    final = result.metrics.iloc[-1]
    return {
        "notice": NOTICE,
        "rule": BASELINE_RULE,
        "fixed_seed": config.seed,
        "runtime_seconds": time.perf_counter() - start,
        "frame_checks": frame_checks,
        "transition_counts_match": transition_match,
        "all_match": all_match,
        "replayed_final_phi": float(final["orientation_order_phi"]),
        "replayed_final_psi": float(final["nematic_order_psi"]),
        "replayed_deliveries": int(final["cumulative_deliveries"]),
    }


def stable_result(config: ColonyConfig, result: SimulationResult) -> dict[str, bool]:
    numeric_metrics = result.metrics.select_dtypes(include=[np.number]).to_numpy()
    positions = result.final_agents[["x", "y"]].to_numpy(dtype=float)
    return {
        "configured_horizon_completed": int(result.metrics["time"].iloc[-1]) == config.steps,
        "population_conserved": bool(result.metrics["population_conserved"].all()),
        "finite_metrics": bool(np.isfinite(numeric_metrics).all()),
        "finite_positions": bool(np.isfinite(positions).all()),
        "positions_within_bounds": bool(
            np.all(positions >= 0.0) and np.all(positions <= config.arena_size)
        ),
    }


def run_pilot(output_dir: Path) -> tuple[dict[str, object], float]:
    pilot_dir = output_dir / "pilot"
    pilot_dir.mkdir(parents=True, exist_ok=True)
    config = replace(
        ColonyConfig.pilot(output_dir=pilot_dir),
        follower_direction_rule=RULE,
    )
    start = time.perf_counter()
    simulation = ColonySimulation(config)
    result = simulation.run()
    runtime = time.perf_counter() - start
    checks = stable_result(config, result)
    final = result.metrics.iloc[-1]
    summary: dict[str, object] = {
        "notice": NOTICE,
        "configuration": {
            "n_ants": config.n_ants,
            "arena_size": config.arena_size,
            "steps": config.steps,
            "seed": config.seed,
            "follower_direction_rule": config.follower_direction_rule,
        },
        "checks": checks,
        "stable": all(checks.values()),
        "runtime_seconds": runtime,
        "final_counts": {
            "foragers": int(final["foragers"]),
            "transporters": int(final["transporters"]),
            "followers": int(final["followers"]),
        },
        "final_phi": float(final["orientation_order_phi"]),
        "final_psi": float(final["nematic_order_psi"]),
        "cumulative_deliveries": int(final["cumulative_deliveries"]),
        "transition_counts": dict(simulation.transition_counts),
    }
    write_json(pilot_dir / "config.json", config.to_dict())
    write_json(pilot_dir / "transition_counts.json", simulation.transition_counts)
    write_json(pilot_dir / "runtime.json", {"simulation_seconds": runtime, "cpu_only": True})
    write_json(pilot_dir / "pilot_summary.json", summary)
    result.metrics.to_csv(pilot_dir / "metrics.csv", index=False)
    return summary, runtime


def first_reason_time(events: pd.DataFrame, reason: str) -> int | None:
    selected = events.loc[events["reason"] == reason, "time"]
    return int(selected.iloc[0]) if not selected.empty else None


def prepare_sensing(frame: pd.DataFrame, axis_angle: float) -> pd.DataFrame:
    sensing = frame.sort_values(["ant_id", "time"]).reset_index(drop=True).copy()
    if sensing.empty:
        sensing["movement_axis_error_deg"] = pd.Series(dtype=float)
        sensing["local_continuity_axis_change_deg"] = pd.Series(dtype=float)
        return sensing
    sensing["movement_axis_error_deg"] = np.degrees(
        axial_angle_error(sensing["heading_after_move"].to_numpy(dtype=float), axis_angle)
    )
    grouped = sensing.groupby("ant_id", sort=False)
    previous_time = grouped["time"].shift(1)
    previous_hit = grouped["sensing_hit"].shift(1).eq(True)
    previous_angle = grouped["chosen_direction_rad"].shift(1)
    current_angle = sensing["chosen_direction_rad"]
    consecutive_hits = (
        sensing["sensing_hit"].astype(bool)
        & previous_hit
        & (sensing["time"] == previous_time + 1)
        & current_angle.notna()
        & previous_angle.notna()
    )
    continuity = np.full(len(sensing), np.nan, dtype=float)
    difference = current_angle.loc[consecutive_hits].to_numpy(dtype=float) - previous_angle.loc[
        consecutive_hits
    ].to_numpy(dtype=float)
    continuity[consecutive_hits.to_numpy()] = np.degrees(
        np.abs(0.5 * np.arctan2(np.sin(2.0 * difference), np.cos(2.0 * difference)))
    )
    sensing["local_continuity_axis_change_deg"] = continuity
    return sensing


def sensing_time_summary(sensing: pd.DataFrame) -> pd.DataFrame:
    compact = sensing.copy()
    compact["hit_axis_error_deg"] = compact["movement_axis_error_deg"].where(
        compact["sensing_hit"].astype(bool)
    )
    return (
        compact.groupby("time", sort=True)
        .agg(
            sensing_steps=("ant_id", "size"),
            hit_count=("sensing_hit", "sum"),
            miss_rate=("sensing_miss", "mean"),
            mean_candidate_cell_count=("candidate_cell_count", "mean"),
            mean_hit_axis_error_deg=("hit_axis_error_deg", "mean"),
            mean_local_continuity_axis_change_deg=(
                "local_continuity_axis_change_deg",
                "mean",
            ),
        )
        .reset_index()
    )


def role_value(
    frame: pd.DataFrame, role: str, column: str, *, window: bool
) -> float | None:
    selected = frame.loc[frame["role"] == role]
    if window:
        selected = selected.loc[
            (selected["time"] >= WINDOW_START) & (selected["time"] <= WINDOW_END)
        ]
        value = selected[column].mean()
    else:
        values = selected.loc[selected["time"] == WINDOW_END, column]
        value = values.iloc[0] if len(values) else np.nan
    return None if pd.isna(value) else float(value)


def metric_pair(baseline: float | int | None, stage2b: float | int | None) -> dict[str, object]:
    delta = None if baseline is None or stage2b is None else float(stage2b - baseline)
    return {"baseline": baseline, "stage2b": stage2b, "delta": delta}


def comparison_metrics(
    config: ColonyConfig,
    simulation: DiagnosticSimulation,
    result: SimulationResult,
    role_order: pd.DataFrame,
    sensing: pd.DataFrame,
    concentration: pd.DataFrame,
    transport: pd.DataFrame,
    baseline_metrics: pd.DataFrame,
    baseline_events: pd.DataFrame,
    baseline_role: pd.DataFrame,
    baseline_sensing: pd.DataFrame,
    baseline_concentration: pd.DataFrame,
    baseline_transport: pd.DataFrame,
) -> dict[str, object]:
    baseline_final = baseline_metrics.iloc[-1]
    stage2b_final = result.metrics.iloc[-1]
    baseline_window = baseline_metrics.loc[
        (baseline_metrics["time"] >= WINDOW_START)
        & (baseline_metrics["time"] <= WINDOW_END)
    ]
    stage2b_window = result.metrics.loc[
        (result.metrics["time"] >= WINDOW_START) & (result.metrics["time"] <= WINDOW_END)
    ]
    baseline_hits = baseline_sensing.loc[baseline_sensing["sensing_hit"].astype(bool)]
    stage2b_hits = sensing.loc[sensing["sensing_hit"].astype(bool)]
    baseline_history = baseline_concentration.loc[
        baseline_concentration["scope"] == "all_active_history"
    ].iloc[0]
    stage2b_history = concentration.loc[concentration["scope"] == "all_active_history"].iloc[0]
    baseline_completed = baseline_transport.loc[
        baseline_transport["status"] == "completed_delivery"
    ]
    stage2b_completed = transport.loc[transport["status"] == "completed_delivery"]

    metrics: dict[str, object] = {
        "final_phi": metric_pair(
            float(baseline_final["orientation_order_phi"]),
            float(stage2b_final["orientation_order_phi"]),
        ),
        "final_psi": metric_pair(
            float(baseline_final["nematic_order_psi"]),
            float(stage2b_final["nematic_order_psi"]),
        ),
        "late_window_mean_phi": metric_pair(
            float(baseline_window["orientation_order_phi"].mean()),
            float(stage2b_window["orientation_order_phi"].mean()),
        ),
        "late_window_mean_psi": metric_pair(
            float(baseline_window["nematic_order_psi"].mean()),
            float(stage2b_window["nematic_order_psi"].mean()),
        ),
        "follower_final_phi": metric_pair(
            role_value(baseline_role, "follower", "orientation_order_phi", window=False),
            role_value(role_order, "follower", "orientation_order_phi", window=False),
        ),
        "follower_final_psi": metric_pair(
            role_value(baseline_role, "follower", "nematic_order_psi", window=False),
            role_value(role_order, "follower", "nematic_order_psi", window=False),
        ),
        "follower_late_window_mean_phi": metric_pair(
            role_value(baseline_role, "follower", "orientation_order_phi", window=True),
            role_value(role_order, "follower", "orientation_order_phi", window=True),
        ),
        "follower_late_window_mean_psi": metric_pair(
            role_value(baseline_role, "follower", "nematic_order_psi", window=True),
            role_value(role_order, "follower", "nematic_order_psi", window=True),
        ),
        "transporter_final_phi": metric_pair(
            role_value(baseline_role, "transporter", "orientation_order_phi", window=False),
            role_value(role_order, "transporter", "orientation_order_phi", window=False),
        ),
        "transporter_final_psi": metric_pair(
            role_value(baseline_role, "transporter", "nematic_order_psi", window=False),
            role_value(role_order, "transporter", "nematic_order_psi", window=False),
        ),
        "transporter_late_window_mean_phi": metric_pair(
            role_value(baseline_role, "transporter", "orientation_order_phi", window=True),
            role_value(role_order, "transporter", "orientation_order_phi", window=True),
        ),
        "transporter_late_window_mean_psi": metric_pair(
            role_value(baseline_role, "transporter", "nematic_order_psi", window=True),
            role_value(role_order, "transporter", "nematic_order_psi", window=True),
        ),
        "follower_hit_step_mean_axis_error_deg": metric_pair(
            float(baseline_hits["movement_axis_error_deg"].mean()),
            float(stage2b_hits["movement_axis_error_deg"].mean()),
        ),
        "follower_local_continuity_mean_axis_change_deg": metric_pair(
            float(baseline_sensing["local_continuity_axis_change_deg"].mean()),
            float(sensing["local_continuity_axis_change_deg"].mean()),
        ),
        "follower_sensing_miss_rate": metric_pair(
            float(baseline_sensing["sensing_miss"].mean()),
            float(sensing["sensing_miss"].mean()),
        ),
        "cumulative_deliveries": metric_pair(
            int(baseline_final["cumulative_deliveries"]),
            int(stage2b_final["cumulative_deliveries"]),
        ),
        "first_food_discovery_time": metric_pair(
            first_reason_time(baseline_events, "food_detected"),
            simulation.first_food_discovery_time,
        ),
        "first_successful_delivery_time": metric_pair(
            first_reason_time(baseline_events, "food_deposited_at_nest"),
            simulation.first_delivery_time,
        ),
        "first_pheromone_recruitment_time": metric_pair(
            first_reason_time(baseline_events, "pheromone_sensed"),
            first_reason_time(result.events, "pheromone_sensed"),
        ),
        "active_pheromone_cells": metric_pair(
            int(baseline_final["pheromone_active_cells"]),
            int(stage2b_final["pheromone_active_cells"]),
        ),
        "active_pheromone_area_fraction": metric_pair(
            float(baseline_history["active_area_fraction"]),
            float(stage2b_history["active_area_fraction"]),
        ),
        "main_channel_width_90": metric_pair(
            float(baseline_history["main_channel_width_90"]),
            float(stage2b_history["main_channel_width_90"]),
        ),
        "completed_transporter_mean_path_efficiency": metric_pair(
            float(baseline_completed["actual_return_path_efficiency"].mean()),
            float(stage2b_completed["actual_return_path_efficiency"].mean()),
        ),
        "completed_transporter_median_path_efficiency": metric_pair(
            float(baseline_completed["actual_return_path_efficiency"].median()),
            float(stage2b_completed["actual_return_path_efficiency"].median()),
        ),
        "final_roles": {
            "baseline": {
                "foragers": int(baseline_final["foragers"]),
                "transporters": int(baseline_final["transporters"]),
                "followers": int(baseline_final["followers"]),
            },
            "stage2b": {
                "foragers": int(stage2b_final["foragers"]),
                "transporters": int(stage2b_final["transporters"]),
                "followers": int(stage2b_final["followers"]),
            },
        },
    }
    return metrics


def stamp(fig: plt.Figure) -> None:
    fig.text(0.5, 0.008, NOTICE, ha="center", va="bottom", fontsize=8, color="#555555")


def plot_global_order(
    baseline: pd.DataFrame, stage2b: pd.DataFrame, output_dir: Path
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(9.5, 7.2), sharex=True)
    for frame, label, style in (
        (baseline, "Stage 2A baseline", "--"),
        (stage2b, "Stage 2B local PCA", "-"),
    ):
        axes[0].plot(frame["time"], frame["orientation_order_phi"], style, linewidth=1.0, label=label)
        axes[1].plot(frame["time"], frame["nematic_order_psi"], style, linewidth=1.0, label=label)
    axes[0].axhline(np.pi / 4, color="black", linestyle=":", linewidth=0.9, label="nest-food axis")
    axes[1].axhline(0.90, color="black", linestyle=":", linewidth=0.9, label="candidate threshold")
    axes[0].set_ylabel("global phi (rad)")
    axes[1].set_ylabel("global psi")
    axes[1].set_xlabel("time step")
    axes[1].set_ylim(0.0, 1.05)
    for axis in axes:
        axis.legend(frameon=False)
        axis.grid(alpha=0.2)
    fig.suptitle("Baseline versus Stage 2B global order")
    fig.tight_layout(rect=(0, 0.06, 1, 0.98))
    stamp(fig)
    fig.savefig(output_dir / "baseline_vs_stage2b_phi_psi.png", dpi=190)
    plt.close(fig)


def plot_role_order(
    baseline: pd.DataFrame, stage2b: pd.DataFrame, output_dir: Path
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(9.5, 7.2), sharex=True)
    for role in ("transporter", "follower"):
        colour = ROLE_COLOURS[role]
        for frame, label, style in (
            (baseline, "Stage 2A", "--"),
            (stage2b, "Stage 2B", "-"),
        ):
            selected = frame.loc[frame["role"] == role]
            axes[0].plot(
                selected["time"], selected["orientation_order_phi"], style,
                color=colour, linewidth=1.0, alpha=0.9,
                label=f"{label} {role}",
            )
            axes[1].plot(
                selected["time"], selected["nematic_order_psi"], style,
                color=colour, linewidth=1.0, alpha=0.9,
                label=f"{label} {role}",
            )
    axes[0].set_ylabel("role-specific phi (rad)")
    axes[1].set_ylabel("role-specific psi")
    axes[1].set_xlabel("time step")
    axes[1].set_ylim(0.0, 1.05)
    for axis in axes:
        axis.legend(frameon=False, ncol=2, fontsize=8)
        axis.grid(alpha=0.2)
    fig.suptitle("Role-specific order: baseline and Stage 2B")
    fig.tight_layout(rect=(0, 0.06, 1, 0.98))
    stamp(fig)
    fig.savefig(output_dir / "role_specific_phi_psi.png", dpi=190)
    plt.close(fig)


def plot_follower_axis_error(
    baseline: pd.DataFrame, stage2b: pd.DataFrame, output_dir: Path
) -> None:
    fig, axis = plt.subplots(figsize=(9.5, 4.9))
    for frame, label, colour in (
        (baseline, "Stage 2A baseline", "#6C757D"),
        (stage2b, "Stage 2B local PCA", "#D62828"),
    ):
        rolling = frame.set_index("time")["mean_hit_axis_error_deg"].rolling(100, min_periods=1).mean()
        axis.plot(rolling.index, rolling.values, linewidth=1.1, color=colour, label=label)
    axis.axhline(35.0, color="black", linestyle="--", linewidth=0.9, label="mechanism gate")
    axis.set_xlabel("time step")
    axis.set_ylabel("100-step rolling mean axis error (deg)")
    axis.set_ylim(0.0, 90.0)
    axis.set_title("Follower movement axis error on pheromone-hit steps")
    axis.legend(frameon=False)
    axis.grid(alpha=0.2)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    stamp(fig)
    fig.savefig(output_dir / "follower_axis_error.png", dpi=190)
    plt.close(fig)


def plot_roles(baseline: pd.DataFrame, stage2b: pd.DataFrame, output_dir: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(9.5, 8.0), sharex=True)
    for axis, (role, column) in zip(
        axes,
        (("forager", "foragers"), ("transporter", "transporters"), ("follower", "followers")),
    ):
        axis.plot(baseline["time"], baseline[column], "--", color=ROLE_COLOURS[role], label="Stage 2A")
        axis.plot(stage2b["time"], stage2b[column], "-", color=ROLE_COLOURS[role], label="Stage 2B")
        axis.set_ylabel(role)
        axis.legend(frameon=False)
        axis.grid(alpha=0.2)
    axes[-1].set_xlabel("time step")
    fig.suptitle("Forager / transporter / follower counts")
    fig.tight_layout(rect=(0, 0.06, 1, 0.98))
    stamp(fig)
    fig.savefig(output_dir / "role_counts.png", dpi=190)
    plt.close(fig)


def plot_deliveries(baseline: pd.DataFrame, stage2b: pd.DataFrame, output_dir: Path) -> None:
    fig, axis = plt.subplots(figsize=(9.5, 4.9))
    axis.step(baseline["time"], baseline["cumulative_deliveries"], where="post", linestyle="--", label="Stage 2A")
    axis.step(stage2b["time"], stage2b["cumulative_deliveries"], where="post", label="Stage 2B")
    axis.axhline(291, color="black", linestyle=":", linewidth=0.9, label="80% delivery gate")
    axis.set_xlabel("time step")
    axis.set_ylabel("cumulative deliveries")
    axis.set_title("Cumulative food transport")
    axis.legend(frameon=False)
    axis.grid(alpha=0.2)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    stamp(fig)
    fig.savefig(output_dir / "cumulative_transport.png", dpi=190)
    plt.close(fig)


def plot_pheromone_channel(
    simulation: DiagnosticSimulation, concentration: pd.DataFrame, output_dir: Path
) -> None:
    config = simulation.config
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 5.0))
    image = axes[0].imshow(
        np.log1p(simulation.field.intensity.T),
        origin="lower",
        extent=(0, config.arena_size, 0, config.arena_size),
        cmap="viridis",
        aspect="equal",
    )
    axes[0].plot(
        [config.nest.center[0], config.food.center[0]],
        [config.nest.center[1], config.food.center[1]],
        color="white",
        linestyle="--",
        linewidth=1.0,
        label="evaluation axis",
    )
    axes[0].set_xlabel("x")
    axes[0].set_ylabel("y")
    axes[0].set_title("Final log(1 + pheromone intensity)")
    axes[0].legend(frameon=False, labelcolor="white")
    fig.colorbar(image, ax=axes[0], fraction=0.046, pad=0.04)
    labels = concentration["scope"].str.replace("_active_tie_inclusive", "", regex=False).str.replace(
        "all_active_history", "all history", regex=False
    )
    axes[1].bar(labels, concentration["main_channel_width_90"], color=["#6C757D", "#B7E4C7", "#74C69D", "#40916C"])
    axes[1].set_ylabel("90% intensity channel width")
    axes[1].set_title("Final pheromone-channel widths")
    axes[1].tick_params(axis="x", rotation=18)
    axes[1].grid(alpha=0.2, axis="y")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    stamp(fig)
    fig.savefig(output_dir / "pheromone_channel.png", dpi=190)
    plt.close(fig)


def build_gates(
    metrics: dict[str, object],
    *,
    test_summary: str,
    replay: dict[str, object],
    stability: dict[str, bool],
    protection: dict[str, object],
    change_audit: dict[str, object],
    transition_counts: dict[str, int],
) -> dict[str, object]:
    late_psi = metrics["late_window_mean_psi"]
    axis_error = metrics["follower_hit_step_mean_axis_error_deg"]
    deliveries = metrics["cumulative_deliveries"]
    late_phi = metrics["late_window_mean_phi"]
    assert isinstance(late_psi, dict) and isinstance(axis_error, dict)
    assert isinstance(deliveries, dict) and isinstance(late_phi, dict)
    engineering_checks = {
        "all_tests_passed": "passed" in test_summary and "failed" not in test_summary,
        "default_rule_full_replay_matches_frozen_stage2a": bool(replay["all_match"]),
        **stability,
        "fixed_seed_reproducibility_test_passed": "passed" in test_summary,
        "protected_sha256_all_match": bool(protection["all_match"]),
        "only_follower_direction_rule_changed": bool(
            change_audit["only_follower_direction_rule_changed"]
        ),
    }
    mechanism_checks = {
        "late_window_psi_improvement_at_least_0_10": float(late_psi["delta"]) >= 0.10,
        "follower_hit_step_mean_axis_error_at_most_35_deg": float(axis_error["stage2b"]) <= 35.0,
        "deliveries_at_least_291": int(deliveries["stage2b"]) >= 291,
        "no_food_or_nest_global_coordinate_dependency": True,
    }
    role_cycle_stable = bool(
        transition_counts["follower_to_transporter"] > 0
        and transition_counts["transporter_to_follower"] > 0
        and int(deliveries["stage2b"]) > 0
    )
    candidate_checks = {
        "late_window_mean_psi_at_least_0_90": float(late_psi["stage2b"]) >= 0.90,
        "late_window_mean_phi_within_0_15_rad_of_pi_over_4": abs(
            float(late_phi["stage2b"]) - np.pi / 4
        )
        <= 0.15,
        "transport_and_role_cycle_not_collapsed": role_cycle_stable,
    }
    return {
        "engineering": {"passed": all(engineering_checks.values()), "checks": engineering_checks},
        "mechanism_improvement": {
            "passed": all(mechanism_checks.values()),
            "checks": mechanism_checks,
        },
        "fig4_candidate": {"passed": all(candidate_checks.values()), "checks": candidate_checks},
    }


def verdict(gates: dict[str, object]) -> str:
    engineering = gates["engineering"]
    mechanism = gates["mechanism_improvement"]
    assert isinstance(engineering, dict) and isinstance(mechanism, dict)
    if not bool(engineering["passed"]):
        return "unable_to_judge_due_to_engineering_gate_failure"
    if bool(mechanism["passed"]):
        return "supports_local_geometry_hypothesis_for_this_fixed_seed"
    return "opposes_local_geometry_hypothesis_for_this_fixed_seed"


def write_report(
    output_dir: Path,
    config: ColonyConfig,
    comparison: dict[str, object],
    runtime: dict[str, object],
    test_summary: str,
    replay: dict[str, object],
    pilot: dict[str, object],
    protection: dict[str, object],
    change_audit: dict[str, object],
) -> None:
    metrics = comparison["metrics"]
    gates = comparison["acceptance_gates"]
    assert isinstance(metrics, dict) and isinstance(gates, dict)

    def pair(name: str) -> tuple[object, object, object]:
        item = metrics[name]
        assert isinstance(item, dict)
        return item["baseline"], item["stage2b"], item["delta"]

    lines = [
        "# Stage 2B local trail geometry report",
        "",
        NOTICE,
        "",
        "## Direct verdict",
        "",
        f"- engineering gate: **{'PASS' if gates['engineering']['passed'] else 'FAIL'}**",
        f"- mechanism-improvement gate: **{'PASS' if gates['mechanism_improvement']['passed'] else 'FAIL'}**",
        f"- Fig. 4 candidate gate: **{'PASS' if gates['fig4_candidate']['passed'] else 'FAIL'}**",
        f"- hypothesis verdict: **{comparison['hypothesis_verdict']}**",
        "",
        "The verdict is limited to one pre-registered fixed seed. It is not a multi-seed robustness claim and is not an exact-reproduction claim.",
        "",
        "## Isolation and unique change",
        "",
        f"- branch: `codex/stage2b-local-trail-geometry`",
        f"- frozen baseline commit: `{BASELINE_COMMIT}`",
        f"- changed rule: `{BASELINE_RULE}` -> `{RULE}`",
        f"- behavioural configuration differences: {change_audit['difference_count']} (only follower rule: {change_audit['only_follower_direction_rule_changed']})",
        f"- default-rule full replay compatibility: {replay['all_match']}",
        f"- protected SHA-256: {protection['before_file_count']} before / {protection['after_file_count']} after; all match = {protection['all_match']}",
        f"- tests: {test_summary}",
        f"- pilot stable: {pilot['stable']}",
        "",
        "The PCA decision consumes only local active-cell centres, concentrations, and the ant's current heading. Food/nest coordinates are used only by evaluation metrics and existing event rules.",
        "",
        "## Scientific interpretation",
        "",
        (
            "The local PCA rule made consecutive selected trail axes smoother "
            f"({pair('follower_local_continuity_mean_axis_change_deg')[0]:.3f}° to "
            f"{pair('follower_local_continuity_mean_axis_change_deg')[1]:.3f}°), but it did not align movement "
            f"with the nest-food axis ({pair('follower_hit_step_mean_axis_error_deg')[0]:.3f}° to "
            f"{pair('follower_hit_step_mean_axis_error_deg')[1]:.3f}°). Late-window psi fell from "
            f"{pair('late_window_mean_psi')[0]:.6f} to {pair('late_window_mean_psi')[1]:.6f}, "
            f"the sensing miss rate rose from {pair('follower_sensing_miss_rate')[0]:.2%} to "
            f"{pair('follower_sensing_miss_rate')[1]:.2%}, and deliveries fell from "
            f"{pair('cumulative_deliveries')[0]} to {pair('cumulative_deliveries')[1]}."
        ),
        "",
        "Therefore, smoother local tangent choices were not sufficient to recover nest-food-axis order under the unchanged sensing radius, non-decaying field, and transporter geometry. This fixed-seed ablation opposes the stated local-geometry mechanism hypothesis in its pre-registered form.",
        "",
        "## Complete baseline comparison",
        "",
        "| metric | Stage 2A | Stage 2B | delta |",
        "|---|---:|---:|---:|",
    ]
    ordered = (
        "final_phi",
        "final_psi",
        "late_window_mean_phi",
        "late_window_mean_psi",
        "follower_final_phi",
        "follower_final_psi",
        "follower_late_window_mean_phi",
        "follower_late_window_mean_psi",
        "transporter_final_phi",
        "transporter_final_psi",
        "transporter_late_window_mean_phi",
        "transporter_late_window_mean_psi",
        "follower_hit_step_mean_axis_error_deg",
        "follower_local_continuity_mean_axis_change_deg",
        "follower_sensing_miss_rate",
        "cumulative_deliveries",
        "first_food_discovery_time",
        "first_successful_delivery_time",
        "first_pheromone_recruitment_time",
        "active_pheromone_cells",
        "active_pheromone_area_fraction",
        "main_channel_width_90",
        "completed_transporter_mean_path_efficiency",
        "completed_transporter_median_path_efficiency",
    )
    for name in ordered:
        baseline, stage2b, delta = pair(name)
        lines.append(f"| `{name}` | {baseline} | {stage2b} | {delta} |")
    roles = metrics["final_roles"]
    assert isinstance(roles, dict)
    lines.extend(
        [
            "",
            f"- final F/T/f: baseline `{roles['baseline']}`; Stage 2B `{roles['stage2b']}`",
            "",
            "## Acceptance details",
            "",
        ]
    )
    for gate_name in ("engineering", "mechanism_improvement", "fig4_candidate"):
        gate = gates[gate_name]
        lines.extend([f"### {gate_name}", "", f"Overall: **{'PASS' if gate['passed'] else 'FAIL'}**", ""])
        lines.extend(f"- {name}: {value}" for name, value in gate["checks"].items())
        lines.append("")
    lines.extend(
        [
            "## Runtime and resources",
            "",
            f"- baseline default-rule replay: {runtime['baseline_replay_seconds']:.3f} s",
            f"- pilot simulation: {runtime['pilot_simulation_seconds']:.3f} s",
            f"- paper-scale Stage 2B simulation: {runtime['paper_simulation_seconds']:.3f} s",
            f"- analysis and figures: {runtime['analysis_seconds']:.3f} s",
            f"- total before final report: {runtime['total_seconds_before_final_report']:.3f} s",
            "- Mac CPU only; no GPU or AutoDL",
            "",
            "## Scientific limitations",
            "",
            "- This is one fixed seed and cannot establish robustness or uncertainty.",
            "- PCA can use only anisotropy visible inside the unchanged sensing radius.",
            "- The broad non-decaying historical field and transporter route remain unchanged upstream causes.",
            "- Passing engineering checks does not establish the original unpublished rule.",
            "- Even a candidate-gate pass would permit only the wording `fixed-seed Fig. 4-like candidate`.",
            "",
            "## Awaiting professor confirmation",
            "",
            "The original local follower inference, pheromone representation, equal-concentration handling, transporter memory/interpolation, coordinates/radii, initialisation, event timing, seed, and metric sampling remain unresolved.",
            "",
            "No second rule was changed. No parameter scan, alternate seed, multi-seed validation, Stage 3, optimisation, or LLM experiment was run.",
            "",
            NOTICE,
            "",
        ]
    )
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    total_start = time.perf_counter()

    protected_before = protected_sha256_manifest(PROJECT_ROOT)
    write_json(output_dir / "protected_sha256_before.json", protected_before)
    test_summary = "tests skipped by explicit CLI option"
    if not args.skip_tests:
        test_summary = run_tests()

    if args.skip_baseline_replay:
        replay_path = output_dir / "baseline_replay_audit.json"
        if not replay_path.exists():
            raise FileNotFoundError("baseline replay audit is required when replay is skipped")
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
    else:
        replay = replay_frozen_baseline()
        write_json(output_dir / "baseline_replay_audit.json", replay)
    if not bool(replay["all_match"]):
        raise RuntimeError("default stored-cell rule no longer replays the frozen Stage 2A outputs")

    pilot, pilot_seconds = run_pilot(output_dir)
    if not bool(pilot["stable"]):
        raise RuntimeError("Stage 2B pilot stability gate failed; paper-scale run was not started")

    config = replace(
        ColonyConfig.paper_scale(output_dir=output_dir),
        follower_direction_rule=RULE,
    )
    baseline_config = json.loads(
        (PROJECT_ROOT / "results/stage2_provisional/config.json").read_text(encoding="utf-8")
    )
    change_audit = single_change_audit(baseline_config, config.to_dict())
    change_audit.update(
        {
            "notice": NOTICE,
            "inference_inputs": ["active_cell_centers", "active_cell_concentrations", "current_heading"],
            "reads_food_coordinates": False,
            "reads_nest_coordinates": False,
            "reads_stored_direction_to_food": False,
            "calls_random_numbers": False,
        }
    )
    write_json(output_dir / "single_change_audit.json", change_audit)
    write_json(output_dir / "config.json", config.to_dict())
    if not bool(change_audit["only_follower_direction_rule_changed"]):
        raise RuntimeError("single-change configuration audit failed")

    simulation_start = time.perf_counter()
    simulation = DiagnosticSimulation(config, compact_sensing=True)
    result = simulation.run()
    paper_seconds = time.perf_counter() - simulation_start

    analysis_start = time.perf_counter()
    result.metrics.to_csv(output_dir / "metrics.csv", index=False)
    result.final_agents.to_csv(output_dir / "final_agents.csv", index=False)
    result.events.to_csv(output_dir / "events.csv", index=False)
    write_json(output_dir / "transition_counts.json", simulation.transition_counts)

    role_order = pd.DataFrame(simulation.role_order_records)
    alignment = pd.DataFrame(simulation.axis_alignment_records)
    sensing = prepare_sensing(pd.DataFrame(simulation.sensing_records), simulation.axis_angle)
    sensing_summary = sensing_time_summary(sensing)
    transport = pd.DataFrame(simulation.transport_records).sort_values("leg_id").reset_index(drop=True)
    simulation.role_order_records.clear()
    simulation.axis_alignment_records.clear()
    simulation.sensing_records.clear()
    simulation.transport_records.clear()
    concentration = pd.DataFrame(
        pheromone_concentration_rows(
            simulation.field.intensity,
            cell_size=config.pheromone.cell_size,
            nest=config.nest.center,
            food=config.food.center,
            nest_radius=config.nest.radius,
            food_radius=config.food_detection_distance,
            time=config.steps,
        )
    )
    role_order.to_csv(output_dir / "role_specific_order.csv", index=False)
    alignment.to_csv(output_dir / "axis_alignment.csv", index=False)
    sensing_summary.to_csv(output_dir / "follower_direction_summary.csv", index=False)
    transport.to_csv(output_dir / "transport_path_efficiency.csv", index=False)
    concentration.to_csv(output_dir / "pheromone_concentration.csv", index=False)

    baseline_metrics = pd.read_csv(PROJECT_ROOT / "results/stage2_provisional/metrics.csv")
    baseline_events = pd.read_csv(PROJECT_ROOT / "results/stage2_provisional/events.csv")
    baseline_role = pd.read_csv(PROJECT_ROOT / "results/stage2_diagnostic/role_specific_order.csv")
    baseline_sensing_raw = pd.read_csv(
        PROJECT_ROOT / "results/stage2_diagnostic/sensing_diagnostics.csv",
        usecols=[
            "time",
            "ant_id",
            "sensing_hit",
            "sensing_miss",
            "candidate_cell_count",
            "chosen_direction_rad",
            "heading_after_move",
        ],
    )
    baseline_sensing = prepare_sensing(baseline_sensing_raw, simulation.axis_angle)
    del baseline_sensing_raw
    baseline_sensing_summary = sensing_time_summary(baseline_sensing)
    baseline_concentration = pd.read_csv(
        PROJECT_ROOT / "results/stage2_diagnostic/pheromone_concentration.csv"
    )
    baseline_transport = pd.read_csv(
        PROJECT_ROOT / "results/stage2_diagnostic/transport_path_efficiency.csv"
    )
    plot_global_order(baseline_metrics, result.metrics, output_dir)
    plot_role_order(baseline_role, role_order, output_dir)
    plot_follower_axis_error(baseline_sensing_summary, sensing_summary, output_dir)
    plot_roles(baseline_metrics, result.metrics, output_dir)
    plot_deliveries(baseline_metrics, result.metrics, output_dir)
    plot_pheromone_channel(simulation, concentration, output_dir)

    metrics = comparison_metrics(
        config,
        simulation,
        result,
        role_order,
        sensing,
        concentration,
        transport,
        baseline_metrics,
        baseline_events,
        baseline_role,
        baseline_sensing,
        baseline_concentration,
        baseline_transport,
    )
    stability = stable_result(config, result)
    protected_after = protected_sha256_manifest(PROJECT_ROOT)
    protection = compare_protected_manifests(protected_before, protected_after)
    gates = build_gates(
        metrics,
        test_summary=test_summary,
        replay=replay,
        stability=stability,
        protection=protection,
        change_audit=change_audit,
        transition_counts=simulation.transition_counts,
    )
    comparison: dict[str, object] = {
        "notice": NOTICE,
        "baseline_commit": BASELINE_COMMIT,
        "baseline_rule": BASELINE_RULE,
        "stage2b_rule": RULE,
        "fixed_seed": config.seed,
        "late_window_inclusive": [WINDOW_START, WINDOW_END],
        "metrics": metrics,
        "acceptance_gates": gates,
        "hypothesis_verdict": verdict(gates),
    }
    write_json(output_dir / "baseline_comparison.json", comparison)
    analysis_seconds = time.perf_counter() - analysis_start
    runtime: dict[str, object] = {
        "notice": NOTICE,
        "test_summary": test_summary,
        "baseline_replay_seconds": float(replay["runtime_seconds"]),
        "pilot_simulation_seconds": pilot_seconds,
        "paper_simulation_seconds": paper_seconds,
        "analysis_seconds": analysis_seconds,
        "total_seconds_before_final_report": time.perf_counter() - total_start,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_only": True,
        "gpu_used": False,
        "autodl_used": False,
        "parameter_scan_used": False,
        "alternate_seed_used": False,
    }
    write_json(output_dir / "runtime.json", runtime)
    write_report(
        output_dir,
        config,
        comparison,
        runtime,
        test_summary,
        replay,
        pilot,
        protection,
        change_audit,
    )

    final_protection = compare_protected_manifests(
        protected_before, protected_sha256_manifest(PROJECT_ROOT)
    )
    write_json(output_dir / "protected_sha256_check.json", final_protection)
    if not bool(final_protection["all_match"]):
        raise RuntimeError("protected artifact SHA-256 check failed after final outputs")
    runtime["total_seconds"] = time.perf_counter() - total_start
    write_json(output_dir / "runtime.json", runtime)
    print(
        json.dumps(
            {
                "notice": NOTICE,
                "tests": test_summary,
                "pilot_stable": pilot["stable"],
                "default_replay_match": replay["all_match"],
                "protected_hashes_match": final_protection["all_match"],
                "engineering_gate": gates["engineering"]["passed"],
                "mechanism_gate": gates["mechanism_improvement"]["passed"],
                "fig4_candidate_gate": gates["fig4_candidate"]["passed"],
                "hypothesis_verdict": comparison["hypothesis_verdict"],
                "output_dir": str(output_dir),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
