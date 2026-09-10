"""Separate unchanged historical v1 from calibrated fixed-scale v2 evidence."""
import argparse
import json
from pathlib import Path
import h5py
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write
from scripts.l1r_q2_mdbc_bridge import sha256
from scripts.l1r_f3_metrics import observe
from scripts.f3_observation_v2 import observe_arrays,compare,U


def historical():
    gates=json.loads((OUT/'F3-GATES.json').read_text())
    old=json.loads((OUT/'F3-SPATIAL-RESULTS.json').read_text())
    records=json.loads((OUT/'F3-INPUT-REPAIR-READY.json').read_text())['records']
    pairs=[]
    for background in gates['backgrounds']:
        group=[r for r in records if r['background_id']==background]
        vals=[observe(r,gates['observation_times_s']) for r in group]
        for i in range(2):
            observations=[]
            for a,b in zip(vals[i],vals[i+1]):
                d=(a['hist']-b['hist'])[:-2].reshape(15,3,9)
                ix=np.unravel_index(np.argmax(np.abs(d)),d.shape)
                observations.append(dict(target_s=a['target_s'],actual_s=[a['actual_s'],b['actual_s']],
                    tv=float(.5*np.abs(a['hist']-b['hist']).sum()),
                    com=float(np.linalg.norm(a['com']-b['com'])/.9),q90=abs(a['q90']-b['q90'])/.9,
                    velocity=float(np.linalg.norm(a['mean_velocity']-b['mean_velocity'])/U),
                    largest_cell_index=[int(k) for k in ix],largest_cell_signed_mass_fraction=float(d[ix]),
                    marginal_tv_lower_bounds=[float(.5*np.abs(d.sum(axis=tuple(j for j in range(3) if j!=k))).sum()) for k in range(3)]))
            names=[group[i]['id'],group[i+1]['id']]
            maximum=max(x['tv'] for x in observations)
            prior=next(p for p in old['pairs'] if p['cases']==names)
            assert abs(maximum-prior['maxima']['tv'])<1e-12,'v1 re-read does not reproduce historical TV'
            pairs.append(dict(cases=names,background=background,max_tv=maximum,
                              old_v1_status='pass' if prior['registered_screen_pass'] else 'fail',
                              historical_tv_reproduced=True,observations=observations))
    write('F3-V1-REAUDIT.json',dict(pairs=pairs,original_report_sha256=sha256(OUT/'F3-SPATIAL-RESULTS.json'),
                                  interpretation='marginal TVs are lower bounds, not additive causal contributions; original report unmodified'))
    print(json.dumps([{k:p[k] for k in ('background','max_tv','historical_tv_reproduced')} for p in pairs]),flush=True)


def state(h,t):
    times=h['time'][:]
    if not times[0]<=t<=times[-1]:raise ValueError('target outside actual solver domain')
    right=int(np.searchsorted(times,t,side='left'))
    left=max(0,right-1)
    if times[right]==t:left=right
    a=h['valid'][left];b=h['valid'][right]
    if not np.array_equal(a,b):raise ValueError('lifecycle changed within interpolation interval')
    mass=h['mass'][left][a].astype(float)
    if not np.array_equal(mass,h['mass'][right][b].astype(float)):
        raise ValueError('mass changed within interpolation interval')
    weight=0 if left==right else (t-times[left])/(times[right]-times[left])
    p=(1-weight)*h['position'][left][a].astype(float)+weight*h['position'][right][b].astype(float)
    v=(1-weight)*h['velocity'][left][a].astype(float)+weight*h['velocity'][right][b].astype(float)
    return p,v,mass,[float(times[left]),float(times[right])]


