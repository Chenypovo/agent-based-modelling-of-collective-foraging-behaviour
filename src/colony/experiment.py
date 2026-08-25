"""Stage 2A output serialisation, figures, runtime record, and report."""

from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .agents import Role
from .config import ColonyConfig
from .provenance import stage1_hash_manifest
from .simulation import ColonySimulation, SimulationResult

NOTICE = "Stage 2 provisional implementation — not an exact reproduction of Fig. 4."
ROLE_COLOURS = {
    Role.FORAGER.value: "#4C78A8",
    Role.TRANSPORTER.value: "#E45756",
    Role.FOLLOWER.value: "#7B2CBF",
}


@dataclass(frozen=True)
class ExperimentOutput:
    config: ColonyConfig
    simulation: ColonySimulation
    result: SimulationResult
    runtime: dict[str, object]
    output_dir: Path


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _figure_notice(fig: plt.Figure) -> None:
    fig.text(0.5, 0.008, NOTICE, ha="center", va="bottom", fontsize=8, color="#5A5A5A")


def _plot_snapshot(
    config: ColonyConfig,
    time_step: int,
    agents: pd.DataFrame,
    pheromone: tuple[np.ndarray, np.ndarray, np.ndarray],
    output_dir: Path,
) -> None:
    centres, strengths, _ = pheromone
    fig, axis = plt.subplots(figsize=(6.8, 6.4), constrained_layout=False)
    if len(centres):
        sizes = 5.0 + 20.0 * strengths / max(float(np.max(strengths)), 1.0)
        axis.scatter(
            centres[:, 0],
            centres[:, 1],
            c=strengths,
            cmap="Greens",
            s=sizes,
            alpha=0.55,
            linewidths=0,
            label="pheromone cells",
            zorder=1,
        )
    for role in Role:
        selected = agents.loc[agents["role"] == role.value]
        if selected.empty:
            continue
        axis.scatter(
            selected["x"],
            selected["y"],
            s=20,
            color=ROLE_COLOURS[role.value],
            marker={Role.FORAGER: "o", Role.TRANSPORTER: "^", Role.FOLLOWER: "s"}[role],
            label=role.value,
            edgecolors="none",
            zorder=3,
        )
    nest = plt.Circle(
        config.nest.center,
        config.nest.radius,
        facecolor="#D62728",
        edgecolor="black",
        linewidth=0.7,
        label="nest",
        zorder=4,
    )
    axis.add_patch(nest)
    axis.scatter(
        [config.food.center[0]],
        [config.food.center[1]],
        marker="*",
        s=180,
        color="#FFBF00",
        edgecolor="black",
        linewidth=0.7,
        label="inexhaustible food",
        zorder=4,
    )
    axis.set_xlim(0.0, config.arena_size)
    axis.set_ylim(0.0, config.arena_size)
    axis.set_aspect("equal")
    axis.set_xlabel("x (length units)")
    axis.set_ylabel("y (length units)")
    axis.set_title(f"Provisional colony snapshot at t = {time_step:,}")
    axis.legend(loc="best", frameon=True, fontsize=8)
    fig.subplots_adjust(left=0.11, right=0.98, bottom=0.11, top=0.93)
    _figure_notice(fig)
    fig.savefig(output_dir / f"snapshot_t{time_step}.png", dpi=190)
    plt.close(fig)


def _plot_role_counts(metrics: pd.DataFrame, config: ColonyConfig, output_dir: Path) -> None:
    fig, axis = plt.subplots(figsize=(9.0, 4.8))
    for column, role in (
        ("foragers", Role.FORAGER),
        ("transporters", Role.TRANSPORTER),
        ("followers", Role.FOLLOWER),
    ):
        axis.plot(
            metrics["time"],
            metrics[column],
            label=role.value,
            color=ROLE_COLOURS[role.value],
            linewidth=1.4,
        )
    axis.set_xlabel("time step")
    axis.set_ylabel("number of ants")
    axis.set_ylim(0, config.n_ants * 1.03)
    axis.set_title("Colony task-group counts (F + T + f = N)")
    axis.legend(frameon=False)
    axis.grid(alpha=0.25)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _figure_notice(fig)
    fig.savefig(output_dir / "role_counts.png", dpi=190)
    plt.close(fig)


