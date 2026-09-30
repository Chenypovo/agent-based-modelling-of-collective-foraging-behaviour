#!/usr/bin/env python3
"""Run only the five fixed Stage 3A engineering fixtures into a fresh directory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["MPLBACKEND"] = "Agg"
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalar_baseline.pilot import run_pilots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results/stage3a_scalar_baseline/pilot")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    protected = [ROOT / name for name in (".git", "src", "tests", "scripts", "docs", ".tmp_progress_report", "from_prof", "reports")]
    protected += [p for p in (ROOT / "results").iterdir() if p.name != "stage3a_scalar_baseline"]
    if output == ROOT or any(output == p or p in output.parents for p in protected):
        parser.error("output cannot be inside a protected tree")
    if output.exists():
        parser.error("output must be a fresh directory; existing evidence is never overwritten")
    start = time.perf_counter()
    outputs, timings = run_pilots()
    output.mkdir(parents=True)
    sizes = {}
    for name, data in outputs.items():
        path = output / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
        sizes[path.name] = path.stat().st_size
    runtime = {"purpose": "engineering validation only", "seconds_by_fixture": timings,
               "total_seconds_including_output": time.perf_counter() - start,
               "artifact_bytes_excluding_this_runtime_file": sum(sizes.values()), "files": sizes,
               "formal_experiment_runs": 0, "recovery_C_implemented": False}
    (output / "runtime.json").write_text(json.dumps(runtime, indent=2) + "\n")
    print(json.dumps(runtime, indent=2))


if __name__ == "__main__":
    main()
