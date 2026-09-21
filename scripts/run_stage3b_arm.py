#!/usr/bin/env python3
"""Run one frozen Stage 3B arm into a fresh evidence directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['MPLBACKEND'] = 'Agg'
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/stage3b_recovery_pilot'
sys.path.insert(0, str(ROOT / 'src'))
from scalar_baseline.functional_validation import SEEDS
from scalar_baseline.stage3b import paired_config, run_arm

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seed', type=int, choices=SEEDS, required=True)
parser.add_argument('--arm', choices=('B0','C'), required=True)
args = parser.parse_args()
if not all(json.loads((OUT / name).read_text())['pass'] for name in
           ('single_change_audit.json','food_coordinate_isolation.json','baseline_prefix_replay.json')):
    parser.error('pre-run audits must pass')
seed_index = SEEDS.index(args.seed)
if args.arm == 'C' and not (OUT / 'runs' / str(args.seed) / 'B0' / 'summary.json').is_file():
    parser.error('paired B0 must complete first')
if seed_index > 0:
    first = OUT / 'runs' / str(SEEDS[0])
    if not all((first / arm / 'summary.json').is_file() for arm in ('B0','C')) or not (OUT / 'first_pair_audit.json').is_file():
        parser.error('first pair audit required before expansion')
    if not json.loads((OUT / 'first_pair_audit.json').read_text())['pass']:
        parser.error('first pair audit failed')
output = OUT / 'runs' / str(args.seed) / args.arm
if output.exists():
    parser.error('existing evidence cannot be overwritten')
source_paths = [ROOT/'docs/STAGE3B_RECOVERY_PILOT_SPEC.md', ROOT/'src/scalar_baseline/stage3b.py',
                ROOT/'scripts/run_stage3b_arm.py', ROOT/'tests/test_stage3b_recovery.py']
manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
(OUT/f'prerun_source_{args.seed}_{args.arm}.json').write_text(json.dumps(manifest, indent=2)+'\n')
result = run_arm(output, paired_config(args.seed), args.arm,
                 retain_events=args.seed == SEEDS[0])
print(json.dumps(result, indent=2))
raise SystemExit(0 if result['status'] == 'complete' else 1)
