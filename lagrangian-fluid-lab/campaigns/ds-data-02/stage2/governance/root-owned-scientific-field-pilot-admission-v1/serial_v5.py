"""Resume after an immutable yield and a genuinely closed intervening parent.

The V4 source, consumed requests, proofs, and yield markers remain unchanged.
Only exact closed parents are reused, with no H5 reread. New requests bind this
controller and its immutable grant. A fresh marker can yield again between cases.
"""
from pathlib import Path
import argparse
import datetime
import fcntl
import importlib.util
import json

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('root_field_serial_v4',HERE/'serial_v4.py')
base=importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
S=base.S;D=base.D;GATE=base.GATE;INDEX=base.INDEX

def validate_grant(path):
    grant=base.load(path)
    assert grant['schema']=='ds02.stage2.root-field-boundary-resume-grant.v1'
    assert grant['source_gate']==base.ref(GATE)
    assert grant['field_controller_source']==base.ref(Path(__file__))
    previous=grant['preceding_yield_marker']
    assert base.sha(previous['path'])==previous['sha256']
    marker=base.load(previous['path'])
    assert marker['schema']=='ds02.stage2.root-field-case-boundary-yield.v1'
    assert marker['source_gate']==base.ref(GATE) and marker['yield_after_current_case'] is True
    census_ref=grant['closed_field_census']
    assert base.sha(census_ref['path'])==census_ref['sha256']
    census=base.load(census_ref['path'])
    assert census['schema']=='ds02.stage2.closed-actual-field-census.v2'
    assert census['source_gate']==base.ref(GATE) and census['active_reservation_count']==0
    assert census['scientific_Q_credit']==0 and census['goal_complete'] is False
    parents=grant['intervening_actual_parent_proofs']
    assert parents and len({r['path'] for r in parents})==len(parents)
    for r in parents:
        assert base.sha(r['path'])==r['sha256']
        p=base.load(r['path'])
        assert p['schema']=='ds02.stage2.root-actual-verification.v1'
        assert p['parent_reservation_released'] is True and p['repeat_fee_idempotent'] is True
        assert p['goal_complete'] is False
        for key in ['request','receipt','systemd_evidence','terminal_cpu_reconciliation']:
            assert base.sha(p[key])==p[key+'_sha256']
        assert isinstance(p['full_systemd_cpu_seconds'],(int,float)) and p['full_systemd_cpu_seconds']>=0
    assert not base.load(D/'runtime/resource-ledger.json')['reservations']
    return grant

