#!/usr/bin/env python3
"""Stage 3C gated runner. Stage 3C-E must invoke dry-run only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["MPLBACKEND"] = "Agg"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalar_baseline.stage3c import (  # noqa: E402
    ARMS,
    CONFIRMATORY_SEEDS,
    FORMAL_RESULTS_RELATIVE,
    confirmatory_config,
    create_first_pair_engineering_receipt,
    initialise_prerun_engineering_audit,
    initialise_study_protection,
    run_arm_atomic,
    schedule_prefix_audit,
    validate_first_pair_engineering_receipt,
    validate_prerun_engineering_audit,
    verify_study_protection,
)
from scalar_baseline.stage3c_analysis import write_analysis  # noqa: E402


def dry_run() -> dict:
    """Validate the frozen plan without constructing a simulation."""
    configurations = [
        confirmatory_config(seed, arm).as_record()
        for seed in CONFIRMATORY_SEEDS
        for arm in ARMS
    ]
    return {
        "mode": "dry-run",
        "simulation_initialised": False,
        "simulation_steps_executed": 0,
        "confirmatory_seeds_run": 0,
        "configurations_validated": len(configurations),
        "seed_order": list(CONFIRMATORY_SEEDS),
        "arm_order": list(ARMS),
        "schedule_prefix_audit": schedule_prefix_audit(),
        "formal_results_directory_created": (ROOT / FORMAL_RESULTS_RELATIVE).exists(),
    }


def first_pair(study_root: Path) -> dict:
    protection_before = initialise_study_protection(study_root, ROOT)
    engineering_gate = initialise_prerun_engineering_audit(study_root, ROOT)
    seed = CONFIRMATORY_SEEDS[0]
    arms = {}
    for arm in ARMS:
        arms[arm] = run_arm_atomic(
            study_root,
            confirmatory_config(seed, arm),
            ROOT,
            retain_observations=False,
        )
    protection_after = verify_study_protection(study_root, ROOT)
    receipt = create_first_pair_engineering_receipt(study_root, ROOT)
    return {"mode": "first-pair", "seed": seed, "engineering_gate": engineering_gate,
            "arms": arms,
            "protection_before": protection_before, "protection_after": protection_after,
            "receipt": receipt}


def remaining(study_root: Path) -> dict:
    validate_prerun_engineering_audit(study_root, ROOT)
    gate = validate_first_pair_engineering_receipt(study_root, ROOT)
    completed = []
    for seed in CONFIRMATORY_SEEDS[1:]:
        for arm in ARMS:
            run_arm_atomic(
                study_root,
                confirmatory_config(seed, arm),
                ROOT,
                retain_observations=False,
            )
            completed.append({"seed": seed, "arm": arm})
    protection = verify_study_protection(study_root, ROOT)
    return {"mode": "remaining", "gate": gate, "completed": completed,
            "protection": protection}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dry-run", "first-pair", "remaining", "analyse"))
    parser.add_argument(
        "--study-root",
        type=Path,
        default=ROOT / FORMAL_RESULTS_RELATIVE,
        help="formal evidence root; tests must pass a temporary path",
    )
    args = parser.parse_args(argv)

    if args.mode == "dry-run":
        result = dry_run()
    elif args.mode == "first-pair":
        result = first_pair(args.study_root)
    elif args.mode == "remaining":
        result = remaining(args.study_root)
    else:
        validate_prerun_engineering_audit(args.study_root, ROOT)
        verify_study_protection(args.study_root, ROOT)
        result = {"mode": "analyse", "analysis": write_analysis(args.study_root)}
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
