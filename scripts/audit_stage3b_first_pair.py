#!/usr/bin/env python3
"""Gate expansion after the frozen first B0/C pair."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/stage3b_recovery_pilot'
seed = 2026091701


def read(path):
    return json.loads(path.read_text())


b0 = read(OUT / f'runs/{seed}/B0/summary.json')
c = read(OUT / f'runs/{seed}/C/summary.json')
old = read(ROOT / f'results/stage3a_functional_validation/original/{seed}/summary.json')
b0_events = read(OUT / f'runs/{seed}/B0/ledger_events.json')
old_ledger = read(ROOT / f'results/stage3a_functional_validation/original/{seed}/ledger.json')['events']
old_prefix = [e for e in old_ledger if e['time'] < 6000]
new_prefix = [e for e in b0_events if e['time'] < 6000]
checks = {
    'B0_complete': b0['status'] == 'complete' and b0['steps_completed'] == 12000,
    'C_complete': c['status'] == 'complete' and c['steps_completed'] == 12000,
    'B0_pre_relocation_ledger_matches_Stage3A': new_prefix == old_prefix,
    'B0_first_A_discovery_matches_Stage3A': b0['first_A_discovery'] == old['first_discovery']['time'],
    'B0_first_A_delivery_matches_Stage3A': b0['first_A_delivery'] == old['first_delivery']['time'],
    'C_recovery_triggered': c['recovery_episodes'] > 0,
    'C_episode_partition': c['recovery_episodes'] == c['recovery_reacquired'] + c['recovery_timeouts'] + c['recovery_food_contacts'],
    'no_anchor_fallback': c['anchor_fallbacks'] == 0,
    'resource_limits': all(x['wall_seconds'] < 600 and x['cpu_seconds'] < 600 and x['peak_rss_bytes'] < 2*1024**3 for x in (b0,c)),
    'prerun_single_change': read(OUT/'single_change_audit.json')['pass'],
    'prerun_prefix_replay': read(OUT/'baseline_prefix_replay.json')['pass'],
    'prerun_isolation': read(OUT/'food_coordinate_isolation.json')['pass'],
}
storage_targets = {}
for arm in ('B0','C'):
    folder = OUT / f'runs/{seed}/{arm}'
    storage_targets[f'{arm}_output_under_10MiB_target'] = sum(p.stat().st_size for p in folder.iterdir() if p.is_file()) < 10*1024**2
    checks[f'{arm}_files_under_50MiB'] = all(p.stat().st_size < 50*1024**2 for p in folder.iterdir() if p.is_file())
result = {'pass': all(checks.values()), 'seed': seed, 'checks': checks,
          'advisory_storage_targets': storage_targets,
          'descriptive_first_pair': {'B0': b0, 'C': c},
          'expansion_authorised_by_protocol': all(checks.values())}
(OUT/'first_pair_audit.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
print(json.dumps({'pass':result['pass'],'checks':checks},indent=2))
raise SystemExit(0 if result['pass'] else 1)
