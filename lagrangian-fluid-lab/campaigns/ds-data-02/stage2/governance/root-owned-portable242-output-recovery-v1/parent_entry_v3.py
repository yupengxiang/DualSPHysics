"""Close a fresh portable parent's external bytes, including failed copies."""
from pathlib import Path
import argparse
import json
import os
import sys

HERE=Path(__file__).resolve().parent
S=HERE.parents[1]
LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
sys.path.insert(0,str(LAB/'scripts'))
sys.path.insert(0,str(S/'governance/root-owned-portable-admission-v1'))
from ds_data02_runtime_v8 import run_request,ledger_locked
from external_storage_v1 import reconcile,small

def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);args=p.parse_args()
    q,_=small(args.request)
    evidence=Path(q['root_external_storage_evidence']['path'])
    assert evidence.parent==S/'accounting' and evidence.name=='root242-v14-recursive-source-external-storage-evidence-v1.json'
    try:
        result=run_request(args.request,data_root=D,parent_pid=os.getppid())
    finally:
        receipt=D/'families'/q['family_id']/q['case_id']/q['attempt_id']/'execution-receipt.json'
        if receipt.exists():
            fee=reconcile(args.request,D,ledger_locked,evidence)
            assert reconcile(args.request,D,ledger_locked,evidence)['status']=='ALREADY_APPLIED_SAME_PARENT_EXTERNAL_STORAGE'
            print(json.dumps({'external_storage_fee':fee['status'],'repeat_idempotent':True}),flush=True)
    print(json.dumps(result),flush=True)
    return 0 if result['status']=='completed' else 1

if __name__=='__main__': raise SystemExit(main())
