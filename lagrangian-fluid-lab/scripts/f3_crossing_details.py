"""Locate nominal wall crossings and retain surrounding native-frame tracks."""
import argparse
import json
import h5py
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write
from scripts.finite_wall_audit import segment_crossing_events,FACE_AXIS
from scripts.l1r_q2_mdbc_bridge import sha256


def run(name):
    a=json.loads((OUT/(name+'-AUDIT.json')).read_text())
    path=LAB/a['hdf5'];digest=sha256(path)
    if digest!=a['hdf5_sha256']:raise ValueError('audited source changed')
    rows=[];groups=[]
    with h5py.File(path) as h:
        t=h['time'][:];ids=h['particle_id'][:]
        previous=h['position'][0].astype(float);previous_valid=h['valid'][0]
        for fi in range(1,len(t)):
            p=h['position'][fi].astype(float);valid=h['valid'][fi]
            selected=np.flatnonzero(valid&previous_valid)
            for ev in segment_crossing_events(previous[selected],p[selected],a['wall_spec'],.51*a['dp_m']):
                if ev['kind']!='closed_face':raise ValueError('this report is restricted to plain tank faces')
                ix=int(selected[ev['point_index']]);axis,side=FACE_AXIS[ev['face']]
                bound=a['wall_spec']['container_interior']['xyz'[axis]+('max' if side else 'min')]
                rows.append(dict(particle_id=int(ids[ix]),face=ev['face'],frame=fi,
                    event_time_s=float(t[fi-1]+ev['fraction']*(t[fi]-t[fi-1])),
                    endpoint_outward_depth_m=float((1 if side else -1)*(p[ix,axis]-bound)),
                    samples=[dict(time_s=float(t[j]),valid=bool(h['valid'][j,ix]),
                        position_m=h['position'][j,ix].tolist() if h['valid'][j,ix] else None,
                        velocity_m_s=h['velocity'][j,ix].tolist() if h['valid'][j,ix] else None)
                        for j in range(max(0,fi-2),min(len(t),fi+4))]))
            previous=p;previous_valid=valid
        for pid,face in sorted(set((r['particle_id'],r['face']) for r in rows)):
            ix=int(np.flatnonzero(ids==pid)[0]);track=h['position'][:,ix,:].astype(float)
            axis,side=FACE_AXIS[face];bound=a['wall_spec']['container_interior']['xyz'[axis]+('max' if side else 'min')]
            depth=(1 if side else -1)*(track[:,axis]-bound);valid=h['valid'][:,ix]
            mask=(depth>0)&valid;outside=np.flatnonzero(mask)
            longest=streak=0
            for x in mask:
                streak=streak+1 if x else 0;longest=max(longest,streak)
            groups.append(dict(particle_id=pid,face=face,max_outward_depth_m=float(depth[valid].max()),
                outside_frames=len(outside),longest_consecutive_outside_frames=longest,
                first_outside_s=float(t[outside[0]]),last_outside_s=float(t[outside[-1]])))
    if len(rows)!=a['penetration']['swept_crossing_count']:raise ValueError('crossing count differs from audit')
    r=dict(case=name,source_sha256=digest,program_sha256=sha256(LAB/'scripts/f3_crossing_details.py'),
        crossing_count=len(rows),events=rows,tracks_summary=groups,qualified=False,
        interpretation='Saved endpoints are outside nominal finite wall planes; time is a linear-chord locator within a native saved interval. This diagnostic never overrides hard gates.')
    write(name+'-CROSSING-DETAIL.json',r)
    print(json.dumps({k:v for k,v in r.items() if k not in ('events','tracks_summary')},indent=2),flush=True)
    return r


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('name');a=p.parse_args();run(a.name)
