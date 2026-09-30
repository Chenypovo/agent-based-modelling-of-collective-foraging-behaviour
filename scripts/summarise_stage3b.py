#!/usr/bin/env python3
"""Build Stage 3B paired descriptive tables, audits and fixed figures."""

import csv
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['MPLBACKEND'] = 'Agg'
os.environ['MPLCONFIGDIR'] = '/tmp/ph6780-stage3b-mpl'
Path(os.environ['MPLCONFIGDIR']).mkdir(parents=True, exist_ok=True)
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/stage3b_recovery_pilot'
sys.path.insert(0, str(ROOT/'src'))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from scalar_baseline.functional_validation import SEEDS

DISCLAIMER = 'Exploratory five-seed paired pilot; not confirmatory evidence.'


def read(path):
    return json.loads(path.read_text())


def write(name, data):
    (OUT/name).write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def delta(a,b):
    return a-b if a is not None and b is not None else None


rows=[]; arms={}; episode_outcomes={}; post_windows={}; max_recovery_duration=0
for seed in SEEDS:
    arms[seed]={}
    for arm in ('B0','C'):
        folder=OUT/f'runs/{seed}/{arm}'
        arms[seed][arm]=read(folder/'summary.json')
    b,c=arms[seed]['B0'],arms[seed]['C']
    episodes=read(OUT/f'runs/{seed}/C/recovery_episodes.json')
    max_recovery_duration=max(max_recovery_duration,max((e['duration'] for e in episodes),default=0))
    outcomes={name:sum(e['outcome']==name for e in episodes) for name in ('reacquired','timeout','food_contact')}
    episode_outcomes[seed]=outcomes
    post_windows[seed]={'B_discovery':sum(e['B_discovery_within_window'] for e in episodes),
                        'B_delivery':sum(e['B_delivery_within_window'] for e in episodes)}
    rows.append({'seed':seed,
        'B0_first_B_discovery':b['first_B_discovery'],'C_first_B_discovery':c['first_B_discovery'],
        'delta_first_B_discovery_C_minus_B0':delta(c['first_B_discovery'],b['first_B_discovery']),
        'B0_first_B_delivery':b['first_B_delivery'],'C_first_B_delivery':c['first_B_delivery'],
        'delta_first_B_delivery_C_minus_B0':delta(c['first_B_delivery'],b['first_B_delivery']),
        'B0_capped_recovery_time':b['capped_recovery_time'],'C_capped_recovery_time':c['capped_recovery_time'],
        'delta_capped_recovery_time_C_minus_B0':c['capped_recovery_time']-b['capped_recovery_time'],
        'B0_B_deliveries':b['B_deliveries'],'C_B_deliveries':c['B_deliveries'],
        'delta_B_deliveries_C_minus_B0':c['B_deliveries']-b['B_deliveries'],
        'B0_pre_A_deliveries':b['pre_relocation_A_deliveries'],'C_pre_A_deliveries':c['pre_relocation_A_deliveries'],
        'delta_pre_A_deliveries_C_minus_B0':c['pre_relocation_A_deliveries']-b['pre_relocation_A_deliveries'],
        'B0_old_food_dwell_ant_steps':b['old_food_dwell_ant_steps'],'C_old_food_dwell_ant_steps':c['old_food_dwell_ant_steps'],
        'old_food_dwell_ratio_C_over_B0':c['old_food_dwell_ant_steps']/b['old_food_dwell_ant_steps'] if b['old_food_dwell_ant_steps'] else None,
        'recovery_episodes':c['recovery_episodes'],'recovery_reacquisition_rate':c['recovery_reacquisition_rate'],
        'recovery_timeouts':c['recovery_timeouts'],'recovery_food_contacts':c['recovery_food_contacts'],
        'episode_B_discovery_within_100_steps':post_windows[seed]['B_discovery'],
        'episode_B_delivery_within_100_steps':post_windows[seed]['B_delivery']})

with (OUT/'per_seed_comparison.csv').open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)

def directional_count(key):
    values=[r[key] for r in rows if r[key] is not None]
    return {'negative_C_lower_or_earlier':sum(v<0 for v in values),'zero':sum(v==0 for v in values),
            'positive_C_higher_or_later':sum(v>0 for v in values),'comparable_pairs':len(values)}

