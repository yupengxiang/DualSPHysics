#!/usr/bin/env python3
"""Forward-only Stage2 runtime v5 with Home-floor fast reservation accounting.

The consumed v2 runtime remains the executor.  This version writes a final
receipt whose ``bytes`` value includes that receipt itself, then verifies the
post-write tree size before v2 charges the same receipt object.  v3 receipts
remain immutable and continue to identify their own runner.  Under the shared
``home_free_floor`` policy the parent guard does not need the existing whole
data-root byte total: it checks the fresh Home ``statvfs`` value plus every
ledger charge/reservation.  This wrapper therefore skips the redundant
``tree_bytes(data_root)`` walk while retaining exact per-attempt output-tree
fixed-point accounting.  Non-Home storage policies still use the full legacy
existing-tree measurement.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

import ds_data02_runtime_v2 as base

DATA_ROOT = base.DATA_ROOT
RUNTIME_PATH = str(Path(__file__).resolve())
BASE_RUNTIME_PATH = str(Path(base.__file__).resolve())
_BASE_TREE_BYTES = base.tree_bytes
_ACTIVE_DATA_ROOT: Path | None = None
# Keep the parent lock as part of the forward runtime's public guard surface.
ledger_locked = base.ledger_locked

_base_validate = base.validate_request
_base_check_reservation = base.check_reservation
_base_atomic_json = base.atomic_json


def _finite_number(value, name, *, minimum=0, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' must be finite numeric data')
    if value < minimum or (integer and not isinstance(value, int)):
        raise ValueError(name + ' has an invalid range or type')


def validate_request(request, *, approval_context=None):
    _finite_number(request.get('max_wall_seconds'), 'max_wall_seconds', minimum=1e-9)
    _finite_number(request.get('cpu_threads'), 'cpu_threads', minimum=1, integer=True)
    _finite_number(request.get('estimated_storage_bytes'), 'estimated_storage_bytes', integer=True)
    if request.get('kind') in {'qualification', 'production'}:
        _finite_number(request.get('estimated_peak_gpu_mib'), 'estimated_peak_gpu_mib', minimum=1e-9)
    actual = _base_validate(request, approval_context=approval_context)
    if BASE_RUNTIME_PATH not in actual:
        raise ValueError('Stage2 v4 runtime must bind consumed runtime v2')
    return actual


def check_reservation(ledger, reservation, existing_bytes, **kwargs):
    for key in ('gpu_seconds', 'cpu_core_seconds', 'new_storage_bytes'):
        _finite_number(ledger['limits'][key], 'limit.' + key)
        _finite_number(reservation[key], 'reservation.' + key)
        for row in ledger['charges'] + ledger['reservations']:
            _finite_number(row.get(key, 0), 'ledger.' + key)
    for key in ('qualification_attempts', 'production_attempts'):
        _finite_number(ledger['limits'][key], 'limit.' + key, integer=True)
    if ledger['limits'].get('storage_policy') == 'home_free_floor':
        _finite_number(ledger['limits']['home_min_free_bytes'], 'home_min_free_bytes', integer=True)
    _finite_number(reservation['cpu_threads'], 'cpu_threads', minimum=1, integer=True)
    stamp = kwargs.get('current_time') or datetime.now(timezone.utc)
    deadline = datetime.fromisoformat(ledger['deadline_utc'])
    if reservation['cpu_core_seconds'] / reservation['cpu_threads'] > (deadline - stamp).total_seconds():
        raise RuntimeError('reserved duration would exceed campaign deadline')
    return _base_check_reservation(ledger, reservation, existing_bytes, **kwargs)


def tree_bytes(root):
    """Avoid only the redundant Home-wide scan used by reservation checks.

    The v2 runner also calls ``tree_bytes`` for the active attempt output and
    the v4 fixed-point terminal receipt.  Those paths must retain exact byte
    measurement, so only the active parent ``data_root`` is short-circuited
    under the Home-floor policy.  Non-Home policy behavior remains unchanged.
    """
    target = Path(root).expanduser().resolve()
    active = _ACTIVE_DATA_ROOT
    if active is not None and target == active:
        ledger_path = target / "runtime" / "resource-ledger.json"
        try:
            ledger = json.loads(ledger_path.read_text())
        except (OSError, json.JSONDecodeError):
            return _BASE_TREE_BYTES(root)
        limits = ledger.get("limits", {})
        if limits.get("storage_policy") == "home_free_floor":
            # v2.check_reservation ignores existing_bytes in this policy; the
            # fresh statvfs and full ledger reservations are authoritative.
            return 0
    return _BASE_TREE_BYTES(root)


def _json_bytes(value):
    """Return the bytes written by the shared atomic JSON writer."""
    return len((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def _non_receipt_bytes(path):
    root = Path(path).parent
    total = base.tree_bytes(root)
    receipt_size = Path(path).stat().st_size if Path(path).is_file() else 0
    return total - receipt_size


def _set_terminal_fields(value, actual_bytes, reservation_bytes, non_receipt_bytes):
    value['bytes'] = actual_bytes
    if actual_bytes > reservation_bytes:
        prior_reason = value.get('termination_reason')
        if prior_reason and prior_reason != 'terminal_storage_reservation_exceeded':
            value['pre_terminal_storage_termination_reason'] = prior_reason
        value['status'] = 'failed'
        value['termination_reason'] = 'terminal_storage_reservation_exceeded'
        status = 'failed'
    else:
        status = 'passed'
    value['terminal_storage_guard'] = dict(
        status=status,
        actual_bytes=actual_bytes,
        reservation_bytes=reservation_bytes,
        excess_bytes=max(0, actual_bytes - reservation_bytes),
        measurement='fixed_point_including_final_receipt',
        non_receipt_bytes=non_receipt_bytes,
    )


def _prepare_terminal_receipt(path, value):
    """Solve the receipt-size fixed point before the final atomic write."""
    if not isinstance(value, dict) or 'request' not in value:
        return None
    if 'finished_at_utc' not in value or 'input_hashes_after_run' not in value:
        value['terminal_storage_guard'] = dict(
            status='pending',
            reservation_bytes=value['request']['estimated_storage_bytes'],
            measurement='fixed_point_including_final_receipt',
        )
        return None
    reservation_bytes = value['request']['estimated_storage_bytes']
    non_receipt_bytes = _non_receipt_bytes(path)
    predicted = max(non_receipt_bytes, int(value.get('bytes', 0)))
    for _ in range(128):
        _set_terminal_fields(value, predicted, reservation_bytes, non_receipt_bytes)
        next_value = non_receipt_bytes + _json_bytes(value)
        if next_value == predicted:
            return predicted
        predicted = next_value
    raise RuntimeError('terminal storage receipt fixed point did not converge')


def _write_terminal_receipt(path, value):
    """Write and verify the exact final directory byte count."""
    for _ in range(16):
        predicted = _prepare_terminal_receipt(path, value)
        if predicted is None:
            return _base_atomic_json(path, value)
        _base_atomic_json(path, value)
        actual = base.tree_bytes(Path(path).parent)
        if actual == value['bytes'] == predicted:
            return
    raise RuntimeError('terminal storage receipt changed after fixed-point write')


def _guarded_atomic_json(path, value):
    path = Path(path)
    if path.name == 'execution-receipt.json' and isinstance(value, dict):
        if value.get('schema') == 'ds02.execution-receipt.v1':
            value['runner_source'] = RUNTIME_PATH
            value['runner_sha256'] = base.sha256(__file__)
            if _ACTIVE_DATA_ROOT is not None:
                value['storage_accounting'] = {
                    'policy': 'home_free_floor_fast_parent_guard',
                    'data_root_existing_tree_scan': 'SKIPPED_ONLY_FOR_HOME_FLOOR_RESERVATION',
                    'existing_bytes_argument_to_guard': 0,
                    'fresh_home_statvfs_required': True,
                    'ledger_charges_and_reservations_included': True,
                    'attempt_output_tree_fixed_point_exact': True,
                    'non_home_policy_full_existing_tree_scan': True,
                }
            return _write_terminal_receipt(path, value)
    return _base_atomic_json(path, value)


def run_request(request_path, *, data_root=DATA_ROOT):
    old_validate = base.validate_request
    old_check = base.check_reservation
    old_atomic = base.atomic_json
    old_tree_bytes = base.tree_bytes
    global _ACTIVE_DATA_ROOT
    previous_data_root = _ACTIVE_DATA_ROOT
    _ACTIVE_DATA_ROOT = Path(data_root).expanduser().resolve()
    base.validate_request = validate_request
    base.check_reservation = check_reservation
    base.atomic_json = _guarded_atomic_json
    base.tree_bytes = tree_bytes
    try:
        return base.run_request(request_path, data_root=data_root)
    finally:
        base.validate_request = old_validate
        base.check_reservation = old_check
        base.atomic_json = old_atomic
        base.tree_bytes = old_tree_bytes
        _ACTIVE_DATA_ROOT = previous_data_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'status', 'run'])
    parser.add_argument('--request', type=Path)
    parser.add_argument('--data-root', type=Path, default=DATA_ROOT)
    args = parser.parse_args()
    if args.action == 'inventory':
        result = base.inventory()
    elif args.action == 'status':
        ledger = json.loads((args.data_root / 'runtime/resource-ledger.json').read_text())
        result = dict(totals_with_reservations=base.usage_totals(ledger),
                      actual_bytes=base.tree_bytes(args.data_root), ledger=ledger)
    else:
        if args.request is None:
            parser.error('--request is required')
        result = run_request(args.request, data_root=args.data_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(args.action == 'run' and result['status'] != 'completed')


if __name__ == '__main__':
    raise SystemExit(main())