def load_observations(name,horizon=8.35):
    path=LAB/'campaigns/l1-resume/data/continuation'/(name+'.h5')
    audit=json.loads((OUT/(name+'-AUDIT.json')).read_text())
    if audit['audit_status']!='pass_diagnostic':raise ValueError('source hard diagnostic failed')
    if audit['hdf5_sha256'] != sha256(path):raise ValueError('source changed since hard audit')
    cache=path.with_name(name+f'-v2-{horizon}.npz')
    meta=cache.with_suffix('.json')
    identity=dict(hdf5_sha256=sha256(path),operator_sha256=sha256(LAB/'scripts/f3_observation_v2.py'),
                  scoring_sha256=sha256(Path(__file__)),horizon_s=horizon)
    if cache.exists() and meta.exists() and json.loads(meta.read_text())==identity:
        return dict(np.load(cache))
    times=np.arange(round(horizon/.01)+1)*.01
    assert abs(times[-1]-horizon)<1e-10
    result={k:[] for k in ('hist','momentum','com','q90','mean_velocity','energy_normalized','mass_fraction','bracket_s')}
    with h5py.File(path,'r') as h:
        m0=float(h['mass'][0][h['valid'][0]].astype(float).sum())
        for j,t in enumerate(times):
            p,v,m,bracket=state(h,float(t))
            o=observe_arrays(p,v,m,m0)
            o['bracket_s']=bracket
            for k in result:result[k].append(o[k])
            if j%100==0:print(name,'observed',j,'/',len(times),flush=True)
    result={k:np.array(v) for k,v in result.items()}
    result['time']=times
    np.savez_compressed(cache,**result)
    meta.write_text(json.dumps(identity,indent=2)+'\n')
    return result


def pair(first,second,horizon=8.35,threshold=.05):
    a,b=load_observations(first,horizon),load_observations(second,horizon)
    rows=[]
    for i,t in enumerate(a['time']):
        x={k:v[i] for k,v in a.items()};y={k:v[i] for k,v in b.items()}
        rows.append(dict(time_s=float(t),**compare(x,y)))
    keys=[k for k in rows[0] if k!='time_s']
    maxima={k:max(r[k] for r in rows) for k in keys}
    result=dict(cases=[first,second],protocol='F3-V2-OBSERVATION-DESIGN.json',
                horizon_s=horizon,threshold=threshold,maxima=maxima,
                all_observations_pass=all(v<=threshold for v in maxima.values()),
                peak_times={k:max(rows,key=lambda r:r[k])['time_s'] for k in keys},
                time_alignment='linear interpolation of same native identities and constant masses; exact shared requested times',
                interpolation_qualification='requires finer-output comparison, not proven by this pair',
                rows=rows)
    write(f'{first}--{second}-V2.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True)
    return result


def diagnostic_pair(first,second,horizon=8.35):
    """Keep missing mass and nearest native times for failed-source diagnosis."""
    paths=[LAB/'campaigns/l1-resume/data/continuation'/(name+'.h5') for name in (first,second)]
    rows=[]
    with h5py.File(paths[0]) as a,h5py.File(paths[1]) as b:
        handles=[a,b];native=[h['time'][:] for h in handles]
        initial=[float(h['mass'][0][h['valid'][0]].astype(float).sum()) for h in handles]
        for target in np.arange(round(horizon/.01)+1)*.01:
            obs=[];actual=[]
            for h,ts,m0 in zip(handles,native,initial):
                if not ts[0]<=target<=ts[-1]:raise ValueError('diagnostic target outside source domain')
                i=int(np.argmin(abs(ts-target)));valid=h['valid'][i]
                obs.append(observe_arrays(h['position'][i][valid],h['velocity'][i][valid],h['mass'][i][valid],m0))
                actual.append(float(ts[i]))
            rows.append(dict(target_s=float(target),actual_s=actual,
                             missing_mass_fractions=[float(o['hist'][-1]) for o in obs],**compare(*obs)))
    keys=[k for k in rows[0] if k not in ('target_s','actual_s','missing_mass_fractions')]
    result=dict(cases=[first,second],source_hashes=[sha256(p) for p in paths],
                scope='diagnostic only; failed hard gates are not waived',qualified=False,
                time_policy='nearest native samples, no interpolation across lost identities',
                maximum_timestamp_mismatch_s=max(abs(r['actual_s'][0]-r['actual_s'][1]) for r in rows),
                maxima={k:max(r[k] for r in rows) for k in keys},rows=rows)
    write(f'{first}--{second}-DIAGNOSTIC.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['historical','observe','pair','diagnostic-pair'])
    p.add_argument('names',nargs='*');p.add_argument('--horizon',type=float,default=8.35)
    p.add_argument('--threshold',type=float,default=.05)
    a=p.parse_args()
    if a.action=='historical':historical()
    elif a.action=='observe':load_observations(a.names[0],a.horizon)
    elif a.action=='pair':pair(*a.names,horizon=a.horizon,threshold=a.threshold)
    else:diagnostic_pair(*a.names,horizon=a.horizon)


if __name__=='__main__':main()
