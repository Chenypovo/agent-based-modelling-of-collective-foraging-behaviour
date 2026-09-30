"""Frozen paired analysis for Stage 3C synthetic tests and future evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import statistics

import numpy as np

from .stage3c import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    CAPPED_RECOVERY_TIME,
    CONFIRMATORY_SEEDS,
    validate_complete_study,
)


REQUIRED_FIELDS = {
    "seed",
    "B0_capped_recovery_time",
    "C_capped_recovery_time",
    "B0_non_delivery",
    "C_non_delivery",
    "B0_pre_A_deliveries",
    "C_pre_A_deliveries",
}


def _inconclusive(errors: list[str]) -> dict:
    return {
        "decision": "INCONCLUSIVE",
        "valid": False,
        "errors": errors,
        "secondary_metrics_used_for_decision": False,
    }


def _validate_rows(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    if len(rows) != len(CONFIRMATORY_SEEDS):
        errors.append("analysis requires exactly 20 paired rows")
    seeds = [row.get("seed") for row in rows]
    if len(seeds) != len(set(seeds)):
        errors.append("duplicate seed")
    if set(seeds) != set(CONFIRMATORY_SEEDS):
        errors.append("missing, additional, or replaced seed")
    for index, row in enumerate(rows):
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            errors.append(f"row {index} missing fields: {sorted(missing)}")
            continue
        for arm in ("B0", "C"):
            value = row[f"{arm}_capped_recovery_time"]
            non_delivery = row[f"{arm}_non_delivery"]
            pre_a = row[f"{arm}_pre_A_deliveries"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"row {index} {arm} capped time is not numeric")
            elif not np.isfinite(value) or not 0 <= value <= CAPPED_RECOVERY_TIME:
                errors.append(f"row {index} {arm} capped time is invalid")
            if not isinstance(non_delivery, (bool, np.bool_)):
                errors.append(f"row {index} {arm} non-delivery is not boolean")
            elif isinstance(value, (int, float)) and bool(non_delivery) != (
                value == CAPPED_RECOVERY_TIME
            ):
                errors.append(f"row {index} {arm} non-delivery/cap mismatch")
            if isinstance(pre_a, bool) or not isinstance(pre_a, (int, np.integer)) or pre_a < 0:
                errors.append(f"row {index} {arm} pre-A deliveries are invalid")
    return errors


def analyse_pairs(rows: list[dict]) -> dict:
    """Apply the preregistered analysis and decision with no alternatives."""
    rows = list(rows)
    errors = _validate_rows(rows)
    if errors:
        return _inconclusive(errors)
    ordered = sorted(rows, key=lambda row: row["seed"])
    b0 = np.asarray([row["B0_capped_recovery_time"] for row in ordered], dtype=float)
    candidate = np.asarray(
        [row["C_capped_recovery_time"] for row in ordered], dtype=float
    )
    deltas = candidate - b0
    pre_b0 = sum(row["B0_pre_A_deliveries"] for row in ordered)
    pre_candidate = sum(row["C_pre_A_deliveries"] for row in ordered)
    if float(b0.mean()) == 0:
        return _inconclusive(["mean B0 capped recovery time is zero"])
    if pre_b0 == 0:
        return _inconclusive(["baseline pre-A denominator is zero"])

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(
        0,
        len(ordered),
        size=(BOOTSTRAP_REPLICATES, len(ordered)),
    )
    bootstrap_means = deltas[indices].mean(axis=1)
    interval = np.percentile(bootstrap_means, [2.5, 97.5], method="linear")
    mean_b0 = float(b0.mean())
    mean_candidate = float(candidate.mean())
    relative_reduction = (mean_b0 - mean_candidate) / mean_b0
    pre_a_ratio = pre_candidate / pre_b0
    thresholds = {
        "mean_reduction_at_least_20_percent": relative_reduction >= 0.20,
        "paired_bootstrap_upper_strictly_below_zero": float(interval[1]) < 0,
        "pre_A_ratio_at_least_0_80": pre_a_ratio >= 0.80,
        "all_40_runs_valid": True,
    }
    decision = "PASS" if all(thresholds.values()) else "FAIL"
    return {
        "decision": decision,
        "valid": True,
        "errors": [],
        "seeds": [row["seed"] for row in ordered],
        "B0": {
            "mean": mean_b0,
            "median": float(statistics.median(b0.tolist())),
            "non_delivery_count": sum(row["B0_non_delivery"] for row in ordered),
        },
        "C": {
            "mean": mean_candidate,
            "median": float(statistics.median(candidate.tolist())),
            "non_delivery_count": sum(row["C_non_delivery"] for row in ordered),
        },
        "delta_time_C_minus_B0": deltas.tolist(),
        "mean_paired_difference": float(deltas.mean()),
        "paired_bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "resampling_unit": "seed pair",
            "percentile_method": "linear",
            "confidence_interval_95": interval.tolist(),
            "replicate_means_sha256": __import__("hashlib").sha256(
                bootstrap_means.tobytes()
            ).hexdigest(),
        },
        "relative_reduction": relative_reduction,
        "pre_A_totals": {"B0": pre_b0, "C": pre_candidate},
        "pre_A_ratio": pre_a_ratio,
        "thresholds": thresholds,
        "secondary_metrics_used_for_decision": False,
    }


def rows_from_study(study_root: Path) -> list[dict]:
    """Load exactly one validated paired row per preregistered seed."""
    validate_complete_study(study_root)
    rows = []
    for seed in CONFIRMATORY_SEEDS:
        summaries = {
            arm: json.loads(
                (study_root / "runs" / str(seed) / arm / "summary.json").read_text()
            )
            for arm in ("B0", "C")
        }
        rows.append(
            {
                "seed": seed,
                "B0_capped_recovery_time": summaries["B0"]["capped_recovery_time"],
                "C_capped_recovery_time": summaries["C"]["capped_recovery_time"],
                "B0_non_delivery": summaries["B0"]["non_delivery"],
                "C_non_delivery": summaries["C"]["non_delivery"],
                "B0_pre_A_deliveries": summaries["B0"][
                    "pre_relocation_A_deliveries"
                ],
                "C_pre_A_deliveries": summaries["C"][
                    "pre_relocation_A_deliveries"
                ],
            }
        )
    return rows


def analyse_study(study_root: Path) -> dict:
    return analyse_pairs(rows_from_study(study_root))


def write_analysis(study_root: Path) -> dict:
    """Write the single frozen analysis only after complete-study validation."""
    rows = rows_from_study(study_root)
    result = analyse_pairs(rows)
    if result["decision"] == "INCONCLUSIVE":
        raise RuntimeError("validated evidence unexpectedly produced INCONCLUSIVE")
    with (study_root / "paired_primary.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (study_root / "confirmatory_analysis.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n"
    )
    return result
