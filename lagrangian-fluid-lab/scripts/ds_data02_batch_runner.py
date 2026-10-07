#!/usr/bin/env python3
"""Run a homogeneous DS-DATA-02 batch through the Stage2 guarded dispatcher.

Logs go directly to files; terminal receipts use their own JSON channel. A
failure stops pending requests in this batch. Submit independent families as
separate batches so one family's input failure does not stop another family.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from uuid import uuid4

from ds_data02_runtime_v2 import DATA_ROOT, atomic_json

REPO = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPT = REPO / 'scripts/ds_data02_stage2_dispatch.py'
PYTHON_BIN = Path(sys.executable)


def load_request(path):
    raw = path.read_bytes()
    request = json.loads(raw)
    for key in ('family_id', 'case_id', 'attempt_id'):
        if not isinstance(request.get(key), str) or not re.fullmatch(r'[A-Za-z0-9_-]+', request[key]):
            raise ValueError('Invalid request identity: ' + key)
    return request, hashlib.sha256(raw).hexdigest()


def run_batch(request_paths, max_concurrency=2, label='batch', *, data_root=DATA_ROOT,
              output_dir=None):
    if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int) or max_concurrency <= 0:
        raise ValueError('concurrency must be a positive integer')
    data_root = Path(data_root).resolve()
    rows = []
    identities = set()
    for path in request_paths:
        path = Path(path).resolve()
        request, digest = load_request(path)
        identity = '/'.join(request[key] for key in ('family_id', 'case_id', 'attempt_id'))
        if identity in identities:
            raise ValueError('Duplicate attempt in batch: ' + identity)
        identities.add(identity)
        rows.append(dict(request=str(path), request_sha256=digest, identity=identity,
                         receipt=str(data_root / 'families' / identity / 'execution-receipt.json')))
    output_dir = Path(output_dir) if output_dir else data_root / 'runtime/batches' / uuid4().hex
    output_dir.mkdir(parents=True, exist_ok=False)
    summary = dict(schema='ds02.batch-receipt.v2', label=label, status='running',
                   dispatcher=str(RUNTIME_SCRIPT), concurrency=max_concurrency,
                   requests=rows, completed=[], failed=[], skipped=[])
    summary_path = output_dir / 'batch-receipt.json'
    atomic_json(summary_path, summary)
    pending = deque(rows)
    running = {}
    stopped = False

    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'batch cancelled by signal {signum}')

    old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in old_handlers:
        signal.signal(sig, interrupted)
    try:
        while pending or running:
            # Reap before replenishing: a known failure cannot launch another request.
            for proc, (row, log, started) in list(running.items()):
                if proc.poll() is None:
                    continue
                log.close()
                del running[proc]
                result = dict(row, returncode=proc.returncode, elapsed_seconds=time.monotonic() - started)
                try:
                    receipt = json.loads(Path(row['receipt']).read_text())
                    if receipt.get('request_sha256') != row['request_sha256']:
                        raise ValueError('Receipt does not bind this request')
                    result['status'] = receipt.get('status')
                    if result['status'] not in ('completed', 'failed'):
                        raise ValueError('Receipt is not terminal')
                except (OSError, ValueError) as error:
                    result.update(status='failed', error=str(error))
                if proc.returncode == 0 and result['status'] == 'completed':
                    summary['completed'].append(result)
                else:
                    summary['failed'].append(result)
                    stopped = True
                atomic_json(summary_path, summary)
            if stopped:
                summary['skipped'].extend(pending)
                pending.clear()
            while pending and len(running) < max_concurrency:
                row = pending.popleft()
                log_path = output_dir / f'{len(summary["completed"]) + len(summary["failed"]) + len(running):04d}.log'
                row['log'] = str(log_path)
                log = log_path.open('xb')
                try:
                    proc = subprocess.Popen(
                        [str(PYTHON_BIN), str(RUNTIME_SCRIPT), 'run', '--request', row['request'],
                         '--data-root', str(data_root), '--parent-pid', str(os.getpid())],
                        cwd=REPO, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                except BaseException:
                    log.close()
                    raise
                running[proc] = (row, log, time.monotonic())
            if pending or running:
                time.sleep(0.1)
        summary['status'] = 'failed' if summary['failed'] else 'completed'
    except BaseException as error:
        summary.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'failed', error=str(error))
        summary['skipped'].extend(pending)
        pending.clear()
        for sig in old_handlers:
            signal.signal(sig, signal.SIG_IGN)
        for proc in running:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
        for proc, (row, log, started) in running.items():
            proc.wait()  # runtime bounds its worker's TERM/KILL shutdown
            log.close()
            summary['failed'].append(dict(row, status='cancelled', returncode=proc.returncode))
        if not isinstance(error, KeyboardInterrupt):
            raise
    finally:
        atomic_json(summary_path, summary)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    print(f"{summary['status']}: {len(summary['completed'])} completed, "
          f"{len(summary['failed'])} failed, {len(summary['skipped'])} skipped; {summary_path}", flush=True)
    return 0 if summary['status'] == 'completed' else max(1, len(summary['failed']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('requests', nargs='+', type=Path)
    parser.add_argument('--concurrency', type=int, default=2)
    parser.add_argument('--label', default='batch')
    parser.add_argument('--data-root', type=Path, default=DATA_ROOT)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.concurrency <= 0:
        parser.error('concurrency must be a positive integer')
    return run_batch(args.requests, args.concurrency, args.label,
                     data_root=args.data_root, output_dir=args.output_dir)


if __name__ == '__main__':
    raise SystemExit(main())
