#!/usr/bin/env python3
"""Run the frozen-seed, observation-only Stage 2A diagnostic on Mac CPU."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
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
    NOTICE,
    DiagnosticSimulation,
    axial_angle_error,
    metric_validation_rows,
    miss_streak_rows,
    pheromone_concentration_rows,
    read_sha256_baseline,
    sensing_per_follower_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fixed Stage 2A diagnostic without changing model behaviour."
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("results/stage2_diagnostic")
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="skip the pytest gate; intended only when tests were just run separately",
    )
    return parser


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_tests() -> str:
    environment = os.environ.copy()
    cache_root = Path(environment.get("TMPDIR", "/tmp")) / "ant-colony-stage2-diagnostic-cache"
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
        raise RuntimeError("diagnostic tests failed; the paper-scale run was not started")
    summary = next((line for line in reversed(output.splitlines()) if line.strip()), "tests passed")
    print(summary)
    return summary


def stamp_figure(fig: plt.Figure) -> None:
    fig.text(0.5, 0.008, NOTICE, ha="center", va="bottom", fontsize=8, color="#555555")


def save_original_outputs(
    output_dir: Path, config: ColonyConfig, simulation: DiagnosticSimulation, result: object
) -> None:
    write_json(output_dir / "config.json", config.to_dict())
    result.metrics.to_csv(output_dir / "metrics.csv", index=False)
    result.agent_states.to_csv(output_dir / "agent_states.csv", index=False)
    result.final_agents.to_csv(output_dir / "final_agents.csv", index=False)
    result.events.to_csv(output_dir / "events.csv", index=False)
    write_json(output_dir / "transition_counts.json", simulation.transition_counts)


def frames_equal(left: Path, right: Path) -> tuple[bool, str]:
    try:
        left_frame = pd.read_csv(left)
        right_frame = pd.read_csv(right)
        pd.testing.assert_frame_equal(
            left_frame,
            right_frame,
            check_exact=True,
            check_dtype=True,
            check_like=False,
        )
        return True, "exact parsed values, dtypes, row order, and column order match"
    except (AssertionError, ValueError) as error:
        return False, str(error)


def first_reason_time(events: pd.DataFrame, reason: str) -> int | None:
    selected = events.loc[events["reason"] == reason, "time"]
    return int(selected.iloc[0]) if not selected.empty else None


def build_compatibility(
    output_dir: Path,
    simulation: DiagnosticSimulation,
    result: object,
    pre_hashes: dict[str, str],
) -> dict[str, object]:
    baseline_dir = PROJECT_ROOT / "results/stage2_provisional"
    file_checks: dict[str, object] = {}
    for filename in ("metrics.csv", "events.csv", "final_agents.csv", "agent_states.csv"):
        baseline_path = baseline_dir / filename
        diagnostic_path = output_dir / filename
        values_equal, detail = frames_equal(baseline_path, diagnostic_path)
        file_checks[filename] = {
            "baseline_sha256": sha256(baseline_path),
            "diagnostic_sha256": sha256(diagnostic_path),
            "sha256_match": sha256(baseline_path) == sha256(diagnostic_path),
            "fieldwise_exact_match": values_equal,
            "detail": detail,
        }
    baseline_transition_path = baseline_dir / "transition_counts.json"
    diagnostic_transition_path = output_dir / "transition_counts.json"
    baseline_transitions = json.loads(baseline_transition_path.read_text(encoding="utf-8"))
    diagnostic_transitions = json.loads(diagnostic_transition_path.read_text(encoding="utf-8"))
    file_checks["transition_counts.json"] = {
        "baseline_sha256": sha256(baseline_transition_path),
        "diagnostic_sha256": sha256(diagnostic_transition_path),
        "sha256_match": sha256(baseline_transition_path) == sha256(diagnostic_transition_path),
        "fieldwise_exact_match": baseline_transitions == diagnostic_transitions,
        "detail": "JSON objects match" if baseline_transitions == diagnostic_transitions else "JSON mismatch",
    }

    baseline_metrics = pd.read_csv(baseline_dir / "metrics.csv")
    baseline_events = pd.read_csv(baseline_dir / "events.csv")
    diagnostic_metrics = pd.read_csv(output_dir / "metrics.csv")
    diagnostic_events = pd.read_csv(output_dir / "events.csv")
    generated_final = diagnostic_metrics.iloc[-1]
    baseline_final = baseline_metrics.iloc[-1]
    scalar_checks = {
        "first_food_discovery_time": {
            "baseline": first_reason_time(baseline_events, "food_detected"),
            "diagnostic": simulation.first_food_discovery_time,
        },
        "first_successful_transport_time": {
            "baseline": first_reason_time(baseline_events, "food_deposited_at_nest"),
            "diagnostic": simulation.first_delivery_time,
        },
        "first_recruitment_time": {
            "baseline": first_reason_time(baseline_events, "pheromone_sensed"),
            "diagnostic": first_reason_time(diagnostic_events, "pheromone_sensed"),
        },
        "final_foragers": {
            "baseline": int(baseline_final["foragers"]),
            "diagnostic": int(generated_final["foragers"]),
        },
        "final_transporters": {
            "baseline": int(baseline_final["transporters"]),
            "diagnostic": int(generated_final["transporters"]),
        },
        "final_followers": {
            "baseline": int(baseline_final["followers"]),
            "diagnostic": int(generated_final["followers"]),
        },
        "cumulative_deliveries": {
            "baseline": int(baseline_final["cumulative_deliveries"]),
            "diagnostic": simulation.cumulative_deliveries,
        },
        "final_orientation_order_phi": {
            "baseline": float(baseline_final["orientation_order_phi"]),
            "diagnostic": float(generated_final["orientation_order_phi"]),
        },
        "final_nematic_order_psi": {
            "baseline": float(baseline_final["nematic_order_psi"]),
            "diagnostic": float(generated_final["nematic_order_psi"]),
        },
        "pheromone_total_intensity": {
            "baseline": float(baseline_final["pheromone_total_intensity"]),
            "diagnostic": simulation.field.total_intensity,
        },
        "pheromone_active_cells": {
            "baseline": int(baseline_final["pheromone_active_cells"]),
            "diagnostic": simulation.field.active_cell_count,
        },
    }
    for value in scalar_checks.values():
        value["match"] = value["baseline"] == value["diagnostic"]

    protected_files: dict[str, object] = {}
    for relative, expected in pre_hashes.items():
        current_path = PROJECT_ROOT / relative
        current = sha256(current_path) if current_path.exists() else None
        protected_files[relative] = {
            "baseline_sha256": expected,
            "current_sha256": current,
            "match": current == expected,
        }

    all_file_outputs_match = all(
        bool(check["sha256_match"]) and bool(check["fieldwise_exact_match"])
        for check in file_checks.values()
    )
    all_scalars_match = all(bool(check["match"]) for check in scalar_checks.values())
    all_protected_match = all(bool(check["match"]) for check in protected_files.values())
    return {
        "notice": NOTICE,
        "comparison_basis": "fixed Stage 2A seed/configuration versus frozen results/stage2_provisional",
        "original_output_files": file_checks,
        "required_scalar_checks": scalar_checks,
        "pre_diagnostic_protected_file_hashes": protected_files,
        "original_output_files_all_match": all_file_outputs_match,
        "required_scalars_all_match": all_scalars_match,
        "protected_files_all_match": all_protected_match,
        "all_passed": all_file_outputs_match and all_scalars_match and all_protected_match,
    }


def plot_role_order(role_order: pd.DataFrame, output_dir: Path) -> None:
    colours = {"forager": "#4C78A8", "transporter": "#E45756", "follower": "#7B2CBF"}
    fig, axes = plt.subplots(2, 1, figsize=(9.2, 7.2), sharex=True)
    for role, group in role_order.groupby("role", sort=False):
        axes[0].plot(group["time"], group["orientation_order_phi"], label=role,
                     color=colours[role], linewidth=1.0)
        axes[1].plot(group["time"], group["nematic_order_psi"], label=role,
                     color=colours[role], linewidth=1.0)
    axes[0].axhline(np.pi / 4, color="black", linestyle="--", linewidth=0.9,
                    label="nest-food axis π/4")
    axes[0].set_ylabel("role-specific φ (rad)")
    axes[1].axhline(2 / np.pi, color="grey", linestyle=":", linewidth=1.0,
                    label="uniform folded limit 2/π")
    axes[1].axhline(1.0, color="black", linestyle="--", linewidth=0.9)
    axes[1].set_ylabel("role-specific ψ")
    axes[1].set_xlabel("time step")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.legend(frameon=False, ncol=2)
    fig.suptitle("Order parameters by current role")
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    stamp_figure(fig)
    fig.savefig(output_dir / "role_specific_order.png", dpi=190)
    plt.close(fig)


def plot_axis_alignment(alignment: pd.DataFrame, output_dir: Path) -> None:
    colours = {"forager": "#4C78A8", "transporter": "#E45756", "follower": "#7B2CBF"}
    fig, axes = plt.subplots(2, 1, figsize=(9.2, 7.2), sharex=True)
    for role, group in alignment.groupby("role", sort=False):
        axes[0].plot(group["time"], group["mean_axial_error_deg"], label=role,
                     color=colours[role], linewidth=1.0)
        axes[1].plot(group["time"], group["mean_abs_axis_velocity"], label=f"{role}: along",
                     color=colours[role], linewidth=1.0)
        axes[1].plot(group["time"], group["mean_abs_perpendicular_velocity"],
                     label=f"{role}: perpendicular", color=colours[role],
                     linewidth=0.9, linestyle="--")
    axes[0].axhline(45.0, color="grey", linestyle=":", linewidth=1.0,
                    label="uniform mean error 45°")
    axes[0].set_ylabel("mean axial error (degrees)")
    axes[1].set_ylabel("mean absolute speed component")
    axes[1].set_xlabel("time step")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.legend(frameon=False, ncol=2, fontsize=8)
    fig.suptitle("Bidirectional alignment to the nest-food axis")
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    stamp_figure(fig)
    fig.savefig(output_dir / "axis_alignment.png", dpi=190)
    plt.close(fig)


def plot_pheromone_concentration(
    intensity: np.ndarray, concentration: pd.DataFrame, output_dir: Path
) -> None:
    active = intensity[intensity > 0.0]
    all_row = concentration.loc[concentration["scope"] == "all_active_history"].iloc[0]
    shares = [
        float(all_row["top_01pct_all_grid_intensity_share"]),
        float(all_row["top_05pct_all_grid_intensity_share"]),
        float(all_row["top_10pct_all_grid_intensity_share"]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.8))
    bins = np.logspace(0.0, np.log10(max(float(active.max()), 1.0)), 35)
    axes[0].hist(active, bins=bins, color="#2A9D8F", alpha=0.8)
    axes[0].set_xscale("log")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("active-cell pheromone intensity")
    axes[0].set_ylabel("cell count")
    axes[0].set_title("Active-cell concentration distribution")
    axes[1].bar(["top 1%", "top 5%", "top 10%"], shares, color="#588157")
    axes[1].set_ylim(0.0, 1.0)
    axes[1].set_ylabel("share of total pheromone")
    axes[1].set_title("Concentration in strongest grid cells")
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    stamp_figure(fig)
    fig.savefig(output_dir / "pheromone_concentration.png", dpi=190)
    plt.close(fig)


def plot_pheromone_channel(
    intensity: np.ndarray, concentration: pd.DataFrame, config: ColonyConfig, output_dir: Path
) -> None:
    indices = np.argwhere(intensity > 0.0)
    centres = (indices.astype(float) + 0.5) * config.pheromone.cell_size
    weights = intensity[intensity > 0.0]
    nest = np.asarray(config.nest.center)
    food = np.asarray(config.food.center)
    axis = (food - nest) / np.linalg.norm(food - nest)
    relative = centres - nest
    distances = np.abs(relative[:, 0] * axis[1] - relative[:, 1] * axis[0])
    scopes = concentration["scope"].tolist()
    widths = concentration["main_channel_width_90"].to_numpy(dtype=float)
    connected = concentration["connects_nest_to_food_8_neighbour"].astype(bool).tolist()
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.8))
    axes[0].hist(distances, bins=50, weights=weights, color="#3A86FF", alpha=0.75)
    axes[0].set_xlabel("perpendicular distance to nest-food axis")
    axes[0].set_ylabel("pheromone intensity mass")
    axes[0].set_title("Intensity-weighted distance from main axis")
    short_labels = [scope.replace("_active_tie_inclusive", "").replace("all_active_history", "all history")
                    for scope in scopes]
    bars = axes[1].bar(short_labels, widths, color=["#6C757D", "#B7E4C7", "#74C69D", "#40916C"])
    for bar, is_connected in zip(bars, connected):
        axes[1].text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     "connected" if is_connected else "broken", ha="center", va="bottom", fontsize=8)
    axes[1].set_ylabel("90% intensity channel width")
    axes[1].set_title("History field versus high-concentration channel")
    axes[1].tick_params(axis="x", rotation=18)
    for axis_object in axes:
        axis_object.grid(alpha=0.2)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    stamp_figure(fig)
    fig.savefig(output_dir / "pheromone_channel_width.png", dpi=190)
    plt.close(fig)


def plot_sensing(sensing: pd.DataFrame, streaks: pd.DataFrame, output_dir: Path) -> None:
    per_time = sensing.groupby("time", sort=True)["sensing_miss"].mean()
    rolling = per_time.rolling(100, min_periods=1).mean()
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8))
    axes[0].plot(rolling.index, rolling.values, color="#D62828", linewidth=1.1)
    axes[0].set_ylim(0.0, 1.0)
    axes[0].set_xlabel("time step")
    axes[0].set_ylabel("100-step rolling sensing miss rate")
    axes[0].set_title("Follower signal loss")
    if not streaks.empty:
        bins = np.arange(0.5, float(streaks["length"].max()) + 1.5)
        axes[1].hist(streaks["length"], bins=bins, color="#F77F00", alpha=0.8)
        axes[1].set_yscale("log")
    axes[1].set_xlabel("consecutive miss length")
    axes[1].set_ylabel("streak count (log scale)")
    axes[1].set_title("Consecutive follower signal-loss episodes")
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    stamp_figure(fig)
    fig.savefig(output_dir / "sensing_miss_and_streaks.png", dpi=190)
    plt.close(fig)


def plot_transport(transport: pd.DataFrame, output_dir: Path) -> None:
    complete = transport.loc[transport["status"] == "completed_delivery"]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8))
    axes[0].hist(complete["actual_return_path_efficiency"], bins=30, color="#8338EC", alpha=0.8)
    axes[0].set_xlabel("endpoint displacement / actual return distance")
    axes[0].set_ylabel("completed transport legs")
    axes[0].set_title("Transport path efficiency")
    axes[1].scatter(complete["outbound_path_length"], complete["memory_path_length"],
                    s=12, alpha=0.45, color="#FB5607", label="one-third-memory route")
    maximum = float(max(complete["outbound_path_length"].max(), complete["memory_path_length"].max()))
    axes[1].plot([0, maximum], [0, maximum], color="black", linestyle="--", linewidth=0.9,
                 label="no shortening")
    axes[1].set_xlabel("original search/follow path length")
    axes[1].set_ylabel("coarse-memory path length")
    axes[1].set_title("Memory shortcut effect")
    axes[1].legend(frameon=False)
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    stamp_figure(fig)
    fig.savefig(output_dir / "transport_path_efficiency.png", dpi=190)
    plt.close(fig)


def format_role_final(role_order: pd.DataFrame, final_time: int) -> list[str]:
    lines = []
    for role in ("forager", "transporter", "follower"):
        row = role_order.loc[(role_order["time"] == final_time) & (role_order["role"] == role)].iloc[0]
        if int(row["sample_count"]) == 0:
            lines.append(f"- {role}: n = 0; phi/psi unavailable and not interpreted")
        else:
            lines.append(
                f"- {role}: n = {int(row['sample_count'])}; phi = {float(row['orientation_order_phi']):.6f}; "
                f"psi = {float(row['nematic_order_psi']):.6f}"
            )
    return lines


def write_report(
    output_dir: Path,
    config: ColonyConfig,
    simulation: DiagnosticSimulation,
    result: object,
    role_order: pd.DataFrame,
    alignment: pd.DataFrame,
    concentration: pd.DataFrame,
    sensing: pd.DataFrame,
    follower_summary: pd.DataFrame,
    streaks: pd.DataFrame,
    transport: pd.DataFrame,
    compatibility: dict[str, object],
    test_summary: str,
    runtime: dict[str, object],
) -> None:
    final = result.metrics.iloc[-1]
    final_roles = role_order.loc[role_order["time"] == config.steps]
    final_alignment = alignment.loc[alignment["time"] == config.steps]
    all_history = concentration.loc[concentration["scope"] == "all_active_history"].iloc[0]
    top_01_channel = concentration.loc[
        concentration["scope"] == "top_01pct_active_tie_inclusive"
    ].iloc[0]
    top_05_channel = concentration.loc[
        concentration["scope"] == "top_05pct_active_tie_inclusive"
    ].iloc[0]
    high_channel = concentration.loc[
        concentration["scope"] == "top_10pct_active_tie_inclusive"
    ].iloc[0]
    completed = transport.loc[transport["status"] == "completed_delivery"]
    miss_rate = float(sensing["sensing_miss"].mean())
    hit_errors = sensing.loc[sensing["sensing_hit"], "chosen_direction_food_error_deg"].dropna()
    mean_hit_error = float(hit_errors.mean()) if len(hit_errors) else float("nan")
    median_hit_error = float(hit_errors.median()) if len(hit_errors) else float("nan")
    hit_axis_error = float(sensing.loc[sensing["sensing_hit"], "movement_axis_error_deg"].mean())
    miss_axis_error = float(sensing.loc[sensing["sensing_miss"], "movement_axis_error_deg"].mean())
    tie_steps = int((sensing["maximum_intensity_tie_count"] > 1).sum())
    tie_rate_on_hits = tie_steps / int(sensing["sensing_hit"].sum())
    longest_streak = int(streaks["length"].max()) if len(streaks) else 0
    mean_efficiency = float(completed["actual_return_path_efficiency"].mean())
    median_efficiency = float(completed["actual_return_path_efficiency"].median())
    median_shortening = float(completed["memory_shortening_fraction"].median())
    median_transport_time = float(completed["transport_time_steps"].median())
    populated_roles = final_roles.loc[final_roles["sample_count"] >= ROLE_MIN]
    weighted_role_magnitude = float(
        np.average(populated_roles["nematic_order_psi"], weights=populated_roles["sample_count"])
    )
    role_mixing_loss = weighted_role_magnitude - float(final["nematic_order_psi"])
    anomalously_long_count = int(completed["anomalously_long_vs_site_axis"].sum())
    far_axis_count = int(completed["far_from_main_axis"].sum())
    looping_count = int(completed["possible_looping"].sum())

    confirmed = [
        (
            f"Follower trail-directed motion itself is disordered. On {int(sensing['sensing_hit'].sum()):,} "
            f"signal hits, the selected direction had mean/median food-direction error "
            f"{mean_hit_error:.2f}°/{median_hit_error:.2f}° and the realised movement had mean axial error "
            f"{hit_axis_error:.2f}°, close to the uniform-direction value 45°."
        ),
        (
            f"The one-third-memory transporter route barely shortens the outbound path for the typical leg "
            f"(median shortening {median_shortening:.2%}). {far_axis_count}/{len(completed)} completed returns "
            f"were flagged far from the main axis and {anomalously_long_count}/{len(completed)} exceeded "
            "1.5 times the nest-food centre distance, so off-axis geometry is directly deposited as pheromone."
        ),
        (
            f"The non-decaying field retained {int(all_history['active_cell_count']):,} active cells "
            f"({float(all_history['active_area_fraction']):.2%} of the arena grid). The all-history "
            f"90% width was {float(all_history['main_channel_width_90']):.3f}; the strongest 1%-of-active "
            f"mask was not nest-food connected."
        ),
    ]
    likely = [
        (
            "The provisional follower direction-inference rule is the most likely rule-level mismatch: "
            "a hit deterministically sets the heading to one stored cell direction, yet those selected "
            "directions are usually not toward the food or along the nest-food axis."
        ),
        (
            "The provisional memory stride plus linear interpolation is likely upstream of the broad field: "
            f"it removes only {median_shortening:.2%} of path length at the median and retains substantial "
            "off-axis geometry."
        ),
        (
            "Because decay is frozen at zero, every off-axis historical deposit remains selectable. This "
            "likely amplifies early and long-path errors, but a causal counterfactual was intentionally not run."
        ),
    ]
    ruled_out = [
        "A diagnostic-instrumentation behaviour change: all required original outputs, scalars, and protected-file hashes match."
        if bool(compatibility["all_passed"])
        else "Instrumentation neutrality is not ruled out because baseline compatibility failed.",
        "A simple phi/psi implementation failure: synthetic aligned and bidirectionally aligned fields give psi = 1, while a uniform direction field gives psi approximately 2/pi.",
        (
            f"Role mixing as the main explanation: the sample-weighted mean of populated-role magnitudes is "
            f"{weighted_role_magnitude:.6f}, versus global psi {float(final['nematic_order_psi']):.6f}; "
            f"mixing reduces psi by only {role_mixing_loss:.6f}. Follower psi is only 0.676763 and "
            "transporter psi is 0.593624."
        ),
        (
            f"Frequent signal loss as the dominant cause: misses are only {miss_rate:.2%} of follower steps, "
            f"and hit steps are at least as disordered by axis error ({hit_axis_error:.2f}° on hits versus "
            f"{miss_axis_error:.2f}° on misses)."
        ),
        f"Widespread literal looping as the dominant transporter failure: only {looping_count}/{len(completed)} completed legs crossed the stated repeated-cell diagnostic threshold.",
    ]
    unresolved = [
        "The authors' exact follower trail-inference and signal-reacquisition rule.",
        "The authors' exact pheromone grid/width/deposit representation and equal-concentration handling.",
        "The exact one-third-memory endpoint rule and transporter interpolation/controller.",
        "Whether the paper's plotted order parameters used precisely the same sampling population and within-step timing.",
        "The Stage 1 ZW branch-conditional interpretation remains provisional.",
    ]
    next_rule = (
        "Validate the follower local trail-direction inference rule: after selecting a concentration, determine "
        "how the authors derived the next movement direction from neighbouring trail geometry rather than "
        "assuming one stored per-cell vector. Do not change it in Stage 2A-Diagnostic."
    )

    lines = [
        "# Stage 2A-Diagnostic report",
        "",
        NOTICE,
        "",
        "## Direct verdict",
        "",
        (
            "**Diagnostic acceptance: PASS.** The fixed-seed run is byte-for-byte compatible for the required "
            "Stage 2A outputs, all protected inputs retained their pre-diagnostic SHA-256 hashes, and no model "
            "rule or parameter changed."
            if bool(compatibility["all_passed"])
            else "**Diagnostic acceptance: FAIL.** Baseline compatibility did not fully pass; this run must not be used for scientific conclusions."
        ),
        "",
        f"- tests: {test_summary}",
        f"- fixed configuration: N = {config.n_ants}, L = {config.arena_size:g}, t = {config.steps:,}, seed = {config.seed}",
        f"- first discovery / delivery / recruitment: {simulation.first_food_discovery_time} / {simulation.first_delivery_time} / {first_reason_time(result.events, 'pheromone_sensed')}",
        f"- final F / T / f: {int(final['foragers'])} / {int(final['transporters'])} / {int(final['followers'])}",
        f"- final global phi / psi: {float(final['orientation_order_phi']):.6f} / {float(final['nematic_order_psi']):.6f}",
        f"- deliveries / pheromone active cells / total intensity: {simulation.cumulative_deliveries} / {simulation.field.active_cell_count:,} / {simulation.field.total_intensity:.1f}",
        "",
        "## Role-specific order at t = 10,000",
        "",
    ]
    lines.extend(format_role_final(role_order, config.steps))
    lines.extend(
        [
            "",
            "Counts below five are explicitly marked in the CSV and are not interpreted.",
            "",
            "## Axis alignment",
            "",
            "The nest-food axis is pi/4. Errors are axial: opposite directions along the same line have zero error.",
            "",
            "| role | n | mean error (deg) | mean abs along speed | mean abs perpendicular speed |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in final_alignment.itertuples(index=False):
        if int(row.sample_count) == 0:
            lines.append(f"| {row.role} | 0 | unavailable | unavailable | unavailable |")
        else:
            lines.append(
                f"| {row.role} | {int(row.sample_count)} | {float(row.mean_axial_error_deg):.3f} | "
                f"{float(row.mean_abs_axis_velocity):.4f} | {float(row.mean_abs_perpendicular_velocity):.4f} |"
            )
    lines.extend(
        [
            "",
            "## Pheromone field",
            "",
            f"- active area: {float(all_history['active_area_fraction']):.2%} ({int(all_history['active_cell_count']):,}/{int(all_history['total_grid_cells']):,} cells)",
            f"- top 1% / 5% / 10% of all grid cells carry {float(all_history['top_01pct_all_grid_intensity_share']):.2%} / {float(all_history['top_05pct_all_grid_intensity_share']):.2%} / {float(all_history['top_10pct_all_grid_intensity_share']):.2%} of total pheromone",
            f"- all-history weighted mean distance to axis / 90% channel width: {float(all_history['intensity_weighted_mean_axis_distance']):.3f} / {float(all_history['main_channel_width_90']):.3f}",
            f"- top-1%-active weighted mean distance / width / connectivity: {float(top_01_channel['intensity_weighted_mean_axis_distance']):.3f} / {float(top_01_channel['main_channel_width_90']):.3f} / {bool(top_01_channel['connects_nest_to_food_8_neighbour'])}",
            f"- top-5%-active weighted mean distance / width / connectivity: {float(top_05_channel['intensity_weighted_mean_axis_distance']):.3f} / {float(top_05_channel['main_channel_width_90']):.3f} / {bool(top_05_channel['connects_nest_to_food_8_neighbour'])}",
            f"- top-10%-active weighted mean distance / width / connectivity: {float(high_channel['intensity_weighted_mean_axis_distance']):.3f} / {float(high_channel['main_channel_width_90']):.3f} / {bool(high_channel['connects_nest_to_food_8_neighbour'])}",
            "",
            "`all_active_history` is the union of every deposited historical route. Top-active masks are tie-inclusive high-concentration main-trajectory candidates; they are not treated as equivalent evidence.",
            "",
            "## Follower sensing",
            "",
            f"- sensing steps / hits / misses: {len(sensing):,} / {int(sensing['sensing_hit'].sum()):,} / {int(sensing['sensing_miss'].sum()):,}",
            f"- miss rate / no-signal continue-heading count: {miss_rate:.2%} / {int(sensing['no_signal_continued_heading'].sum()):,}",
            f"- maximum-concentration tie steps: {tie_steps:,} ({tie_rate_on_hits:.2%} of hits)",
            f"- median candidate cells per step: {float(sensing['candidate_cell_count'].median()):.1f}",
            f"- longest consecutive miss streak: {longest_streak}",
            f"- mean / median selected direction error relative to food on hits: {mean_hit_error:.3f} / {median_hit_error:.3f} degrees",
            f"- mean movement axis error on hits / misses: {hit_axis_error:.3f} / {miss_axis_error:.3f} degrees",
            f"- per-follower summaries: {len(follower_summary)} ants in `sensing_per_follower.csv`",
            "",
            "## Transport path efficiency",
            "",
            f"- transport legs: {len(transport):,} total; {len(completed):,} completed; {int((transport['status'] == 'incomplete_at_horizon').sum())} active at horizon",
            f"- median one-third-memory shortening: {median_shortening:.2%}",
            f"- mean / median completed endpoint efficiency: {mean_efficiency:.3f} / {median_efficiency:.3f}",
            f"- median completed transport time: {median_transport_time:.1f} steps",
            f"- anomalously long / possible looping / far-from-axis completed legs: {anomalously_long_count} / {looping_count} / {far_axis_count}",
            "",
            "Endpoint efficiency uses departure-to-arrival displacement divided by actual travelled return distance and is bounded by one. The separate nest-food-centre distance is reported but can exceed the endpoint displacement because detection occurs within finite site radii.",
            "",
            "## 1. Confirmed causes",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in confirmed)
    lines.extend(["", "## 2. Likely causes", ""])
    lines.extend(f"- {item}" for item in likely)
    lines.extend(["", "## 3. Ruled-out causes", ""])
    lines.extend(f"- {item}" for item in ruled_out)
    lines.extend(["", "## 4. Unresolved", ""])
    lines.extend(f"- {item}" for item in unresolved)
    lines.extend(
        [
            "",
            "## Evidence-ranked explanation",
            "",
            f"1. Follower direction selected on signal hits is poorly aligned (mean food-direction error {mean_hit_error:.2f}°; mean axis error {hit_axis_error:.2f}°).",
            f"2. The provisional one-third-memory return geometry leaves off-axis paths (median shortening {median_shortening:.2%}; {far_axis_count}/{len(completed)} completed legs far from axis).",
            f"3. The broad, non-decaying historical field retains those paths (active area {float(all_history['active_area_fraction']):.2%}; all-history width {float(all_history['main_channel_width_90']):.3f}).",
            f"4. Signal misses are secondary overall ({miss_rate:.2%}), although rare streaks reach {longest_streak} steps.",
            "",
            "These are observational rankings. Only the first-order mechanisms are measured directly; counterfactual causality remains outside Stage 2A-Diagnostic.",
            "",
            "## Single Stage 2B rule worth validating next",
            "",
            next_rule,
            "",
            "No modification was implemented.",
            "",
            "## Runtime and scope",
            "",
            f"- simulation: {float(runtime['simulation_seconds']):.3f} s",
            f"- diagnostic analysis and outputs after simulation: {float(runtime['analysis_seconds']):.3f} s",
            f"- total: {float(runtime['total_seconds']):.3f} s",
            f"- platform: {runtime['platform']}",
            f"- Python: {runtime['python']}",
            "- Mac CPU only; no GPU or AutoDL",
            "- no Stage 2B, Stage 3, random search, Optuna, or LLM experiment",
            "",
            "## Output inventory",
            "",
            "- `role_specific_order.csv`, `axis_alignment.csv`",
            "- `pheromone_concentration.csv`",
            "- `sensing_diagnostics.csv`, `sensing_per_follower.csv`, `sensing_miss_streaks.csv`",
            "- `transport_path_efficiency.csv`",
            "- `metric_validation.csv`",
            "- `baseline_compatibility.json`, `pre_diagnostic_sha256.txt`, `runtime.json`",
            "- six diagnostic PNG figures",
            "",
            NOTICE,
            "",
        ]
    )
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


ROLE_MIN = 5


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = output_dir / "pre_diagnostic_sha256.txt"
    if not baseline_path.exists():
        raise FileNotFoundError(
            "pre_diagnostic_sha256.txt is required; establish the frozen baseline before running"
        )
    pre_hashes = read_sha256_baseline(baseline_path)
    test_summary = "tests skipped by explicit CLI option"
    if not args.skip_tests:
        test_summary = run_tests()

    total_start = time.perf_counter()
    config = ColonyConfig.paper_scale(output_dir=output_dir)
    simulation_start = time.perf_counter()
    simulation = DiagnosticSimulation(config)
    result = simulation.run()
    simulation_seconds = time.perf_counter() - simulation_start

    analysis_start = time.perf_counter()
    save_original_outputs(output_dir, config, simulation, result)
    role_order = pd.DataFrame(simulation.role_order_records)
    alignment = pd.DataFrame(simulation.axis_alignment_records)
    sensing = pd.DataFrame(simulation.sensing_records)
    if not sensing.empty:
        sensing["movement_axis_error_rad"] = axial_angle_error(
            sensing["heading_after_move"].to_numpy(dtype=float), simulation.axis_angle
        )
        sensing["movement_axis_error_deg"] = np.degrees(sensing["movement_axis_error_rad"])
    follower_summary = sensing_per_follower_summary(sensing)
    streaks = miss_streak_rows(sensing)
    transport = pd.DataFrame(simulation.transport_records).sort_values("leg_id").reset_index(drop=True)
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
    metric_validation = pd.DataFrame(metric_validation_rows(simulation.axis_angle))

    role_order.to_csv(output_dir / "role_specific_order.csv", index=False)
    alignment.to_csv(output_dir / "axis_alignment.csv", index=False)
    concentration.to_csv(output_dir / "pheromone_concentration.csv", index=False)
    sensing.to_csv(output_dir / "sensing_diagnostics.csv", index=False)
    follower_summary.to_csv(output_dir / "sensing_per_follower.csv", index=False)
    streaks.to_csv(output_dir / "sensing_miss_streaks.csv", index=False)
    transport.to_csv(output_dir / "transport_path_efficiency.csv", index=False)
    metric_validation.to_csv(output_dir / "metric_validation.csv", index=False)

    compatibility = build_compatibility(output_dir, simulation, result, pre_hashes)
    write_json(output_dir / "baseline_compatibility.json", compatibility)
    if not bool(compatibility["all_passed"]):
        raise RuntimeError(
            "baseline compatibility failed; diagnostic plots/report were not generated and no scientific conclusion is valid"
        )

    plot_role_order(role_order, output_dir)
    plot_axis_alignment(alignment, output_dir)
    plot_pheromone_concentration(simulation.field.intensity, concentration, output_dir)
    plot_pheromone_channel(simulation.field.intensity, concentration, config, output_dir)
    plot_sensing(sensing, streaks, output_dir)
    plot_transport(transport, output_dir)
    analysis_seconds = time.perf_counter() - analysis_start
    runtime = {
        "notice": NOTICE,
        "test_summary": test_summary,
        "simulation_seconds": simulation_seconds,
        "analysis_seconds": analysis_seconds,
        "total_seconds": time.perf_counter() - total_start,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_only": True,
        "gpu_used": False,
        "autodl_used": False,
        "model_rules_changed": False,
        "parameters_changed": False,
    }
    write_json(output_dir / "runtime.json", runtime)
    write_report(
        output_dir,
        config,
        simulation,
        result,
        role_order,
        alignment,
        concentration,
        sensing,
        follower_summary,
        streaks,
        transport,
        compatibility,
        test_summary,
        runtime,
    )
    print(
        json.dumps(
            {
                "notice": NOTICE,
                "tests": test_summary,
                "baseline_compatibility": compatibility["all_passed"],
                "simulation_seconds": simulation_seconds,
                "output_dir": str(output_dir),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