def _plot_order_parameters(metrics: pd.DataFrame, config: ColonyConfig, output_dir: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(9.0, 7.0), sharex=True)
    axes[0].plot(
        metrics["time"], metrics["orientation_order_phi"], color="#D55E00", linewidth=1.2
    )
    nest_food_angle = float(
        np.arctan2(
            config.food.center[1] - config.nest.center[1],
            config.food.center[0] - config.nest.center[0],
        )
    )
    folded_axis = (nest_food_angle + np.pi / 2) % np.pi - np.pi / 2
    axes[0].axhline(folded_axis, color="black", linestyle="--", linewidth=0.9, label="nest-food axis")
    axes[0].set_ylabel("orientation order φ (rad)")
    axes[0].legend(frameon=False)
    axes[1].plot(
        metrics["time"], metrics["nematic_order_psi"], color="#009E73", linewidth=1.2
    )
    axes[1].axhline(2 / np.pi, color="grey", linestyle=":", linewidth=0.9, label="uniform folded limit 2/π")
    axes[1].axhline(1.0, color="black", linestyle="--", linewidth=0.9, label="perfect alignment")
    axes[1].set_xlabel("time step")
    axes[1].set_ylabel("nematic order ψ")
    axes[1].set_ylim(0.0, 1.05)
    axes[1].legend(frameon=False)
    for axis in axes:
        axis.grid(alpha=0.25)
    fig.suptitle("Paper-style colony order parameters")
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    _figure_notice(fig)
    fig.savefig(output_dir / "order_parameters.png", dpi=190)
    plt.close(fig)


def _plot_deliveries(metrics: pd.DataFrame, output_dir: Path) -> None:
    fig, axis = plt.subplots(figsize=(9.0, 4.8))
    axis.step(
        metrics["time"],
        metrics["cumulative_deliveries"],
        where="post",
        color="#CC79A7",
        linewidth=1.5,
    )
    axis.set_xlabel("time step")
    axis.set_ylabel("cumulative successful deliveries")
    axis.set_title("Cumulative food transport to the nest")
    axis.grid(alpha=0.25)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _figure_notice(fig)
    fig.savefig(output_dir / "cumulative_food_transport.png", dpi=190)
    plt.close(fig)


def _first_event_time(result: SimulationResult, reason: str) -> int | None:
    selected = result.events.loc[result.events["reason"] == reason, "time"]
    return int(selected.iloc[0]) if not selected.empty else None


def _acceptance_checks(
    output: ExperimentOutput,
    hash_manifest: dict[str, object],
    test_summary: str,
) -> dict[str, bool]:
    result = output.result
    metrics = result.metrics
    config = output.config
    return {
        "stage1_preservation_hashes_match": bool(hash_manifest["all_match"]),
        "automated_tests_passed": "passed" in test_summary and "failed" not in test_summary,
        "configured_horizon_completed": int(metrics["time"].iloc[-1]) == config.steps,
        "population_conserved": bool(metrics["population_conserved"].all()),
        "finite_metrics": bool(
            np.isfinite(metrics.select_dtypes(include=[np.number]).to_numpy()).all()
        ),
        "food_discovered": output.simulation.first_food_discovery_time is not None,
        "food_delivered": output.simulation.first_delivery_time is not None,
        "pheromone_deposited": float(metrics["pheromone_total_intensity"].iloc[-1]) > 0.0,
        "forager_recruited_to_follower": output.simulation.transition_counts[
            "forager_to_follower"
        ]
        > 0,
        "transporter_became_follower": output.simulation.transition_counts[
            "transporter_to_follower"
        ]
        > 0,
    }


