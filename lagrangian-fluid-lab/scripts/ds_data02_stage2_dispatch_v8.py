"""Forward Stage2 v8 entry with strict digest and parent reservation guards."""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import signal

import ds_data02_strict_dispatch_v8 as strict


runtime = strict.runtime
GUARD_PATH = str(Path(__file__).resolve())
BOUND_RUNNER_FILES = (
    GUARD_PATH,
    strict.GUARD_PATH,
    runtime.RUNTIME_PATH,
    runtime.V6_RUNTIME_PATH,
)
_base_check_reservation = runtime.check_reservation


def validate_request(request, approval_context=None):
    actual = strict.validate_request(request, approval_context=approval_context)
    for path in BOUND_RUNNER_FILES:
        if path not in actual:
            raise ValueError("Stage2 v8 runner must be a digest-bound input: " + path)
    return actual


def check_reservation(ledger, reservation, existing_bytes, **kwargs):
    return _base_check_reservation(ledger, reservation, existing_bytes, **kwargs)


def install_guard():
    if runtime.validate_request not in (strict._base_validate, strict.validate_request, validate_request):
        raise RuntimeError("shared v8 validator was unexpectedly replaced")
    if runtime.check_reservation not in (_base_check_reservation, check_reservation):
        raise RuntimeError("shared v8 reservation guard was unexpectedly replaced")
    runtime.validate_request = validate_request
    runtime.check_reservation = check_reservation


def _cancel(signum, _frame):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise KeyboardInterrupt("v8 launcher cancelled by signal " + str(signum))


def _watch_parent(parent_pid):
    if parent_pid is None:
        return
    if parent_pid <= 1:
        raise ValueError("invalid supervising parent PID")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot install parent-death cancellation")
    if os.getppid() != parent_pid:
        raise KeyboardInterrupt("supervising parent already exited")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run"])
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=runtime.DATA_ROOT)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, _cancel)
    signal.signal(signal.SIGINT, _cancel)
    _watch_parent(args.parent_pid)
    install_guard()
    result = runtime.run_request(args.request, data_root=args.data_root, parent_pid=args.parent_pid)
    print(result, flush=True)
    return int(result["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
