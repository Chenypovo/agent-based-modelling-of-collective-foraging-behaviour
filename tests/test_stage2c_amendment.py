"""Resource migration fixtures: no registered seed, constructor, step or analysis."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json

import numpy as np
import pytest

import colony.stage2c as r
import colony.stage2c_amendment as a
import colony.stage2c_analysis as analysis
from colony.config import SiteConfig
from colony.agents import Ant, Role
from colony.environment import SquareEnvironment
from colony.pheromone import PheromoneField
from colony.simulation import ColonySimulation
from colony.stage2c_streaming import StreamingSimulation
from colony.stage2c_storage import HistoryStore, sha256_file
from colony.stage2c_checkpoint import (write_json, json_bytes, digest_bytes, hash_value,
    behavioural_config, _storage_fixture_state, save_shared_seed_artifact,
    save_field_artifact, save_checkpoint, load_shared_seed_artifact, storage_only_measurement)
from colony.stage2c_repair import _committed_sources

ROOT = Path(__file__).resolve().parents[1]


def snapshot(path):
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob('*') if p.is_file()}


@pytest.fixture(autouse=True)
def no_science(monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail('amendment attempted scientific execution')
    for cls in (ColonySimulation, StreamingSimulation):
        for name in ('__init__', 'step', 'run'): monkeypatch.setattr(cls, name, forbidden)
    monkeypatch.setattr(StreamingSimulation, 'endpoint_metrics', forbidden)
    monkeypatch.setattr(r.Study, 'execute', forbidden)
    monkeypatch.setattr(r.Study, 'analyse', forbidden)
    monkeypatch.setattr(r, 'run_one', forbidden)
    monkeypatch.setattr(r, 'analyse_rows', forbidden)


@pytest.fixture(scope="module")
def identity_template():
    return r.build_identity(ROOT, ROOT / r.DEFAULT_OUTPUT)


@pytest.fixture
def completed_fixture(tmp_path, monkeypatch, identity_template):
    # The code-equivalence gate reads committed function ASTs, not patched objects.
    current = deepcopy(identity_template)
    old = deepcopy(current); old.pop('resource_amendment')
    old.update(runner_commit=a.OLD_COMMIT, runner_worktree_clean=True,
               source_hashes=dict(_committed_sources(ROOT, a.OLD_COMMIT)))
    old['source_hash'] = hash_value(old['source_hashes'])
    new = deepcopy(current); new.update(runner_commit='c' * 40, runner_worktree_clean=True)
    seeds = tuple(range(991337, 991357))
    monkeypatch.setattr(r, 'SEEDS', seeds); monkeypatch.setattr(analysis, 'SEEDS', seeds)
    out = tmp_path / 'study'; out.mkdir(); (out / '.runner.lock').touch()
    small = replace(r.ColonyConfig.paper_scale(), n_ants=2, steps=9, arena_size=10.0,
                    seed=991337, nest=SiteConfig((1.5, 5.0), 1), food=SiteConfig((7.0, 5.0), 1),
                    snapshot_steps=(), agent_state_interval=3)
    def config_pair(seed, directory):
        assert seed in seeds
        return tuple(replace(small, seed=seed, follower_direction_rule=rule,
                             output_dir=str(directory / 'runs' / str(seed) / rule)) for rule in r.RULES)
    monkeypatch.setattr(r, 'config_pair', config_pair)
    monkeypatch.setattr(a, 'BASELINE_ATTEMPTS', [{'start_time_step':0,'status':'interrupted'}, {'start_time_step':8,'status':'completed'}])
    def measured(config, identity, directory):
        return storage_only_measurement(small, identity, directory)
    monkeypatch.setattr(r, 'storage_only_measurement', measured)
    monkeypatch.setattr(r, 'build_identity', lambda *args: deepcopy(old))
    study = r.Study(ROOT, out)
    study.resources()
    old_validation = {'identity': old, 'passed': True, 'passed_count': 185, 'output': '185 passed in 1.0s\n',
                      'elapsed_seconds': 1.0, 'temporary_artifact_bytes': 1234, 'temporary_directory': str(tmp_path/'old-tests'),
                      'paper_scale_simulation_executed': False, 'exit_code': 0}
    write_json(out/'engineering_validation.json', old_validation)
    config = config_pair(seeds[0], out)[0]; run = Path(config.output_dir); complete = run/'completed'; complete.mkdir(parents=True)
    ants = [Ant(i, np.asarray(small.nest.center), 0.0, Role.FORAGER, travel_path=[np.asarray(small.nest.center)]) for i in range(2)]
    initial = SimpleNamespace(time=0, ants=ants, turn_schedules=np.zeros((2,9)), config=config,
        rng_state={'policy':'frozen_pre_generated_turn_schedules','seed':991337,'live_generator_state':None})
    shared = run.parent/'shared_seed_artifact.zip'
    shared_sha, initial_id = save_shared_seed_artifact(shared, initial, old)
    field = PheromoneField(10.0, config.pheromone, food_position=np.asarray(config.food.center))
    sim = object.__new__(StreamingSimulation)
    sim.__dict__.update(_storage_fixture_state(config, ants, field, time_step=9))
    sim.config=config; sim.environment=SquareEnvironment(10.0); sim.turn_schedules=initial.turn_schedules
    sim.late_window=(0,9); sim.runtime_counters={}
    sim._metric_rows=[{'time':t,'cumulative_deliveries':9 if t==9 else 0} for t in range(10)]
    sim.role_rows=[{'time':t,'forager_count':2,'transporter_count':0,'follower_count':0} for t in range(10)]
    sim._agent_state_rows=[{'time':0,'ant_id':0,'x':1.5,'y':5.0,'heading':0.0,'role':'forager'}]
    sim._event_records=[]; sim.completed_transport=[]; sim._snapshots={}; sim._pheromone_snapshots={}
    manifest, manifest_sha=HistoryStore.write_completed(complete,sim,102)
    for name in ('result.json','diagnostic_accumulators.json','transition_counts.json'):
        write_json(complete/name, {'fixture_only':True})
    (complete/'final_agents.csv').write_text('fixture_only\n1\n')
    write_json(complete/'config.json',config.to_dict())
    save_field_artifact(complete/'final_pheromone.npz',field)
    checkpoint=complete/'final_checkpoint.zip'
    checkpoint_sha=save_checkpoint(checkpoint,sim,old,shared_artifact=shared,history_manifest=manifest,
                                  initial=initial_id,external_field=complete/'final_pheromone.npz',completed=True)
    receipt={'identity':old,'config_hash':hash_value(behavioural_config(config)),'final_checkpoint':'final_checkpoint.zip',
             'final_checkpoint_sha256':checkpoint_sha,'checkpoint_generation':102,'history_manifest':str(manifest.relative_to(complete)),
             'history_manifest_sha256':manifest_sha,'shared_seed_artifact':'../../shared_seed_artifact.zip','shared_seed_artifact_sha256':shared_sha,
             'artifact_hashes':{str(p.relative_to(complete)):sha256_file(p) for p in complete.rglob('*') if p.is_file()}}
    write_json(complete/'receipt.json',receipt)
    p=study.progress; b=p['runs'][0]
    b.update(status='completed',reason='complete_horizon_and_engineering_checks',time=9,elapsed_seconds=250.956673666,
             checkpoint='completed/final_checkpoint.zip',checkpoint_sha256=checkpoint_sha,checkpoint_generation=102,
             history_manifest='completed/'+receipt['history_manifest'],history_manifest_sha256=manifest_sha,
             shared_seed_artifact='../../shared_seed_artifact.zip',shared_seed_artifact_sha256=shared_sha,
             initial_identity=initial_id,attempts=deepcopy(a.BASELINE_ATTEMPTS))
    p['study_state']='paused'; study.persist()
    runtime=json.loads((out/'runtime.json').read_bytes())
    runtime.update(action='pause',reasons=['four_hour_limit'],time_limit_seconds=14400.0,remaining_runs=39)
    runtime.pop('resource_amendment',None);runtime.pop('effective_time_limit_seconds',None);runtime.pop('original_time_limit_seconds',None)
    write_json(out/'runtime.json',runtime);p['resource_history']=[runtime];study.persist()
    # Small, hash-valid engineering archive. It is never read from the formal site.
    prior={n:(out/n).read_bytes() for n in a.ADMIN}
    folder=out/'engineering_failures/attempt-01'
    for n,raw in prior.items(): (folder/'files'/n).parent.mkdir(parents=True,exist_ok=True);(folder/'files'/n).write_bytes(raw)
    intent={'original_files':a._hashes(prior),'new_identity':old};write_json(folder/'intent.json',intent)
    failed={'intent_sha256':sha256_file(folder/'intent.json'),'files':intent['original_files'],'old_engineering_temporary_bytes':456}
    write_json(folder/'failure_receipt.json',failed);(folder/'replacement.zip').write_bytes(a._zip({'fixture':b'zero steps'}))
    write_json(folder/'complete.json',{'identity':old,'failure_receipt_sha256':sha256_file(folder/'failure_receipt.json'),
        'replacement_sha256':sha256_file(folder/'replacement.zip'),'engineering_validation_sha256':sha256_file(out/'engineering_validation.json')})
    e2=out/'checkpoint_repairs/attempt-01';write_json(e2/'intent.json',{'fixture_only':True})
    write_json(e2/'repair_receipt.json',{'status':'checkpoint_path_repaired','intent_sha256':sha256_file(e2/'intent.json'),
        'before_resource':{'elapsed_seconds':1},'after_resource':{'elapsed_seconds':3}})
    monkeypatch.setattr(a,'E2_INTENT_SHA',sha256_file(e2/'intent.json'));monkeypatch.setattr(a,'E2_RECEIPT_SHA',sha256_file(e2/'repair_receipt.json'))
    monkeypatch.setattr(r,'build_identity',lambda *args:deepcopy(new))
    def committed(root,identity):
        if not identity['runner_worktree_clean']:raise ValueError('committed clean code required')
        assert identity['source_hashes']==current['source_hashes']
    monkeypatch.setattr(a,'_require_committed',committed)
    calls=[]
    def tests(root,output,identity):
        path=output/'engineering_validation.json'
        if path.exists():return json.loads(path.read_bytes())
        calls.append(True)
        value=dict(old_validation,identity=identity,temporary_artifact_bytes=2345)
        write_json(path,value,replace=False);return value
    monkeypatch.setattr(r,'verify_engineering_tests',tests)
    return SimpleNamespace(out=out,old=old,new=new,complete=complete,shared=shared,calls=calls,
                           configs=config_pair(seeds[0],out),tests=tests)


def test_exact_state_migrates_with_immutable_baseline_and_all_costs(completed_fixture):
    f=completed_fixture;before=snapshot(f.out);old_history=json.loads(before['checkpoint/progress_manifest.json'])['resource_history']
    result=a.repair_resource_amendment(ROOT,f.out)
    assert result['status']=='resource_amendment_repaired' and result['simulation_steps_executed']==0
    assert result['simulation_started'] is result['scientific_metrics_generated'] is False
    for name,raw in before.items():
        if name.startswith('runs/'): assert (f.out/name).read_bytes()==raw
    assert json.loads((f.complete/'receipt.json').read_bytes())['identity']==f.old
    p=json.loads((f.out/'checkpoint/progress_manifest.json').read_bytes())
    assert p['resource_history'][:-1]==old_history and p['resource_history'][0]['reasons']==['four_hour_limit']
    assert p['identity']==f.new
    assert a.execution_identity(ROOT,f.out,p,0,f.new)==f.old
    assert a.execution_identity(ROOT,f.out,p,1,f.new)==f.new
    study=object.__new__(r.Study);study.root=ROOT;study.output=f.out;study.progress=p;study.identity=f.new
    reports=study.execution_identity_report()
    assert reports[0]['execution_identity']==f.old and all(e['execution_identity']==f.new for e in reports[1:])
    projection=result['runtime']
    assert projection['time_limit_seconds']==28800 and projection['resource_amendment']==f.new['resource_amendment']
    assert projection['stored_bytes']==r.retained_study_bytes(f.out)+1234+456+2345
    assert len(f.calls)==1
    # Both identities can read exactly the same old shared artifact; no rewriting.
    new_shared=load_shared_seed_artifact(f.shared,f.configs[1],f.new)
    old_shared=load_shared_seed_artifact(f.shared,f.configs[0],f.old)
    assert new_shared['sha256']==old_shared['sha256']
    after=snapshot(f.out)
    with pytest.raises(ValueError,match='must not be repeated'):a.repair_resource_amendment(ROOT,f.out)
    assert snapshot(f.out)==after


@pytest.mark.parametrize('mutation', ['pca_time','pca_identity','pca_attempt','pca_dir','other_seed','extra','missing','corrupt',
    'rule','seed','config','metric','science','old_commit','dirty','amendment','reason','e2','engineering_archive'])
def test_refuse_before_any_write(completed_fixture,monkeypatch,mutation):
    f=completed_fixture;p=json.loads((f.out/'checkpoint/progress_manifest.json').read_bytes())
    if mutation=='pca_time':p['runs'][1]['time']=1
    if mutation=='pca_identity':p['runs'][1]['initial_identity']={}
    if mutation=='pca_attempt':p['runs'][1]['attempts']=[{}]
    if mutation=='other_seed':p['runs'][2]['status']='running'
    if mutation=='rule':p['runs'][0]['rule']='wrong'
    if mutation=='seed':p['runs'][0]['seed']=0
    write_json(f.out/'checkpoint/progress_manifest.json',p)
    if mutation=='pca_dir':Path(f.configs[1].output_dir).mkdir()
    if mutation=='extra':(f.complete/'extra.json').write_text('{}')
    if mutation=='missing':(f.complete/'final_checkpoint.zip').unlink()
    if mutation=='corrupt':(f.complete/'final_checkpoint.zip').write_bytes(b'broken')
    if mutation=='config':
        q=f.out/'config_manifest.json';d=json.loads(q.read_bytes());d['configurations'][0]['config']['steps']=10;write_json(q,d)
    if mutation in ('metric','science'):
        old=a.scientific_equivalence
        def reject(*args): raise ValueError('scientific/metric definition changed')
        monkeypatch.setattr(a,'scientific_equivalence',reject)
    if mutation=='old_commit':
        p['identity']['runner_commit']='d'*40;write_json(f.out/'checkpoint/progress_manifest.json',p)
    if mutation=='dirty':f.new['runner_worktree_clean']=False
    if mutation=='amendment':f.new['resource_amendment']['sha256']='0'*64
    if mutation=='reason':
        q=f.out/'runtime.json';d=json.loads(q.read_bytes());d['reasons']=['two_gb_limit'];write_json(q,d)
    if mutation=='e2':(f.out/'checkpoint_repairs/attempt-01/intent.json').write_text('{}')
    if mutation=='engineering_archive':(f.out/'engineering_failures/attempt-01/files/runtime.json').write_text('{}')
    before=snapshot(f.out)
    with pytest.raises((ValueError,FileNotFoundError)):a.repair_resource_amendment(ROOT,f.out)
    assert snapshot(f.out)==before and not (f.out/'resource_amendments').exists()


@pytest.mark.parametrize('phase',['intent','previous','prepared','root','before_tests','after_tests','runtime','progress','receipt'])
def test_interrupted_transaction_preserves_and_resumes_one_intent(completed_fixture,monkeypatch,phase):
    f=completed_fixture;baseline=snapshot(f.complete);once=a._once;atomic=a.atomic_write;tests=r.verify_engineering_tests;tripped=[]
    def interrupt():
        if not tripped:tripped.append(True);raise KeyboardInterrupt
    def publish(path,raw):
        once(path,raw)
        if (phase=='intent' and path.name=='intent.json') or (phase=='previous' and path.name=='previous.zip') or (phase=='prepared' and path.name=='prepared.zip') or (phase=='receipt' and path.name=='receipt.json'):interrupt()
    def write(path,raw,**kwargs):
        atomic(path,raw,**kwargs)
        if path.parent==f.out and ((phase=='root' and path.name=='config_manifest.json') or (phase=='runtime' and path.name=='runtime.json' and f.calls)):interrupt()
        if phase=='progress' and path==f.out/'checkpoint/progress_manifest.json' and f.calls:interrupt()
    def test(*args):
        if phase=='before_tests':interrupt()
        value=tests(*args)
        if phase=='after_tests':interrupt()
        return value
    monkeypatch.setattr(a,'_once',publish);monkeypatch.setattr(a,'atomic_write',write);monkeypatch.setattr(r,'verify_engineering_tests',test)
    with pytest.raises(KeyboardInterrupt):a.repair_resource_amendment(ROOT,f.out)
    assert snapshot(f.complete)==baseline
    intent=(f.out/a.ATTEMPT/'intent.json').read_bytes()
    if phase!='receipt':
        with pytest.raises((ValueError,FileNotFoundError)):r.Study(ROOT,f.out)
    monkeypatch.setattr(a,'_once',once);monkeypatch.setattr(a,'atomic_write',atomic);monkeypatch.setattr(r,'verify_engineering_tests',tests)
    if phase=='receipt':
        with pytest.raises(ValueError,match='must not be repeated'):a.repair_resource_amendment(ROOT,f.out)
    else:
        result=a.repair_resource_amendment(ROOT,f.out);assert result['status']=='resource_amendment_repaired'
    assert (f.out/a.ATTEMPT/'intent.json').read_bytes()==intent and snapshot(f.complete)==baseline and len(f.calls)==1


def test_failed_new_engineering_tests_are_preserved(completed_fixture,monkeypatch):
    f=completed_fixture
    def failed(root,output,identity):
        value=f.tests(root,output,identity);value.update(passed=False,exit_code=1,output='1 failed, 184 passed\n')
        write_json(output/'engineering_validation.json',value)
        raise RuntimeError('engineering tests failed')
    monkeypatch.setattr(r,'verify_engineering_tests',failed)
    with pytest.raises(RuntimeError):a.repair_resource_amendment(ROOT,f.out)
    before=snapshot(f.out)
    with pytest.raises(ValueError):a.repair_resource_amendment(ROOT,f.out)
    assert snapshot(f.out)==before
    with pytest.raises(ValueError):r.Study(ROOT,f.out)


def test_storage_pause_preserves_evidence_and_completed_migration(completed_fixture,monkeypatch):
    f=completed_fixture
    def costly(*args):
        value=f.tests(*args);value['temporary_artifact_bytes']=2_000_000_001;write_json(args[1]/'engineering_validation.json',value);return value
    monkeypatch.setattr(r,'verify_engineering_tests',costly)
    result=a.repair_resource_amendment(ROOT,f.out)
    assert result['action']=='pause' and 'two_gb_limit' in result['runtime']['reasons']
    assert (f.out/a.ATTEMPT/'receipt.json').is_file()


@pytest.mark.parametrize('elapsed,seconds,action',[(0,400,'continue'),(0,500,'pause'),(28800,1,'pause'),(28801,1,'pause')])
def test_eight_hour_gate_and_policy_evidence(elapsed,seconds,action):
    value=r.resource_projection(elapsed_seconds=elapsed,stored_bytes=0,remaining_runs=40,run_seconds=seconds,
        retained_completed_run_bytes=1,retained_checkpoint_bytes_per_completed_run=1,shared_seed_artifact_bytes=1,
        remaining_shared_seed_artifacts=20,active_checkpoint_overlap_bytes=1)
    assert value['action']==action and value['safety_factor']==1.5 and value['storage_limit_bytes']==2_000_000_000
    assert value['original_time_limit_seconds']==14400 and value['time_limit_seconds']==28800
    assert value['resource_amendment']['sha256']==sha256_file(ROOT/a.AMENDMENT_PATH)
    if action=='pause':assert 'eight_hour_limit' in value['reasons']


def test_cli_rejects_resume_seed_and_rule_without_execution():
    spec=importlib.util.spec_from_file_location('amendment_cli',ROOT/'scripts/run_stage2c.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    for extra in (['--resume'],['--seed','991337'],['--rule','stored_cell_direction']):
        with pytest.raises(SystemExit):cli.main(['--mode','repair-resource-amendment',*extra])


def test_deterministic_archive_and_real_uncommitted_gate():
    payload={'b.json':b'{}\n','a.txt':b'original bytes\n'}
    assert a._zip(payload)==a._zip(dict(reversed(list(payload.items()))))
    assert a._unzip(a._zip(payload))==payload
    with pytest.raises(ValueError):a._require_committed(ROOT,dict(r.build_identity(ROOT),runner_worktree_clean=False))


@pytest.mark.parametrize('definition', ['stage2c_analysis.py', 'stage2c_streaming.py', 'stage2c_checkpoint.py', 'stage2c.py'])
def test_actual_changed_definition_is_rejected(completed_fixture, tmp_path, monkeypatch, definition):
    import colony.stage2c_repair as repair
    f = completed_fixture
    root = tmp_path / 'changed-source'
    for name in ('stage2c_analysis.py', 'stage2c_streaming.py', 'stage2c_storage.py', 'stage2c_checkpoint.py', 'stage2c.py'):
        dest = root / 'src/colony' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / 'src/colony' / name).read_bytes())
    target = root / 'src/colony' / definition
    text = target.read_text()
    if definition == 'stage2c.py':
        text = text.replace('def run_one(', 'def changed_run_one(', 1)
        text += '\ndef run_one():\n    raise RuntimeError("changed dynamics")\n'
    else:
        text += '\nCHANGED_SCIENTIFIC_DEFINITION = True\n'
    target.write_text(text)
    original_git = r.git
    monkeypatch.setattr(r, 'git', lambda ignored, *args: original_git(ROOT, *args))
    monkeypatch.setattr(repair, 'git', lambda ignored, *args: original_git(ROOT, *args))
    before = snapshot(f.out)
    with pytest.raises(ValueError, match='changed'):
        a.scientific_equivalence(root, f.old, f.new)
    assert snapshot(f.out) == before


def test_new_execution_checkpoint_reads_exact_old_shared_artifact(completed_fixture):
    from colony.stage2c_checkpoint import load_checkpoint
    f = completed_fixture
    a.repair_resource_amendment(ROOT, f.out)
    baseline = snapshot(f.complete)
    sim = load_checkpoint(f.complete/'final_checkpoint.zip', f.configs[0], f.old)
    sim.config = f.configs[1]
    run = Path(sim.config.output_dir)
    history, _ = HistoryStore.write_completed(run, sim, 1)
    path = run/'fixture_checkpoint.zip'
    initial = load_shared_seed_artifact(f.shared, f.configs[1], f.new)['initial_identity']
    checksum = save_checkpoint(path, sim, f.new, shared_artifact=f.shared,
                               history_manifest=history, initial=initial)
    restored = load_checkpoint(path, f.configs[1], f.new, expected_sha256=checksum)
    assert restored.time == 9 and len(restored.ants) == 2
    with pytest.raises(ValueError): load_checkpoint(path, f.configs[1], f.old, expected_sha256=checksum)
    assert snapshot(f.complete) == baseline


def test_lineage_tampering_and_old_floor_reduction_are_rejected(completed_fixture):
    f = completed_fixture
    result = a.repair_resource_amendment(ROOT, f.out)
    p = json.loads((f.out/'checkpoint/progress_manifest.json').read_bytes())
    p['execution_identity_lineage']['runs'][1]['execution_commit'] = f.old['runner_commit']
    with pytest.raises(ValueError, match='lineage'):
        a.execution_identity(ROOT, f.out, p, 1, f.new)
    history = r.historical_resources(ROOT, json.loads((f.out/'storage_preflight.json').read_bytes()))
    old = result['runtime']
    elevated = dict(old, retained_checkpoint_bytes_per_completed_run=99_000_000,
                    completed_checkpoint_seconds_allowance=99)
    bounded = a.retain_resource_floors(history, elevated)
    assert bounded['retained_checkpoint_bytes_per_completed_run'] == 99_000_000
    assert bounded['completed_checkpoint_seconds'] == 99


def test_scientific_state_after_interrupted_tests_refused_before_writes(completed_fixture, monkeypatch):
    f = completed_fixture
    tests = r.verify_engineering_tests
    def interrupt(*args):
        tests(*args)
        raise KeyboardInterrupt
    monkeypatch.setattr(r, 'verify_engineering_tests', interrupt)
    with pytest.raises(KeyboardInterrupt): a.repair_resource_amendment(ROOT, f.out)
    p = json.loads((f.out/'checkpoint/progress_manifest.json').read_bytes())
    p['runs'][1]['time'] = 1
    write_json(f.out/'checkpoint/progress_manifest.json', p)
    before = snapshot(f.out)
    monkeypatch.setattr(r, 'verify_engineering_tests', tests)
    with pytest.raises(ValueError): a.repair_resource_amendment(ROOT, f.out)
    assert snapshot(f.out) == before


def test_exclusive_lock_refuses_without_writes(completed_fixture):
    import fcntl
    f = completed_fixture
    before = snapshot(f.out)
    with (f.out/'.runner.lock').open('rb') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError): a.repair_resource_amendment(ROOT, f.out)
    assert snapshot(f.out) == before


def test_interrupted_archive_corruption_cannot_be_replaced(completed_fixture, monkeypatch):
    f = completed_fixture
    original = a._once
    def interrupt(path, raw):
        original(path, raw)
        if path.name == 'prepared.zip': raise KeyboardInterrupt
    monkeypatch.setattr(a, '_once', interrupt)
    with pytest.raises(KeyboardInterrupt): a.repair_resource_amendment(ROOT, f.out)
    archive = f.out/a.ATTEMPT/'previous.zip'
    archive.write_bytes(b'corrupt retained evidence')
    before = snapshot(f.out)
    monkeypatch.setattr(a, '_once', original)
    with pytest.raises(Exception): a.repair_resource_amendment(ROOT, f.out)
    assert snapshot(f.out) == before