paired={'scope':DISCLAIMER,'seeds':list(SEEDS),'pairs_completed':10,
        'total_B_deliveries':{'B0':sum(r['B0_B_deliveries'] for r in rows),'C':sum(r['C_B_deliveries'] for r in rows)},
        'seeds_with_B_discovery':{'B0':sum(r['B0_first_B_discovery'] is not None for r in rows),'C':sum(r['C_first_B_discovery'] is not None for r in rows)},
        'seeds_with_B_delivery':{'B0':sum(r['B0_first_B_delivery'] is not None for r in rows),'C':sum(r['C_first_B_delivery'] is not None for r in rows)},
        'pre_A_deliveries':{'B0':sum(r['B0_pre_A_deliveries'] for r in rows),'C':sum(r['C_pre_A_deliveries'] for r in rows)},
        'pre_verified_recruitments':{'B0':sum(arms[s]['B0']['pre_relocation_verified_recruitments'] for s in SEEDS),
                                     'C':sum(arms[s]['C']['pre_relocation_verified_recruitments'] for s in SEEDS)},
        'pre_follower_food_arrivals':{'B0':sum(arms[s]['B0']['pre_relocation_follower_food_arrivals'] for s in SEEDS),
                                      'C':sum(arms[s]['C']['pre_relocation_follower_food_arrivals'] for s in SEEDS)},
        'direction_counts':{
            'first_B_discovery':directional_count('delta_first_B_discovery_C_minus_B0'),
            'capped_recovery_time':directional_count('delta_capped_recovery_time_C_minus_B0'),
            'B_deliveries':directional_count('delta_B_deliveries_C_minus_B0'),
            'pre_A_deliveries':directional_count('delta_pre_A_deliveries_C_minus_B0')},
        'recovery':{'episodes':sum(r['recovery_episodes'] for r in rows),
                    'reacquired':sum(episode_outcomes[s]['reacquired'] for s in SEEDS),
                    'timeouts':sum(episode_outcomes[s]['timeout'] for s in SEEDS),
                    'food_contacts':sum(episode_outcomes[s]['food_contact'] for s in SEEDS),
                    'maximum_duration':max_recovery_duration,
                    'overall_reacquisition_rate':sum(episode_outcomes[s]['reacquired'] for s in SEEDS)/sum(r['recovery_episodes'] for r in rows),
                    'episode_B_discovery_within_100_steps':sum(post_windows[s]['B_discovery'] for s in SEEDS),
                    'episode_B_delivery_within_100_steps':sum(post_windows[s]['B_delivery'] for s in SEEDS)},
        'statistical_tests':None,'confirmatory_claim':False,
        'descriptive_direction':'Mixed and overall not favourable to C: C found B earlier in 3/4 directly comparable pairs, but missed B in one seed; B0 completed B delivery in 2/5 seeds versus C in 1/5, with totals 2 versus 1. Pre-relocation A delivery totals tied 16 versus 16 but varied strongly by seed.'}
write('paired_summary.json',paired)

# Resource and source identity audits.
run_folders=[OUT/f'runs/{s}/{a}' for s in SEEDS for a in ('B0','C')]
run_bytes={str(p.relative_to(OUT)):sum(x.stat().st_size for x in p.iterdir() if x.is_file()) for p in run_folders}
all_summaries=[arms[s][a] for s in SEEDS for a in ('B0','C')]
all_output_files=[p for p in OUT.rglob('*') if p.is_file()]
resources={'limits':{'per_run_wall_seconds':600,'per_run_cpu_seconds':600,'per_run_peak_rss_bytes':2*1024**3,
                     'all_pairs_cpu_seconds':7200,'all_pairs_retained_bytes':2*1024**3,'single_file_bytes':50*1024**2},
           'total_cpu_seconds':sum(s['cpu_seconds'] for s in all_summaries),
           'total_wall_seconds_sequential':sum(s['wall_seconds'] for s in all_summaries),
           'max_run_cpu_seconds':max(s['cpu_seconds'] for s in all_summaries),
           'max_run_wall_seconds':max(s['wall_seconds'] for s in all_summaries),
           'max_peak_rss_bytes':max(s['peak_rss_bytes'] for s in all_summaries),
           'run_output_bytes':run_bytes,'total_run_output_bytes':sum(run_bytes.values()),
           'largest_file_bytes_before_report':max(p.stat().st_size for p in all_output_files),
           'all_limits_pass':False}
resources['all_limits_pass']=(resources['max_run_cpu_seconds']<600 and resources['max_run_wall_seconds']<600
    and resources['max_peak_rss_bytes']<2*1024**3 and resources['total_cpu_seconds']<7200
    and resources['total_run_output_bytes']<2*1024**3 and resources['largest_file_bytes_before_report']<50*1024**2)
write('resource_summary.json',resources)

manifests=[read(OUT/f'prerun_source_{s}_{a}.json') for s in SEEDS for a in ('B0','C')]
source_identity={'pass':all(m==manifests[0] for m in manifests),'manifest_count':len(manifests),
                 'common_manifest':manifests[0]}
write('run_source_identity.json',source_identity)

before=read(OUT/'protected_sha256_before.json')
missing=[];changed=[]
for name,expected in before['files'].items():
    path=ROOT/name
    if not path.is_file():missing.append(name)
    elif sha256(path)!=expected:changed.append(name)
protected_roots=[ROOT/p for p in ('.tmp_progress_report','from_prof','output','reports')]
protected_roots.append(ROOT/'results/stage2c_multiseed_confirmation')
added=[str(p.relative_to(ROOT)) for folder in protected_roots for p in folder.rglob('*')
       if p.is_file() and str(p.relative_to(ROOT)) not in before['files']]
protection={'pass':not(missing or changed or added),'files_checked':len(before['files']),
            'missing':missing,'changed':changed,'new_files_in_named_protected_trees':added}
write('protected_sha256_check.json',protection)

