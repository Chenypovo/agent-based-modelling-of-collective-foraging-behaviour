#!/usr/bin/env python3
"""One fixed functional-validation seed, without relocation or optimisation."""

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
from scalar_baseline.functional_validation import SEEDS, research_config, run_seed

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--seed", type=int, choices=SEEDS, required=True)
args = parser.parse_args()
base = ROOT / "results/stage3a_functional_validation"
output = base / "original" / str(args.seed)
if args.seed != SEEDS[0]:
    pilot = json.loads((base / "original" / str(SEEDS[0]) / "summary.json").read_text())
    if not pilot["functional_success"]:
        parser.error("first fixed pilot did not pass; expansion prohibited")
if output.exists():
    parser.error("existing seed evidence cannot be overwritten")
manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src/scalar_baseline").glob('*.py'))}
manifest['docs/STAGE3A_FUNCTIONAL_VALIDATION_PROTOCOL.md'] = hashlib.sha256((ROOT / 'docs/STAGE3A_FUNCTIONAL_VALIDATION_PROTOCOL.md').read_bytes()).hexdigest()
(base / f"prerun_sources_{args.seed}.json").write_text(json.dumps(manifest, indent=2) + "\n")
result = run_seed(output, research_config(args.seed))
raise SystemExit(0 if result['status'] == 'complete' else 1)
