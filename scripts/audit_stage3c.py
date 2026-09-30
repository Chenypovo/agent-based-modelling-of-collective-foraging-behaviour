#!/usr/bin/env python3
"""Build Stage 3C engineering audits with non-confirmatory fixtures only."""

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

from scalar_baseline.stage3c import prerun_engineering_audit  # noqa: E402


def build_audit(include_replay: bool = True) -> dict:
    audits = prerun_engineering_audit(ROOT)
    if not include_replay:
        audits.pop("B0_replay")
        audits["scope"]["fixture_simulation_steps_executed"] = 0
    return audits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-replay", action="store_true")
    args = parser.parse_args(argv)
    result = build_audit(include_replay=not args.skip_replay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
