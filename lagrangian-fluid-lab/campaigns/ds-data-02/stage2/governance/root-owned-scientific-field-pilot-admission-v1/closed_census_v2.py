"""Snapshot exact closed field parents using bounded control metadata only.

The source gate binds the original 23 actual cases. Additional closed parents
are deduplicated by physical identity; an active next parent is not counted.
No payload is opened, hashed, or traversed. This is not scientific Q evidence.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import math
import os
import subprocess

S = Path(__file__).resolve().parents[2]
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
GATE = S/'checkpoints/SCIENTIFIC_FIELD_H5_REMAINING_V4_ALL311_SOURCE_ACTUAL23_GATE_V1.json'
FORBIDDEN = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.pvtu', '.jsonl'}
STATUS = 'VERIFIED_ACTUAL_PRODUCTION_H5_FIELD_SCAN_METADATA_CLOSURE_NO_PHYSICAL_Q'

def read(path):
    p = Path(path)
    assert p.suffix.lower() not in FORBIDDEN and not p.is_symlink()
    a = p.stat()
    assert p.is_file() and a.st_size <= 10485760
    data = p.read_bytes()
    b = p.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns) == (b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns)
    return json.loads(data), {'path': str(p), 'sha256': hashlib.sha256(data).hexdigest()}

def bound(path, digest):
    value, reference = read(path)
    assert reference['sha256'] == digest, path
    return value

def actual(path):
    p, reference = read(path)
    assert p['status'] == STATUS and p['actual_production_h5_scan'] is True
    assert p['parent_reservation_released'] is True and p['repeat_fee_idempotent'] is True
    assert p['scientific_Q_credit'] == 0 and p['root_h5_payload_content_read'] is False
    q = bound(p['request'], p['request_sha256'])
    manifest = bound(p['manifest'], p['manifest_sha256'])
    independent = bound(p['independent_verification'], p['independent_verification_sha256'])
    assert independent['status'] == 'VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT'
    assert independent['case_count'] == 1 and len(manifest['cases']) == 1
    case = manifest['cases'][0]
    assert case['physical_case_id'] == q['case_id'] == independent['cases'][0]['physical_case_id']
    assert case['family_id'] == q['family_id']
    bound(p['receipt'], p['receipt_sha256'])
    bound(p['systemd_evidence'], p['systemd_evidence_sha256'])
    bound(p['terminal_cpu_reconciliation'], p['terminal_cpu_reconciliation_sha256'])
    unit = 'ds02-scientific-field-h5-v3-v10-root-' + q['attempt_id'].split('-')[0][4:]
    state = subprocess.check_output(['systemctl','--user','show',unit,'-p','SubState','-p','MainPID'], text=True)
    assert 'SubState=dead' in state and 'MainPID=0' in state, (unit,state)
    seconds = p['full_systemd_cpu_seconds']
    assert isinstance(seconds,(int,float)) and math.isfinite(seconds) and seconds >= 0
    return {'actual_proof':reference,'physical_case_id':q['case_id'],'family_id':q['family_id'],
            'source_h5_bytes':case['trajectory_h5']['bytes'],
            'full_cpu_seconds':seconds,'scientific_Q_credit':0,
            'request':{'path':p['request'],'sha256':p['request_sha256']}}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--through',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    assert 380 <= args.through <= 690 and not args.output.exists()
    gate, gate_ref=read(GATE)
    base_refs=gate['actual_pilot_proofs'] + gate['previous_actual_remaining_proofs']
    assert len(base_refs)==23
    base=[]
    for r in base_refs:
        value=actual(r['path'])
        assert value['actual_proof']==r
        base.append(value)
    additional=[]
    for n in range(380,args.through+1):
        value=actual(S/f'checkpoints/SCIENTIFIC_FIELD_H5_ACTUAL_ROOT_VERIFICATION_{n}.json')
        p,_=read(value['actual_proof']['path'])
        assert p['source_gate']==gate_ref
        assert value['physical_case_id']==gate['selected_cases'][n-380]
        value['namespace']=n
        additional.append(value)
    identities=[r['physical_case_id'] for r in base+additional]
    assert len(set(identities))==len(identities)
    ledger, ledger_ref=read(D/'runtime/resource-ledger.json')
    home=os.statvfs(ledger['limits']['home_path']); external=os.statvfs('/var/tmp')
    total=len(identities)
    result={'schema':'ds02.stage2.closed-actual-field-census.v2',
        'status':'EXACT_ACTUAL_FIELD_PROOFS_CLOSED_NOT_SCIENTIFIC_QUALIFICATION',
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_gate':gate_ref,'base_actual_rows':base,'additional_actual_rows':additional,
        'actual_canonical_field_cases_total':total,'canonical_source_count':335,
        'canonical_unscanned_count':335-total,'remaining_executable_count':334-total,
        'missing_case_manifest_unknown_count':1,'alias_unknown_count':1,
        'additional_full_cpu_seconds':sum(r['full_cpu_seconds'] for r in additional),
        'additional_source_h5_bytes':sum(r['source_h5_bytes'] for r in additional),
        'estimated_minimum_read_bytes_additional':3*sum(r['source_h5_bytes'] for r in additional),
        'ledger_snapshot':ledger_ref,'active_reservation_count':len(ledger['reservations']),
        'active_reservations':ledger['reservations'],
        'ledger_cpu_core_hours':sum(r.get('cpu_core_seconds',0) for r in ledger['charges'])/3600,
        'ledger_gpu_hours':sum(r.get('gpu_seconds',0) for r in ledger['charges'])/3600,
        'qualification_attempts_used':sum(r['kind']=='qualification' for r in ledger['attempts']),
        'production_attempts_used':sum(r['kind']=='production' for r in ledger['attempts']),
        'home_free_bytes':home.f_bavail*home.f_frsize,
        'external_free_bytes':external.f_bavail*external.f_frsize,
        'deadline_utc':ledger['deadline_utc'],'root_payload_content_read':False,
        'scientific_Q_credit':0,'goal_complete':False,'goal_status':'ACTIVE_FULL_SEVEN_ITEMS'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps({k:result[k] for k in ['status','actual_canonical_field_cases_total','remaining_executable_count','active_reservation_count','additional_full_cpu_seconds','scientific_Q_credit','goal_complete']}))

if __name__=='__main__':main()
