#!/usr/bin/env python3
"""Gated Stage 3D matched-lifetime decay-law runner."""

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

from scalar_baseline.stage3d import (  # noqa: E402
    FORMAL_RESULTS_RELATIVE,
    dry_run,
    run_all,
    validate_complete_study,
)
from scalar_baseline.stage3d_analysis import write_analysis  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dry-run", "run", "validate", "analyse"))
    parser.add_argument(
        "--study-root", type=Path, default=ROOT / FORMAL_RESULTS_RELATIVE,
        help="formal Stage 3D evidence root; tests must use a temporary path",
    )
    args = parser.parse_args(argv)
    if args.mode == "dry-run":
        result = dry_run(ROOT)
    elif args.mode == "run":
        result = run_all(args.study_root, ROOT)
    elif args.mode == "validate":
        result = {"mode": "validate", "validation": validate_complete_study(args.study_root, ROOT)}
    else:
        validate_complete_study(args.study_root, ROOT)
        result = {"mode": "analyse", "analysis": write_analysis(args.study_root, ROOT)}
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
