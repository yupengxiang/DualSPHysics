"""Frozen affine-field material-path calibration with independent physical seeds."""
import json
import argparse
import time
import h5py
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write,ledger,resource_limits
from scripts.l1r_q2_mdbc_bridge import sha256
from scripts.passive_tracers import advect_hdf5,box_surface_triangles
from scripts.f3_material_labels import residence_times


def exact(points,t,kind):
    p=points.copy();v=np.zeros_like(p)
    if kind=='shear':
        p[:,0]+=t*p[:,1];v[:,0]=p[:,1]
    elif kind=='rotation':
        c,s=np.cos(t),np.sin(t);p[:,:2]=points[:,:2]@np.array([[c,s],[-s,c]])
        v[:,0]=-p[:,1];v[:,1]=p[:,0]
    else:raise ValueError(kind)
    return p,v


def run(revision='original'):
    suffix='' if revision=='original' else '-contact-v2'
    target=OUT/('F3-MATERIAL-AFFINE-CALIBRATION'+suffix+'.json')
    if target.exists():raise ValueError('calibration already registered; inspect without rerunning')
    ledger();budget=json.loads((OUT/'RESOURCE-LEDGER.json').read_text())
    if budget['material_configurations_used']+4>resource_limits()['materials']:
        raise ValueError('material configuration budget')
    times=np.linspace(0,.5,51)
    axes=[[-.021,-.007,.007,.021],[-.021,-.007,.007,.021],[.024,.036,.048,.060]]
    seeds=np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1).reshape(-1,3)
    record=dict(status='running',revision=revision,configuration_charge=4,configurations=[{'flow':kind,'dp_m':dp} for kind in ('shear','rotation') for dp in (.01,.006)],
        design=dict(rate_per_s=1.,time_window_s=[0,.5],output_interval_s=.01,substeps=2,seeds=64,
        same_physical_seeds_across_resolutions=True,seed_positions_m=seeds.tolist(),neighbours=24,regularization_m=.004,maximum_support_distance_m=.03,
        acceptance=dict(maximum_path_error_m=.001,maximum_residence_error_s=.01,required_reliable_fraction=1.,terminal_disagreement_fraction=0.)),
        scope='manufactured reference reconstruction calibration; not CFD source or full-window material qualification',
        program_sha256=sha256(LAB/'scripts/f3_material_calibration.py'),tracer_sha256=sha256(LAB/'scripts/passive_tracers.py'),results=[])
    write(target.name,record)
    folder=LAB/('campaigns/l1-resume/data/f3-material-calibration'+suffix);folder.mkdir(parents=True,exist_ok=True)
    walls=box_surface_triangles([-.45,-.09,0],[.45,.09,.51],sides=('xmin','xmax','ymin','ymax','zmin'))
    def barrier(h,f0,f1,alpha):return walls
    outputs={}
    for cfg in record['configurations']:
        start=time.monotonic();kind,dp=cfg['flow'],cfg['dp_m'];name=f'{kind}-dp{dp}'
        xy=np.arange(-.06,.060001,dp);z=np.arange(.005,.085001,dp)
        cloud=np.stack(np.meshgrid(xy,xy,z,indexing='ij'),axis=-1).reshape(-1,3)
        native=[exact(cloud,t,kind) for t in times];source=folder/(name+'.h5')
        with h5py.File(source,'w') as h:
            h['time']=times;h['position']=np.stack([p for p,v in native]);h['velocity']=np.stack([v for p,v in native])
            h['valid']=np.ones((len(times),len(cloud)),bool);h['type']=np.full((len(times),len(cloud)),3,np.int8)
        trace=advect_hdf5(source,seeds,substeps_per_interval=2,barrier_provider=barrier,maximum_support_distance=.03,
            support_gate={'minimum_effective_sample_size':4.,'minimum_geometry_rank':3,'minimum_anisotropy':.005,'maximum_reconstruction_error_mps':.05*np.sqrt(9.81*.09)})
        truth=np.stack([exact(seeds,t,kind)[0] for t in times]);pos=trace['position'];ok=trace['reliability_history']
        errors=np.linalg.norm(pos-truth,axis=-1);residence=residence_times(times,pos,ok)
        left=np.where(seeds[:,0]<0,.5,0.)
        crossed=(seeds[:,0]<0)!=(truth[-1,:,0]<0)
        crossing=(-seeds[:,0]/seeds[:,1]) if kind=='shear' else np.mod(np.arctan2(seeds[:,0],seeds[:,1]),np.pi)
        left[crossed]=np.where(seeds[crossed,0]<0,crossing[crossed],.5-crossing[crossed])
        terminal=np.where(ok[-1],(pos[-1,:,0]>=0).astype(int),2);expected=(truth[-1,:,0]>=0).astype(int)
        artifact=folder/(name+'.npz');np.savez_compressed(artifact,time=times,position=pos,truth=truth,reliable=ok,initial_position=seeds,residence_left_s=residence[0],exact_residence_left_s=left,terminal_label=terminal)
        row=dict(**cfg,source_sha256=sha256(source),artifact=str(artifact.relative_to(LAB)),artifact_sha256=sha256(artifact),
            max_path_error_m=float(errors.max()),max_path_error_over_dp=float(errors.max()/dp),reliable_fraction=float(ok.mean()),
            maximum_residence_error_s=float(np.max(np.abs(residence[0]-left))),terminal_disagreement_fraction=float(np.mean(terminal!=expected)),elapsed_seconds=time.monotonic()-start)
        row['passed']=bool(row['max_path_error_m']<=.001 and row['maximum_residence_error_s']<=.01 and ok.all() and row['terminal_disagreement_fraction']==0)
        record['results'].append(row);write(target.name,record);outputs[(kind,dp)]=pos
        print(json.dumps(row),flush=True)
    record['same_seed_cross_resolution_max_path_difference_m']={kind:float(np.linalg.norm(outputs[kind,.01]-outputs[kind,.006],axis=-1).max()) for kind in ('shear','rotation')}
    record.update(status='completed',calibrated=all(r['passed'] for r in record['results']),qualified_T2=False)
    write(target.name,record);ledger()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--revision',choices=['original','contact-v2'],default='original')
    run(p.parse_args().revision)
