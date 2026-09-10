"""Freeze independent forcing cases and public development splits; no CFD launch."""
import argparse
import hashlib
import json
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write
from scripts.l1r_q2_mdbc_bridge import sha256

REGISTRY='F3-DEVELOPMENT-CANDIDATES.json'
PILOT={0,6,12,13,18,19,25,31}
VALIDATION={8,13,18,23}
INITIAL={'tank_bounds_m':[-.45,.45,-.09,.09,0.,.51],'open_face':'top','water_depth_m':.09,'initial_velocity_mps':[0.,0.,0.],'initial_density_rule':'registered hydrostatic initialization','coordinate_frame':'fixed computational tank'}


def semantic_hash(values):
    a=np.array(values,dtype='<f8',copy=True)
    if a.ndim!=2 or a.shape[1]!=7 or not np.isfinite(a).all():raise ValueError('invalid forcing array')
    a[a==0]=0.
    return hashlib.sha256(a.tobytes()).hexdigest()


def candidates():
    rows=[]
    for i in range(32):
        amplitude=.9+(i+.5)*.2/32
        role='train' if 6<=i<=25 and i not in VALIDATION else ('validation' if i in VALIDATION else 'test')
        rows.append(dict(case_id=f'F3_DEV_{i:02d}_a{amplitude:.6f}'.replace('.','p'),index=i,drive_amplitude=amplitude,
            split=role,evaluation_role={'train':'training','validation':'development_interpolation','test':'development_extrapolation'}[role],pilot=i in PILOT))
    return rows


def validate(rows):
    if len(rows)!=32 or len({r['case_id'] for r in rows})!=32:raise ValueError('case count or duplicate case IDs')
    if len({r['effective_control_sha256'] for r in rows})!=32:raise ValueError('duplicate effective control crosses physical-case definitions')
    if len({r['physical_lineage_sha256'] for r in rows})!=32:raise ValueError('duplicate physical lineage')
    if sum(r['pilot'] for r in rows)!=8:raise ValueError('pilot must contain eight distinct physical cases')
    train=[r['drive_amplitude'] for r in rows if r['split']=='train'];low,high=min(train),max(train)
    if [sum(r['split']==s for r in rows) for s in ('train','validation','test')]!=[16,4,12]:raise ValueError('registered role counts changed')
    for r in rows:
        a=r['drive_amplitude']
        if not .9<a<1.1 or any(abs(a-x)<1e-10 for x in (.9,.97,1.,1.1)):raise ValueError('outside target domain or overlap with qualification case')
        if r['split']=='validation' and not low<a<high:raise ValueError('interpolation case outside training axis support')
        if r['split']=='test' and low<=a<=high:raise ValueError('extrapolation case inside training axis support')
    return dict(train_amplitude_support=[low,high],physical_cases=32,pilot_cases=8,role_counts={'train':16,'development_interpolation':4,'development_extrapolation':12})


def register():
    target=OUT/REGISTRY
    if target.exists():raise ValueError('registry already exists; use check or inspect partial preparation')
    source=LAB/'vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAccData.csv'
    nominal=np.loadtxt(source,delimiter=';',comments='#');g=np.array([0.,0.,-9.81])
    folder=LAB/'campaigns/l1-resume/data/f3-development-inputs';folder.mkdir(parents=True,exist_ok=True)
    record=dict(status='preparing_inputs',source_drive_sha256=sha256(source),program_sha256=sha256(LAB/'scripts/f3_development_candidates.py'),initial_physical_definition=INITIAL,
        cases=[],completed_development_solver_attempts=0,completed_training_attempts=0,launch_allowed=False,
        prerequisite='qualified reproducible recipe and .9-1.1 control domain, full-window hard audits, frozen scoring and input contracts',
        split_semantics='All are public development cases, including the test-labelled extrapolation role. Shared initial water geometry is intentional; independence is distinct full effective forcing plus initial physical definition, not different initial states or arbitrary time windows.',
        expansion='Run registered pilot eight first. Stop expansion on new systematic physical failures; do not replace failures with new draws. Then complete the remaining24 to total32 under the development40 cap.',
        learning_plan={'routes':['particle_mlp','local_interaction'],'final_seeds':[17,29,43],'pilot_training_attempts':2,'final_training_attempts':6,'training_attempt_reserve':4,'max_training_attempts':12,'input_adapter':'scripts/f3_learning_inputs.py','score_scope':'autonomous position/velocity/distribution, qualified transport tasks only, all failures and cost; raw/stabilized outputs separate'})
    write(REGISTRY,record)
    for row in candidates():
        a=nominal.copy();amplitude=row['drive_amplitude'];a[:,1:4]=g+amplitude*(a[:,1:4]-g);a[:,4:]*=amplitude
        path=folder/(row['case_id']+'.csv')
        if path.exists():raise ValueError('pre-existing control asset; do not overwrite')
        tmp=path.with_suffix('.partial');np.savetxt(tmp,a,delimiter=';',fmt='%.17g',header='Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ');tmp.replace(path)
        effective=semantic_hash(a);lineage=hashlib.sha256(json.dumps({'initial':INITIAL,'effective_control_sha256':effective},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        row.update(control_path=str(path.relative_to(LAB)),control_file_sha256=sha256(path),effective_control_sha256=effective,physical_lineage_sha256=lineage)
        record['cases'].append(row);write(REGISTRY,record)
        if len(record['cases'])%8==0:print('prepared controls',len(record['cases']),flush=True)
    record.update(status='inputs_registered_no_fluid_data',split_check=validate(record['cases']))
    write(REGISTRY,record);print(json.dumps(record['split_check']),flush=True)


def check():
    r=json.loads((OUT/REGISTRY).read_text());v=validate(r['cases'])
    source=LAB/'vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAccData.csv'
    if sha256(source)!=r['source_drive_sha256']:raise ValueError('source drive changed')
    nominal=np.loadtxt(source,delimiter=';',comments='#');g=np.array([0.,0.,-9.81])
    for row in r['cases']:
        path=LAB/row['control_path'];a=np.loadtxt(path,delimiter=';',comments='#')
        expected=nominal.copy();expected[:,1:4]=g+row['drive_amplitude']*(expected[:,1:4]-g);expected[:,4:]*=row['drive_amplitude']
        if sha256(path)!=row['control_file_sha256'] or semantic_hash(a)!=row['effective_control_sha256'] or not np.array_equal(a,expected):raise ValueError('changed or inconsistent forcing')
        digest=hashlib.sha256(json.dumps({'initial':r['initial_physical_definition'],'effective_control_sha256':semantic_hash(a)},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if digest!=row['physical_lineage_sha256']:raise ValueError('physical lineage changed')
    print(json.dumps(v),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['register','check']);a=p.parse_args()
    (register if a.action=='register' else check)()
