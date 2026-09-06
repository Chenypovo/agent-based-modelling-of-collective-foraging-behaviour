"""Zero-step administrative fixtures only; never touch the real failed study."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import importlib.util

import pytest

import colony.stage2c as runner
import colony.stage2c_repair as repair
from colony.config import SiteConfig
from colony.simulation import ColonySimulation
from colony.stage2c_checkpoint import (digest_bytes, hash_value, json_bytes, read_json,
                                      storage_only_measurement, write_json)
from colony.stage2c_streaming import StreamingSimulation

ROOT = Path(__file__).resolve().parents[1]
FAILURE = ("=================================== FAILURES ===================================\n"
           "test_dry_run_no_simulation_or_initialisation\n"
           "assert not (ROOT / 'results/stage2c_multiseed_confirmation').exists()\n"
           "E AssertionError: assert not True\n"
           "FAILED tests/test_stage2c_multiseed.py::test_dry_run_no_simulation_or_initialisation\n"
           "1 failed, 127 passed in 68.71s\n")


def snapshot(path):
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob('*') if p.is_file()}


@pytest.fixture(autouse=True)
def no_scientific_execution(monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail('repair attempted scientific simulation/execution')
    for name in ('__init__', 'step', 'run'):
        monkeypatch.setattr(ColonySimulation, name, forbidden)
    monkeypatch.setattr(StreamingSimulation, '__init__', forbidden)
    monkeypatch.setattr(StreamingSimulation, 'endpoint_metrics', forbidden)
    monkeypatch.setattr(runner.Study, 'execute', forbidden)
    monkeypatch.setattr(runner.Study, 'analyse', forbidden)


@pytest.fixture(scope='module')
def old_identity():
    old = runner.build_identity(ROOT, ROOT / runner.DEFAULT_OUTPUT)
    commit = runner.git(ROOT, 'rev-parse', 'HEAD').decode().strip()
    names = runner.git(ROOT, 'ls-tree', '-r', '--name-only', commit, '--',
                       'src', 'scripts', 'tests', 'run_stage2c.sh', 'requirements.txt').decode().splitlines()
    old['source_hashes'] = {n: digest_bytes(runner.git(ROOT, 'show', f'{commit}:{n}')) for n in names
                            if n.endswith('.py') or n in ('run_stage2c.sh', 'requirements.txt')}
    old.update(source_hash=hash_value(old['source_hashes']), runner_commit=commit, runner_worktree_clean=True)
    return old


@pytest.fixture
def failed(tmp_path, monkeypatch, old_identity):
    old = deepcopy(old_identity)
    new = deepcopy(old)
    new['source_hashes']['tests/repair_fixture_only.py'] = 'a' * 64
    new.update(source_hash=hash_value(new['source_hashes']), runner_commit='c' * 40)
    monkeypatch.setattr(runner, 'build_identity', lambda *a, **k: deepcopy(old))

    def small_storage(config, identity, directory):
        # The production fixture always substitutes 991337 and executes no steps.
        config = replace(config, n_ants=2, steps=9, arena_size=10.0, seed=991337,
                         nest=SiteConfig((1.5, 5.0), 1.0), food=SiteConfig((7.0, 5.0), 1.0),
                         snapshot_steps=(3, 6, 9), agent_state_interval=3)
        return storage_only_measurement(config, identity, directory)
    monkeypatch.setattr(runner, 'storage_only_measurement', small_storage)
    out = tmp_path / 'failed-preflight'
    with runner.study_lock(out):
        study = runner.Study(ROOT, out)
        study.resources()
    receipt = {'identity': old, 'passed': False, 'passed_count': 127, 'output': FAILURE,
               'elapsed_seconds': 69.102336208, 'temporary_artifact_bytes': 3384769,
               'temporary_directory': str(tmp_path / 'old-test-evidence'),
               'paper_scale_simulation_executed': False}
    write_json(out / 'engineering_validation.json', receipt)
    monkeypatch.setattr(runner, 'build_identity', lambda *a, **k: deepcopy(new))
    monkeypatch.setattr(repair, 'build_identity', lambda *a, **k: deepcopy(new))
    calls = []

    def successful_tests(root, output, identity):
        path = output / 'engineering_validation.json'
        if path.exists():
            result = read_json(path)
            assert result['passed'] and result['identity'] == identity
            return result
        calls.append(identity)
        result = dict(receipt, identity=identity, passed=True, passed_count=128,
                      output='128 passed in 1.0s\n', exit_code=0,
                      elapsed_seconds=1.0, temporary_artifact_bytes=2345)
        write_json(path, result, replace=False)
        return result
    monkeypatch.setattr(repair, 'verify_engineering_tests', successful_tests)
    return out, old, new, calls


def test_exact_zero_step_failure_archive_identity_and_resources(failed):
    out, old, new, calls = failed
    before = snapshot(out)
    result = repair.repair_preflight(ROOT, out)
    assert result['status'] == 'preflight_repaired'
    assert result['simulation_started'] is result['scientific_metrics_generated'] is False
    archived = out / repair.ATTEMPT / 'files'
    assert snapshot(archived) == {n: before[n] for n in repair.FILES}
    receipt = read_json(out / repair.ATTEMPT / 'failure_receipt.json')
    assert receipt['old_runner_commit'] == old['runner_commit']
    assert receipt['old_source_hash'] == old['source_hash'] and receipt['exit_code'] == 1
    assert receipt['failed_tests'] == ['tests/test_stage2c_multiseed.py::test_dry_run_no_simulation_or_initialisation']
    assert (archived / 'engineering_validation.json').read_bytes() == before['engineering_validation.json']
    assert read_json(out / 'engineering_validation.json')['identity'] == new
    assert read_json(out / 'config_manifest.json')['identity'] == new
    assert read_json(out / 'storage_preflight.json')['source_hash'] == new['source_hash']
    progress = read_json(out / 'checkpoint/progress_manifest.json')
    assert progress['runs'] == runner.new_progress(new)['runs']
    assert not (out / 'runs').exists() and len(calls) == 1
    r = result['runtime']
    assert r['remaining_runs'] == 40 and r['safety_factor'] == 1.5
    assert r['elapsed_seconds'] >= 69.102336208
    assert r['stored_bytes'] >= runner.directory_bytes(out / 'engineering_failures') + 3384769 + 2345
    assert repair.verify_repair_archive(out) == 3384769
    # Later resources continue to charge archived failures and their test files.
    study = runner.Study(ROOT, out)
    later = study.resources()
    assert later['stored_bytes'] >= r['stored_bytes']
    assert later['elapsed_seconds'] >= r['elapsed_seconds']
    settled = snapshot(out)
    with pytest.raises(ValueError, match='must not be repaired again'):
        repair.repair_preflight(ROOT, out)
    assert snapshot(out) == settled


@pytest.mark.parametrize('field,value', [
    ('status', 'running'), ('status', 'interrupted'), ('status', 'completed'),
    ('time', 1), ('attempts', [{}]), ('checkpoint', 'checkpoint-1.zip'),
    ('history_manifest', 'history.json'), ('initial_identity', {}),
    ('shared_seed_artifact', 'shared.zip'), ('checkpoint_generation', 1),
    ('checkpoint_sha256', 'a' * 64), ('history_manifest_sha256', 'a' * 64),
    ('shared_seed_artifact_sha256', 'a' * 64), ('seed', 991337), ('rule', 'wrong')])
def test_any_nonzero_or_unrecognised_record_refused_without_writes(failed, field, value):
    out, *_ = failed
    path = out / 'checkpoint/progress_manifest.json'
    p = read_json(path); p['runs'][0][field] = value; write_json(path, p)
    before = snapshot(out)
    with pytest.raises(ValueError):
        repair.repair_preflight(ROOT, out)
    assert snapshot(out) == before
    assert not (out / 'engineering_failures').exists()


@pytest.mark.parametrize('extra', ['runs', 'completed', 'analysis', 'summary.json', 'shared_seed_artifact.zip'])
def test_scientific_paths_refused_even_empty(failed, extra):
    out, *_ = failed
    (out / extra).mkdir()
    before = snapshot(out)
    with pytest.raises(ValueError, match='scientific state'):
        repair.repair_preflight(ROOT, out)
    assert snapshot(out) == before and not (out / 'engineering_failures').exists()


@pytest.mark.parametrize('mutation', ['passed', 'paper', 'missing', 'corrupt', 'output', 'identity', 'table', 'seed_manifest', 'config', 'dirty'])
def test_invalid_failure_receipts_and_preconditions_refused(failed, monkeypatch, mutation):
    out, old, new, _ = failed
    path = out / 'engineering_validation.json'; data = read_json(path)
    if mutation == 'passed': data['passed'] = True
    if mutation == 'paper': data['paper_scale_simulation_executed'] = True
    if mutation == 'output': data['output'] = 'incomplete test output'
    if mutation == 'identity': data['identity']['source_hash'] = '0' * 64
    write_json(path, data)
    if mutation == 'missing': path.unlink()
    if mutation == 'corrupt': path.write_text('{invalid')
    if mutation == 'table': (out / 'per_seed_metrics.csv').write_text('seed,psi\n20260901,0.99\n')
    if mutation == 'seed_manifest': write_json(out / 'seed_manifest.json', {'seed': 991337})
    if mutation == 'config':
        p = out / 'config_manifest.json'; d = read_json(p); d['configurations'][0]['config']['n_ants'] = 99; write_json(p, d)
    if mutation == 'dirty': monkeypatch.setattr(repair, 'build_identity', lambda *a: dict(new, runner_worktree_clean=False))
    before = snapshot(out)
    with pytest.raises(ValueError): repair.repair_preflight(ROOT, out)
    assert snapshot(out) == before and not (out / 'engineering_failures').exists()


@pytest.mark.parametrize('phase', ['intent', 'archive', 'bundle', 'publish', 'before_tests', 'tests', 'account', 'finalise'])
def test_interruption_reuses_one_attempt_without_overwriting_evidence(failed, monkeypatch, phase):
    out, old, new, calls = failed
    before = snapshot(out)
    once = repair._once; atomic = repair.atomic_write; test = repair.verify_engineering_tests
    resources = runner.Study.resources
    tripped = []
    def stop():
        if not tripped:
            tripped.append(True); raise KeyboardInterrupt('injected repair interruption')
    def interrupted_once(path, data):
        once(path, data)
        if phase == 'intent' and path.name == 'intent.json': stop()
        if phase == 'archive' and path.parent.name == 'files': stop()
        if phase == 'bundle' and path.name == 'replacement.zip': stop()
        if phase == 'finalise' and path.name == 'complete.json': stop()
    def interrupted_atomic(path, data, **kwargs):
        atomic(path, data, **kwargs)
        if phase == 'publish' and path == out / 'config_manifest.json': stop()
    def interrupted_tests(*args):
        if phase == 'before_tests': stop()
        result = test(*args)
        if phase == 'tests': stop()
        return result
    def interrupted_resources(study):
        result = resources(study)
        if phase == 'account' and study.output == out: stop()
        return result
    monkeypatch.setattr(repair, '_once', interrupted_once)
    monkeypatch.setattr(repair, 'atomic_write', interrupted_atomic)
    monkeypatch.setattr(repair, 'verify_engineering_tests', interrupted_tests)
    monkeypatch.setattr(runner.Study, 'resources', interrupted_resources)
    with pytest.raises(KeyboardInterrupt): repair.repair_preflight(ROOT, out)
    archived_before = snapshot(out / repair.ATTEMPT / 'files')
    if phase == 'finalise':
        with pytest.raises(ValueError, match='must not be repaired again'): repair.repair_preflight(ROOT, out)
    else:
        assert repair.repair_preflight(ROOT, out)['status'] == 'preflight_repaired'
    archived_after = snapshot(out / repair.ATTEMPT / 'files')
    assert all(archived_after[n] == raw for n, raw in archived_before.items())
    assert archived_after == {n: before[n] for n in repair.FILES}
    assert [p.name for p in (out / 'engineering_failures').iterdir()] == ['attempt-01']
    assert len(calls) == 1
    assert read_json(out / 'checkpoint/progress_manifest.json')['runs'] == runner.new_progress(new)['runs']


def test_repair_test_failure_preserved_and_never_retried_implicitly(failed, monkeypatch):
    out, old, new, _ = failed
    def failed_again(root, output, identity):
        receipt = read_json(output / repair.ATTEMPT / 'files/engineering_validation.json')
        receipt['identity'] = identity
        write_json(output / 'engineering_validation.json', receipt, replace=False)
        raise RuntimeError('injected engineering failure')
    monkeypatch.setattr(repair, 'verify_engineering_tests', failed_again)
    with pytest.raises(RuntimeError): repair.repair_preflight(ROOT, out)
    before = snapshot(out)
    with pytest.raises(ValueError, match='failed or is inconsistent'): repair.repair_preflight(ROOT, out)
    assert snapshot(out) == before
    assert read_json(out / 'engineering_validation.json')['identity'] == new
    assert read_json(out / repair.ATTEMPT / 'files/engineering_validation.json')['identity'] == old


def test_partial_atomic_publication_preserves_original_and_retains_temporary(failed, monkeypatch):
    import os
    out, *_ = failed
    before = snapshot(out)
    original = os.replace
    blocked = []
    def fail_once(source, target):
        if Path(target) == out / 'config_manifest.json' and not blocked:
            blocked.append(True)
            raise OSError('injected before atomic root publication')
        return original(source, target)
    monkeypatch.setattr(os, 'replace', fail_once)
    with pytest.raises(OSError): repair.repair_preflight(ROOT, out)
    assert (out / 'config_manifest.json').read_bytes() == before['config_manifest.json']
    leftovers = {p: p.read_bytes() for p in out.glob('.config_manifest.json.*.tmp')}
    assert leftovers
    assert repair.repair_preflight(ROOT, out)['status'] == 'preflight_repaired'
    assert all(p.read_bytes() == raw for p, raw in leftovers.items())


def test_incomplete_repair_cannot_enter_normal_study(failed, monkeypatch):
    out, *_ = failed
    def interrupt(*a): raise KeyboardInterrupt
    monkeypatch.setattr(repair, '_replacement', interrupt)
    with pytest.raises(KeyboardInterrupt): repair.repair_preflight(ROOT, out)
    with pytest.raises(ValueError, match='incomplete'): runner.Study(ROOT, out)
    archive = out / repair.ATTEMPT / 'files/engineering_validation.json'
    archive.write_bytes(archive.read_bytes() + b'corrupt')
    before = snapshot(out)
    with pytest.raises(ValueError, match='checksum'): repair.repair_preflight(ROOT, out)
    assert snapshot(out) == before


@pytest.mark.parametrize('field', ['old_identity', 'failed_tests', 'schema_version'])
def test_contradictory_interrupted_intent_is_refused(failed, monkeypatch, field):
    out, *_ = failed
    monkeypatch.setattr(repair, '_replacement', lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt): repair.repair_preflight(ROOT, out)
    path = out / repair.ATTEMPT / 'intent.json'
    intent = read_json(path)
    intent[field] = {} if field == 'old_identity' else [] if field == 'failed_tests' else 99
    write_json(path, intent)
    before = snapshot(out)
    with pytest.raises(ValueError, match='contradicts'): repair.repair_preflight(ROOT, out)
    assert snapshot(out) == before


@pytest.mark.parametrize('exists', [False, True])
def test_dry_run_preserves_formal_directory_state(failed, tmp_path, monkeypatch, exists):
    _, _, new, _ = failed
    fake_root = tmp_path / 'project'; fake_root.mkdir()
    formal = fake_root / runner.DEFAULT_OUTPUT
    if exists:
        formal.mkdir(parents=True); (formal / 'original.json').write_bytes(b'original evidence')
    # Only repository provenance/history lookup is substituted. dry_run itself,
    # routing, manifests and no-simulation guards are production code.
    historical = runner.historical_resources
    monkeypatch.setattr(runner, 'historical_resources', lambda root, storage: historical(ROOT, storage))
    before = snapshot(formal)
    result = runner.dry_run(fake_root, tmp_path / 'dry-output')
    assert Path(result['output_dir']) == (tmp_path / 'dry-output').resolve()
    assert formal.exists() == exists and snapshot(formal) == before
    assert result['simulation_started'] is result['scientific_metrics_generated'] is False


def test_cli_dispatches_repair_without_study_or_execution(failed, monkeypatch):
    out, *_ = failed
    spec = importlib.util.spec_from_file_location('stage2c_cli_test', ROOT / 'scripts/run_stage2c.py')
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    seen = []
    monkeypatch.setattr(cli, 'repair_preflight', lambda root, output: seen.append(output) or {'status': 'preflight_repaired'})
    assert cli.main(['--mode', 'repair-preflight', '--output-dir', str(out)]) == 0
    assert seen == [out]
    with pytest.raises(SystemExit): cli.main(['--mode', 'repair-preflight', '--resume'])
