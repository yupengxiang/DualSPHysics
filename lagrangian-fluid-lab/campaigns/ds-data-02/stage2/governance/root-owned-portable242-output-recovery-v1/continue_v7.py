"""Admit a fresh portable retry, then publish the existing waiting handoff."""
from pathlib import Path
import datetime
import fcntl
import hashlib
import json
import subprocess

from launch_v5 import launch,UNIT,PYTHON,D,LAB,S
from prepare_v6 import prepare,sha
from external_storage_v1 import small

def ref(p):return {'path':str(p),'sha256':sha(p)}

def main():
    failed=S/'checkpoints/ROOT242_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json'
    f,_=small(failed);assert f['reservation_released'] and f['unit_cgroup_empty'] and f['repeat_cpu_fee_idempotent']
    failed13=S/'checkpoints/ROOT242_V13_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json';f13,_=small(failed13);assert f13['reservation_released'] and f13['unit_cgroup_empty'] and f13['repeat_cpu_fee_idempotent']
    failed14=S/'checkpoints/ROOT242_V14_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json';f14,_=small(failed14);assert f14['reservation_released'] and f14['unit_cgroup_empty'] and f14['repeat_cpu_fee_idempotent']
    barrier=S/'checkpoints/ROOT313_AFTER_NATIVE_ACTUAL_MASS_FULL_GOAL_CONTINUATION_V2.json';prior,_=small(barrier)
    for k in ['actual_lifecycle_terminal','actual_native_scope','actual_mass_proof']:assert sha(prior[k]['path'])==prior[k]['sha256']
    geometry=S/'checkpoints/GEOMETRY_SUPPORT_ACTUAL_ROOT_VERIFICATION_316.json';g,_=small(geometry)
    assert g['parent_reservation_released'] and g['repeat_fee_idempotent']
    request=prepare();launch(request)
    subprocess.run([PYTHON,'-B',str(Path(__file__).parent/'verify_v5.py'),str(request)],cwd=LAB,check=True)
    raw=subprocess.check_output(['systemctl','--user','show',UNIT,'-p','SubState','-p','MainPID'],text=True)
    u=dict(line.split('=',1) for line in raw.splitlines());assert u=={'MainPID':'0','SubState':'dead'}
    proof=S/'checkpoints/PORTABLE_TYPED_V15_ACTUAL_ROOT_VERIFICATION_242.json';p,_=small(proof)
    assert p['parent_reservation_released'] and p['repeat_fee_idempotent'] and p['exact_output_slot_rebound']
    checkpoint=S/'checkpoints/ROOT242_AFTER_MASS313_GEOMETRY316_PORTABLE_V11_FULL_GOAL_CONTINUATION_V2.json'
    v={'schema':'ds02.stage2.root-postmass-geometry-portable-continuation.v2','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'goal_status':'ACTIVE_FULL_SEVEN_ITEMS','goal_complete':False,'preceding_actual_mass_handoff':ref(barrier),'actual_lifecycle_terminal':prior['actual_lifecycle_terminal'],'actual_native_scope':prior['actual_native_scope'],'actual_geometry_support_proof':ref(geometry),'actual_portable_runtime_proof':ref(proof),'actual_portable_executor_version':14,'actual_portable_rebinder_version':15,'legacy_barrier_filename_for_frozen_waiters':True,'failed_portable_v11_lineage':ref(failed),'failed_portable_v13_lineage':ref(failed13),'failed_portable_v14_lineage':ref(failed14),'new_native_cause_or_join_credit':0,'scientific_Q_credit':0,'portable_cold_replay_credit':'NOT_CLAIMED','root_payload_content_read':False,'next':'Actual276/314/mass30/native117/GenCase9 prerequisites, then scientific field audits and actual fourteen reference terminal studies'}
    with checkpoint.open('x') as h:json.dump(v,h,indent=2);h.write('\n')
    print(json.dumps({'event':'ACTUAL_PORTABLE_V15_TERMINAL_HANDOFF','checkpoint':str(checkpoint),'goal_complete':False}),flush=True)

if __name__=='__main__':
    with (D/'runtime/root-owned-postmass-geometry-portable-v1.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