def seal(row,num,grant_path):
    source=Path(row['request']['path'])
    assert base.sha(source)==row['request']['sha256']
    q=base.load(source)
    q['attempt_id']=f'root{num}-scientific-field-h5-v3-v10-actual-remaining-001'
    q['root_scientific_field_remaining_binding']={'namespace':num,'source_request':base.ref(source),
        'source_index':base.ref(INDEX),'source_gate':base.ref(GATE),
        'root_payload_content_read':False,'qualification':base.UNKNOWN,
        'resume_grant':base.ref(grant_path),'controller':base.ref(Path(__file__))}
    gate=base.load(GATE);grant=base.load(grant_path)
    extras=[Path(__file__),HERE/'serial_v4.py',source,INDEX,GATE,grant_path,
        S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
        S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
        base.LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py']
    extras += [Path(r['path']) for r in gate['actual_pilot_proofs']+gate['previous_actual_remaining_proofs']]
    extras += [Path(gate[k]['path']) for k in ['actual_pilot_cost','previous_actual_remaining_cost']]
    extras += [Path(grant[k]['path']) for k in ['preceding_yield_marker','closed_field_census']]
    extras += [Path(r['path']) for r in grant['intervening_actual_parent_proofs']]
    q['input_files']=list(dict.fromkeys(q['input_files']+list(map(str,extras))))
    old=dict(q['input_sha256']);hashes={p:base.sha(p) for p in q['input_files']}
    for p,h in old.items():assert hashes[p]==h,p
    q['input_sha256']=hashes;q['input_hashes']=hashes
    out=S/f'requests/scientific-field-h5-v3-v10-actual-remaining-root-{num}-001.json'
    base.new(out,q)
    return out

def main(grant_path,yield_marker):
    grant_path=grant_path.absolute();yield_marker=yield_marker.absolute()
    grant=validate_grant(grant_path)
    assert yield_marker.parent==S/'checkpoints'
    assert str(yield_marker)!=grant['preceding_yield_marker']['path']
    gate=base.load(GATE);index=base.load(INDEX)
    assert base.sha(INDEX)==gate['source_index']['sha256']
    assert gate['selected_count']==311 and index['executable_case_count']==327
    by_id={r['physical_case_id']:r for r in index['requests']}
    proofs=[]
    for num,cid in zip(range(380,691),gate['selected_cases']):
        if yield_marker.exists():
            marker=base.load(yield_marker)
            assert marker['schema']=='ds02.stage2.root-field-case-boundary-yield.v1'
            assert marker['source_gate']==base.ref(GATE) and marker['yield_after_current_case'] is True
            print(json.dumps({'event':'FIELD_CONTROLLER_YIELDED_AT_CLOSED_CASE_BOUNDARY',
                'next_namespace':num,'closed_this_continuation':len(proofs),'goal_complete':False}),flush=True)
            return
        qp=S/f'requests/scientific-field-h5-v3-v10-actual-remaining-root-{num}-001.json'
        proof=S/f'checkpoints/SCIENTIFIC_FIELD_H5_ACTUAL_ROOT_VERIFICATION_{num}.json'
        if proof.exists():
            p=base.load(proof);q=base.load(qp)
            assert p['status']=='VERIFIED_ACTUAL_PRODUCTION_H5_FIELD_SCAN_METADATA_CLOSURE_NO_PHYSICAL_Q'
            assert p['parent_reservation_released'] is True and p['repeat_fee_idempotent'] is True
            assert p['request']==str(qp) and p['request_sha256']==base.sha(qp)
            assert q['case_id']==cid and q['root_scientific_field_remaining_binding']['source_gate']==base.ref(GATE)
            assert base.state(f'ds02-scientific-field-h5-v3-v10-root-{num}')['SubState']=='dead'
            proofs.append(base.ref(proof))
            print(json.dumps({'event':'REUSED_EXACT_CLOSED_FIELD_PARENT_NO_H5_REREAD','namespace':num}),flush=True)
            continue
        assert not qp.exists(),'unfinished parent requires independent closure, never implicit relaunch'
        qp=seal(by_id[cid],num,grant_path)
        base.launch(qp,num);proof=base.verify(qp,num);proofs.append(base.ref(proof))
        p=base.load(proof)
        base.new(S/f'checkpoints/ROOT{num}_ACTUAL_SCIENTIFIC_FIELD_H5_REMAINING_HANDOFF_V1.json',{
            'schema':'ds02.stage2.root-actual-scientific-field-remaining-handoff.v1',
            'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'actual_remaining_count_this_batch':len(proofs),'actual_previous_field_count':23,
            'actual_proofs':list(proofs),'source_index':base.ref(INDEX),'source_gate':base.ref(GATE),
            'resume_grant':base.ref(grant_path),'selected_case_id':cid,
            'full_cpu_seconds':p['full_systemd_cpu_seconds'],'production_scientific_Q_credit':0,
            'goal_complete':False,'goal_status':'ACTIVE_FULL_SEVEN_ITEMS'})
        print(json.dumps({'event':'ACTUAL_REMAINING_FIELD_CLOSED','namespace':num,
            'remaining_count_this_batch':len(proofs),'goal_complete':False}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-grant',type=Path,required=True)
    parser.add_argument('--yield-marker',type=Path,required=True)
    args=parser.parse_args()
    with (D/'runtime/root-owned-scientific-field-pilots-v1.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        main(args.resume_grant,args.yield_marker)
