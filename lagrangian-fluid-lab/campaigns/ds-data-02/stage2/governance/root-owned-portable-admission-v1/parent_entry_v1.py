"""One bounded existing-ledger parent, including external storage finalization."""
from pathlib import Path
import argparse
import json
import os
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
sys.path.insert(0, str(LAB / 'scripts'))
from ds_data02_runtime_v8 import run_request, ledger_locked
from external_storage_v1 import reconcile, small


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True, type=Path)
    args = parser.parse_args()
    q, _ = small(args.request)
    data = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
    evidence = LAB / 'campaigns/ds-data-02/stage2/accounting/root242-external-storage-evidence-v1.json'
    try:
        result = run_request(args.request, data_root=data, parent_pid=os.getppid())
    finally:
        receipt = data / 'families' / q['family_id'] / q['case_id'] / q['attempt_id'] / 'execution-receipt.json'
        if receipt.exists():
            fee = reconcile(args.request, data, ledger_locked, evidence)
            repeat = reconcile(args.request, data, ledger_locked, evidence)
            assert repeat['status'] == 'ALREADY_APPLIED_SAME_PARENT_EXTERNAL_STORAGE'
            print(json.dumps({'external_storage_fee': fee['status'], 'repeat_idempotent': True}), flush=True)
    print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
