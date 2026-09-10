"""Separate native domain loss, finite-wall penetration and chord diagnostics."""
import argparse
import json
from pathlib import Path
import h5py
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write
from scripts.l1r_q2_mdbc_bridge import sha256
from scripts.finite_wall_audit import outside_closed_face_masks,FACE_AXIS
from scripts.r6_n2_campaign import _partout_exclusion_evidence


def main(name):
    audit=json.loads((OUT/(name+'-AUDIT.json')).read_text())
    solver=json.loads((OUT/(name+'-SOLVER.json')).read_text())
    source=LAB/audit['hdf5']
    tol=.51*audit['dp_m']
    worst=None;first=None;longest=dict(consecutive_frames=0)
    with h5py.File(source,'r') as h:
        ids=h['particle_id'][:];times=h['time'][:]
        streak=np.zeros(len(ids),int)
        for fi,t in enumerate(times):
            p=h['position'][fi].astype(float);valid=h['valid'][fi]
            masks=outside_closed_face_masks(p,audit['wall_spec'],tol)
            union=np.zeros(len(ids),bool)
            for face,mask in masks.items():
                mask &= valid
                union |= mask
                ix=np.flatnonzero(mask)
                if not len(ix):continue
                axis,side=FACE_AXIS[face]
                bound=audit['wall_spec']['container_interior'][('xyz'[axis])+('min' if side==0 else 'max')]
                depth=(bound-p[ix,axis]) if side==0 else (p[ix,axis]-bound)
                chosen=ix[np.argmax(depth)]
                event=dict(frame=fi,time_s=float(t),face=face,particle_id=int(ids[chosen]),
                           position_m=p[chosen].tolist(),depth_from_nominal_wall_m=float(depth.max()),
                           excess_over_registered_tolerance_m=float(depth.max()-tol))
                if first is None:first=event
                if worst is None or event['depth_from_nominal_wall_m']>worst['depth_from_nominal_wall_m']:worst=event
            streak=np.where(union,streak+1,0)
            ix=int(np.argmax(streak))
            if streak[ix]>longest['consecutive_frames']:
                longest=dict(consecutive_frames=int(streak[ix]),particle_id=int(ids[ix]),
                             start_s=float(times[fi-streak[ix]+1]),end_s=float(t))
        tracks={}
        for event in (first,worst):
            if event is None:continue
            ix=int(np.flatnonzero(ids==event['particle_id'])[0]);fi=event['frame']
            tracks[str(event['particle_id'])]=[
                dict(time_s=float(times[j]),valid=bool(h['valid'][j,ix]),
                     position_m=h['position'][j,ix].tolist() if h['valid'][j,ix] else None,
                     velocity_m_s=h['velocity'][j,ix].tolist() if h['valid'][j,ix] else None)
                for j in range(max(0,fi-3),min(len(times),fi+4))]
    excluded=_partout_exclusion_evidence(Path(solver['attempt_directory']))
    rows=excluded['rows'];domain=audit['wall_spec']['runtime_domain']
    categories={}
    for row in rows:
        for axis in 'xyz':
            j='xyz'.index(axis)
            for side,sign in [('min',-1),('max',1)]:
                key=axis+side
                if sign*(row['position_m'][j]-domain[key])>0:
                    categories[key]=categories.get(key,0)+1
    result=dict(case=name,source_sha256=sha256(source),tolerance_m=tol,
                first_true_penetration=first,worst_true_penetration=worst,longest_penetration=longest,
                local_tracks=tracks,excluded_count=len(rows),native_reason_counts=excluded['reason_counts'],
                runtime_face_counts=categories,first_native_exclusion=rows[0] if rows else None,
                saved_frame_loss_count=audit['initial_identities_missing_at_final'],
                loss_reconciled=len(rows)==audit['initial_identities_missing_at_final']==audit['excluded_particles_from_solver_log'],
                chord_event_count=audit['penetration']['swept_crossing_count'],
                interpretation='Chord plane crossings are separate from tolerance exceedance. Native position exclusions are not density failure. Domain expansion alone cannot repair finite-wall penetration.',
                current_recipe_qualified=False)
    write(name+'-FORENSICS.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='local_tracks'},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('name');a=p.parse_args();main(a.name)