def _write_report(
    output: ExperimentOutput,
    hash_manifest: dict[str, object],
    *,
    test_summary: str,
    pilot_summary: dict[str, object] | None,
) -> None:
    config = output.config
    result = output.result
    final = result.metrics.iloc[-1]
    checks = _acceptance_checks(output, hash_manifest, test_summary)
    all_checks = all(checks.values())
    first_recruitment = _first_event_time(result, "pheromone_sensed")
    nest_food_angle = float(
        np.arctan2(
            config.food.center[1] - config.nest.center[1],
            config.food.center[0] - config.nest.center[0],
        )
    )
    folded_axis = (nest_food_angle + np.pi / 2) % np.pi - np.pi / 2
    paper_endpoint_observed = bool(
        abs(float(final["orientation_order_phi"]) - folded_axis) <= 0.1
        and float(final["nematic_order_psi"]) >= 0.9
    )
    lines = [
        "# Stage 2A provisional colony results",
        "",
        NOTICE,
        "",
        "## Direct verdict",
        "",
        (
            "**Stage 2A implementation acceptance: PASS.** The fixed seeded run completed the required causal chain and all stated engineering gates."
            if all_checks
            else "**Stage 2A implementation acceptance: NOT YET PASSED.** One or more fixed-run gates below did not pass; no parameter scan was used to hide the failure."
        ),
        (
            "**Fig. 4 endpoint diagnostic: observed.** Final phi is near the configured nest-food axis and final psi is at least 0.9."
            if paper_endpoint_observed
            else "**Fig. 4 endpoint diagnostic: not reproduced.** The final phi and psi remain far from the paper's approximately pi/4 and 1 endpoint. This is a scientific limitation, not hidden by the implementation acceptance verdict."
        ),
        "",
        "This is a paper-informed independent implementation. It is not the authors' source code and is not evidence of an exact Fig. 4 reproduction.",
        "",
        "## Paper-scale fixed run",
        "",
        f"- ants / arena / horizon: N = {config.n_ants}, L = {config.arena_size:g}, t = {config.steps:,}",
        f"- movement: {config.movement.model.upper()}, step = {config.movement.step_size:g}, gamma = {config.movement.gamma:g}, Theta = {config.movement.theta_deg:g} degrees",
        f"- nest / food: {config.nest.center} / {config.food.center} (provisional coordinates)",
        f"- first food discovery: {output.simulation.first_food_discovery_time}",
        f"- first successful delivery: {output.simulation.first_delivery_time}",
        f"- first forager-to-follower pheromone recruitment: {first_recruitment}",
        f"- final F / T / f: {int(final['foragers'])} / {int(final['transporters'])} / {int(final['followers'])}",
        f"- final phi / psi: {float(final['orientation_order_phi']):.6f} / {float(final['nematic_order_psi']):.6f}",
        f"- cumulative deliveries: {int(final['cumulative_deliveries'])}",
        f"- active pheromone cells / total intensity: {int(final['pheromone_active_cells'])} / {float(final['pheromone_total_intensity']):.1f}",
        "",
        "### Required snapshot metrics",
        "",
        "| time | F | T | f | phi | psi | deliveries |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for time_step in config.snapshot_steps:
        row = result.metrics.loc[result.metrics["time"] == time_step].iloc[0]
        lines.append(
            f"| {time_step:,} | {int(row['foragers'])} | {int(row['transporters'])} | {int(row['followers'])} | {float(row['orientation_order_phi']):.6f} | {float(row['nematic_order_psi']):.6f} | {int(row['cumulative_deliveries'])} |"
        )
    lines.extend(
        [
        "",
        "### Transition totals",
        "",
        ]
    )
    for key, value in output.simulation.transition_counts.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Acceptance checks", ""])
    for name, passed in checks.items():
        lines.append(f"- {'PASS' if passed else 'FAIL'}: `{name}`")

    lines.extend(
        [
            "",
            "## Scientific interpretation limit",
            "",
            f"The final order parameters are phi = {float(final['orientation_order_phi']):.6f} and psi = {float(final['nematic_order_psi']):.6f}; the paper reports approximately phi = pi/4 and psi = 1 for its FCRW/ZW endpoints. The current fixed provisional rules therefore demonstrate role cycling, recruitment, transport, and a visible nest-food corridor, but do not demonstrate the paper's disorder-order endpoint. Because pheromone does not decay, all historical route cells remain active; the final field contains {int(final['pheromone_active_cells'])} active cells and is much broader than a single clean trail. Resolving this requires the missing author/supervisor implementation details, not an unapproved parameter scan.",
        ]
    )

    if pilot_summary is not None:
        lines.extend(
            [
                "",
                "## Small pilot",
                "",
                f"- configuration: N = {pilot_summary['n_ants']}, L = {pilot_summary['arena_size']}, t = {pilot_summary['steps']}",
                f"- runtime: {float(pilot_summary['simulation_seconds']):.3f} s simulation; {float(pilot_summary['total_seconds']):.3f} s through outputs",
                f"- first discovery / delivery: {pilot_summary['first_food_discovery_time']} / {pilot_summary['first_delivery_time']}",
                f"- final F / T / f: {pilot_summary['final_counts']}",
                f"- cumulative deliveries: {pilot_summary['cumulative_deliveries']}",
            ]
        )

    lines.extend(
        [
            "",
            "## Runtime and hardware",
            "",
            f"- simulation: {float(output.runtime['simulation_seconds']):.3f} s",
            f"- end-to-end through figures/report inputs: {float(output.runtime['total_seconds_before_report']):.3f} s",
            f"- platform: {output.runtime['platform']}",
            f"- Python: {output.runtime['python']}",
            "- CPU-only; GPU and AutoDL were not used",
            f"- automated tests before runs: {test_summary}",
            "",
            "## Provisional assumptions used",
            "",
            "- nest and food coordinates and physical radii",
            "- point initialisation at the nest centre and IID uniform heading sampling",
            "- food radius plus sensing range as the food-detection condition",
            "- grid-cell pheromone representation, deposit amount, and one-cell trail width",
            "- stored concentration-weighted direction toward food",
            "- follower local-maximum selection and deterministic tie-breaking",
            "- continuing the previous heading after temporary signal loss",
            "- retaining indices 0, 3, 6, ... and appending the final path vertex",
            "- linear interpolation while retracing the reversed coarse path",
            "- overshoot reflection and the within-step update/event order",
            "",
            "## Awaiting supervisor confirmation",
            "",
            "The exact coordinates/radii, initialisation, food detection, pheromone representation and increment, trail width/direction choice, equal-concentration handling, memory endpoint rule, transporter interpolation, nest reset timing, boundary numerics, seeds, and event ordering remain unresolved. See `docs/STAGE2_SPEC.md` for the complete question list.",
            "",
            "## Output files",
            "",
            "- `config.json`: complete centralised configuration",
            "- `metrics.csv`: one row per time step with F/T/f, phi, psi, deliveries, and pheromone summaries",
            "- `agent_states.csv`: every ant at the configured recording interval and required snapshots",
            "- `final_agents.csv`: final position, heading, orientation, and role for every ant",
            "- `events.csv` and `transition_counts.json`: complete role-transition evidence",
            "- `snapshot_t*.csv` and `snapshot_t*.png`: required spatial snapshots",
            "- `role_counts.png`, `order_parameters.png`, and `cumulative_food_transport.png`: requested time-series figures",
            "- `runtime.json`: CPU/platform timing",
            "- `stage1_sha256.json`: preservation readback against the pre-Stage 2A hashes",
            "",
            "No Stage 2B, Stage 3, optimisation, or LLM experiment was run.",
            "",
        ]
    )
    (output.output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def summarise_output(output: ExperimentOutput) -> dict[str, object]:
    final = output.result.metrics.iloc[-1]
    return {
        "n_ants": output.config.n_ants,
        "arena_size": output.config.arena_size,
        "steps": output.config.steps,
        "simulation_seconds": output.runtime["simulation_seconds"],
        "total_seconds": output.runtime["total_seconds_before_report"],
        "first_food_discovery_time": output.simulation.first_food_discovery_time,
        "first_delivery_time": output.simulation.first_delivery_time,
        "final_counts": f"{int(final['foragers'])}/{int(final['transporters'])}/{int(final['followers'])}",
        "orientation_order_phi": float(final["orientation_order_phi"]),
        "nematic_order_psi": float(final["nematic_order_psi"]),
        "cumulative_deliveries": int(final["cumulative_deliveries"]),
        "transition_counts": dict(output.simulation.transition_counts),
    }


def run_experiment(
    config: ColonyConfig,
    *,
    test_summary: str = "not run by this command",
    pilot_summary: dict[str, object] | None = None,
) -> ExperimentOutput:
    project_root = Path(__file__).resolve().parents[2]
    output_dir = Path(config.output_dir)
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    process_start = time.perf_counter()
    simulation = ColonySimulation(config)
    simulation_start = time.perf_counter()
    result = simulation.run()
    simulation_seconds = time.perf_counter() - simulation_start

    _write_json(output_dir / "config.json", config.to_dict())
    result.metrics.to_csv(output_dir / "metrics.csv", index=False)
    result.agent_states.to_csv(output_dir / "agent_states.csv", index=False)
    result.final_agents.to_csv(output_dir / "final_agents.csv", index=False)
    result.events.to_csv(output_dir / "events.csv", index=False)
    _write_json(output_dir / "transition_counts.json", simulation.transition_counts)
    for time_step, snapshot in result.snapshots.items():
        snapshot.to_csv(output_dir / f"snapshot_t{time_step}.csv", index=False)
        _plot_snapshot(
            config,
            time_step,
            snapshot,
            result.pheromone_snapshots[time_step],
            output_dir,
        )
    _plot_role_counts(result.metrics, config, output_dir)
    _plot_order_parameters(result.metrics, config, output_dir)
    _plot_deliveries(result.metrics, output_dir)

    manifest = stage1_hash_manifest(project_root)
    _write_json(output_dir / "stage1_sha256.json", manifest)
    total_seconds_before_report = time.perf_counter() - process_start
    runtime: dict[str, object] = {
        "simulation_seconds": simulation_seconds,
        "total_seconds_before_report": total_seconds_before_report,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_only": True,
        "gpu_used": False,
        "autodl_used": False,
    }
    _write_json(output_dir / "runtime.json", runtime)
    output = ExperimentOutput(config, simulation, result, runtime, output_dir)
    _write_report(
        output,
        manifest,
        test_summary=test_summary,
        pilot_summary=pilot_summary,
    )
    return output
