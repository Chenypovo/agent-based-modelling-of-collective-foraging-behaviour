"""Resource-only amendment, execution lineage and explicit immutable migration.

No simulation constructor, step, endpoint calculator or scientific analyser is used.
"""
from __future__ import annotations

import ast
import fcntl
import io
import json
import math
import os
import tempfile
import time
import zipfile
from copy import deepcopy
from pathlib import Path

from .stage2c_checkpoint import (atomic_write, behavioural_config, digest_bytes,
    hash_value, json_bytes, load_checkpoint, read_json)
from .stage2c_storage import sha256_file

OLD_COMMIT = '51504fa4156042f1fbc7468c4db26a64dd16d527'
AMENDMENT_PATH = 'docs/STAGE2C_RESOURCE_AMENDMENT.md'
ORIGINAL_TIME_LIMIT = 14400.0
EFFECTIVE_TIME_LIMIT = 28800.0
POLICY = dict(original_time_limit_seconds=ORIGINAL_TIME_LIMIT,
              effective_time_limit_seconds=EFFECTIVE_TIME_LIMIT,
              storage_limit_bytes=2_000_000_000, safety_factor=1.5,
              amendment_before_pca_initialisation=True)
ATTEMPT = 'resource_amendments/attempt-01'
ADMIN = ('config_manifest.json', 'checkpoint/progress_manifest.json', 'seed_manifest.json',
         'storage_preflight.json', 'runtime.json', 'engineering_validation.json',
         'per_seed_metrics.csv', 'paired_comparison.csv')
E2_INTENT_SHA = '4d029590e7c71177630286fb93ef5e6768df85ea25e62bac618cf6179d5f83df'
E2_RECEIPT_SHA = '7dd96aa1df1ec11d60d6b07fb83305e7a275b52d5f58b6c4a6470555db7870a4'
BASELINE_ATTEMPTS = [{'start_time_step': 0, 'status': 'interrupted'},
                     {'start_time_step': 9500, 'status': 'completed'}]
# This is the sole administrative compatibility change in the checkpoint module.
OLD_SHARED_GUARD = '''        if metadata.get("identity_hash") != hash_value(_identity_binding(identity)):
            raise ValueError("shared seed artifact identity mismatch")'''
NEW_SHARED_GUARD = '''        if metadata.get("identity_hash") != hash_value(_identity_binding(identity)):
            from .stage2c_amendment import verify_legacy_shared_identity
            verify_legacy_shared_identity(Path(path), config, identity, metadata, checksum)'''


def amendment_evidence(root: Path | None = None) -> dict:
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    raw = (root / AMENDMENT_PATH).read_bytes()
    declared = json.loads(raw.decode().split('<!-- resource-policy -->')[1].split('<!-- /resource-policy -->')[0])
    if declared != POLICY:
        raise ValueError('resource amendment declaration differs from effective policy')
    return dict(POLICY, path=AMENDMENT_PATH, sha256=digest_bytes(raw))


def _json(raw):
    return json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def _hashes(payload):
    return {n: {'bytes': len(v), 'sha256': digest_bytes(v)} for n, v in sorted(payload.items())}


def _inventory(output):
    return {p.relative_to(output).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha256_file(p)}
            for p in sorted(output.rglob('*')) if p.is_file()}


def _verify_files(output, expected):
    for name, value in expected.items():
        p = output / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size != value['bytes'] or sha256_file(p) != value['sha256']:
            raise ValueError('immutable study evidence changed: ' + name)


