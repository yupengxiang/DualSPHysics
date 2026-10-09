"""Close the killed ROOT301 parent without inventing a runtime receipt."""
from pathlib import Path
import argparse
import copy
import datetime
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
UNIT = 'ds02-typed-lifecycle-batch-v1-f5-root-301'
REQUEST = S / 'requests/typed-lifecycle-batch-v1-f5-root-forward-301-001.json'
EVIDENCE = S / 'accounting/ROOT301_ORPHAN_SYSTEMD_FAILURE_EVIDENCE_V1.json'
PROOF = S / 'checkpoints/ROOT301_ORPHAN_FAILED_PARENT_RECONCILIATION_V1.json'
sys.path.insert(0, str(LAB / 'scripts'))
from ds_data02_runtime_v8 import ledger_locked


def sha(path):
    path = Path(path)
    assert path.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.vtu','.jsonl'}
    assert path.stat().st_size <= 10485760
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    assert Path(path).stat().st_size <= 10485760
    return json.loads(Path(path).read_text())


def state():
    raw = subprocess.check_output(['systemctl','--user','show',UNIT,'-p','SubState','-p','MainPID','-p','Result','-p','ExecMainStatus','-p','CPUUsageNSec','-p','TasksCurrent','-p','ControlGroup','-p','ExecMainExitTimestamp'], text=True)
    return dict(x.split('=',1) for x in raw.splitlines())


def tree_bytes(base):
    paths = list(base.rglob('*'))
    assert not any(p.is_symlink() for p in paths)
    return sum(p.stat().st_size for p in paths if p.is_file())


def dead_without_receipt(q):
    st = state()
    assert st['MainPID'] == '0' and st['SubState'] == 'failed' and st['Result'] == 'signal' and st['ExecMainStatus'] == '9', st
    assert st['TasksCurrent'] in {'0','[not set]'}, st
    cg = Path('/sys/fs/cgroup') / st['ControlGroup'].lstrip('/')
    if st['ControlGroup'] and (cg/'cgroup.procs').exists():
        assert not (cg/'cgroup.procs').read_text().strip()
    base = D / 'families' / q['family_id'] / q['case_id'] / q['attempt_id']
    assert base.is_dir() and not (base/'execution-receipt.json').exists()
    return st, base


def new(path, value):
    assert not path.exists()
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


def snapshot():
    q = load(REQUEST)
    st, base = dead_without_receipt(q)
    journal = subprocess.check_output(['journalctl','--user','-u',UNIT,'--no-pager','-o','short-iso'], text=True)
    assert 'systemd-oomd killed 2 process(es) in this unit.' in journal
    identity = '/'.join(q[k] for k in ['family_id','case_id','attempt_id'])
    ledger = load(D/'runtime/resource-ledger.json')
    reservations = [r for r in ledger['reservations'] if r['id']==identity]
    assert len(reservations)==1 and not any(c['id']==identity for c in ledger['charges'])
    assert not (Path('/proc')/str(reservations[0]['launcher_pid'])).exists()
    value = {'schema':'ds02.stage2.orphan-systemd-parent-failure-evidence.v1','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'request':{'path':str(REQUEST),'sha256':sha(REQUEST)},'unit':UNIT,'systemd':st,'journal':journal,
        'original_reservation':reservations[0],'attempt_root':str(base),'partial_tree_bytes':tree_bytes(base),
        'actual_cpu_core_seconds':int(st['CPUUsageNSec'])/1e9,'runtime_terminal_receipt_exists':False,
        'source_prepost_hash_closure':'UNKNOWN_PARENT_KILLED_BEFORE_FINAL_RECEIPT','root_payload_content_read':False,
        'scientific_or_saved_mask_credit':0,'goal_complete':False}
    new(EVIDENCE,value)
    print(json.dumps({'evidence':str(EVIDENCE),'sha256':sha(EVIDENCE),'cpu_core_seconds':value['actual_cpu_core_seconds'],'partial_tree_bytes':value['partial_tree_bytes']}))


def reconcile():
    e = load(EVIDENCE)
    assert e['unit']==UNIT and e['request']['path']==str(REQUEST) and sha(REQUEST)==e['request']['sha256']
    q=load(REQUEST);st,base=dead_without_receipt(q)
    assert st['CPUUsageNSec']==e['systemd']['CPUUsageNSec'] and tree_bytes(base)==e['partial_tree_bytes']
    identity=e['original_reservation']['id']
    stamp=e['utc']
    charge={'id':identity,'gpu_seconds':0.0,'cpu_core_seconds':e['actual_cpu_core_seconds'],
        'new_storage_bytes':e['partial_tree_bytes'],'status':'failed','finished_at_utc':stamp,
        'accounting_source':'orphan_systemd_oomd_terminal_cpu_and_stat_only_partial_tree',
        'failure_evidence':{'path':str(EVIDENCE),'sha256':sha(EVIDENCE)}}
    with ledger_locked(D) as ledger:
        prior=copy.deepcopy(ledger)
        existing=[c for c in ledger['charges'] if c['id']==identity]
        if existing:
            assert existing==[charge] and not any(r['id']==identity for r in ledger['reservations'])
            assert any(a['id']==identity and a['status']=='failed' for a in ledger['attempts'])
            assert ledger==prior
            result='IDEMPOTENT_ALREADY_RECONCILED'
        else:
            matches=[r for r in ledger['reservations'] if r['id']==identity]
            assert matches==[e['original_reservation']]
            attempts=[a for a in ledger['attempts'] if a['id']==identity]
            assert len(attempts)==1 and attempts[0]['status']=='reserved'
            ledger['reservations']=[r for r in ledger['reservations'] if r['id']!=identity]
            ledger['charges'].append(charge)
            attempts[0].update(status='failed',finished_at_utc=stamp,termination_reason='systemd_oomd_sigkill_no_final_runtime_receipt')
            assert ledger['limits']==prior['limits'] and ledger['deadline_utc']==prior['deadline_utc']
            assert ledger['charges'][:-1]==prior['charges'] and len(ledger['attempts'])==len(prior['attempts'])
            result='APPENDED_FAILED_ORIGINAL_PARENT_CHARGE_AND_RELEASED_ORPHAN_RESERVATION'
    if not PROOF.exists():
        new(PROOF,{'schema':'ds02.stage2.orphan-failed-parent-reconciliation.v1','status':result,
            'failure_evidence':{'path':str(EVIDENCE),'sha256':sha(EVIDENCE)},'request':e['request'],'parent_charge':charge,
            'reservation_released':True,'runtime_receipt_reconstructed':False,'partial_outputs_preserved':True,
            'scientific_or_saved_mask_credit':0,'root_payload_content_read':False,'goal_complete':False,
            'next':'new attempt identity with explicit failed lineage; independently verify complete batch before credit'})
    print(json.dumps({'status':result,'proof':str(PROOF),'sha256':sha(PROOF),'charge':charge}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['snapshot','reconcile']);a=parser.parse_args()
    snapshot() if a.action=='snapshot' else reconcile()
