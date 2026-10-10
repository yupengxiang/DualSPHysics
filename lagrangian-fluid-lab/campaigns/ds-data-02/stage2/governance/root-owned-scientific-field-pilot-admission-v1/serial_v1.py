"""Run seven independently source-checked H5 pilots under serial V10 parents.

ROOT reads only bounded metadata/code; the bound V3 child streams production
H5 after reservation. Scientific qualification and physical authority remain
UNKNOWN. All observations, failed attempts, and complete fees are preserved.
"""
from pathlib import Path
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import time

HERE=Path(__file__).resolve().parent;S=HERE.parents[1];LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PY='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
INDEX=S/'requests/scientific-field-h5-seven-pilots-v10-v3-root-primary-001/scientific-field-h5-pilot-v10-request-index.json'
GATE=S/'checkpoints/SCIENTIFIC_FIELD_H5_SEVEN_PILOT_V10_V7_SOURCE_VERIFICATION_V1.json'
UNKNOWN={'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'}

def sha(p):
    p=Path(p);assert not p.is_symlink() and p.is_file() and p.stat().st_size<=10485760
    assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.vtu','.pvtu','.jsonl'}
    a=p.stat();b=p.read_bytes();z=p.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns)
    return hashlib.sha256(b).hexdigest()

def load(p):sha(p);return json.loads(Path(p).read_text())
def ref(p):return {'path':str(p),'sha256':sha(p)}
def new(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')

def state(unit):
    raw=subprocess.check_output(['systemctl','--user','show',unit,'-p','SubState','-p','MainPID','-p','Result','-p','CPUUsageNSec'],text=True)
    return dict(line.split('=',1) for line in raw.splitlines())

def seal(row,num):
    source=Path(row['request']['path']);assert sha(source)==row['request']['sha256'];q=load(source)
    q['attempt_id']=f'root{num}-scientific-field-h5-v3-v10-actual-pilot-001'
    q['root_scientific_field_pilot_binding']={'namespace':num,'source_request':ref(source),'source_index':ref(INDEX),'source_gate':ref(GATE),'root_payload_content_read':False,'qualification':UNKNOWN}
    common=S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    footer=S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py'
    extras=[Path(__file__),source,INDEX,GATE,common,footer,LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py']
    q['input_files']=list(dict.fromkeys(q['input_files']+list(map(str,extras))))
    old=dict(q['input_sha256']);hashes={p:sha(p) for p in q['input_files']}
    for p,h in old.items():assert hashes[p]==h,p
    q['input_sha256']=hashes;q['input_hashes']=hashes
    out=S/f'requests/scientific-field-h5-v3-v10-actual-pilot-root-{num}-001.json'
    new(out,q);return out

def launch(qp,num):
    q=load(qp);l=load(D/'runtime/resource-ledger.json');assert not l['reservations']
    assert datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=q['max_wall_seconds']+90)<datetime.datetime.fromisoformat(l['deadline_utc'])
    assert sum(x.get('cpu_core_seconds',0) for x in l['charges'])+q['cpu_threads']*q['max_wall_seconds']<l['limits']['cpu_core_seconds']
    disk=os.statvfs(l['limits']['home_path']);assert disk.f_bavail*disk.f_frsize-q['estimated_storage_bytes']>=l['limits']['home_min_free_bytes']
    assert q['cpu_threads']==1 and q['estimated_storage_bytes']==48234496 and q['command'][0]==PY
    assert not (D/'families'/q['family_id']/q['case_id']/q['attempt_id']).exists()
    for p,h in q['input_sha256'].items():assert sha(p)==h,p
    unit=f'ds02-scientific-field-h5-v3-v10-root-{num}'
    code='import sys,os,json;sys.path.insert(0,'+repr(str(LAB/'scripts'))+');from ds_data02_runtime_v10_git_bound import run_request;r=run_request('+repr(str(qp))+',data_root='+repr(str(D))+',parent_pid=os.getppid());print(json.dumps(r));raise SystemExit(0 if r["status"]=="completed" else 1)'
    argv=['systemd-run','--user','--unit='+unit,'--working-directory='+str(LAB),'--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec='+str(q['max_wall_seconds']+60),'--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes','--property=MemoryAccounting=yes','--property=MemoryMax='+str(q['max_memory_bytes'])]
    argv+=['--setenv='+k+'=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    argv+=[PY,'-B','-I','-c',code];subprocess.run(argv,check=True)
    while True:
        u=state(unit)
        if u['SubState']!='running':break
        print(json.dumps({'event':'RUNNING_ACTUAL_H5_FIELD_PILOT','namespace':num,'family':q['family_id'],'cpu_seconds':int(u['CPUUsageNSec'])/1e9}),flush=True);time.sleep(30)
    assert u['MainPID']=='0'
    assert u['SubState']=='exited' and u['Result']=='success',u
    return unit

def verify(qp,num):
    common=S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    ctx={'__file__':str(common),'__name__':'root_actual_scientific_field_pilot'}
    exec(common.read_text(),ctx);ctx.update(sha=sha,load=load)
    q,b,r,p=ctx['common'](qp)
    manifest=Path(q['manifest_contract']['path']);assert sha(manifest)==q['manifest_contract']['sha256']
    report=b/'scientific-field-h5-audit.json';actual=load(report)
    assert actual['schema']=='ds02.stage2.scientific-field-h5-audit.v3' and actual['status']=='COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT'
    assert actual['counts']=={'requested':1,'completed':1,'failed':0}
    independent=S/f'checkpoints/ROOT{num}_SCIENTIFIC_FIELD_H5_INDEPENDENT_V5.json'
    verifier=LAB/'scripts/ds_data02_stage2_verify_scientific_field_h5_audit_v5.py'
    subprocess.run([PY,'-B',str(verifier),'verify','--manifest',str(manifest),'--report',str(report),'--output',str(independent)],cwd=LAB,check=True)
    v=load(independent);assert v['status']=='VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT' and v['case_count']==1
    assert {x['physical_case_id'] for x in v['cases']}=={q['case_id']}
    p.update(status='VERIFIED_ACTUAL_PRODUCTION_H5_FIELD_SCAN_METADATA_CLOSURE_NO_PHYSICAL_Q',report=str(report),report_sha256=sha(report),manifest=str(manifest),manifest_sha256=sha(manifest),independent_verification=str(independent),independent_verification_sha256=sha(independent),case_verifications=v['cases'],actual_production_h5_scan=True,root_h5_payload_content_read=False,units_material_physical_authority='UNKNOWN',scientific_Q_credit=0,source_index=ref(INDEX),source_gate=ref(GATE))
    footer=(S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text()
    footer=footer.replace('1073741824',str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json',f'SCIENTIFIC_FIELD_H5_ACTUAL_ROOT_VERIFICATION_{num}.json')
    ctx.update(q=q,b=b,r=r,p=p,qp=qp,num=str(num),name='scientific-field-h5-v3-v10',subprocess=subprocess,importlib=importlib)
    exec(footer,ctx)
    proof=S/f'checkpoints/SCIENTIFIC_FIELD_H5_ACTUAL_ROOT_VERIFICATION_{num}.json'
    assert state(f'ds02-scientific-field-h5-v3-v10-root-{num}')['SubState']=='dead'
    return proof

def main():
    gate=load(GATE);assert gate['status']=='VERIFIED_SOURCE_PREPARED_SEVEN_SINGLE_CASE_V3_NOT_RUN' and gate['case_count']==7
    index=load(INDEX);assert sha(INDEX)=='8f3c0cd76029a256df6cac9feac956d155536dd9d82ec491c52f757905bf6d9a'
    proofs=[]
    for num,row in zip(range(346,353),index['requests']):
        qp=seal(row,num);launch(qp,num);proof=verify(qp,num);proofs.append(ref(proof))
        p=load(proof)
        cp=S/f'checkpoints/ROOT{num}_ACTUAL_SCIENTIFIC_FIELD_H5_PILOT_HANDOFF_V1.json'
        new(cp,{'schema':'ds02.stage2.root-actual-scientific-field-pilot-handoff.v1','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actual_pilot_count':len(proofs),'actual_proofs':list(proofs),'source_index':ref(INDEX),'selected_case_id':row['physical_case_id'],'full_cpu_seconds':p['full_systemd_cpu_seconds'],'production_scientific_Q_credit':0,'goal_complete':False,'goal_status':'ACTIVE_FULL_SEVEN_ITEMS','next':'Use actual pilot throughput to admit remaining guarded335 field audit groups and continue independent portable/reference chain'})
        print(json.dumps({'event':'ACTUAL_FIELD_PILOT_CLOSED','namespace':num,'pilot_count':len(proofs),'proof':str(proof),'goal_complete':False}),flush=True)

if __name__=='__main__':
    with (D/'runtime/root-owned-scientific-field-pilots-v1.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