def _zip(payload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, raw in sorted(payload.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o600 << 16
            z.writestr(info, raw, compresslevel=9)
    return buffer.getvalue()


def _unzip(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if len(z.namelist()) != len(set(z.namelist())) or sum(i.file_size for i in z.infolist()) > 1_000_000_000:
            raise ValueError('invalid migration archive')
        return {name: z.read(name) for name in z.namelist()}


def _once(path, raw):
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('immutable amendment transaction differs')
    else:
        atomic_write(path, raw, replace=False)


def _fsync(path):
    fd = os.open(str(path), os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _require_committed(root, identity):
    from .stage2c import git
    from .stage2c_repair import _committed_sources
    if (not identity['runner_worktree_clean'] or git(root, 'rev-parse', 'HEAD').decode().strip() != identity['runner_commit']
            or dict(_committed_sources(root, identity['runner_commit'])) != identity['source_hashes']):
        raise ValueError('resource migration requires committed clean code')


def scientific_equivalence(root, old, current):
    """Compare actual old Git blobs; never infer scientific equivalence from labels."""
    from .stage2c import git
    from .stage2c_repair import _old_identity
    if old['runner_commit'] != OLD_COMMIT:
        raise ValueError('only the recorded E3 execution identity can migrate')
    _old_identity(root, old, current)
    checked = {}
    for name in ('src/colony/stage2c_analysis.py', 'src/colony/stage2c_streaming.py',
                 'src/colony/stage2c_storage.py', 'src/colony/stage2c_checkpoint.py'):
        original = git(root, 'show', OLD_COMMIT + ':' + name)
        actual = (root / name).read_bytes()
        if name.endswith('stage2c_checkpoint.py'):
            actual = actual.decode().replace(NEW_SHARED_GUARD, OLD_SHARED_GUARD).encode()
        if original != actual:
            raise ValueError('scientific/metric/checkpoint definition changed: ' + name)
        checked[name] = digest_bytes(original)
    old_tree = ast.parse(git(root, 'show', OLD_COMMIT + ':src/colony/stage2c.py'))
    new_tree = ast.parse((root / 'src/colony/stage2c.py').read_bytes())
    for name in ('run_one', '_publish_checkpoint', '_write_completed', '_bind_completed_entry',
                 '_completed_record', '_artifact_hashes', 'config_pair', 'audit_pair', 'new_progress'):
        def body(tree):
            return ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), include_attributes=False)
        if body(old_tree) != body(new_tree):
            raise ValueError('scientific runner behaviour changed: ' + name)
        checked['runner:' + name] = digest_bytes(body(old_tree).encode())
    return dict(checked_definitions=checked, sha256=hash_value(checked),
                preregistration_hash=current['preregistration_hash'], input_hash=current['input_hash'],
                frozen_source_hashes=current['frozen_source_hashes'])


def _lineage(old, new, runs, proof):
    if old['runner_commit'] == new['runner_commit']:
        raise ValueError('resource amendment must have a new committed identity')
    return {'identities': {old['runner_commit']: old, new['runner_commit']: new},
            'runs': [{'seed': e['seed'], 'rule': e['rule'],
                      'execution_commit': old['runner_commit'] if i == 0 else new['runner_commit']}
                     for i, e in enumerate(runs)], 'scientific_equivalence': proof}


def _validate_state(payload, output, identity, *, old=True):
    from . import stage2c as r
    from .stage2c_analysis import seed_manifest
    p = _json(payload['checkpoint/progress_manifest.json'])
    if p['identity'] != identity or len(p['runs']) != 40 or p['study_state'] != 'paused':
        raise ValueError('migration requires the paused 40-run study')
    config = [c for s in r.SEEDS for c in r.config_pair(s, output)]
    expected = r.new_progress(identity)['runs']
    b = p['runs'][0]
    if (b['seed'] != expected[0]['seed'] or b['rule'] != expected[0]['rule'] or b['status'] != 'completed'
            or b['time'] != config[0].steps or b['attempts'] != BASELINE_ATTEMPTS
            or p['runs'][1:] != expected[1:] or b['elapsed_seconds'] != 250.956673666):
        raise ValueError('requires exact completed Baseline and 39 uninitialised planned runs')
    manifest = _json(payload['config_manifest.json'])
    entries = [{'seed': c.seed, 'rule': c.follower_direction_rule,
                'config': dict(behavioural_config(c), output_dir=c.output_dir),
                'config_hash': hash_value(behavioural_config(c))} for c in config]
    initial = [{'seed': e['seed'], 'rule': e['rule'],
                'initial_state_hash': (e['initial_identity'] or {}).get('initial_state_hash'),
                'turn_schedule_hash': (e['initial_identity'] or {}).get('turn_schedule_hash'),
                'availability': 'available' if e['initial_identity'] else 'unavailable',
                'reason': '' if e['initial_identity'] else 'not_initialised'} for e in p['runs']]
    if (manifest['identity'] != identity or manifest['configurations'] != entries
            or manifest['late_window'] != [9000, 10000] or manifest['dry_run'] is not False
            or manifest['initialisation_hashes'] != initial
            or manifest['pair_audits'] != [r.audit_pair(*r.config_pair(s, output)) for s in r.SEEDS]
            or _json(payload['seed_manifest.json']) != seed_manifest()):
        raise ValueError('seed/rule/configuration/initial identity mismatch')
    storage = _json(payload['storage_preflight.json'])
    if (storage['source_hash'] != identity['source_hash'] or storage['simulation_steps_executed'] != 0
            or storage['scientific_seed_used'] is not False or storage['storage_fixture_seed'] != 991337):
        raise ValueError('invalid storage-only preflight')
    if old:
        runtime = _json(payload['runtime.json'])
        if (runtime['action'] != 'pause' or runtime['reasons'] != ['four_hour_limit']
                or runtime['time_limit_seconds'] != ORIGINAL_TIME_LIMIT or runtime['remaining_runs'] != 39
                or runtime['current_machine_pilot_observed'] is not False
                or runtime['storage_limit_bytes'] != 2_000_000_000 or runtime['safety_factor'] != 1.5
                or runtime['storage_only_preflight'] != storage):
            raise ValueError('requires the original four-hour resource pause')
    if not math.isfinite(p['elapsed_seconds']) or p['elapsed_seconds'] < 0:
        raise ValueError('invalid elapsed accounting')
    return p, config


def _baseline(output, progress, config, old):
    """Read only configuration/receipt/integrity; result values are opaque bytes."""
    run = Path(config.output_dir); complete = run / 'completed'; e = progress['runs'][0]
    receipt = read_json(complete / 'receipt.json')
    actual = {p.relative_to(complete).as_posix(): sha256_file(p)
              for p in complete.rglob('*') if p.is_file() and p.name != 'receipt.json'}
    required = {'agent_states.csv', 'completed_transport.csv', 'config.json', 'diagnostic_accumulators.json',
                'events.csv', 'final_agents.csv', 'final_checkpoint.zip', 'final_pheromone.npz',
                'history/manifests/history-%08d.json' % e['checkpoint_generation'], 'metrics.csv', 'pheromone_snapshots.npz', 'result.json',
                'role_specific_order.csv', 'transition_counts.json'}
    if (set(actual) != required or actual != receipt['artifact_hashes'] or receipt['identity'] != old
            or receipt['config_hash'] != hash_value(behavioural_config(config))):
        raise ValueError('Baseline artifact/receipt identity mismatch or extra/missing files')
    stored_config = read_json(complete / 'config.json'); stored_config.pop('output_dir')
    if stored_config != behavioural_config(config):
        raise ValueError('Baseline configuration changed')
    for entry_key, receipt_key in (('checkpoint_sha256', 'final_checkpoint_sha256'),
                                  ('history_manifest_sha256', 'history_manifest_sha256'),
                                  ('shared_seed_artifact_sha256', 'shared_seed_artifact_sha256')):
        if e[entry_key] != receipt[receipt_key]: raise ValueError('progress receipt hash mismatch')
    if (e['checkpoint'] != 'completed/' + receipt['final_checkpoint']
            or e['history_manifest'] != 'completed/' + receipt['history_manifest']
            or e['checkpoint_generation'] != receipt['checkpoint_generation']):
        raise ValueError('Baseline progress references mismatch')
    shared = run.parent / 'shared_seed_artifact.zip'
    if (complete / receipt['shared_seed_artifact']).resolve() != shared or sha256_file(shared) != receipt['shared_seed_artifact_sha256']:
        raise ValueError('Baseline shared artifact mismatch')
    state = load_checkpoint(run / e['checkpoint'], config, old, expected_sha256=e['checkpoint_sha256'])
    if state.time != config.steps or len(state.ants) != config.n_ants:
        raise ValueError('Baseline checkpoint time or population mismatch')
    del state
    return complete, shared


def _e2(output):
    path = output / 'checkpoint_repairs/attempt-01'
    if sha256_file(path / 'intent.json') != E2_INTENT_SHA or sha256_file(path / 'repair_receipt.json') != E2_RECEIPT_SHA:
        raise ValueError('checkpoint path repair evidence changed')
    receipt = read_json(path / 'repair_receipt.json')
    if receipt['status'] != 'checkpoint_path_repaired' or receipt['intent_sha256'] != E2_INTENT_SHA:
        raise ValueError('invalid checkpoint path repair receipt')
    return receipt


def _layout(output, allowed_files):
    allowed_dirs = {str(Path(n).parent) for n in allowed_files}
    for n in list(allowed_dirs):
        allowed_dirs.update(str(p) for p in Path(n).parents)
    allowed_dirs.discard('.')
    for p in output.rglob('*'):
        n = p.relative_to(output).as_posix()
        if p.is_symlink() or (p.is_dir() and n not in allowed_dirs) or (p.is_file() and n not in allowed_files):
            # Atomic-write leftovers are retained, never deleted or reused.
            pending = p.is_file() and p.name.startswith('.') and p.name.endswith('.tmp') and any(
                p.parent == (output / a).parent and p.name.startswith('.' + Path(a).name + '.') for a in allowed_files)
            if not pending or p.is_symlink():
                raise ValueError('unexpected study artifact or scientific state: ' + n)


def _initial(root, output, current):
    from . import stage2c as r
    from .stage2c_repair import _passed_receipt, verify_repair_archive
    payload = {n: (output / n).read_bytes() for n in ADMIN}
    old = _json(payload['checkpoint/progress_manifest.json'])['identity']
    proof = scientific_equivalence(root, old, current)
    _passed_receipt(_json(payload['engineering_validation.json']), old)
    p, configs = _validate_state(payload, output, old)
    complete, shared = _baseline(output, p, configs[0], old)
    verify_repair_archive(output); _e2(output)
    expected = set(ADMIN) | {'.runner.lock'}
    expected |= {x.relative_to(output).as_posix() for x in complete.rglob('*') if x.is_file()}
    expected.add(shared.relative_to(output).as_posix())
    expected |= {'checkpoint_repairs/attempt-01/' + n for n in ('intent.json', 'repair_receipt.json')}
    expected |= {'engineering_failures/attempt-01/' + n for n in ('intent.json', 'failure_receipt.json', 'replacement.zip', 'complete.json')}
    expected |= {'engineering_failures/attempt-01/files/' + n for n in ADMIN}
    _layout(output, expected)
    files = _inventory(output)
    return payload, old, proof, files, p, configs


def _context(output, *, require_complete=True):
    folder = output / ATTEMPT
    if not (output / 'resource_amendments').exists(): return None
    if sorted(p.name for p in folder.parent.iterdir()) != ['attempt-01']:
        raise ValueError('unknown resource amendment transaction')
    intent = read_json(folder / 'intent.json')
    previous_raw = (folder / 'previous.zip').read_bytes()
    prepared_raw = (folder / 'prepared.zip').read_bytes()
    if digest_bytes(previous_raw) != intent['previous_sha256'] or digest_bytes(prepared_raw) != intent['prepared_sha256']:
        raise ValueError('migration archive hash mismatch')
    previous, prepared = _unzip(previous_raw), _unzip(prepared_raw)
    if set(previous) != set(ADMIN) or set(prepared) != set(ADMIN) - {'engineering_validation.json'} or _hashes(previous) != intent['previous_files']:
        raise ValueError('migration archive member mismatch')
    _verify_files(output, intent['immutable_files'])
    if require_complete:
        complete = read_json(folder / 'receipt.json') if (folder / 'receipt.json').exists() else None
        if complete is None: raise ValueError('resource amendment migration incomplete; explicit repair required')
        if (complete.get('status') != 'resource_amendment_repaired'
                or complete.get('simulation_steps_executed') != 0
                or complete.get('scientific_metrics_generated') is not False
                or complete['intent_sha256'] != sha256_file(folder / 'intent.json')
                or complete['new_identity'] != intent['new_identity']
                or complete['engineering_validation_sha256'] != sha256_file(output / 'engineering_validation.json')):
            raise ValueError('resource amendment completion receipt mismatch')
    return intent, previous, prepared


def migration_context(output):
    """Called before ordinary Study construction; read-only, fails closed."""
    return _context(Path(output))


def execution_identity(root, output, progress, index, current):
    lineage = progress.get('execution_identity_lineage')
    context = migration_context(output)
    if context is None:
        if lineage is not None: raise ValueError('unverified execution lineage')
        return current
    intent, previous, _ = context
    if current != intent['new_identity']:
        raise ValueError('migration control identity mismatch')
    old = intent['old_identity']
    proof = scientific_equivalence(root, old, current)
    expected = _lineage(old, current, _json(previous['checkpoint/progress_manifest.json'])['runs'], proof)
    if lineage != expected: raise ValueError('execution identity lineage changed')
    return lineage['identities'][lineage['runs'][index]['execution_commit']]


def verify_legacy_shared_identity(path, config, identity, metadata, checksum):
    """The exact preserved seed artifact is validated against its old identity."""
    from .stage2c_checkpoint import _identity_binding
    output = path.resolve().parents[2]
    context = migration_context(output)
    if context is None: raise ValueError('shared seed artifact identity mismatch')
    intent, previous, _ = context
    if identity != intent['new_identity']:
        raise ValueError('shared artifact control identity mismatch')
    relative = path.resolve().relative_to(output).as_posix()
    if (relative != intent['shared_artifact'] or config.seed != intent['baseline_seed']
            or checksum != intent['immutable_files'][relative]['sha256']
            or metadata.get('identity_binding') != _identity_binding(intent['old_identity'])
            or metadata.get('identity_hash') != hash_value(_identity_binding(intent['old_identity']))):
        raise ValueError('unrecognised legacy shared artifact identity')
    # The migration proof is pinned by immutable intent; independently compare the
    # scientific fields, rather than trusting an arbitrary compatible commit list.
    for key in ('preregistration_hash', 'input_hash', 'frozen_source_hashes'):
        if intent['old_identity'][key] != identity[key]: raise ValueError('shared scientific identity mismatch')
    if _json(previous['checkpoint/progress_manifest.json'])['runs'][0]['initial_identity'] != metadata['initial_identity']:
        raise ValueError('legacy shared initial identity mismatch')


def retain_resource_floors(history, previous_runtime):
    """A resource amendment cannot lower a previously recorded reservation."""
    result = deepcopy(history)
    for target, source in (
        ('run_seconds', 'per_run_seconds'),
        ('completed_checkpoint_seconds', 'completed_checkpoint_seconds_allowance'),
        ('retained_completed_run_bytes', 'retained_completed_run_bytes'),
        ('retained_checkpoint_bytes_per_completed_run', 'retained_checkpoint_bytes_per_completed_run'),
        ('shared_seed_artifact_bytes', 'shared_seed_artifact_bytes'),
        ('active_checkpoint_overlap_bytes', 'active_checkpoint_overlap_bytes'),
        ('completion_publication_overlap_bytes', 'completion_publication_overlap_bytes')):
        result[target] = max(result[target], previous_runtime[source])
    return result


def _projection(root, output, p, storage, current, old, elapsed, extra_bytes=0):
    from . import stage2c as r
    from .stage2c_repair import verify_repair_archive
    history = retain_resource_floors(r.historical_resources(root, storage), _json(old['runtime.json']))
    complete = Path(r.config_pair(r.SEEDS[0], output)[0].output_dir) / 'completed'
    cp_bytes = (complete / 'final_checkpoint.zip').stat().st_size
    retained = max(history['retained_completed_run_bytes'], r.directory_bytes(complete) - cp_bytes)
    checkpoint = max(history['retained_checkpoint_bytes_per_completed_run'], cp_bytes)
    tests = read_json(output / 'engineering_validation.json')['temporary_artifact_bytes']
    tests += _json(old['engineering_validation.json'])['temporary_artifact_bytes']
    tests += verify_repair_archive(output, engineering_validation_bytes=old['engineering_validation.json'])
    return r.resource_projection(elapsed_seconds=elapsed,
        stored_bytes=r.retained_study_bytes(output) + tests + extra_bytes, remaining_runs=39,
        run_seconds=max(p['runs'][0]['elapsed_seconds'], history['run_seconds']),
        completed_checkpoint_seconds=history['completed_checkpoint_seconds'],
        retained_completed_run_bytes=retained, retained_checkpoint_bytes_per_completed_run=checkpoint,
        shared_seed_artifact_bytes=history['shared_seed_artifact_bytes'], remaining_shared_seed_artifacts=19,
        active_checkpoint_overlap_bytes=history['active_checkpoint_overlap_bytes'],
        completion_publication_overlap_bytes=history['completion_publication_overlap_bytes'],
        amendment=current['resource_amendment'])


def repair_resource_amendment(root: Path, output: Path):
    from . import stage2c as r
    from .stage2c_repair import _passed_receipt
    root, output = Path(root).resolve(), Path(output).resolve()
    r.validate_output(root, output)
    if not output.is_dir() or not (output / '.runner.lock').is_file() or (output / '.runner.lock').is_symlink():
        raise ValueError('existing locked formal preflight required')
    current = r.build_identity(root, output)
    if current.get('resource_amendment') != amendment_evidence(root) or r.TIME_LIMIT != EFFECTIVE_TIME_LIMIT:
        raise ValueError('amendment identity and code disagree')
    _require_committed(root, current)
    with (output / '.runner.lock').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _migrate_locked(root, output, current)


def prepare_bundles(output, current, previous, old, proof, files, p, configs, storage, started):
    """Pure byte preparation, shared by migration and read-only size audits."""
    prepared = {n: raw for n, raw in previous.items() if n != 'engineering_validation.json'}
    updated = deepcopy(p); updated['identity'] = current
    updated['execution_identity_lineage'] = _lineage(old, current, p['runs'], proof)
    prepared['checkpoint/progress_manifest.json'] = json_bytes(updated)
    config = _json(previous['config_manifest.json']); config['identity'] = current
    config['execution_identity_lineage'] = updated['execution_identity_lineage']
    prepared['config_manifest.json'] = json_bytes(config)
    prepared['storage_preflight.json'] = json_bytes(storage)
    # Original runtime remains in the immutable archive and history; root is
    # replaced only after tests by a fresh eight-hour projection.
    previous_raw, prepared_raw = _zip(previous), _zip(prepared)
    immutable = {n: v for n, v in files.items() if n not in ADMIN}
    shared = str((Path(configs[0].output_dir).parent / 'shared_seed_artifact.zip').relative_to(output))
    intent = {'old_identity': old, 'new_identity': current, 'scientific_equivalence': proof,
              'started_at_epoch': started, 'previous_files': _hashes(previous),
              'previous_sha256': digest_bytes(previous_raw), 'prepared_sha256': digest_bytes(prepared_raw),
              'prepared_archive_hex': prepared_raw.hex(), 'immutable_files': immutable,
              'baseline_seed': configs[0].seed, 'shared_artifact': shared}
    return intent, previous_raw, prepared_raw, prepared


def _migrate_locked(root, output, current):
    from . import stage2c as r
    from .stage2c_repair import _passed_receipt
    folder = output / ATTEMPT; intent_path = folder / 'intent.json'
    if (folder / 'receipt.json').exists():
        _context(output)
        raise ValueError('completed resource migration must not be repeated')
    if intent_path.exists():
        intent = read_json(intent_path)
        if intent['new_identity'] != current: raise ValueError('interrupted migration identity changed')
        old = intent['old_identity']
        if scientific_equivalence(root, old, current) != intent['scientific_equivalence']:
            raise ValueError('interrupted scientific proof changed')
        # Archives are durable before root publication. Partial archive publication
        # can only be recovered from exact original root bytes.
        if (folder / 'previous.zip').exists():
            previous_raw = (folder / 'previous.zip').read_bytes(); previous = _unzip(previous_raw)
        else:
            previous = {n: (output / n).read_bytes() for n in ADMIN}; previous_raw = _zip(previous)
        if digest_bytes(previous_raw) != intent['previous_sha256'] or _hashes(previous) != intent['previous_files']:
            raise ValueError('original migration evidence changed')
        prepared_raw = (folder / 'prepared.zip').read_bytes() if (folder / 'prepared.zip').exists() else bytes.fromhex(intent['prepared_archive_hex'])
        if digest_bytes(prepared_raw) != intent['prepared_sha256']: raise ValueError('prepared bundle changed')
        prepared = _unzip(prepared_raw)
    else:
        if (output / 'resource_amendments').exists(): raise ValueError('unrecognised migration without intent')
        previous, old, proof, files, p, configs = _initial(root, output, current)
        started = time.time()
        with tempfile.TemporaryDirectory(prefix='stage2c-amendment-storage-') as temporary:
            storage = r.storage_only_measurement(r.ColonyConfig.paper_scale(), current, Path(temporary))
        storage['source_hash'] = current['source_hash']
        storage['resource_amendment'] = current['resource_amendment']
        intent, previous_raw, prepared_raw, prepared = prepare_bundles(
            output, current, previous, old, proof, files, p, configs, storage, started)
        if _inventory(output) != files: raise ValueError('study changed during read-only preparation')
    # Recheck strict state from archived original bytes on every invocation.
    if set(previous) != set(ADMIN) or set(prepared) != set(ADMIN) - {'engineering_validation.json'}:
        raise ValueError('migration archive members changed')
    old_p, configs = _validate_state(previous, output, old)
    _baseline(output, old_p, configs[0], old); _e2(output)
    _verify_files(output, intent['immutable_files'])
    allowed = set(ADMIN) | set(intent['immutable_files']) | {ATTEMPT + '/' + n for n in ('intent.json', 'previous.zip', 'prepared.zip', 'receipt.json')}
    _layout(output, allowed)
    expected_lineage = _lineage(old, current, old_p['runs'], intent['scientific_equivalence'])
    prepared_progress, _ = _validate_state(prepared, output, current, old=False)
    if (prepared_progress['runs'] != old_p['runs']
            or prepared_progress['resource_history'] != old_p['resource_history']
            or prepared_progress.get('execution_identity_lineage') != expected_lineage
            or _json(prepared['config_manifest.json']).get('execution_identity_lineage') != expected_lineage):
        raise ValueError('prepared migration changes run state, history or lineage')
    new_validation = output / 'engineering_validation.json'
    finalising = new_validation.exists() and new_validation.read_bytes() != previous['engineering_validation.json']
    if finalising:
        _passed_receipt(read_json(new_validation), current)
        root_progress, _ = _validate_state({**prepared,
            'checkpoint/progress_manifest.json': (output / 'checkpoint/progress_manifest.json').read_bytes()},
            output, current, old=False)
        if (root_progress['runs'] != old_p['runs']
                or root_progress.get('execution_identity_lineage') != expected_lineage
                or root_progress['resource_history'][:len(old_p['resource_history'])] != old_p['resource_history']):
            raise ValueError('interrupted root scientific state/history changed')
    for name in ADMIN:
        path = output / name
        if name == 'engineering_validation.json':
            if not path.exists() and not (folder / 'prepared.zip').exists(): raise ValueError('missing old test evidence')
            continue
        if finalising and name in ('checkpoint/progress_manifest.json', 'runtime.json'):
            continue
        if not path.exists() or path.read_bytes() not in (previous[name], prepared[name]):
            raise ValueError('unexpected root publication bytes: ' + name)
    _once(intent_path, json_bytes(intent))
    _once(folder / 'previous.zip', previous_raw); _once(folder / 'prepared.zip', prepared_raw)
    for path in (folder, folder.parent, output): _fsync(path)
    for name, raw in prepared.items():
        if finalising and name in ('checkpoint/progress_manifest.json', 'runtime.json'): continue
        if (output / name).read_bytes() != raw: atomic_write(output / name, raw)
    if new_validation.exists() and new_validation.read_bytes() == previous['engineering_validation.json']:
        new_validation.unlink(); _fsync(output)
    validation = r.verify_engineering_tests(root, output, current)
    _passed_receipt(validation, current)
    if r.build_identity(root, output) != current: raise ValueError('source changed during migration tests')
    p = read_json(output / 'checkpoint/progress_manifest.json')
    _validate_state({**prepared, 'checkpoint/progress_manifest.json': json_bytes(p)}, output, current, old=False)
    expected_lineage = _lineage(old, current, old_p['runs'], intent['scientific_equivalence'])
    if p.get('execution_identity_lineage') != expected_lineage or p['resource_history'][:len(old_p['resource_history'])] != old_p['resource_history']:
        raise ValueError('historical resource evidence or lineage changed')
    e2 = _e2(output)
    carry = max(old_p['elapsed_seconds'], _json(previous['runtime.json'])['elapsed_seconds'])
    carry += max(0, e2['after_resource']['elapsed_seconds'] - e2['before_resource']['elapsed_seconds'])
    elapsed = max(p['elapsed_seconds'], carry + max(0, time.time() - intent['started_at_epoch']))
    storage = _json(prepared['storage_preflight.json'])
    # Final root bytes and immutable receipt are prepared to a size fixed point:
    # include every final byte without repeatedly appending resource histories.
    p['elapsed_seconds'] = elapsed
    p['resource_history'] = deepcopy(old_p['resource_history'])
    old_root_bytes = (output / 'runtime.json').stat().st_size + (output / 'checkpoint/progress_manifest.json').stat().st_size
    receipt = {'status': 'resource_amendment_repaired', 'intent_sha256': sha256_file(intent_path),
               'new_identity': current, 'engineering_validation_sha256': sha256_file(new_validation),
               'baseline_execution_identity': old, 'simulation_started': False,
               'simulation_steps_executed': 0, 'scientific_metrics_generated': False,
               'pca_initialised': False, 'pilot_resumed': False, 'final_scientific_conclusion_available': False}
    extra = 0
    for _ in range(30):
        projection = _projection(root, output, p, storage, current, previous, elapsed, extra)
        p['resource_history'] = deepcopy(old_p['resource_history']) + [projection]
        receipt['runtime'] = projection
        runtime_raw, progress_raw, receipt_raw = json_bytes(projection), json_bytes(p), json_bytes(receipt)
        desired = len(runtime_raw) + len(progress_raw) + len(receipt_raw) - old_root_bytes
        if desired == extra: break
        extra = desired
    else: raise ValueError('resource receipt size did not converge')
    _verify_files(output, intent['immutable_files'])
    atomic_write(output / 'runtime.json', runtime_raw)
    atomic_write(output / 'checkpoint/progress_manifest.json', progress_raw)
    _once(folder / 'receipt.json', receipt_raw)
    # No scientific state or prior record was rewritten. A storage pause is a
    # completed identity migration, never permission to discard evidence.
    return dict(receipt, action=projection['action'])
