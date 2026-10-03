"""Audit exported actual rigid history and typed nodes without substituting declared state."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import numpy as np

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(config, output):
    c=json.loads(config.read_text())
    for p in c['receipts']:
        r=json.loads(Path(p).read_text()); assert r['status']=='completed' and r['returncode']==0
    spec=importlib.util.spec_from_file_location('prepared_f6_state',c['helper']);helper=importlib.util.module_from_spec(spec);sys.modules[spec.name]=helper;spec.loader.exec_module(helper)
    root=ET.parse(c['generated_xml']).getroot();block=root.find('.//execution/particles/floating');n=int(block.get('count'));begin=int(block.get('begin'));cfg=dict(helper.CASE_CONFIGS[c['role']])
    cfg['expected_counts']=dict(cfg['expected_counts'], floating=n)
    cfg['massbody_kg']=float(block.find('massbody').get('value'));cfg['masspart_kg']=float(block.find('masspart').get('value'));cfg['derived_node_mass_kg']=cfg['massbody_kg']/n
    rows=helper.parse_floating_info_csv(c['floating_csv']);motion=helper.audit_floating_motion(rows,cfg['expected_angvelini'],cfg['expected_center'])
    with Path(c['floating_csv']).open() as f:
        native=list(csv.DictReader(f,delimiter=';'))
    time=np.array([float(r['time [s]']) for r in native]);assert len(time)==241 and time[0]==0 and time[-1]>=12 and (np.diff(time)>0).all()
    assert np.isfinite([[float(v) for v in r.values()] for r in native]).all()
    fields=['Pos.x [m]','Pos.y [m]','Pos.z [m]','Vel.x [m/s]','Vel.y [m/s]','Vel.z [m/s]','Mass [kg]','Idp','Zone','Type','Mk']
    data=[];source_times=[]
    for p in c['part_csvs']:
        with Path(p).open() as f:
            meta=next(csv.reader([f.readline()]));tline=next(csv.reader([f.readline()]));source_times.append(float(tline[0]))
            for skipped,line in enumerate(f,3):
                header=[x.strip() for x in next(csv.reader([line]))]
                if 'Pos.x [m]' in header:break
        a=np.loadtxt(p,delimiter=',',skiprows=skipped,usecols=[header.index(x) for x in fields]);assert a.shape==(n,len(fields)) and np.isfinite(a).all()
        assert (a[:,6]>0).all() and (a[:,8]==0).all() and (a[:,9]==2).all() and (a[:,10]==int(block.get('mk'))).all()
        assert np.array_equal(np.sort(a[:,7]),np.arange(begin,begin+n))
        data.append(helper.parse_floating_particles_csv(p))
    assert abs(source_times[0]-time[0])<=1e-6 and abs(source_times[1]-time[1])<=1e-6, 'Official PartVTK metadata rounds saved time to six decimals'
    nodes=helper.audit_floating_particles(data[0],data[1],cfg,motion['frame_0'],motion['frame_1'])
    checks={'actual_all_required_receipts_completed':True,'full241_saved_rigid_history_finite_and_monotone_through12':True,'both_native_node_frames_finite_typed_exact_UIDs':True,'native_and_rigid_rows_same_saved_times':True,'initial_rigid_state_matches_declared':motion['initial_rigid_state_verified'],'initial_native_nodes_verified':nodes['floating_nodes_verified'],'first_nonzero_native_velocity_matches_actual_rigid_state':nodes['frame_1']['kinematic_consistency']['consistent_with_rigid_kinematics']}
    result={'schema':'ds02.f6.root-actual-rigid-state-audit.v2','case_id':c['case_id'],'checks':checks,'all_actual_checks_passed':all(checks.values()),'actual_rigid_history':motion,'actual_typed_nodes':nodes,'actual_generated_massbody_kg':cfg['massbody_kg'],'actual_generated_interaction_masspart_kg':cfg['masspart_kg'],'derived_uniform_diagnostic_mass_kg':cfg['derived_node_mass_kg'],'generated_inertia_kg_m2':{k:float(block.find('inertia').get(k)) for k in 'xyz'},'source_sha256':{p:digest(p) for p in [str(config),c['helper'],c['generated_xml'],c['floating_csv'],*c['part_csvs'],*c['receipts']]},'q_n_status':'not_assessed','qualification':'Actual rigid/native initialization semantics only; no convergence approval or transfer from historical zero-spin reference.'}
    p=output/'actual-rigid-state-report-v2.json'
    if p.exists():raise FileExistsError(p)
    p.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':result['all_actual_checks_passed'],'checks':checks}),flush=True)
    return result['all_actual_checks_passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();sys.exit(0 if run(a.config,a.output_dir) else 1)
