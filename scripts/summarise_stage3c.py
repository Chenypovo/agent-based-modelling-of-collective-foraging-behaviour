#!/usr/bin/env python3
"""Run the frozen Stage 3C analysis after all 40 arms validate."""

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

from scalar_baseline.stage3c import FORMAL_RESULTS_RELATIVE  # noqa: E402
from scalar_baseline.stage3c_analysis import write_analysis  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--study-root", type=Path, default=ROOT / FORMAL_RESULTS_RELATIVE
    )
    args = parser.parse_args(argv)
    result = write_analysis(args.study_root)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
