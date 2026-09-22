"""Frozen exploratory analysis for the Stage 3D decay-law interaction."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import numpy as np

from .stage3d import (
    ARMS,
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    CAPPED_RECOVERY_TIME,
    SEEDS,
    STAGE3C_RESULTS_RELATIVE,
    validate_complete_study,
)


FOOTNOTE = (
    "Stage 3D exploratory matched-lifetime decay-law ablation; "
    "exponential controls reused from Stage 3C."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def _summary(path: Path) -> dict:
    return json.loads(path.read_text())


def _series(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def primary_rows(study_root: Path, repository_root: Path) -> list[dict]:
    validate_complete_study(study_root, repository_root)
    stage3c_root = repository_root / STAGE3C_RESULTS_RELATIVE
    rows = []
    for seed in SEEDS:
        exponential = {
            arm: _summary(stage3c_root / "runs" / str(seed) / arm / "summary.json")
            for arm in ARMS
        }
        cutoff = {
            arm: _summary(study_root / "runs" / str(seed) / arm / "summary.json")
            for arm in ARMS
        }
        d_exp = (
            exponential["C"]["capped_recovery_time"]
            - exponential["B0"]["capped_recovery_time"]
        )
        d_cut = cutoff["C"]["capped_recovery_time"] - cutoff["B0"]["capped_recovery_time"]
        rows.append({
            "seed": seed,
            "B0_exponential_capped_time": exponential["B0"]["capped_recovery_time"],
            "C_exponential_capped_time": exponential["C"]["capped_recovery_time"],
            "B0_cutoff_capped_time": cutoff["B0"]["capped_recovery_time"],
            "C_cutoff_capped_time": cutoff["C"]["capped_recovery_time"],
            "d_exp_C_minus_B0": d_exp,
            "d_cut_C_minus_B0": d_cut,
            "interaction_d_cut_minus_d_exp": d_cut - d_exp,
            "B0_exponential_non_delivery": exponential["B0"]["non_delivery"],
            "C_exponential_non_delivery": exponential["C"]["non_delivery"],
            "B0_cutoff_non_delivery": cutoff["B0"]["non_delivery"],
            "C_cutoff_non_delivery": cutoff["C"]["non_delivery"],
            "B0_cutoff_pre_A_deliveries": cutoff["B0"]["pre_relocation_A_deliveries"],
            "C_cutoff_pre_A_deliveries": cutoff["C"]["pre_relocation_A_deliveries"],
        })
    return rows


def analyse_rows(rows: list[dict], stage3c_analysis: dict) -> tuple[dict, np.ndarray]:
    rows = sorted(rows, key=lambda row: row["seed"])
    errors = []
    if len(rows) != 20 or {row["seed"] for row in rows} != set(SEEDS):
        errors.append("analysis requires exactly the frozen 20 seeds")
    if len({row["seed"] for row in rows}) != len(rows):
        errors.append("duplicate seed")
    for row in rows:
        for key in (
            "B0_exponential_capped_time", "C_exponential_capped_time",
            "B0_cutoff_capped_time", "C_cutoff_capped_time",
        ):
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= CAPPED_RECOVERY_TIME:
                errors.append(f"invalid capped endpoint for seed {row['seed']}: {key}")
    if errors:
        return ({
            "classification": "INCONCLUSIVE", "valid": False,
            "errors": errors, "secondary_metrics_used_for_decision": False,
        }, np.asarray([], dtype=np.float64))

    arrays = {
        key: np.asarray([row[key] for row in rows], dtype=np.float64)
        for key in (
            "B0_exponential_capped_time", "C_exponential_capped_time",
            "B0_cutoff_capped_time", "C_cutoff_capped_time",
            "d_exp_C_minus_B0", "d_cut_C_minus_B0",
            "interaction_d_cut_minus_d_exp",
        )
    }
    if arrays["d_exp_C_minus_B0"].tolist() != stage3c_analysis["delta_time_C_minus_B0"]:
        return ({
            "classification": "INCONCLUSIVE", "valid": False,
            "errors": ["reused exponential deltas differ from Stage 3C analysis"],
            "secondary_metrics_used_for_decision": False,
        }, np.asarray([], dtype=np.float64))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(0, len(rows), size=(BOOTSTRAP_REPLICATES, len(rows)))
    interaction_means = arrays["interaction_d_cut_minus_d_exp"][indices].mean(axis=1)
    cutoff_means = arrays["d_cut_C_minus_B0"][indices].mean(axis=1)
    interaction_ci = np.percentile(interaction_means, [2.5, 97.5], method="linear")
    cutoff_ci = np.percentile(cutoff_means, [2.5, 97.5], method="linear")
    pre_b0 = sum(row["B0_cutoff_pre_A_deliveries"] for row in rows)
    pre_c = sum(row["C_cutoff_pre_A_deliveries"] for row in rows)
    if pre_b0 == 0:
        return ({
            "classification": "INCONCLUSIVE", "valid": False,
            "errors": ["hard-cutoff pre-A B0 denominator is zero"],
            "secondary_metrics_used_for_decision": False,
        }, interaction_means)
    pre_ratio = pre_c / pre_b0
    interval_one_side = float(interaction_ci[1]) < 0 or float(interaction_ci[0]) > 0
    thresholds = {
        "all_40_new_hard_cutoff_arms_valid": True,
        "all_40_reused_exponential_arms_valid": True,
        "hard_cutoff_pre_A_ratio_at_least_0_80": pre_ratio >= 0.80,
        "interaction_CI_entirely_on_one_side_of_zero": interval_one_side,
    }
    classification = "INTERACTION_DETECTED" if all(thresholds.values()) else "NO_CLEAR_INTERACTION"

    def cell_stats(name: str, non_delivery_key: str) -> dict:
        values = arrays[name]
        return {
            "mean": float(values.mean()),
            "median": float(statistics.median(values.tolist())),
            "non_delivery_count": sum(bool(row[non_delivery_key]) for row in rows),
        }

    result = {
        "study_status": "prospective exploratory extension after Stage 3C",
        "classification": classification,
        "valid": True,
        "errors": [],
        "seeds": [row["seed"] for row in rows],
        "cells": {
            "exponential_B0": cell_stats("B0_exponential_capped_time", "B0_exponential_non_delivery"),
            "exponential_C": cell_stats("C_exponential_capped_time", "C_exponential_non_delivery"),
            "hard_cutoff_B0": cell_stats("B0_cutoff_capped_time", "B0_cutoff_non_delivery"),
            "hard_cutoff_C": cell_stats("C_cutoff_capped_time", "C_cutoff_non_delivery"),
        },
        "exponential_within_law": {
            "source": "read-only Stage 3C reuse",
            "mean_C_minus_B0": float(arrays["d_exp_C_minus_B0"].mean()),
            "confidence_interval_95": stage3c_analysis["paired_bootstrap"]["confidence_interval_95"],
            "stage3c_decision": stage3c_analysis["decision"],
        },
        "hard_cutoff_within_law": {
            "status": "descriptive",
            "mean_C_minus_B0": float(arrays["d_cut_C_minus_B0"].mean()),
            "confidence_interval_95": cutoff_ci.tolist(),
        },
        "interaction": {
            "definition": "(C-B0)_hard_cutoff - (C-B0)_exponential",
            "mean": float(arrays["interaction_d_cut_minus_d_exp"].mean()),
            "confidence_interval_95": interaction_ci.tolist(),
            "direction_if_detected": (
                "hard cutoff makes C relatively more favourable"
                if float(interaction_ci[1]) < 0
                else "hard cutoff makes C relatively less favourable"
                if float(interaction_ci[0]) > 0
                else None
            ),
        },
        "paired_bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "resampling_unit": "complete seed-level four-cell record",
            "percentile_method": "linear",
            "replicate_means_data_sha256": hashlib.sha256(interaction_means.tobytes()).hexdigest(),
        },
        "hard_cutoff_pre_A_totals": {"B0": pre_b0, "C": pre_c},
        "hard_cutoff_pre_A_ratio": pre_ratio,
        "thresholds": thresholds,
        "secondary_metrics_used_for_decision": False,
    }
    return result, interaction_means


def _secondary_rows(study_root: Path, repository_root: Path) -> tuple[list[dict], list[dict]]:
    stage3c_root = repository_root / STAGE3C_RESULTS_RELATIVE
    endpoints = []
    timeseries = []
    for seed in SEEDS:
        for decay, root, provenance in (
            ("exponential", stage3c_root, "reused_stage3c"),
            ("hard_cutoff_cell_timer", study_root, "new_stage3d"),
        ):
            for arm in ARMS:
                run = root / "runs" / str(seed) / arm
                summary = _summary(run / "summary.json")
                series = _series(run / "timeseries_100step.json")
                final = series[-1]
                first = summary.get("first_B_discovery")
                endpoints.append({
                    "seed": seed,
                    "decay_law": decay,
                    "arm": arm,
                    "provenance": provenance,
                    "first_B_discovery_absolute": first,
                    "first_B_discovery_after_relocation": None if first is None else first - 6000,
                    "B_discovery_missing": first is None,
                    "B_deliveries": summary["B_deliveries"],
                    "non_delivery": summary["non_delivery"],
                    "pre_relocation_A_deliveries": summary["pre_relocation_A_deliveries"],
                    "old_food_dwell_ant_steps": summary["old_food_dwell_ant_steps"],
                    "obsolete_trail_ant_steps": summary["obsolete_trail_ant_steps"],
                    "final_obsolete_trail_scalar_mass": final["obsolete_trail_scalar_mass"],
                    "final_obsolete_trail_cells_off": final["obsolete_trail_cells_off"],
                    "final_obsolete_trail_cells_on": final["obsolete_trail_cells_on"],
                    "recovery_count": summary["recovery_count"],
                    "recovery_reacquired": summary["recovery_reacquired"],
                    "recovery_timeouts": summary["recovery_timeouts"],
                    "recovery_food_contacts": summary["recovery_food_contacts"],
                    "recovery_B_discovery_within_100_steps": summary["recovery_B_discovery_within_100_steps"],
                    "recovery_B_delivery_within_100_steps": summary["recovery_B_delivery_within_100_steps"],
                })
                for item in series:
                    timeseries.append({
                        "seed": seed, "decay_law": decay, "arm": arm,
                        "provenance": provenance, "time": item["time"],
                        "old_food_dwell_ant_steps": item["old_food_dwell_ant_steps"],
                        "obsolete_trail_ant_steps": item["obsolete_trail_ant_steps"],
                        "obsolete_trail_scalar_mass": item["obsolete_trail_scalar_mass"],
                        "obsolete_trail_cells_off": item["obsolete_trail_cells_off"],
                        "obsolete_trail_cells_on": item["obsolete_trail_cells_on"],
                        "B_discoveries": item["discoveries"]["B"],
                        "B_deliveries": item["deliveries"]["B"],
                    })
    return endpoints, timeseries


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _secondary_summary(rows: list[dict]) -> dict:
    groups = {}
    for decay in ("exponential", "hard_cutoff_cell_timer"):
        for arm in ARMS:
            subset = [r for r in rows if r["decay_law"] == decay and r["arm"] == arm]
            observed_discovery = [r["first_B_discovery_after_relocation"] for r in subset if not r["B_discovery_missing"]]
            recovery_total = sum(r["recovery_count"] for r in subset)
            key = f"{decay}_{arm}"
            groups[key] = {
                "n": len(subset),
                "first_B_discovery_observed": len(observed_discovery),
                "first_B_discovery_missing": sum(r["B_discovery_missing"] for r in subset),
                "first_B_discovery_after_relocation_mean": _mean(observed_discovery),
                "B_deliveries_mean": _mean([r["B_deliveries"] for r in subset]),
                "non_delivery_fraction": _mean([int(r["non_delivery"]) for r in subset]),
                "pre_relocation_A_deliveries_total": sum(r["pre_relocation_A_deliveries"] for r in subset),
                "old_food_dwell_mean": _mean([r["old_food_dwell_ant_steps"] for r in subset]),
                "obsolete_trail_occupancy_mean": _mean([r["obsolete_trail_ant_steps"] for r in subset]),
                "final_obsolete_scalar_mass_mean": _mean([r["final_obsolete_trail_scalar_mass"] for r in subset]),
                "final_obsolete_cells_off_mean": _mean([r["final_obsolete_trail_cells_off"] for r in subset]),
                "final_obsolete_cells_on_mean": _mean([r["final_obsolete_trail_cells_on"] for r in subset]),
                "recovery_episode_count": recovery_total,
                "recovery_reacquisition_rate": (
                    sum(r["recovery_reacquired"] for r in subset) / recovery_total
                    if recovery_total else None
                ),
                "recovery_timeout_rate": (
                    sum(r["recovery_timeouts"] for r in subset) / recovery_total
                    if recovery_total else None
                ),
                "recovery_food_contact_endings": sum(r["recovery_food_contacts"] for r in subset),
                "recovery_B_discovery_within_100_steps": sum(r["recovery_B_discovery_within_100_steps"] for r in subset),
                "recovery_B_delivery_within_100_steps": sum(r["recovery_B_delivery_within_100_steps"] for r in subset),
            }
    return {
        "evidence_status": "descriptive secondary analysis",
        "aggregation_status": "post_hoc_descriptive",
        "additional_significance_tests": False,
        "primary_classification_unchanged": True,
        "groups": groups,
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _add_footnote(fig) -> None:
    fig.text(0.5, 0.01, FOOTNOTE, ha="center", fontsize=8)


def _plots(study_root: Path, primary: list[dict], secondary: list[dict], timeseries: list[dict], analysis: dict) -> list[str]:
    labels = [str(row["seed"])[-2:] for row in primary]
    interactions = np.asarray([row["interaction_d_cut_minus_d_exp"] for row in primary])
    fig, ax = plt.subplots(figsize=(11, 5.8))
    colours = np.where(interactions < 0, "#2b6cb0", "#c53030")
    ax.bar(labels, interactions, color=colours)
    ax.axhline(0, color="black", linewidth=1)
    ax.axhline(analysis["interaction"]["mean"], color="#6b46c1", linestyle="--", label="Mean interaction")
    ax.set(title="Paired decay-law interaction for all 20 seeds", xlabel="Seed suffix", ylabel="Interaction (steps): d_cut − d_exp")
    ax.legend()
    _add_footnote(fig); fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(study_root / "paired_interaction.png", dpi=180); plt.close(fig)

    cell_keys = ["B0_exponential_capped_time", "C_exponential_capped_time", "B0_cutoff_capped_time", "C_cutoff_capped_time"]
    cell_labels = ["Exp B0", "Exp C", "Cutoff B0", "Cutoff C"]
    fig, ax = plt.subplots(figsize=(9.5, 6))
    data = [[row[key] for row in primary] for key in cell_keys]
    ax.boxplot(data, labels=cell_labels, showmeans=True)
    for index, values in enumerate(data, start=1):
        ax.scatter(np.full(len(values), index), values, alpha=0.55, s=20)
    ax.axhline(CAPPED_RECOVERY_TIME, color="black", linestyle=":", label="12,000 cap")
    ax.set(title="Four-cell capped recovery-time comparison", ylabel="Capped time after relocation (steps)")
    ax.legend()
    _add_footnote(fig); fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(study_root / "four_cell_capped_times.png", dpi=180); plt.close(fig)

    grouped = []
    for decay in ("exponential", "hard_cutoff_cell_timer"):
        for arm in ARMS:
            subset = [r for r in secondary if r["decay_law"] == decay and r["arm"] == arm]
            grouped.append((f"{'Exp' if decay == 'exponential' else 'Cut'} {arm}", subset))
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    axes[0].bar([x[0] for x in grouped], [sum(r["non_delivery"] for r in x[1]) for x in grouped], color="#805ad5")
    axes[0].set(title="Non-delivery count", ylabel="Arms (of 20)")
    axes[1].bar([x[0] for x in grouped], [np.mean([r["B_deliveries"] for r in x[1]]) for x in grouped], color="#319795")
    axes[1].set(title="Mean food B deliveries", ylabel="Deliveries")
    for ax in axes: ax.tick_params(axis="x", rotation=25)
    _add_footnote(fig); fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(study_root / "non_delivery_food_b_delivery.png", dpi=180); plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    metrics = [
        ("obsolete_trail_scalar_mass", "Scalar mass"),
        ("obsolete_trail_cells_off", "Cells ≥ signal_off"),
        ("obsolete_trail_cells_on", "Cells ≥ signal_on"),
    ]
    for decay in ("exponential", "hard_cutoff_cell_timer"):
        for arm in ARMS:
            subset = [r for r in timeseries if r["decay_law"] == decay and r["arm"] == arm and r["time"] >= 6000]
            times = sorted({r["time"] for r in subset})
            label = f"{'Exp' if decay == 'exponential' else 'Cut'} {arm}"
            for ax, (metric, title) in zip(axes, metrics):
                means = [np.mean([r[metric] for r in subset if r["time"] == t]) for t in times]
                ax.plot(np.asarray(times) - 6000, means, label=label)
                ax.set(title=title, xlabel="Steps after relocation")
    axes[0].set_ylabel("Mean across 20 seeds")
    axes[-1].legend(fontsize=8)
    _add_footnote(fig); fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(study_root / "obsolete_trail_persistence.png", dpi=180); plt.close(fig)

    c_groups = [(decay, [r for r in secondary if r["decay_law"] == decay and r["arm"] == "C"]) for decay in ("exponential", "hard_cutoff_cell_timer")]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 5.2))
    names = ["Exponential C", "Hard cutoff C"]
    reacq = [sum(r["recovery_reacquired"] for r in rows) / sum(r["recovery_count"] for r in rows) for _, rows in c_groups]
    timeout = [sum(r["recovery_timeouts"] for r in rows) / sum(r["recovery_count"] for r in rows) for _, rows in c_groups]
    x = np.arange(2)
    axes[0].bar(x - .18, reacq, .36, label="Reacquired")
    axes[0].bar(x + .18, timeout, .36, label="Timeout")
    axes[0].set_xticks(x, names, rotation=15); axes[0].set_ylim(0, 1); axes[0].set(title="Recovery episode outcome rates", ylabel="Fraction")
    axes[0].legend()
    discovery = [sum(r["recovery_B_discovery_within_100_steps"] for r in rows) for _, rows in c_groups]
    delivery = [sum(r["recovery_B_delivery_within_100_steps"] for r in rows) for _, rows in c_groups]
    axes[1].bar(x - .18, discovery, .36, label="B discovery ≤100")
    axes[1].bar(x + .18, delivery, .36, label="B delivery ≤100")
    axes[1].set_xticks(x, names, rotation=15); axes[1].set(title="Same-ant post-recovery events", ylabel="Episode count")
    axes[1].legend()
    _add_footnote(fig); fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(study_root / "recovery_diagnostics.png", dpi=180); plt.close(fig)
    return [
        "paired_interaction.png", "four_cell_capped_times.png",
        "non_delivery_food_b_delivery.png", "obsolete_trail_persistence.png",
        "recovery_diagnostics.png",
    ]


def _report(primary: list[dict], analysis: dict, secondary: dict) -> str:
    cells = analysis["cells"]
    lines = [
        "# PH6780 Stage 3D matched-lifetime decay-law ablation", "",
        "## Evidence status", "",
        "Stage 3D is a prospective exploratory extension designed after the Stage 3C Mechanism FAIL result was observed. It is not an independent confirmatory study. Engineering validity, interaction classification, and descriptive endpoints are reported separately.", "",
        f"Frozen classification: **{analysis['classification']}**.", "",
        "## Frozen design", "",
        "The study reused the 20 completed exponential B0/C pairs from Stage 3C and added 20 hard-cutoff B0/C pairs with the same seeds. The hard cutoff was 2,000 steps, matching only the theoretical single-deposit lifetime from q=1 to signal_off=0.25 under a 1,000-step exponential half-life. Diffusion remained zero. C retained the frozen 24-step recovery search; all other paired dynamics were unchanged.", "",
        "## Primary interaction", "",
        "| Quantity | Result |", "|---|---:|",
        f"| Mean interaction, d_cut − d_exp | {analysis['interaction']['mean']:.4f} steps |",
        f"| 95% paired bootstrap interval | [{analysis['interaction']['confidence_interval_95'][0]:.4f}, {analysis['interaction']['confidence_interval_95'][1]:.4f}] |",
        f"| Hard-cutoff pre-A ratio, C/B0 | {analysis['hard_cutoff_pre_A_ratio']:.6f} |",
        f"| Classification | **{analysis['classification']}** |", "",
        "The interaction is negative when the relative C effect is more favourable under hard cutoff and positive when it is less favourable. Classification follows only the frozen interval, identity, completeness, and pre-A safeguards.", "",
        "## Four-cell primary summaries", "",
        "| Cell | Mean capped time | Median | Non-delivery |", "|---|---:|---:|---:|",
    ]
    for key, label in (
        ("exponential_B0", "Exponential B0"), ("exponential_C", "Exponential C"),
        ("hard_cutoff_B0", "Hard cutoff B0"), ("hard_cutoff_C", "Hard cutoff C"),
    ):
        item = cells[key]
        lines.append(f"| {label} | {item['mean']:.2f} | {item['median']:.2f} | {item['non_delivery_count']}/20 |")
    lines += ["", "The reused exponential mean C−B0 difference was "
        f"{analysis['exponential_within_law']['mean_C_minus_B0']:.2f} steps with its Stage 3C interval "
        f"[{analysis['exponential_within_law']['confidence_interval_95'][0]:.4f}, {analysis['exponential_within_law']['confidence_interval_95'][1]:.4f}]. "
        f"The descriptive hard-cutoff mean C−B0 difference was {analysis['hard_cutoff_within_law']['mean_C_minus_B0']:.2f} steps with interval "
        f"[{analysis['hard_cutoff_within_law']['confidence_interval_95'][0]:.4f}, {analysis['hard_cutoff_within_law']['confidence_interval_95'][1]:.4f}].", "",
        "### All 20 seed-level interactions", "",
        "| Seed | Exp B0 | Exp C | Cut B0 | Cut C | d_exp | d_cut | Interaction |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in primary:
        lines.append(
            f"| {row['seed']} | {row['B0_exponential_capped_time']} | {row['C_exponential_capped_time']} | "
            f"{row['B0_cutoff_capped_time']} | {row['C_cutoff_capped_time']} | "
            f"{row['d_exp_C_minus_B0']:+} | {row['d_cut_C_minus_B0']:+} | {row['interaction_d_cut_minus_d_exp']:+} |"
        )
    lines += ["", "## Descriptive secondary endpoints", "",
        "These aggregates are post hoc descriptive summaries with no additional significance tests. They cannot replace or revise the frozen interaction classification.", ""]
    for key, label in (
        ("exponential_B0", "Exponential B0"), ("exponential_C", "Exponential C"),
        ("hard_cutoff_cell_timer_B0", "Hard cutoff B0"), ("hard_cutoff_cell_timer_C", "Hard cutoff C"),
    ):
        item = secondary["groups"][key]
        lines.append(
            f"**{label}:** discovery observed {item['first_B_discovery_observed']}/20, mean discovery after relocation "
            f"{item['first_B_discovery_after_relocation_mean']}, mean B deliveries {item['B_deliveries_mean']}, "
            f"non-delivery fraction {item['non_delivery_fraction']}, pre-A total {item['pre_relocation_A_deliveries_total']}, "
            f"mean old-food dwell {item['old_food_dwell_mean']}, and mean obsolete-trail occupancy {item['obsolete_trail_occupancy_mean']}."
        )
        lines.append("")
    lines += ["## Interpretation limits", "",
        "The experiment isolates one matched-lifetime contrast in one fixed scalar-only arena. Matching 2,000 steps does not match the full concentration curve, signal_on lifetime, cumulative exposure, or repeated deposition. The model is not an animal experiment. It uses zero diffusion, one half-life, one cutoff, one recovery duration, fixed geometry, a capped endpoint, and 20 reused seeds. The result cannot establish that hard cutoff is more biologically realistic, that either decay law is generally superior, or that the mechanism is SOTA.", "",
        "No seed was removed, added, replaced, or rerun based on outcomes. No parameter scan, LLM, random search, TPE, new recovery strategy, cell direction, PCA, diffusion, or food-coordinate navigation was used.", ""]
    return "\n".join(lines)


def write_analysis(study_root: Path, repository_root: Path) -> dict:
    required_absent = [
        "paired_decay_interaction.csv", "confirmatory_analysis.json",
        "bootstrap_interaction_means.npy", "secondary_endpoints.csv",
        "secondary_timeseries_100step.csv", "secondary_summary.json", "REPORT.md",
        "analysis_manifest.json", "paired_interaction.png", "four_cell_capped_times.png",
        "non_delivery_food_b_delivery.png", "obsolete_trail_persistence.png",
        "recovery_diagnostics.png",
    ]
    existing = [name for name in required_absent if (study_root / name).exists()]
    if existing:
        raise FileExistsError(f"Stage 3D analysis outputs already exist: {existing}")
    rows = primary_rows(study_root, repository_root)
    stage3c_analysis = json.loads(
        (repository_root / STAGE3C_RESULTS_RELATIVE / "confirmatory_analysis.json").read_text()
    )
    analysis, replicate_means = analyse_rows(rows, stage3c_analysis)
    if analysis["classification"] == "INCONCLUSIVE":
        raise RuntimeError(f"Stage 3D analysis is inconclusive: {analysis['errors']}")
    _write_csv(study_root / "paired_decay_interaction.csv", rows)
    np.save(study_root / "bootstrap_interaction_means.npy", replicate_means, allow_pickle=False)
    analysis["paired_bootstrap"]["replicate_means_file"] = "bootstrap_interaction_means.npy"
    analysis["paired_bootstrap"]["replicate_means_file_sha256"] = _sha256(study_root / "bootstrap_interaction_means.npy")
    _write_json(study_root / "confirmatory_analysis.json", analysis)
    endpoints, timeseries = _secondary_rows(study_root, repository_root)
    _write_csv(study_root / "secondary_endpoints.csv", endpoints)
    _write_csv(study_root / "secondary_timeseries_100step.csv", timeseries)
    secondary = _secondary_summary(endpoints)
    secondary["primary_classification"] = analysis["classification"]
    _write_json(study_root / "secondary_summary.json", secondary)
    charts = _plots(study_root, rows, endpoints, timeseries, analysis)
    (study_root / "REPORT.md").write_text(_report(rows, analysis, secondary), encoding="utf-8")
    manifest_names = [
        "paired_decay_interaction.csv", "confirmatory_analysis.json",
        "bootstrap_interaction_means.npy", "secondary_endpoints.csv",
        "secondary_timeseries_100step.csv", "secondary_summary.json", "REPORT.md",
        *charts,
    ]
    manifest = {
        "schema": "stage3d-analysis-manifest-v1",
        "scope": "Stage 3D analysis-layer outputs; manifest excludes itself and raw arm receipts",
        "file_count": len(manifest_names),
        "files": [
            {"path": name, "bytes": (study_root / name).stat().st_size, "sha256": _sha256(study_root / name)}
            for name in manifest_names
        ],
    }
    _write_json(study_root / "analysis_manifest.json", manifest)
    return analysis
