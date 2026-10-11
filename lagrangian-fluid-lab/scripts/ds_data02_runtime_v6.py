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

UPSTREAM_NAS = Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first')
NAS_HEADROOM_FLOOR_BYTES = 2 * 1024 ** 3
UPSTREAM_BATCH_STORAGE_BYTES = 50 * 1024 ** 3
HISTORICAL_EXTERNAL_SCRATCH_ATTEMPT = 'infra/UF_NAS_PREFLIGHT/check-001'
HISTORICAL_EXTERNAL_SCRATCH = UPSTREAM_NAS / 'scratch'


def _upstream_id(value):
    parts = str(value).split('/')
    return len(parts) == 3 and parts[1].startswith('UF_')


def _attempt_id(request):
    return f"{request['family_id']}/{request['case_id']}/{request['attempt_id']}"


def _is_nas_request(request):
    return request.get('output_storage') == 'upstream_nas'


def _row_nas_storage_bytes(row):
    """Return bytes reserved on NAS by a ledger row.

    New rows carry ``output_storage`` explicitly.  A legacy upstream
    reservation without that field is treated as NAS-backed conservatively;
    otherwise a concurrent old launcher could bypass the NAS floor.
    """
    storage = row.get('output_storage')
    if storage == 'home':
        return 0
    if storage == 'upstream_nas' or (
        storage is None and _upstream_id(row.get('id'))
    ):
        return row.get('new_storage_bytes', 0)
    return 0


def _nas_reserved_bytes(ledger, *, exclude_id=None):
    return sum(
        _row_nas_storage_bytes(row)
        for row in ledger.get('reservations', [])
        if row.get('id') != exclude_id
    )


def _is_historical_external_scratch(request):
    external_scratch = request.get('external_scratch')
    if not isinstance(external_scratch, str):
        return False
    return (
        _attempt_id(request) == HISTORICAL_EXTERNAL_SCRATCH_ATTEMPT
        and request.get('family_id') == 'infra'
        and request.get('case_id') == 'UF_NAS_PREFLIGHT'
        and request.get('attempt_id') == 'check-001'
        and request.get('kind') == 'cpu'
        and request.get('cpu_task_kind') == 'audit'
        and Path(external_scratch).resolve() == HISTORICAL_EXTERNAL_SCRATCH.resolve()
    )


def _validate_storage_request(request):
    if 'external_scratch' not in request:
        return
    if _is_historical_external_scratch(request):
        return
    raise ValueError(
        'external_scratch is not supported; place temporary files under the attempt root'
    )


def _nas_available():
    if not Path('/data/nas').is_mount():
        raise RuntimeError('upstream NAS mount is absent; no local fallback')
    if UPSTREAM_NAS.stat().st_dev == Path('/home/jade').stat().st_dev:
        raise RuntimeError('upstream NAS must be a separate filesystem')
    stat = os.statvfs(UPSTREAM_NAS)
    return stat.f_bavail * stat.f_frsize


def _assert_nas_path_live(path):
    """Check the mount and device immediately before an NAS write/scan."""
    _nas_available()
    root = UPSTREAM_NAS.resolve()
    target = Path(path).expanduser().resolve()
    if not target.is_relative_to(root):
        raise RuntimeError('upstream output escapes NAS root')
    probe = target if target.exists() else target.parent
    if probe.exists() and probe.stat().st_dev != root.stat().st_dev:
        raise RuntimeError('upstream NAS device changed; no local fallback')


def _output_path(request, data_root):
    attempt = _attempt_id(request)
    storage = request.get('output_storage', 'home')
    if storage == 'home':
        return data_root / 'families' / attempt
    if storage != 'upstream_nas' or not _upstream_id(attempt):
        raise ValueError('unapproved output storage or upstream namespace')
    _nas_available()
    output = UPSTREAM_NAS / 'runs' / attempt
    _assert_nas_path_live(output)
    return output


def _check_upstream_batch(ledger, reservation, request):
    if not _upstream_id(reservation['id']):
        return
    rows = [row for row in ledger['charges'] + ledger['reservations']
            if _upstream_id(row.get('id'))]
    for key, cap in [('gpu_seconds', 24 * 3600),
                     ('cpu_core_seconds', 96 * 3600),
                     ('new_storage_bytes', UPSTREAM_BATCH_STORAGE_BYTES)]:
        if sum(row.get(key, 0) for row in rows) + reservation[key] > cap:
            raise RuntimeError('upstream first-batch allocation exhausted: ' + key)
    solvers = [row for row in ledger['attempts'] if _upstream_id(row.get('id'))
               and row.get('kind') in {'qualification', 'production'}]
    if reservation['kind'] in {'qualification', 'production'} and len(solvers) >= 24:
        raise RuntimeError('upstream first-batch solver attempt cap reached')
    heavy = lambda row: row.get('kind') in {'qualification', 'production'} or row.get('cpu_task_kind') == 'conversion'
    if heavy(reservation) and any(heavy(row) for row in ledger['reservations']):
        raise RuntimeError('upstream single heavy-task queue is occupied')
    if _is_nas_request(request):
        reserved = _nas_reserved_bytes(ledger, exclude_id=reservation['id'])
        if _nas_available() - reserved < reservation['new_storage_bytes'] + NAS_HEADROOM_FLOOR_BYTES:
            raise RuntimeError('insufficient upstream NAS headroom')


