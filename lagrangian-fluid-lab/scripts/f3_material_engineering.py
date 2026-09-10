"""Exercise independent seeds and unknown-aware labels on the short canary.

This consumes material configurations, not qualification or development cases.
The source has no spatial qualification, so outputs remain engineering evidence.
"""
import argparse
import json
import time
from pathlib import Path
import h5py
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write,resource_limits,material_usage
from scripts.l1r_q2_mdbc_bridge import sha256
from scripts.passive_tracers import advect_hdf5,box_surface_triangles


def run(substeps):
    name='F3_CELL3_plain_0p01'
    source=LAB/'campaigns/l1-resume/data/continuation'/(name+'.h5')
    prefix=LAB/'campaigns/l1-resume/data/f3-material-engineering'/f'{name}-512-s{substeps}'
    manifest=OUT/f'F3-MATERIAL-ENGINEERING-s{substeps}.json'
    if manifest.exists():
        previous=json.loads(manifest.read_text())
        if previous['status']=='completed':return previous
        raise ValueError('existing incomplete material attempt; inspect before retry')
    count=material_usage()
    if count>=resource_limits()['materials']:raise ValueError('material configuration cap')
    a=json.loads((OUT/(name+'-AUDIT.json')).read_text())
    if a['audit_status']!='pass_diagnostic' or a['hdf5_sha256']!=sha256(source):
        raise ValueError('canary integrity/provenance failed')
    axes=[lo+(np.arange(n)+.5)*size/n for lo,size,n in zip([-.45,-.09,0],[.9,.18,.09],[16,8,4])]
    seeds=np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1).reshape(-1,3)
    weights=np.full(len(seeds),1/len(seeds));labels=(seeds[:,0]>=0).astype(int)
    record=dict(status='running',case=name,source_sha256=sha256(source),seeds=512,
                substeps=substeps,configuration_charge=1,
                source_qualification='short canary integrity only; spatial/time reference pending',
                task_qualification='engineering only; no T2-macro or T2-path qualification',
                initial_rule='independent 16x8x4 equal-volume quadrature, not source particle identities',
                coordinate_frame='fixed tank coordinates',neighbours=24,regularization_m=.004,
                maximum_support_distance_m=.03,
                source_program_sha256=sha256(LAB/'scripts/passive_tracers.py'))
    write(manifest.name,record)
    triangles=box_surface_triangles([-.45,-.09,0],[.45,.09,.51],sides=('xmin','xmax','ymin','ymax','zmin'))
    def walls(h,f0,f1,alpha):return triangles
    start=time.monotonic()
    output=advect_hdf5(source,seeds,substeps_per_interval=substeps,barrier_provider=walls,
                      maximum_support_distance=.03,
                      support_gate={'minimum_effective_sample_size':4.,'minimum_geometry_rank':3,
                                    'minimum_anisotropy':.005,'maximum_reconstruction_error_mps':.05*np.sqrt(9.81*.09)})
    p=output['position'];ok=output['reliability_history'];times=output['time']
    first=np.full(len(seeds),np.nan)
    for frame in range(1,len(times)):
        crossed=(p[frame,:,0]>=0)!=(labels==1)
        select=crossed & ok[frame] & np.isnan(first)
        x0,x1=p[frame-1,select,0],p[frame,select,0]
        alpha=np.divide(-x0,x1-x0,out=np.ones_like(x0),where=x1!=x0)
        first[select]=times[frame-1]+np.clip(alpha,0,1)*(times[frame]-times[frame-1])
    terminal=np.where(ok[-1],(p[-1,:,0]>=0).astype(int),2)
    fractions=[float(weights[terminal==k].sum()) for k in (0,1,2)]
    prefix.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(prefix.with_suffix('.npz'),time=times,position=p,reliable=ok,
                        initial_position=seeds,weight=weights,source_label=labels,first_passage_s=first,
                        terminal_label=terminal,nearest_support_distance=output['nearest_support_distance'])
    record.update(status='completed',elapsed_seconds=time.monotonic()-start,
                  artifact=str(prefix.with_suffix('.npz').relative_to(LAB)),artifact_sha256=sha256(prefix.with_suffix('.npz')),
                  terminal_fractions_left_right_unknown=fractions,
                  observed_first_passage_fraction=float(weights[np.isfinite(first)].sum()),
                  unknown_fraction_by_time=(~ok@weights).tolist(),
                  support_gate=output['support_gate'],mass_ledger_closed=abs(sum(fractions)-1)<1e-12,
                  labels='first crossing x=0 to opposite source half; terminal left/right/unknown; no survivor renormalization')
    write(manifest.name,record)
    return record


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--substeps',type=int,choices=[2,4],required=True);a=p.parse_args()
    r=run(a.substeps);print(json.dumps({k:v for k,v in r.items() if k!='unknown_fraction_by_time'}),flush=True)
