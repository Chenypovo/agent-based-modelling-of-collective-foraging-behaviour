#!/usr/bin/env python3
"""Stage 3C gated runner. Stage 3C-E must invoke dry-run only."""

from __future__ import annotations

import argparse
import hashlib
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
    EvidenceError,
    FORMAL_RESULTS_RELATIVE,
    confirmatory_config,
    create_first_pair_engineering_receipt,
    initialise_prerun_engineering_audit,
    initialise_study_protection,
    run_arm_atomic,
    schedule_prefix_audit,
    validate_expansion_authorisation,
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


def first_pair(
    study_root: Path,
    *,
    pair_configs=None,
    identity_provider=None,
) -> dict:
    kwargs = {"identity_provider": identity_provider} if identity_provider else {}
    configs = pair_configs or {
        arm: confirmatory_config(CONFIRMATORY_SEEDS[0], arm) for arm in ARMS
    }
    protection_before = initialise_study_protection(study_root, ROOT)
    if not protection_before["pass"]:
        raise EvidenceError("protected-file validation failed before first pair")
    initialise_prerun_engineering_audit(study_root, ROOT, **kwargs)
    seed = configs["B0"].seed
    arms = {}
    for arm in ARMS:
        arms[arm] = run_arm_atomic(
            study_root,
            configs[arm],
            ROOT,
            retain_observations=False,
            **kwargs,
        )
    protection_after = verify_study_protection(study_root, ROOT)
    if not protection_after["pass"]:
        raise EvidenceError("protected-file validation failed after first pair")
    receipt = create_first_pair_engineering_receipt(
        study_root, ROOT, pair_configs=configs, **kwargs
    )
    return {
        **receipt,
        "first_pair_engineering_receipt_sha256": (
            hashlib.sha256(
                (study_root / "first_pair_engineering_receipt.json").read_bytes()
            ).hexdigest()
        ),
    }


def remaining(study_root: Path) -> dict:
    gate = validate_expansion_authorisation(study_root, ROOT)
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