def _terminal_upstream_overrun(
    ledger,
    reservation,
    *,
    gpu_seconds,
    cpu_core_seconds,
    storage_bytes,
):
    """Compare measured terminal usage with the upstream batch caps.

    The admission reservation is excluded because the measured charge replaces
    it.  Returning details instead of raising lets the receipt retain a true
    failed/overrun status while the ledger still records the measured charge.
    """
    if not _upstream_id(reservation['id']):
        return None
    rows = [
        row for row in ledger['charges'] + ledger['reservations']
        if _upstream_id(row.get('id')) and row.get('id') != reservation['id']
    ]
    measured = {
        'gpu_seconds': gpu_seconds,
        'cpu_core_seconds': cpu_core_seconds,
        'new_storage_bytes': storage_bytes,
    }
    caps = {
        'gpu_seconds': 24 * 3600,
        'cpu_core_seconds': 96 * 3600,
        'new_storage_bytes': UPSTREAM_BATCH_STORAGE_BYTES,
    }
    overrun = {}
    for key, cap in caps.items():
        used_before = sum(row.get(key, 0) for row in rows)
        total = used_before + measured[key]
        if total > cap:
            overrun[key] = {
                'used_before': used_before,
                'measured': measured[key],
                'cap': cap,
                'excess': total - cap,
            }
    return overrun or None


def _apply_terminal_upstream_guard(ledger, reservation, receipt, measured_cpu):
    """Attach a measured batch overrun after the exact receipt byte fixed point."""
    storage_bytes = receipt.get('bytes')
    if not isinstance(storage_bytes, int):
        return None
    overrun = _terminal_upstream_overrun(
        ledger,
        reservation,
        gpu_seconds=receipt.get('gpu_seconds', 0),
        cpu_core_seconds=measured_cpu,
        storage_bytes=storage_bytes,
    )
    if overrun:
        receipt['status'] = 'failed'
        receipt['upstream_batch_overrun'] = overrun
        if not receipt.get('termination_reason'):
            receipt['termination_reason'] = 'upstream_batch_limit_exceeded_after_run'
    return overrun


def _unresolved_storage_reservation_bytes(ledger, reservation):
    """Reserve the remaining upstream storage budget when NAS bytes are unknown."""
    used_before = sum(
        row.get('new_storage_bytes', 0)
        for row in ledger['charges'] + ledger['reservations']
        if _upstream_id(row.get('id')) and row.get('id') != reservation['id']
    )
    remaining_cap = max(0, UPSTREAM_BATCH_STORAGE_BYTES - used_before)
    return max(reservation['new_storage_bytes'], remaining_cap)


def _retain_unresolved_nas_reservation(ledger, reservation, error):
    """Keep the reservation until an operator can inspect the lost NAS output."""
    conservative_bytes = _unresolved_storage_reservation_bytes(ledger, reservation)
    reservation.update(
        output_storage='upstream_nas',
        storage_unresolved=True,
        storage_unresolved_reason=str(error),
        storage_unresolved_at_utc=base.now(),
        estimated_storage_bytes=reservation['new_storage_bytes'],
        new_storage_bytes=conservative_bytes,
    )
    for row in ledger['reservations']:
        if row.get('id') == reservation['id']:
            row.update(reservation)
            break
    return conservative_bytes


def _control_receipt_path(data_root, attempt):
    safe_attempt = attempt.replace('/', '__')
    return Path(data_root) / 'runtime' / 'upstream-control' / f'{safe_attempt}.json'


def _write_unresolved_control_receipt(data_root, attempt, output, reservation, error):
    """Write only a small Home control record after NAS finalization is lost."""
    path = _control_receipt_path(data_root, attempt)
    value = {
        'schema': 'ds02.upstream-control-receipt.v1',
        'attempt_id': attempt,
        'status': 'failed',
        'observed_at_utc': base.now(),
        'output_root': str(output),
        'error': str(error),
        'nas_write_skipped': True,
        'storage': {
            'status': 'unresolved',
            'reservation_retained': True,
            'conservative_reservation_bytes': reservation['new_storage_bytes'],
            'reason': 'NAS unavailable during finalization; manual reconciliation required',
        },
    }
    try:
        base.atomic_json(path, value)
    except OSError:
        return None
    return path


