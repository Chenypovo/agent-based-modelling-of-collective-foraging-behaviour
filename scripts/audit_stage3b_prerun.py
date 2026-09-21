#!/usr/bin/env python3
"""Pre-run single-change, identity, isolation and B0 prefix replay gates."""

from dataclasses import asdict
import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import textwrap
import numpy as np

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['MPLBACKEND'] = 'Agg'
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/stage3b_recovery_pilot'
sys.path.insert(0, str(ROOT / 'src'))

from scalar_baseline.functional_validation import ObservedSimulation
from scalar_baseline.stage3b import (PairedB0Simulation, RecoverySimulation,
                                     paired_config, state_digest)
import scalar_baseline.stage3b as stage3b


def digest(value) -> str:
    return hashlib.sha256(value).hexdigest()


def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


seed = 2026091701
config = paired_config(seed)
b0, candidate = PairedB0Simulation(config), RecoverySimulation(config)
shared = {
    'initial_agents': [asdict(a) for a in b0.ants] == [asdict(a) for a in candidate.ants],
    'initial_field': bool((b0.field.concentration == candidate.field.concentration).all()),
    'FCRW_schedule': np.array_equal(b0._turns, candidate._turns),
    'follower_noise_schedule': np.array_equal(b0._noise, candidate._noise),
    'recovery_side_schedule': bool((b0._recovery_sides == candidate._recovery_sides).all()),
    'environment': (b0.environment._nest, b0.environment._sources, b0.environment._radius,
                    b0.environment._relocation_step) ==
                   (candidate.environment._nest, candidate.environment._sources, candidate.environment._radius,
                    candidate.environment._relocation_step),
    'pheromone': asdict(b0.config.decay) == asdict(candidate.config.decay),
    'configuration': asdict(b0.config) == asdict(candidate.config),
}
single = {'pass': all(shared.values()), 'seed': seed, 'shared_identity': shared,
          'only_mechanism_difference': 'C replaces follower loss-to-FCRW branch with frozen finite recovery; B0 does not read side schedule',
          'B0_recovery_side_reads_in_movement': '_recovery_sides' in inspect.getsource(PairedB0Simulation._move),
          'B0_source_class': 'ObservedSimulation unchanged at commit 658e394',
          'C_recovery_duration': 24}
single['pass'] = single['pass'] and not single['B0_recovery_side_reads_in_movement']
write('single_change_audit.json', single)

tree = ast.parse(textwrap.dedent(inspect.getsource(stage3b.RecoverySimulation)))
names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
hits = sorted(names & {'food_a', 'food_b', 'food_contact', 'environment', 'direction_sum',
                       'mean_direction', 'gradient', 'argmax', 'source_identity'})
# environment/food_contact appear only in inherited contact processing, not _move.
move_tree = ast.parse(textwrap.dedent(inspect.getsource(stage3b.RecoverySimulation._move)))
move_names = {n.id for n in ast.walk(move_tree) if isinstance(n, ast.Name)}
move_names |= {n.attr for n in ast.walk(move_tree) if isinstance(n, ast.Attribute)}
move_hits = sorted(move_names & {'food_a', 'food_b', 'food_contact', 'environment', 'direction_sum',
                                 'mean_direction', 'gradient', 'argmax', 'source_identity'})
isolation = {'pass': not move_hits and config.diffusion == 0,
             'recovery_move_prohibited_identifier_hits': move_hits,
             'whole_class_expected_contact_or_metric_hits': hits,
             'field_slots': list(b0.field.__slots__), 'diffusion': config.diffusion,
             'local_samples_per_recovery_step': 2,
             'limitations': 'Scoped structural audit plus tests; food coordinates remain in environment contacts/offline metrics.'}
write('food_coordinate_isolation.json', isolation)

from dataclasses import replace
static = ObservedSimulation(replace(config, relocation_step=None))
relocating = PairedB0Simulation(config)
for _ in range(5999):
    static.step(); relocating.step()
digest_static, digest_reloc = state_digest(static), state_digest(relocating)
stage3a_events = json.loads((ROOT / f'results/stage3a_functional_validation/original/{seed}/events.json').read_text())
old_prefix = [e for e in stage3a_events if e['time'] <= 5999]
canonical_static = json.loads(json.dumps(static.observations))
canonical_relocating = json.loads(json.dumps(relocating.observations))
replay = {'pass': digest_static == digest_reloc and canonical_static == canonical_relocating
                 and canonical_static == old_prefix,
          'seed': seed, 'compared_through_step': 5999,
          'static_current_digest': digest_static, 'relocation_B0_digest': digest_reloc,
          'current_observation_count': len(static.observations),
          'stage3a_prefix_count': len(old_prefix),
          'current_vs_relocation_observations_equal': canonical_static == canonical_relocating,
          'current_vs_stage3a_observations_equal': canonical_static == old_prefix,
          'random_identity': {k: shared[k] for k in ('FCRW_schedule','follower_noise_schedule','recovery_side_schedule')}}
write('baseline_prefix_replay.json', replay)
print(json.dumps({'single_change': single['pass'], 'isolation': isolation['pass'],
                  'prefix_replay': replay['pass']}, indent=2))
raise SystemExit(0 if single['pass'] and isolation['pass'] and replay['pass'] else 1)