# Delivery and roles, first pair.
fig,axes=plt.subplots(2,2,figsize=(13,8),constrained_layout=True)
for col,arm in enumerate(('B0','C')):
    series=read(OUT/f'runs/{SEEDS[0]}/{arm}/timeseries_100step.json')
    t=[x['time'] for x in series]
    axes[0,col].plot(t,[x['deliveries']['A'] for x in series],label='A deliveries')
    axes[0,col].plot(t,[x['deliveries']['B'] for x in series],label='B deliveries')
    axes[0,col].axvline(6000,color='black',ls='--',lw=1,label='relocation')
    axes[0,col].set(title=f'{arm}: cumulative deliveries',xlabel='step',ylabel='deliveries')
    axes[0,col].legend()
    for role in ('fcrw','follower','recovery','transporter'):
        axes[1,col].plot(t,[x['roles'][role] for x in series],label=role)
    axes[1,col].axvline(6000,color='black',ls='--',lw=1)
    axes[1,col].set(title=f'{arm}: role counts',xlabel='step',ylabel='ants',ylim=(0,100))
    axes[1,col].legend(ncol=2)
fig.suptitle(f'Seed {SEEDS[0]} B0/C relocation time series\n{DISCLAIMER}')
fig.savefig(OUT/'delivery_and_roles.png',dpi=170);plt.close(fig)

# Recovery outcomes.
fig,axes=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
x=np.arange(len(SEEDS));bottom=np.zeros(len(SEEDS))
for outcome,color in (('reacquired','#3A7D44'),('timeout','#B8573C'),('food_contact','#4776A8')):
    values=np.array([episode_outcomes[s][outcome] for s in SEEDS])
    axes[0].bar(x,values,bottom=bottom,label=outcome,color=color);bottom+=values
axes[0].set(xticks=x,xticklabels=[str(s)[-2:] for s in SEEDS],xlabel='seed suffix',ylabel='episodes',title='Recovery episode outcomes')
axes[0].legend()
axes[1].bar(x,[r['old_food_dwell_ratio_C_over_B0'] for r in rows],color='#8367C7')
axes[1].axhline(1,color='black',ls='--',lw=1)
axes[1].set(xticks=x,xticklabels=[str(s)[-2:] for s in SEEDS],xlabel='seed suffix',ylabel='C / B0 dwell ratio',title='Old-food dwell after relocation')
fig.suptitle(DISCLAIMER)
fig.savefig(OUT/'recovery_diagnostics.png',dpi=170);plt.close(fig)

# First-pair scalar snapshots: before, early after, endpoint.
fig,axes=plt.subplots(2,3,figsize=(13,8),constrained_layout=True)
image=None
for row,arm in enumerate(('B0','C')):
    data=np.load(OUT/f'runs/{SEEDS[0]}/{arm}/field_snapshots.npz')
    for col,step in enumerate(('5999','7000','12000')):
        field=data[step]
        image=axes[row,col].imshow(np.ma.masked_less(field.T,0.25),origin='lower',extent=(0,300,0,300),
                                   cmap='YlOrBr',vmin=.25,vmax=5,interpolation='nearest')
        axes[row,col].scatter([150,240,150],[150,150,240],c=['#2467A6','#B63D3D','#3A7D44'],s=20)
        axes[row,col].set(title=f'{arm}, t={step}',xlabel='x',ylabel='y')
fig.colorbar(image,ax=list(axes.flat),shrink=.75,label='scalar concentration (display capped at 5)')
fig.suptitle(f'Seed {SEEDS[0]} scalar field snapshots, threshold display >=0.25\n{DISCLAIMER}')
fig.savefig(OUT/'scalar_field_snapshots.png',dpi=170);plt.close(fig)

test_runtime=read(OUT/'test_runtime.json') if (OUT/'test_runtime.json').is_file() else {'returncode':None}
tests_pass=test_runtime['returncode']==0 and (OUT/'test_results.txt').is_file() and ' passed' in (OUT/'test_results.txt').read_text()
engineering={'engineering_pass':all(s['status']=='complete' and s['valid_state_every_completed_step'] for s in all_summaries)
             and read(OUT/'single_change_audit.json')['pass'] and read(OUT/'baseline_prefix_replay.json')['pass']
             and read(OUT/'food_coordinate_isolation.json')['pass'] and read(OUT/'first_pair_audit.json')['pass']
             and resources['all_limits_pass'] and source_identity['pass'] and protection['pass']
             and tests_pass and max_recovery_duration<=24 and all(arms[s]['C']['anchor_fallbacks']==0 for s in SEEDS),
             'pilot_viability_pass':sum(r['recovery_episodes'] for r in rows)>0
             and any(r['B0_first_B_discovery'] is not None or r['C_first_B_discovery'] is not None for r in rows),
             'runs_complete':sum(s['status']=='complete' for s in all_summaries),'runs_expected':10,
             'tests_pass':tests_pass,'maximum_recovery_duration':max_recovery_duration,
             'baseline_revisions':0,'confirmatory_seeds_run':0,'stage2c_resumed':False}
write('acceptance.json',engineering)
print(json.dumps({'acceptance':engineering,'paired':paired,'resources':resources},indent=2))