def _set_unresolved_storage_fields(value, error, reservation_bytes):
    value['status'] = 'failed'
    value['storage_unresolved'] = True
    value['storage_unresolved_reason'] = str(error)
    value['bytes'] = None
    value['terminal_storage_guard'] = {
        'status': 'unresolved',
        'actual_bytes': None,
        'reservation_bytes': reservation_bytes,
        'measurement': 'NAS unavailable; output tree could not be measured safely',
    }


def _prepare_attempt_tmpdir(output, request):
    """Contain process temporary files inside the registered attempt root."""
    tmpdir = Path(output) / '.tmp'
    tmpdir.mkdir(parents=True, exist_ok=True)
    if _is_nas_request(request):
        _assert_nas_path_live(tmpdir)
    return tmpdir


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
    _validate_storage_request(request)
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
        if Path(path).resolve().is_relative_to(UPSTREAM_NAS.resolve()):
            _assert_nas_path_live(path)
        predicted = _prepare_terminal_receipt(path, value)
        if predicted is None:
            return _base_atomic_json(path, value)
        _base_atomic_json(path, value)
        if Path(path).resolve().is_relative_to(UPSTREAM_NAS.resolve()):
            _assert_nas_path_live(path)
        actual = base.tree_bytes(Path(path).parent)
        if actual == value['bytes'] == predicted:
            return
    raise RuntimeError('terminal storage receipt changed after fixed-point write')


