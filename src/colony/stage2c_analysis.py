"""Fixed seed-pair analysis; incomplete studies never receive a final verdict."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np

from .stage2c_checkpoint import atomic_write, json_bytes
from .stage2c_streaming import measurement

SEEDS = tuple(range(20260901, 20260921))
EXPLORATORY_SEED = 20260824
RULES = ("stored_cell_direction", "local_weighted_pca_tangent")
BOOTSTRAP_SEED = 20260999
BOOTSTRAP_REPETITIONS = 10000
NOTICE = "Stage 2C paired confirmation of a frozen provisional implementation — not an exact reproduction of Fig. 4."
METRICS = (
    "late_window_mean_phi", "late_window_mean_psi", "follower_late_window_mean_phi",
    "follower_late_window_mean_psi", "absolute_late_phi_distance",
    "follower_hit_step_mean_axis_error_deg", "follower_local_continuity_mean_axis_change_deg",
    "follower_sensing_miss_rate", "cumulative_deliveries",
    "completed_transporter_mean_path_efficiency", "completed_transporter_median_path_efficiency",
    "active_pheromone_area_fraction", "main_channel_width_90",
    "final_forager_count", "final_transporter_count", "final_follower_count",
    "first_food_discovery_time", "first_successful_delivery_time", "first_pheromone_recruitment_time",
)
DIRECTIONS = {
    "late_window_mean_psi": 1, "follower_late_window_mean_psi": 1,
    "follower_hit_step_mean_axis_error_deg": -1,
    "follower_local_continuity_mean_axis_change_deg": -1,
    "follower_sensing_miss_rate": -1, "cumulative_deliveries": 1,
    "completed_transporter_mean_path_efficiency": 1,
    "absolute_late_phi_distance": -1, "main_channel_width_90": -1,
}


def seed_manifest() -> dict:
    return {"confirmatory_seeds": list(SEEDS), "exploratory_seed": EXPLORATORY_SEED,
            "exploratory_in_confirmatory_statistics": False, "pilot_seed": SEEDS[0],
            "pilot_in_confirmatory_statistics": True, "rule_order": list(RULES),
            "planned_runs": [{"seed": s, "rule": r} for s in SEEDS for r in RULES]}


def planned_rows() -> list[dict]:
    return [{"seed": s, "rule": r, "status": "planned", "engineering_valid": False,
             "metrics": {m: measurement(None, count=0, reason="planned_not_run") for m in METRICS},
             "transition_counts": None, "initial_identity": None}
            for s in SEEDS for r in RULES]


def index_rows(rows: list[dict]) -> dict:
    expected = [(s, r) for s in SEEDS for r in RULES]
    actual = [(r["seed"], r["rule"]) for r in rows]
    if actual != expected:
        raise ValueError("exactly 40 ordered confirmatory rows are required; no exploratory or replacement seeds")
    return dict(zip(expected, rows))


def value(row: dict, name: str):
    item = row["metrics"][name]
    v = item["value"]
    if v is not None and (not np.isfinite(v) or item["availability"] != "available"):
        raise ValueError("invalid endpoint value/availability")
    if v is None and (item["availability"] != "unavailable" or not item["reason"]):
        raise ValueError("missing endpoints require an explicit reason")
    return v


def paired_rows(rows: list[dict]) -> list[dict]:
    indexed = index_rows(rows)
    output = []
    for seed in SEEDS:
        baseline, pca = (indexed[seed, r] for r in RULES)
        pair = {"seed": seed, "baseline_status": baseline["status"], "pca_status": pca["status"]}
        for row, label in ((baseline, "baseline"), (pca, "pca")):
            pair[label + "_engineering_valid"] = row["engineering_valid"] if row["status"] == "completed" else None
            pair[label + "_candidate_checks"] = candidate_checks(row)
            pair[label + "_late_window_delivery_increment"] = row.get("late_window_delivery_increment")
            pair[label + "_late_window_transition_counts"] = row.get("late_window_transition_counts")
        for name in METRICS:
            b, p = value(baseline, name), value(pca, name)
            pair[name + "_baseline"] = b
            pair[name + "_pca"] = p
            pair[name + "_delta"] = p - b if b is not None and p is not None else None
            pair[name + "_reason"] = "" if b is not None and p is not None else "missing_paired_measurement"
        b, p = value(baseline, "cumulative_deliveries"), value(pca, "cumulative_deliveries")
        ratio = p / b if b is not None and p is not None and b > 0 else None
        pair["delivery_ratio"] = ratio
        pair["delivery_ratio_reason"] = ("" if ratio is not None else
                                          "zero_baseline_deliveries" if b == 0 else "missing_paired_measurement")
        output.append(pair)
    return output


def bootstrap_indices() -> np.ndarray:
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    return rng.integers(0, 20, size=(BOOTSTRAP_REPETITIONS, 20), dtype=np.int64)


def paired_bootstrap(baseline, pca, *, indices=None) -> dict:
    b, p = np.asarray(baseline, dtype=float), np.asarray(pca, dtype=float)
    if b.shape != (20,) or p.shape != (20,) or not np.isfinite(b).all() or not np.isfinite(p).all():
        raise ValueError("bootstrap requires all 20 finite seed pairs")
    draws = bootstrap_indices() if indices is None else indices
    if draws.shape != (10000, 20) or draws.dtype != np.dtype("int64") or np.any(draws < 0) or np.any(draws >= 20):
        raise ValueError("invalid bootstrap index array")
    means = (p - b)[draws].mean(axis=1)
    lower, upper = np.quantile(means, [0.025, 0.975], method="linear")
    return {"seed": BOOTSTRAP_SEED, "repetitions": BOOTSTRAP_REPETITIONS,
            "generator": "PCG64", "numpy_version": np.__version__, "unit": "seed_pair",
            "interval": "percentile", "percentiles": [2.5, 97.5], "quantile_method": "linear",
            "lower": float(lower), "upper": float(upper), "estimate": float(np.mean(p - b))}


def descriptive(values) -> dict:
    available = np.asarray([x for x in values if x is not None], dtype=float)
    if not np.isfinite(available).all():
        raise ValueError("non-finite descriptive observations")
    n = len(available)
    return {"n": n, "unavailable": len(values) - n,
            "mean": float(np.mean(available)) if n else None,
            "median": float(np.median(available)) if n else None,
            "standard_deviation": float(np.std(available, ddof=1)) if n > 1 else None,
            "ddof": 1, "reason": "" if n > 1 else "insufficient_observations_for_sample_sd"}


def cycle_valid(row: dict) -> bool:
    counts = row.get("transition_counts") or {}
    deliveries = value(row, "cumulative_deliveries")
    return bool(deliveries is not None and deliveries > 0 and
                counts.get("follower_to_transporter", 0) > 0 and
                counts.get("transporter_to_follower", 0) > 0)


def candidate_checks(row: dict) -> dict:
    if row["status"] != "completed" or not row["engineering_valid"]:
        return {"passed": None, "reason": "complete_valid_run_required"}
    phi, psi = value(row, "late_window_mean_phi"), value(row, "late_window_mean_psi")
    checks = {"phi_distance_at_most_0_15": phi is not None and abs(phi - np.pi / 4) <= 0.15,
              "psi_at_least_0_90": psi is not None and psi >= 0.90,
              "transport_and_role_cycle": cycle_valid(row)}
    return dict(checks, passed=all(checks.values()),
                reason="required_phi_or_psi_unavailable" if phi is None or psi is None else "")


def analyse_rows(rows: list[dict]) -> dict:
    indexed = index_rows(rows)
    pairs = paired_rows(rows)
    complete = all(row["status"] == "completed" and row["engineering_valid"] for row in rows)
    result = {"notice": NOTICE, "status": "complete" if complete else "incomplete",
              "confirmatory_seeds": list(SEEDS), "completed_valid_runs": sum(
                  row["status"] == "completed" and row["engineering_valid"] for row in rows),
              "final_verdict_available": False, "paired_rows": pairs}
    if not complete:
        result["reason"] = "all_20_valid_complete_pairs_required"
        return result
    # Pair identities are required evidence, not implied by matching seed labels.
    for seed in SEEDS:
        b, p = (indexed[seed, r] for r in RULES)
        if not b.get("initial_identity") or b["initial_identity"] != p.get("initial_identity"):
            result.update(status="invalid", reason="paired_initialisation_mismatch")
            return result
    draws = bootstrap_indices()
    summaries = {}
    for name in METRICS:
        b = [pair[name + "_baseline"] for pair in pairs]
        p = [pair[name + "_pca"] for pair in pairs]
        delta = [pair[name + "_delta"] for pair in pairs]
        sign = DIRECTIONS.get(name)
        counts = {"positive": sum(d is not None and d > 0 for d in delta),
                  "equal": sum(d == 0 for d in delta),
                  "negative": sum(d is not None and d < 0 for d in delta),
                  "unavailable": sum(d is None for d in delta)}
        if sign is not None:
            counts.update(improved=counts["positive" if sign > 0 else "negative"],
                          worsened=counts["negative" if sign > 0 else "positive"])
        summaries[name] = {"baseline": descriptive(b), "pca": descriptive(p),
                           "paired_difference": descriptive(delta), "counts": counts,
                           "favourable_direction": sign,
                           "bootstrap": paired_bootstrap(b, p, indices=draws) if None not in delta else None}
    primary = summaries["late_window_mean_psi"]
    ratios = descriptive([pair["delivery_ratio"] for pair in pairs])
    error = summaries["follower_hit_step_mean_axis_error_deg"]["pca"]
    primary_estimate = primary["paired_difference"]
    checks = {
        "mean_delta_psi_at_least_0_10": primary_estimate["n"] == 20 and primary_estimate["mean"] >= 0.10,
        "bootstrap_lower_above_zero": primary["bootstrap"] is not None and primary["bootstrap"]["lower"] > 0,
        "pca_mean_follower_error_at_most_35": error["n"] == 20 and error["mean"] <= 35,
        "median_per_seed_delivery_ratio_at_least_0_80": ratios["n"] == 20 and ratios["median"] >= 0.80,
        "all_engineering_and_identity_checks": True,
    }
    unresolved = {
        "mean_delta_psi_at_least_0_10": primary_estimate["n"] != 20,
        "bootstrap_lower_above_zero": primary["bootstrap"] is None,
        "pca_mean_follower_error_at_most_35": error["n"] != 20,
        "median_per_seed_delivery_ratio_at_least_0_80": ratios["n"] != 20,
        "all_engineering_and_identity_checks": False,
    }
    reasons = {name: "" if passed else "unresolved_required_measurements" if unresolved[name]
               else "registered_threshold_not_met" for name, passed in checks.items()}
    directions = [summaries[name]["paired_difference"]["mean"] * direction
                  for name, direction in DIRECTIONS.items()
                  if summaries[name]["paired_difference"]["n"] == 20]
    conflict = any(d > 0 for d in directions) and any(d < 0 for d in directions)
    missing = len(directions) != len(DIRECTIONS) or ratios["n"] != 20
    mechanism = "PASS" if all(checks.values()) else "FAIL"
    scientific = "MIXED" if conflict or missing else mechanism
    per_seed_candidates = []
    for row in rows:
        per_seed_candidates.append(dict(seed=row["seed"], rule=row["rule"], **candidate_checks(row)))
    phi_summary = summaries["late_window_mean_phi"]["pca"]
    psi_summary = primary["pca"]
    candidate = (phi_summary["n"] == psi_summary["n"] == 20
                 and abs(phi_summary["mean"] - np.pi / 4) <= 0.15 and psi_summary["mean"] >= 0.90
                 and all(cycle_valid(indexed[s, RULES[1]]) for s in SEEDS))
    result.update(final_verdict_available=True, metrics=summaries, delivery_ratio=ratios,
                  mechanism_checks=checks, mechanism_check_reasons=reasons, mechanism_improvement=mechanism,
                  scientific_conclusion=scientific, directional_conflict=conflict,
                  missing_directional_evidence=missing,
                  fig4_candidate="PASS" if candidate else "FAIL",
                  per_seed_candidates=per_seed_candidates,
                  candidate_counts={rule: sum(r["passed"] for r in per_seed_candidates if r["rule"] == rule)
                                    for rule in RULES},
                  directional_contrasts={name: {"all_20_pairs_available": summaries[name]["paired_difference"]["n"] == 20,
                                               "mean_pca_minus_baseline": summaries[name]["paired_difference"]["mean"],
                                               "favourable_direction": direction}
                                         for name, direction in DIRECTIONS.items()})
    json_bytes(result)
    return result


def csv_bytes(rows: list[dict]) -> bytes:
    buffer = io.StringIO(newline="")
    if not rows:
        return b""
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: json_bytes(v).decode().strip() if isinstance(v, (dict, list)) else v
                         for k, v in row.items()})
    return buffer.getvalue().encode()


def write_metric_tables(output: Path, rows: list[dict]) -> None:
    index_rows(rows)
    flat = []
    for row in rows:
        item = {"seed": row["seed"], "rule": row["rule"], "status": row["status"],
                "engineering_valid": row["engineering_valid"]}
        for name in METRICS:
            metric = row["metrics"][name]
            item[name] = value(row, name)
            for field in ("availability", "reason", "count"):
                item[name + "_" + field] = metric[field]
            if name.startswith("first_"):
                item[name + "_observed"] = metric.get("observed")
                item[name + "_censoring_horizon"] = metric.get("censoring_horizon")
        flat.append(item)
    atomic_write(output / "per_seed_metrics.csv", csv_bytes(flat))
    atomic_write(output / "paired_comparison.csv", csv_bytes(paired_rows(rows)))


def write_comparison_figures(output: Path, rows: list[dict], summary: dict, *, test_fixture: bool = False) -> None:
    """Called only for an already verified complete study (or synthetic tests)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = [
        ("01_primary.png", ["late_window_mean_psi", "delta_psi"]),
        ("02_followers.png", ["follower_late_window_mean_psi", "follower_hit_step_mean_axis_error_deg",
                              "follower_local_continuity_mean_axis_change_deg", "follower_sensing_miss_rate"]),
        ("03_transport.png", ["cumulative_deliveries", "delivery_ratio", "completed_transporter_mean_path_efficiency"]),
        ("04_context.png", ["late_window_mean_phi", "main_channel_width_90", "active_pheromone_area_fraction",
                            "final_forager_count", "final_transporter_count", "final_follower_count",
                            "first_food_discovery_time", "first_successful_delivery_time", "first_pheromone_recruitment_time"]),
    ]
    indexed = index_rows(rows)
    pairs = paired_rows(rows)
    x = np.arange(20)
    for filename, names in groups:
        figure, axes = plt.subplots((len(names) + 1) // 2, 2, figsize=(15, 4.8 * ((len(names) + 1) // 2)), squeeze=False)
        for axis, name in zip(axes.ravel(), names):
            if name in ("delta_psi", "delivery_ratio"):
                values = [p["late_window_mean_psi_delta" if name == "delta_psi" else name] for p in pairs]
                axis.plot(x, [np.nan if v is None else v for v in values], "o")
                for i, v in enumerate(values):
                    if v is None:
                        axis.annotate("unavailable", (i, 0.03), xycoords=("data", "axes fraction"), rotation=90, fontsize=6)
                axis.axhline(0.10 if name == "delta_psi" else 0.80, linestyle="--", color="black")
                if name == "delta_psi":
                    interval = summary["metrics"]["late_window_mean_psi"]["bootstrap"]
                    if interval:
                        axis.axhline(interval["estimate"], color="orange")
                        axis.axhspan(interval["lower"], interval["upper"], alpha=0.15, color="orange")
            else:
                for rule, label in zip(RULES, ("Baseline", "PCA")):
                    values = [value(indexed[s, rule], name) for s in SEEDS]
                    axis.plot(x, [np.nan if v is None else v for v in values], "o-", label=label)
                    for i, v in enumerate(values):
                        if v is None:
                            axis.annotate(label + " unavailable", (i, 0.03), xycoords=("data", "axes fraction"),
                                          rotation=90, fontsize=6)
                if name == "follower_hit_step_mean_axis_error_deg":
                    axis.axhline(35, linestyle="--", color="black")
                axis.legend(fontsize=8)
            axis.set_title(name.replace("_", " "), fontsize=10)
            axis.set_xticks(x, [str(s) for s in SEEDS], rotation=90, fontsize=7)
            axis.grid(alpha=0.2)
        for axis in axes.ravel()[len(names):]:
            axis.set_visible(False)
        title = "SYNTHETIC TEST FIXTURE — NOT SCIENTIFIC RESULTS" if test_fixture else "All 20 preregistered seed pairs; unavailable events remain censored"
        figure.suptitle(title, fontsize=12)
        figure.text(0.5, 0.008, NOTICE, ha="center", fontsize=8)
        figure.tight_layout(rect=(0, 0.03, 1, 0.97))
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", dpi=130)
        plt.close(figure)
        atomic_write(output / filename, buffer.getvalue(), replace=False)
