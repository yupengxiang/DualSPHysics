"""Forward-only Stage2 v6 entry with Home-floor fast reservation accounting."""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import signal

import ds_data02_strict_dispatch_v6 as strict

runtime = strict.runtime
GUARD_PATH = str(Path(__file__).resolve())
BOUND_RUNNER_FILES = (GUARD_PATH, strict.GUARD_PATH,
                      runtime.RUNTIME_PATH, runtime.BASE_RUNTIME_PATH)
_base_reservation = runtime.check_reservation


def finite_number(value, name, *, minimum=0, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' must be finite numeric data')
    if value < minimum or (integer and not isinstance(value, int)):
        raise ValueError(name + ' has an invalid range or type')


def validate_request(request, *, approval_context=None):
    finite_number(request.get('max_wall_seconds'), 'max_wall_seconds', minimum=1e-9)
    finite_number(request.get('cpu_threads'), 'cpu_threads', minimum=1, integer=True)
    finite_number(request.get('estimated_storage_bytes'), 'estimated_storage_bytes', integer=True)
    if request.get('kind') in {'qualification', 'production'}:
        finite_number(request.get('estimated_peak_gpu_mib'), 'estimated_peak_gpu_mib', minimum=1e-9)
    actual = strict.validate_request(request, approval_context=approval_context)
    for path in BOUND_RUNNER_FILES:
        if path not in actual:
            raise ValueError('Stage2 v6 runner must be a digest-bound input: ' + path)
    return actual


def check_reservation(ledger, reservation, existing_bytes, **kwargs):
    for key in ('gpu_seconds', 'cpu_core_seconds', 'new_storage_bytes'):
        finite_number(ledger['limits'][key], 'limit.' + key)
        finite_number(reservation[key], 'reservation.' + key)
        for row in ledger['charges'] + ledger['reservations']:
            finite_number(row.get(key, 0), 'ledger.' + key)
    for key in ('qualification_attempts', 'production_attempts'):
        finite_number(ledger['limits'][key], 'limit.' + key, integer=True)
    if ledger['limits'].get('storage_policy') == 'home_free_floor':
        finite_number(ledger['limits']['home_min_free_bytes'], 'home_min_free_bytes', integer=True)
    finite_number(reservation['cpu_threads'], 'cpu_threads', minimum=1, integer=True)
    stamp = kwargs.get('current_time') or datetime.now(timezone.utc)
    deadline = datetime.fromisoformat(ledger['deadline_utc'])
    if reservation['cpu_core_seconds'] / reservation['cpu_threads'] > (deadline - stamp).total_seconds():
        raise RuntimeError('reserved duration would exceed campaign deadline')
    return _base_reservation(ledger, reservation, existing_bytes, **kwargs)


def install_guard():
    if runtime.validate_request not in (strict._base_validate, strict.validate_request, validate_request):
        raise RuntimeError('Shared v6 validator was unexpectedly replaced')
    if runtime.check_reservation not in (_base_reservation, check_reservation):
        raise RuntimeError('Shared v6 reservation guard was unexpectedly replaced')
    runtime.validate_request = validate_request
    runtime.check_reservation = check_reservation


def cancel(signum, frame):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise KeyboardInterrupt('launcher cancelled by signal ' + str(signum))


def watch_parent(parent_pid):
    if parent_pid is None:
        return
    if parent_pid <= 1:
        raise ValueError('Invalid supervising parent PID')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot install parent-death cancellation')
    if os.getppid() != parent_pid:
        raise KeyboardInterrupt('supervising parent already exited')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run'])
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=runtime.DATA_ROOT)
    parser.add_argument('--parent-pid', type=int)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    watch_parent(args.parent_pid)
    install_guard()
    receipt = runtime.run_request(args.request, data_root=args.data_root)
    print(receipt['status'] + ': ' + receipt['output_root'], flush=True)
    return int(receipt['status'] != 'completed')


if __name__ == '__main__':
    raise SystemExit(main())
