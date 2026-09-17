#!/usr/bin/env python3
"""Post-run evidence summary. Does not run or modify a simulation."""

import csv
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ['MPLBACKEND'] = 'Agg'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/stage3a_functional_validation'
sys.path.insert(0, str(ROOT / 'src'))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from scalar_baseline.functional_validation import SEEDS


def sha256(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            sha.update(block)
    return sha.hexdigest()


def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


rows, summaries, episode_lengths = [], [], []
for seed in SEEDS:
    folder = OUT / 'original' / str(seed)
    s = json.loads((folder / 'summary.json').read_text())
    summaries.append(s)
    first = json.loads((folder / 'first_delivery_field_metrics.json').read_text())
    events = json.loads((folder / 'events.json').read_text())
    arrivals = [e for e in events if e['event'] == 'pickup' and e['role_before_contact'] == 'follower']
    lengths = [e['follower_episode']['duration_steps'] for e in arrivals]
    episode_lengths.extend(lengths)
    rows.append({'seed': seed, 'first_discovery_step': s['first_discovery']['time'],
                 'first_delivery_step': s['first_delivery']['time'],
                 'first_pheromone_recruitment_step': s['first_raw_recruitment']['time'],
                 'first_verified_recruitment_step': s['first_verified_recruitment']['time'],
                 'first_follower_food_arrival_step': s['first_follower_food_arrival']['time'],
                 'discoveries': sum(s['discoveries'].values()), 'deliveries': sum(s['deliveries'].values()),
                 'raw_recruitment_episodes': s['raw_recruitments'], 'verified_recruitment_episodes': s['verified_recruitments'],
                 'unique_verified_recruits': s['unique_verified_recruits'],
                 'follower_food_arrivals': len(arrivals),
                 'arrival_episodes_at_least_10_steps_posthoc': sum(n >= 10 for n in lengths),
                 'max_arrival_episode_steps': max(lengths),
                 'first_return_route_fraction_on': first['first_pickup_ant_route']['on']['detectable_fraction'],
                 'first_return_route_fraction_off': first['first_pickup_ant_route']['off']['detectable_fraction'],
                 'first_return_route_max_gap_on': first['first_pickup_ant_route']['on']['longest_undetectable_run_points'],
                 'first_return_route_max_gap_off': first['first_pickup_ant_route']['off']['longest_undetectable_run_points'],
                 'final_centre_connectivity_on': s['final_field']['on']['nest_food_centre_cells_connected_8'],
                 'final_centre_connectivity_off': s['final_field']['off']['nest_food_centre_cells_connected_8'],
                 'cpu_seconds': s['cpu_seconds'], 'wall_seconds': s['wall_seconds'], 'peak_rss_bytes': s['peak_rss_bytes'],
                 'stored_bytes': sum(p.stat().st_size for p in folder.iterdir() if p.is_file()),
                 'complete_and_valid': s['status'] == 'complete' and s['valid_state_every_completed_step']})
with (OUT / 'per_seed_metrics.csv').open('w') as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)

before = json.loads((OUT / 'protected_before.json').read_text())
missing = [name for name in before['files'] if not (ROOT / name).is_file()]
changed = [name for name, sha in before['files'].items() if name not in missing and sha256(ROOT / name) != sha]
protected_roots = [ROOT / p for p in ('.tmp_progress_report', 'from_prof', 'reports')]
protected_roots += [p for p in (ROOT / 'results').iterdir() if p.is_dir() and p != OUT]
added = [str(p.relative_to(ROOT)) for folder in protected_roots for p in folder.rglob('*')
         if p.is_file() and str(p.relative_to(ROOT)) not in before['files']]
write('protected_check.json', {'pass': not (missing or changed or added), 'count': len(before['files']),
                               'missing': missing, 'changed': changed, 'new_protected_files': added})
frozen = json.loads((ROOT / 'results/stage3a_scalar_baseline/stage3a_source_sha256.json').read_text())
identity = {name: sha256(ROOT / name) == sha for name, sha in frozen.items()}
write('isolation_audit.json', {'pass': all(identity.values()), 'frozen_source_matches': identity,
                              'observer_equivalence_tests': ['test_observer_does_not_change_dynamics', 'test_observer_records_actual_follower_contact_and_delivery'],
                              'food_coordinates_used_only_for': 'original environment contacts and post-movement/offline metrics',
                              'source_identity_in_scalar_field': False,
                              'verified_recruitment_definition': 'fcrw->follower with S>=on in an ant that has never deposited; zero-signal counterfactual remains fcrw',
                              'counterfactual_limitation': 'role triggering only; not evidence for improved food acquisition over a no-pheromone control'})
