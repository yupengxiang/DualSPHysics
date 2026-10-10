"""Serially construct nine actual initial states after a closed field boundary.

This route does not publish the legacy ROOT321/ROOT345 barriers. Native mass,
continuous owner equivalence and all scientific Q await actual downstream
audits. Original producer sources and the old waiting queue stay immutable.
"""
from pathlib import Path
import argparse
import datetime
import fcntl
import importlib
import json
import os
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent;S=HERE.parents[1];LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PY='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
OLD=S/'governance/root-owned-owner-grid-admission-v2'
ROUTE=S/'checkpoints/ROOT_NINE_GENCASE_INDEPENDENT_SOURCE_DEPENDENCY_V2.json'
MANIFEST=S/'requests/three-sentinel-owner-grid-gencase-v3-primary-admission-source-001/owner-grid-gencase-root-admission-manifest-v3.json'

def launch(qp,num,admission,stat_record):
    q=admission.load(qp)
    assert q['execution_allowed'] and not q['source_only'] and not q['launch_disabled']
    assert q['cpu_threads']==1 and q['max_memory_bytes']==4294967296
    assert q['max_wall_seconds']==1800 and q['estimated_storage_bytes']<=8589934592
    controls={r['path']:r for r in q['root_exact_auxiliary_closure']}
    for p,h in q['input_sha256'].items():
        if p in controls and controls[p]['root_content_read'] is False:
            assert stat_record(p)==controls[p]['stat'] and h==controls[p]['sha256']
        else:assert admission.sha(p)==h,p
    ledger=admission.load(D/'runtime/resource-ledger.json')
    assert not ledger['reservations']
    assert datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=1860)<datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert sum(r.get('cpu_core_seconds',0) for r in ledger['charges'])+1800<ledger['limits']['cpu_core_seconds']
    disk=os.statvfs(ledger['limits']['home_path'])
    assert disk.f_bavail*disk.f_frsize-q['estimated_storage_bytes']>=ledger['limits']['home_min_free_bytes']
    assert not Path(q['output_root']).exists()
    code='import sys,os,json;sys.path.insert(0,'+repr(str(LAB/'scripts'))+');from ds_data02_runtime_v10_git_bound import run_request;r=run_request('+repr(str(qp))+',data_root='+repr(str(D))+',parent_pid=os.getppid());print(json.dumps(r));raise SystemExit(0 if r["status"]=="completed" else 1)'
    unit=f'ds02-owner-grid-gencase-v3-root-{num}'
    argv=['systemd-run','--user','--unit='+unit,'--working-directory='+str(LAB),
        '--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec=1860',
        '--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes',
        '--property=MemoryAccounting=yes','--property=MemoryMax=4294967296']
    argv+=['--setenv='+k+'=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    subprocess.run(argv+[PY,'-B','-I','-c',code],check=True)
    while True:
        state=admission.state(unit)
        if state['SubState']!='running':break
        print(json.dumps({'event':'RUNNING_INDEPENDENT_ACTUAL_GENCASE','namespace':num,
            'row_key':q['row_key'],'cpu_seconds':int(state['CPUUsageNSec'])/1e9}),flush=True)
        time.sleep(30)
    assert state['SubState']=='exited' and state['MainPID']=='0' and state['Result']=='success',state

def main(predecessor):
    assert Path.cwd()==LAB
    sys.path.insert(0,str(HERE));import prepare_v1 as prep
    admission=prep.module(S/'governance/root-owned-native-admission-v1/continue_after_serial_v1.py','independent_nine_admission')
    old_prep=prep.module(OLD/'prepare_actual_gencase_v2.py','independent_nine_original_preflight')
    census=admission.load(predecessor)
    assert census['schema']=='ds02.stage2.closed-actual-field-census.v2'
    assert census['active_reservation_count']==0 and census['scientific_Q_credit']==0
    assert not admission.load(D/'runtime/resource-ledger.json')['reservations']
    marker=admission.load(S/'checkpoints/ROOT_FIELD_REMAINING_CASE_BOUNDARY_YIELD_380_V1.json')
    assert marker['yield_after_current_case'] is True and marker['source_gate']==census['source_gate']
    manifest=admission.load(MANIFEST);route=admission.load(ROUTE)
    assert admission.ref(MANIFEST)['sha256']==route['source_manifest']['sha256']
    assert len(manifest['producer_requests'])==9
    products=[];actual=[];previous=predecessor
    common=S/'governance/root-owned-lifecycle-continuation-v1'
    extras=[Path(__file__),MANIFEST,ROUTE,OLD/'verify_actual_gencase_v2.py',
        common/'root_common_verification.py',common/'root_cpu_verification_footer.py',common/'root_forward_metadata.py',
        LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py']
    for num,item in zip(range(700,709),manifest['producer_requests']):
        source=Path(item['path']);assert admission.sha(source)==item['sha256']
        qp=prep.prepare(source,num,previous,extras)
        launch(qp,num,admission,old_prep.stat_record)
        subprocess.run([PY,'-B',str(OLD/'verify_actual_gencase_v2.py'),str(num),'--request',str(qp)],cwd=LAB,check=True)
        proof_path=S/f'checkpoints/ROOT{num}_OWNER_GRID_GENCASE_ACTUAL_ROOT_VERIFICATION_V2.json'
        proof=admission.load(proof_path);q=admission.load(qp)
        assert proof['parent_reservation_released'] and proof['repeat_fee_idempotent']
        assert admission.state(f'ds02-owner-grid-gencase-v3-root-{num}')['SubState']=='dead'
        products.append(dict(proof['products'],sentinel_id=q['sentinel_id'],grid_label=q['grid_label'],
            row_key=q['row_key'],physical_case_id=q['physical_case_id'],family_id=q['family_id'],
            case_id=q['case_id'],attempt_id=q['attempt_id'],planned_output_root=q['output_root'],
            producer_request=admission.ref(qp),actual_producer_proof=admission.ref(proof_path),
            status='ACTUAL_GENCASE_PRODUCTS_AWAIT_INITIAL_SUPPORT_AUDIT',
            actual_auxiliary_runtime_closure=q['root_exact_auxiliary_closure'],
            actual_staged_worker_report=proof.get('staged_worker_report'),
            actual_control_cwd=str(Path(q['output_root'])/'inputs/F3_S1'/q['grid_label']) if q['root_canonical_gencase_binding']['staged_worker'] else q['cwd']))
        actual.append({'namespace':num,'request':admission.ref(qp),'actual_proof':admission.ref(proof_path)})
        cp=S/f'checkpoints/ROOT{num}_INDEPENDENT_OWNER_GRID_GENCASE_ACTUAL_HANDOFF_V1.json'
        admission.new(cp,{'schema':'ds02.stage2.independent-nine-gencase-actual-handoff.v1',
            'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'actual_preceding_handoff':admission.ref(previous),'source_dependency_route':admission.ref(ROUTE),
            'actual_gencase_count':len(actual),'actual_gencase_proofs':list(actual),
            'old_native321_barrier_consumed':False,'initial_support_audited':False,
            'root_native_vtk_payload_content_read':False,'scientific_Q_credit':0,'goal_complete':False})
        previous=cp
        print(json.dumps({'event':'INDEPENDENT_ACTUAL_GENCASE_CLOSED','namespace':num,'actual_count':len(actual),'goal_complete':False}),flush=True)
    directory=S/'requests/three-sentinel-owner-grid-independent-actual-products-root708-001'
    directory.mkdir()
    product_map=directory/'owner-grid-actual-gencase-product-map-v2.json'
    admission.new(product_map,{'schema':'ds02.stage2.three-sentinel.owner-grid-gencase-product-map.v2',
        'status':'NINE_ACTUAL_GENCASE_PRODUCTS_DEFERRED_NATIVE_HASH_INITIAL_AUDIT_REQUIRED',
        'owner_report':manifest['owner_report'],'products':products,'actual_terminal':admission.ref(previous),
        'independent_source_route':admission.ref(ROUTE),'generated_native_payload_read_by_root':False,
        'scientific_Q_credit':0,'goal_complete':False})
    admission.new(S/'checkpoints/ROOT708_NINE_INDEPENDENT_GENCASE_ACTUAL_PRODUCTS_HANDOFF_V1.json',{
        'schema':'ds02.stage2.independent-nine-gencase-actual-products-handoff.v1',
        'actual_serial_terminal':admission.ref(previous),'actual_product_map':admission.ref(product_map),
        'actual_gencase_count':9,'initial_support_audited':False,'old_native321_barrier_consumed':False,
        'scientific_Q_credit':0,'goal_complete':False})

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predecessor',type=Path,required=True)
    args=parser.parse_args()
    with (D/'runtime/root-owned-independent-nine-gencase-v1.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);main(args.predecessor.absolute())