def _guarded_atomic_json(path, value):
    path = Path(path)
    if path.resolve().is_relative_to(UPSTREAM_NAS.resolve()):
        _assert_nas_path_live(path)
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
    attempt = _attempt_id(request)
    output = _output_path(request, data_root)
    if output.exists():
        raise FileExistsError(f'attempt output already exists: {output}')
    reservation = dict(id=attempt, kind=request['kind'], cpu_task_kind=request.get('cpu_task_kind'),
                       cpu_threads=request['cpu_threads'],
                       cpu_core_seconds=request['cpu_threads'] * request['max_wall_seconds'],
                       gpu_seconds=request['max_wall_seconds'] if request['kind'] in {'qualification', 'production'} else 0,
                       new_storage_bytes=request['estimated_storage_bytes'],
                       output_storage=request.get('output_storage', 'home'),
                       reserved_at_utc=base.now(),
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
            _check_upstream_batch(ledger, reservation, request)
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
        tmpdir = _prepare_attempt_tmpdir(output, request)
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
        for name in ('TMPDIR', 'TMP', 'TEMP'):
            env[name] = str(tmpdir)
        env['LD_LIBRARY_PATH'] = str(base.BIN_ROOT) + ':' + env.get('LD_LIBRARY_PATH', '')
        receipt['command'] = command
        receipt['tmpdir'] = str(tmpdir)
        receipt['binary_sha256'] = base.sha256(command[0])
        receipt['started_at_utc'] = base.now()
        child_started = time.monotonic()
        with (output / 'stdout.log').open('w') as log:
            proc = base.subprocess.Popen(command, cwd=request['cwd'], env=env, stdout=log,
                                         stderr=base.subprocess.STDOUT, start_new_session=True)
            receipt['pid'] = proc.pid
            if _is_nas_request(request):
                _assert_nas_path_live(output / 'execution-receipt.json')
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
                    if _is_nas_request(request) and _nas_available() < NAS_HEADROOM_FLOOR_BYTES:
                        reason = 'upstream_nas_headroom_reached'
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
                    if _is_nas_request(request):
                        _assert_nas_path_live(output)
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
        # Perform every source post-hash, output byte walk, stdout hash, and
        # approval revalidation before taking the accounting cutoff.  v2/v5
        # measured before this comprehension, which omitted large post-run
        # source hashes from both the receipt and the parent charge.
        nas_unavailable_error = None
        try:
            input_hashes_after_run = {
                path: base.sha256(path) if Path(path).is_file() else None for path in hashes
            }
        except OSError as error:
            input_hashes_after_run = {}
            if _is_nas_request(request):
                nas_unavailable_error = error
            else:
                raise
        output_bytes = None
        stdout_hash = None
        if nas_unavailable_error is None:
            try:
                if _is_nas_request(request):
                    _assert_nas_path_live(output)
                output_bytes = tree_bytes(output)
                if _is_nas_request(request):
                    _assert_nas_path_live(output)
                stdout_hash = (
                    base.sha256(output / 'stdout.log')
                    if (output / 'stdout.log').is_file() else None
                )
            except (OSError, RuntimeError) as error:
                if _is_nas_request(request):
                    nas_unavailable_error = error
                else:
                    raise
        if input_hashes_after_run != hashes:
            receipt['status'] = 'failed'
            receipt['provenance_error'] = 'input_mutated_during_run'
        if approval_context:
            from ds_data02_production import revalidate_approval
            try:
                receipt['scientific_approval_revalidation'] = revalidate_approval(approval_context)
            except (OSError, ValueError) as error:
                receipt.update(status='failed', provenance_error='selected_scientific_approval_changed',
                               scientific_approval_revalidation=dict(status='failed', error=str(error)))
        measured_cpu = max(0.0, base.cpu_usage() - entry_cpu)
        wall_from_entry = time.monotonic() - entry_wall
        receipt.update(finished_at_utc=base.now(), elapsed_seconds=child_elapsed,
                       wall_seconds_from_entry=wall_from_entry,
                       cpu_core_seconds=measured_cpu,
                       gpu_seconds=child_elapsed if device and child_started is not None else 0.0,
                       bytes=output_bytes, stdout_sha256=stdout_hash,
                       input_hashes_after_run=input_hashes_after_run)
        receipt['timing_scope']['cpu_cutoff'] = 'after_source_posthash_output_bytes_stdout_hash_and_approval_revalidation'
        receipt['timing_scope']['wall_cutoff'] = 'after_source_posthash_output_bytes_stdout_hash_and_approval_revalidation'
        if registered:
            with ledger_locked(data_root) as ledger:
                unresolved = nas_unavailable_error is not None
                control_path = None
                if unresolved:
                    conservative_bytes = _retain_unresolved_nas_reservation(
                        ledger, reservation, nas_unavailable_error
                    )
                    _set_unresolved_storage_fields(receipt, nas_unavailable_error, conservative_bytes)
                    control_path = _write_unresolved_control_receipt(
                        data_root, attempt, output, reservation, nas_unavailable_error
                    )
                else:
                    try:
                        _guarded_atomic_json(output / 'execution-receipt.json', receipt)
                        # The terminal writer changes receipt['bytes'] to the
                        # exact fixed-point tree size.  Recheck the upstream
                        # cap against that value and rewrite until the added
                        # overrun details themselves are included in the
                        # final fixed point.
                        for _ in range(8):
                            prior_overrun = receipt.get('upstream_batch_overrun')
                            overrun = _apply_terminal_upstream_guard(
                                ledger, reservation, receipt, measured_cpu
                            )
                            if not overrun or prior_overrun == overrun:
                                break
                            _guarded_atomic_json(output / 'execution-receipt.json', receipt)
                        else:
                            raise RuntimeError('terminal upstream batch guard did not converge')
                    except (OSError, RuntimeError) as error:
                        if _is_nas_request(request):
                            unresolved = True
                            conservative_bytes = _retain_unresolved_nas_reservation(
                                ledger, reservation, error
                            )
                            _set_unresolved_storage_fields(receipt, error, conservative_bytes)
                            control_path = _write_unresolved_control_receipt(
                                data_root, attempt, output, reservation, error
                            )
                        else:
                            receipt['status'] = 'failed'
                            receipt['finalization_error'] = f'{type(error).__name__}: {error}'
                    if unresolved:
                        # The NAS receipt was never safely committed; retain
                        # the conservative reservation and do not charge an
                        # unknown output tree as zero bytes.
                        pass
                    else:
                        ledger['reservations'] = [
                            row for row in ledger['reservations'] if row['id'] != attempt
                        ]
                        ledger['charges'].append(dict(
                            id=attempt,
                            gpu_seconds=receipt['gpu_seconds'],
                            cpu_core_seconds=measured_cpu,
                            new_storage_bytes=receipt['bytes'],
                            output_storage=reservation.get('output_storage', 'home'),
                            status=receipt['status'],
                            finished_at_utc=receipt['finished_at_utc'],
                        ))
                if control_path:
                    receipt['control_receipt'] = str(control_path)
                for row in ledger['attempts']:
                    if row['id'] == attempt:
                        row.update(status=receipt['status'], finished_at_utc=receipt['finished_at_utc'])
                        if unresolved:
                            row['storage_unresolved'] = True
                if lease_path and (proc is None or proc.poll() is not None):
                    lease_path.unlink(missing_ok=True)
        elif lease_path:
            lease_path.unlink(missing_ok=True)
        elif nas_unavailable_error is None:
            try:
                _guarded_atomic_json(output / 'execution-receipt.json', receipt)
            except (OSError, RuntimeError) as error:
                receipt['status'] = 'failed'
                receipt['finalization_error'] = f'{type(error).__name__}: {error}'
        else:
            _write_unresolved_control_receipt(
                data_root, attempt, output, reservation, nas_unavailable_error
            )
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