max_cpu = max(r['cpu_seconds'] for r in rows)
max_wall = max(r['wall_seconds'] for r in rows)
max_disk = max(r['stored_bytes'] for r in rows)
resources = {'total_cpu_seconds': sum(r['cpu_seconds'] for r in rows),
             'sum_wall_seconds': sum(r['wall_seconds'] for r in rows),
             'total_seed_output_bytes': sum(r['stored_bytes'] for r in rows),
             'max_seed_cpu_seconds': max_cpu, 'max_seed_wall_seconds': max_wall,
             'max_seed_output_bytes': max_disk, 'max_peak_rss_bytes': max(r['peak_rss_bytes'] for r in rows),
             'projection_basis': '2 * pairs * maximum measured B0 cost; no C overhead included; sequential execution',
             'five_pair_projection': {'cpu_seconds': 10 * max_cpu, 'wall_seconds': 10 * max_wall, 'bytes': 10 * max_disk},
             'twenty_pair_projection': {'cpu_seconds': 40 * max_cpu, 'wall_seconds': 40 * max_wall, 'bytes': 40 * max_disk},
             'future_paired_experiments_authorised': False}
write('resource_summary.json', resources)
counts = {'discovery_and_delivery_seeds': sum(r['discoveries'] > 0 and r['deliveries'] > 0 for r in rows),
          'verified_recruitment_seeds': sum(r['unique_verified_recruits'] > 0 for r in rows),
          'follower_arrival_seeds': sum(r['follower_food_arrivals'] > 0 for r in rows),
          'complete_valid_seeds': sum(r['complete_and_valid'] for r in rows)}
resources_pass = (max_cpu < 600 and max_wall < 600 and max_disk < 512 * 1024 ** 2
                  and resources['max_peak_rss_bytes'] < 2 * 1024 ** 3
                  and 10 * max_cpu <= 7200 and 10 * max_disk <= 2 * 1024 ** 3)
gate = {'minimum_functional_gate_pass': counts['discovery_and_delivery_seeds'] >= 4 and counts['verified_recruitment_seeds'] >= 4
         and counts['complete_valid_seeds'] == 5 and resources_pass and all(identity.values()) and not (missing or changed or added),
        **counts, 'resources_pass': resources_pass, 'baseline_revisions': 0, 'recovery_C': False,
        'relocation_runs': 0, 'stage3b_started': False,
        'follower_arrival_episode_steps': {'min': min(episode_lengths), 'median': float(np.median(episode_lengths)), 'max': max(episode_lengths)},
        'limitation': 'Passing the stated minimum gate does not establish continuous nest-to-food following or scientific pheromone benefit. Full regression test receipt is separate.'}
write('gate.json', gate)

fig, axes = plt.subplots(2, 3, figsize=(13, 8), constrained_layout=True)
for ax, row in zip(axes.flat, rows):
    folder = OUT / 'original' / str(row['seed'])
    field = np.load(folder / 'field_final.npz')['concentration']
    image = ax.imshow(np.ma.masked_less(field.T, 0.25), origin='lower', extent=(0, 300, 0, 300),
                      cmap='YlOrBr', vmin=0.25, vmax=5, interpolation='nearest')
    ax.scatter([150, 240], [150, 150], c=['#2467A6', '#B63D3D'], marker='o', s=28)
    ax.annotate('Nest', (150, 150), xytext=(-30, 9), textcoords='offset points', fontsize=8)
    ax.annotate('A', (240, 150), xytext=(5, 8), textcoords='offset points', fontsize=8)
    ax.set_title(f"{row['seed']} | deliveries {row['deliveries']} | follower arrivals {row['follower_food_arrivals']}", fontsize=9)
    ax.set(xlim=(0, 300), ylim=(0, 300), xlabel='x', ylabel='y')
axes.flat[-1].axis('off')
axes.flat[-1].text(0, 0.95, 'Exponential B0: fixed exploratory seeds\n\nN=100, L=300, 12,000 steps\nHalf-life=1,000 steps; diffusion=0\n\nFinal cells with concentration >= 0.25\nNo relocation; no recovery C\n\n5/5 discovery + delivery\n5/5 verified recruitment\n5/5 follower food contact\n\nMinimum gate only:\nnot proof of end-to-end trail following.', va='top', fontsize=11)
fig.colorbar(image, ax=list(axes.flat[:5]), shrink=0.7, label='Scalar concentration (colour saturated at 5)')
fig.savefig(OUT / 'final_scalar_fields.png', dpi=170)
plt.close(fig)
print(json.dumps({'gate': gate, 'resources': resources}, indent=2))
