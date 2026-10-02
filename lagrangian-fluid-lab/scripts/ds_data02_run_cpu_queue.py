#!/usr/bin/env python3
"""Run a registered CPU-only queue through the shared v2 ledger and runner."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import os

from ds_data02_handoff_inventory import sha256


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--runner', type=Path, required=True)
    p.add_argument('--python', type=Path, required=True)
    p.add_argument('--data-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--stop-file', type=Path, required=True)
    p.add_argument('--workers', type=int, default=4)
    a = p.parse_args()
    if not 1 <= a.workers <= 8:
        raise ValueError('CPU queue workers must be between 1 and 8')
    requests = [Path(r['request']) for r in json.loads(a.manifest.read_text())
                if r.get('status') == 'new_audit_request_ready']
    for path in requests:
        if json.loads(path.read_text())['kind'] != 'cpu':
            raise ValueError('this queue cannot launch GPU work')
    rows = []
    state = {'schema': 'ds02.cpu-queue.v1', 'launcher_pid': os.getpid(),
             'started_at_utc': datetime.now(timezone.utc).isoformat(),
             'manifest_sha256': sha256(a.manifest), 'runner_sha256': sha256(a.runner),
             'total_requests': len(requests), 'workers': a.workers,
             'stop_file': str(a.stop_file), 'results': rows}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    if a.output.exists():
        raise FileExistsError('preserve existing queue checkpoint')

    def receipt_path(request):
        return a.data_root / 'families' / request['family_id'] / request['case_id'] / request['attempt_id'] / 'execution-receipt.json'

    def run(path):
        request = json.loads(path.read_text())
        receipt = receipt_path(request)
        if receipt.exists():
            result = json.loads(receipt.read_text())
            if result.get('request_sha256') != sha256(path):
                raise ValueError('existing attempt is bound to a different request')
            return {'case_id': request['case_id'], 'status': 'preserved_existing_attempt',
                    'receipt_status': result.get('status'), 'receipt': str(receipt)}
        result = subprocess.run([str(a.python), str(a.runner), 'run', '--request', str(path)],
                                capture_output=True, text=True)
        if not receipt.is_file():
            return {'case_id': request['case_id'], 'status': 'launcher_rejected',
                    'returncode': result.returncode, 'error': result.stdout[-1200:] + result.stderr[-1200:]}
        native = json.loads(receipt.read_text())
        return {'case_id': request['case_id'], 'status': native.get('status'),
                'returncode': native.get('returncode'), 'receipt': str(receipt),
                'receipt_sha256': sha256(receipt)}

    def save(active, queued):
        state.update(active=active, queued=queued, updated_at_utc=datetime.now(timezone.utc).isoformat())
        tmp = a.output.with_suffix('.tmp')
        tmp.write_text(json.dumps(state, indent=2) + '\n')
        tmp.replace(a.output)

    pending = list(requests)
    active = {}
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        while pending or active:
            while pending and len(active) < a.workers and not a.stop_file.exists():
                path = pending.pop(0)
                active[pool.submit(run, path)] = path
            save([str(v) for v in active.values()], [str(v) for v in pending])
            if not active:
                break
            done, _ = wait(active, timeout=5, return_when=FIRST_COMPLETED)
            for future in done:
                path = active.pop(future)
                try:
                    result = future.result()
                except Exception as error:
                    result = {'request': str(path), 'status': 'queue_error', 'error': str(error)}
                rows.append(result)
                print(json.dumps(result), flush=True)
    state['status'] = 'drained_after_stop_request' if pending else 'terminal'
    save([], [str(v) for v in pending])


if __name__ == '__main__':
    main()
