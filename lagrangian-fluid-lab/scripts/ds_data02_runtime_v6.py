#!/usr/bin/env python3
"""Forward-only Stage2 runtime v6 with Home-floor fast reservation accounting.

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
import time

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
                policy = None
                try:
                    ledger = json.loads((_ACTIVE_DATA_ROOT / 'runtime' / 'resource-ledger.json').read_text())
                    policy = ledger.get('limits', {}).get('storage_policy')
                except (OSError, json.JSONDecodeError):
                    policy = None
                home_fast = policy == 'home_free_floor'
                value['storage_accounting'] = {
                    'policy': policy or 'UNKNOWN_UNREADABLE',
                    'data_root_existing_tree_scan': (
                        'SKIPPED_ONLY_FOR_HOME_FLOOR_RESERVATION' if home_fast
                        else 'PERFORMED_FOR_NON_HOME_POLICY'
                    ),
                    'existing_bytes_argument_to_guard': 0 if home_fast else 'legacy_tree_bytes',
                    'fresh_home_statvfs_required': home_fast,
                    'ledger_charges_and_reservations_included': True,
                    'attempt_output_tree_fixed_point_exact': True,
                    'non_home_policy_full_existing_tree_scan': not home_fast,
                }
            return _write_terminal_receipt(path, value)
    return _base_atomic_json(path, value)


def run_request(request_path, *, data_root=DATA_ROOT):
    """Run one request with accounting clocks started before validation.

    v2/v5 start their CPU clock after loading the request and hashing every
    input.  That is suitable for a tiny metadata audit, but it silently drops
    the cost of a large source preflight.  v6 keeps the v5 reservation and
    receipt semantics while owning the runner loop so ``entry_cpu`` and
    ``entry_wall`` are captured before request parsing or validation.
    """
    global _ACTIVE_DATA_ROOT
    data_root = Path(data_root).expanduser().resolve()
    entry_cpu = base.cpu_usage()
    entry_wall = time.monotonic()
    request = json.loads(Path(request_path).read_text())
    approval_context = {}
    hashes = validate_request(request, approval_context=approval_context)
    attempt = f"{request['family_id']}/{request['case_id']}/{request['attempt_id']}"
    output = data_root / 'families' / attempt
    if output.exists():
        raise FileExistsError(f'attempt output already exists: {output}')
    reservation = dict(id=attempt, kind=request['kind'], cpu_task_kind=request.get('cpu_task_kind'),
                       cpu_threads=request['cpu_threads'],
                       cpu_core_seconds=request['cpu_threads'] * request['max_wall_seconds'],
                       gpu_seconds=request['max_wall_seconds'] if request['kind'] in {'qualification', 'production'} else 0,
                       new_storage_bytes=request['estimated_storage_bytes'], reserved_at_utc=base.now(),
                       launcher_pid=os.getpid(), host=base.socket.gethostname())
    device = None
    lease_path = None
    registered = False
    proc = None
    child_started = None
    receipt = dict(schema='ds02.execution-receipt.v1', request=request,
                   request_sha256=base.sha256(request_path), input_hashes_at_launch=hashes,
                   runner_source=str(Path(__file__).resolve()), runner_sha256=base.sha256(__file__),
                   runner_git_at_launch=base.git_launch_state(Path(__file__).resolve().parents[2]),
                   git_at_launch=base.git_launch_state(request['worktree_root']), started_at_utc=None,
                   output_root=str(output),
                   numerical_reference_status='approved_scope_at_launch' if request['kind'] == 'production' else 'not_assessed',
                   production_product_acceptance='not_assessed',
                   timing_scope={
                       'clock_start': 'function_entry_before_request_load_and_input_validation',
                       'cpu_includes_input_hashing_and_validation': True,
                       'wall_includes_input_hashing_and_validation': True,
                       'cpu_cutoff': 'before_final_execution_receipt_write',
                   })
    if approval_context:
        receipt['scientific_approval_at_launch'] = approval_context
    previous_data_root = _ACTIVE_DATA_ROOT
    _ACTIVE_DATA_ROOT = data_root
    try:
        with ledger_locked(data_root) as ledger:
            stat = os.statvfs(data_root)
            free_disk = stat.f_bavail * stat.f_frsize
            check_reservation(ledger, reservation, tree_bytes(data_root), available_bytes=free_disk)
            if free_disk < request['estimated_storage_bytes'] + 2 * 1024 ** 3:
                raise RuntimeError('insufficient filesystem headroom')
            if request['kind'] in {'qualification', 'production'}:
                snapshot = base.inventory()
                leases = list((data_root / 'leases').glob('*.json'))
                leased_uuids = {json.loads(p.read_text())['uuid'] for p in leases}
                device = base.choose_gpu(snapshot, leased_uuids, request['estimated_peak_gpu_mib'])
                reservation['gpu_uuid'] = device['uuid']
                lease_path = data_root / 'leases' / (device['uuid'] + '.json')
                with lease_path.open('x') as handle:
                    json.dump(dict(uuid=device['uuid'], device_index=device['index'], attempt_id=attempt,
                                   launcher_pid=os.getpid(), host=base.socket.gethostname(), heartbeat_utc=base.now()), handle)
                receipt['gpu_inventory_at_launch'] = snapshot
                receipt['gpu'] = device
            ledger['reservations'].append(reservation)
            ledger['attempts'].append(dict(id=attempt, kind=request['kind'], status='reserved', started_at_utc=base.now()))
            registered = True
        output.mkdir(parents=True, exist_ok=False)
        command = request['command'][:]
        if request.get('cpu_task_kind') == 'gencase' and Path(command[0]).resolve() == (base.BIN_ROOT / 'GenCase_linux64').resolve():
            command = [arg for arg in command if not arg.startswith('-threads:')]
            command.append(f"-threads:{request['cpu_threads']}")
        command = [arg.replace('{attempt_root}', str(output)) for arg in command]
        env = os.environ.copy()
        if device:
            command = base.bind_gpu_visibility(command, env, device)
            receipt['cuda_visible_devices'] = device['uuid']
            receipt['cuda_logical_device'] = 0
        for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            env[name] = str(request['cpu_threads'])
        env['LD_LIBRARY_PATH'] = str(base.BIN_ROOT) + ':' + env.get('LD_LIBRARY_PATH', '')
        receipt['command'] = command
        receipt['binary_sha256'] = base.sha256(command[0])
        receipt['started_at_utc'] = base.now()
        child_started = time.monotonic()
        with (output / 'stdout.log').open('w') as log:
            proc = base.subprocess.Popen(command, cwd=request['cwd'], env=env, stdout=log,
                                         stderr=base.subprocess.STDOUT, start_new_session=True)
            receipt['pid'] = proc.pid
            _base_atomic_json(output / 'execution-receipt.json', dict(receipt, status='running'))
            last_check = 0.0
            reason = None
            while proc.poll() is None:
                elapsed = time.monotonic() - child_started
                if elapsed > request['max_wall_seconds']:
                    reason = 'reserved_wall_time_exceeded'
                if datetime.now(timezone.utc) >= datetime.fromisoformat(json.loads((data_root / 'runtime/resource-ledger.json').read_text())['deadline_utc']):
                    reason = 'campaign_deadline_reached'
                if elapsed - last_check >= 5:
                    last_check = elapsed
                    live_limits = json.loads((data_root / 'runtime/resource-ledger.json').read_text())['limits']
                    if live_limits.get('storage_policy') == 'home_free_floor':
                        live_free = os.statvfs(data_root).f_bavail * os.statvfs(data_root).f_frsize
                        if live_free < live_limits['home_min_free_bytes']:
                            reason = 'home_free_space_floor_reached'
                    if approval_context:
                        from ds_data02_production import revalidate_approval
                        try:
                            receipt['scientific_approval_revalidation'] = revalidate_approval(approval_context)
                        except (OSError, ValueError) as error:
                            receipt['scientific_approval_revalidation'] = dict(status='failed', error=str(error))
                            reason = 'selected_scientific_approval_changed'
                    if lease_path:
                        _base_atomic_json(lease_path, dict(uuid=device['uuid'], device_index=device['index'],
                                                           attempt_id=attempt, launcher_pid=os.getpid(), pid=proc.pid,
                                                           process_group=proc.pid, host=base.socket.gethostname(), heartbeat_utc=base.now()))
                    if tree_bytes(output) > request['estimated_storage_bytes']:
                        reason = 'reserved_storage_exceeded'
                    if base.cpu_usage() - entry_cpu + base.live_group_cpu_seconds(proc.pid) > reservation['cpu_core_seconds']:
                        reason = 'reserved_cpu_budget_exceeded'
                if reason:
                    base.stop_own_process(proc)
                    break
                time.sleep(0.25)
            proc.wait()
        receipt.update(returncode=proc.returncode, termination_reason=reason,
                       status='completed' if proc.returncode == 0 and reason is None else 'failed')
        if request.get('cpu_task_kind') == 'gencase':
            receipt.update(base.parse_gencase_output((output / 'stdout.log').read_text(errors='replace')))
            if receipt.get('total_particles', 0) <= 0:
                receipt.update(status='failed', error='GenCase actual particle count missing')
    except BaseException as error:
        if proc is not None:
            base.stop_own_process(proc)
        receipt.update(status='failed', error=f'{type(error).__name__}: {error}')
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            receipt['interrupted'] = True
    finally:
        child_elapsed = time.monotonic() - child_started if child_started is not None else 0.0
        measured_cpu = max(0.0, base.cpu_usage() - entry_cpu)
        receipt.update(finished_at_utc=base.now(), elapsed_seconds=child_elapsed,
                       wall_seconds_from_entry=time.monotonic() - entry_wall,
                       cpu_core_seconds=measured_cpu,
                       gpu_seconds=child_elapsed if device and child_started is not None else 0.0,
                       bytes=tree_bytes(output),
                       stdout_sha256=base.sha256(output / 'stdout.log') if (output / 'stdout.log').is_file() else None,
                       input_hashes_after_run={path: base.sha256(path) if Path(path).is_file() else None for path in hashes})
        if receipt['input_hashes_after_run'] != hashes:
            receipt['status'] = 'failed'
            receipt['provenance_error'] = 'input_mutated_during_run'
        if approval_context:
            from ds_data02_production import revalidate_approval
            try:
                receipt['scientific_approval_revalidation'] = revalidate_approval(approval_context)
            except (OSError, ValueError) as error:
                receipt.update(status='failed', provenance_error='selected_scientific_approval_changed',
                               scientific_approval_revalidation=dict(status='failed', error=str(error)))
        _guarded_atomic_json(output / 'execution-receipt.json', receipt)
        if registered:
            with ledger_locked(data_root) as ledger:
                ledger['reservations'] = [row for row in ledger['reservations'] if row['id'] != attempt]
                ledger['charges'].append(dict(id=attempt, gpu_seconds=receipt['gpu_seconds'],
                                              cpu_core_seconds=measured_cpu, new_storage_bytes=receipt['bytes'],
                                              status=receipt['status'], finished_at_utc=receipt['finished_at_utc']))
                for row in ledger['attempts']:
                    if row['id'] == attempt:
                        row.update(status=receipt['status'], finished_at_utc=receipt['finished_at_utc'])
                if lease_path and (proc is None or proc.poll() is not None):
                    lease_path.unlink(missing_ok=True)
        elif lease_path:
            lease_path.unlink(missing_ok=True)
        _ACTIVE_DATA_ROOT = previous_data_root
    return receipt


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
                      actual_bytes=tree_bytes(args.data_root), ledger=ledger)
    else:
        if args.request is None:
            parser.error('--request is required')
        result = run_request(args.request, data_root=args.data_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(args.action == 'run' and result['status'] != 'completed')


if __name__ == '__main__':
    raise SystemExit(main())
