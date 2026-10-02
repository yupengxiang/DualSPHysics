"""Wait for shared capacity, then delegate exactly once to the strict runner."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from ds_data02_strict_dispatch_v1 import run_request
from ds_data02_runtime_v2 import DATA_ROOT

def run(request_path, expected_sha, watch_seconds, record):
    started=time.monotonic()
    expected=json.loads(request_path.read_text())
    if hashlib.sha256(request_path.read_bytes()).hexdigest()!=expected_sha:
        raise ValueError('Queued request differs from root registration')
    record.parent.mkdir(parents=True,exist_ok=True)
    if record.exists():
        raise FileExistsError(record)
    state={'schema':'ds02.root-bounded-capacity-watch.v1','request':str(request_path),
        'expected_request_sha256':expected_sha,'waiting_max_seconds':watch_seconds,
        'runner':'unchanged runtime v2 through strict digest guard',
        'qualification_claim':'none','status':'waiting_for_capacity'}
    def write():
        record.write_text(json.dumps(state,indent=2)+'\n')
    write()
    while time.monotonic()-started<watch_seconds:
        ledger=json.loads((DATA_ROOT/'runtime/resource-ledger.json').read_text())
        active=ledger['reservations']
        if expected['kind'] in ['qualification','production']:
            capacity=sum(r['kind'] in ['qualification','production'] for r in active)<4
        elif expected.get('cpu_task_kind')=='conversion':
            capacity=sum(r.get('cpu_task_kind')=='conversion' for r in active)<2
        else:
            capacity=True
        capacity=capacity and sum(r.get('cpu_threads',0) for r in active)+expected['cpu_threads']<=64
        if capacity:
            if hashlib.sha256(request_path.read_bytes()).hexdigest()!=expected_sha:
                raise ValueError('Queued request changed before dispatch')
            state.update(status='dispatching_once',waited_seconds=time.monotonic()-started)
            write()
            # The runner atomically rechecks all resources, UUID leases and
            # budgets. This watcher neither reserves nor selects a device.
            receipt=run_request(request_path)
            state.update(status='runner_terminal',receipt_status=receipt['status'],
                output_root=receipt['output_root'],returncode=receipt.get('returncode'))
            write()
            return state
        time.sleep(10)
    state.update(status='wait_window_exhausted',waited_seconds=time.monotonic()-started)
    write()
    return state

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request',type=Path,required=True)
    p.add_argument('--expected-sha256',required=True)
    p.add_argument('--watch-seconds',type=int,required=True)
    p.add_argument('--record',type=Path,required=True)
    a=p.parse_args()
    if not 0<a.watch_seconds<=7200:
        p.error('Bounded root watch requires 1..7200 seconds')
    print(json.dumps(run(a.request,a.expected_sha256,a.watch_seconds,a.record)),flush=True)
