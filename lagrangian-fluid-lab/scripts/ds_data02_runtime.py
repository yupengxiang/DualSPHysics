#!/usr/bin/env python3
"""Shared DS-DATA-02 process, UUID-lease, and resource accounting runner.

Qualification and bounded CPU work may run here. Production requires an exact
root-approved scientific scope and successful native input QA; this runner
never grants Q-N or counts a finished solver as an accepted data product.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import re
import signal
import socket
import subprocess
import time

DATA_ROOT = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
BASE_LAB = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab')
BIN_ROOT = BASE_LAB / 'vendor/official/DualSPHysics_v5.4/bin/linux'
SOLVER = BIN_ROOT / 'DualSPHysics5.4_linux64'
CPU_KINDS = {'gencase', 'conversion', 'audit', 'labels', 'evaluator', 'preview', 'tests'}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temporary.open('w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@contextmanager
def ledger_locked(data_root=DATA_ROOT):
    runtime = Path(data_root) / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'resource-ledger.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger_path = runtime / 'resource-ledger.json'
        ledger = json.loads(ledger_path.read_text())
        yield ledger
        atomic_json(ledger_path, ledger)


def usage_totals(ledger):
    totals = {key: 0.0 for key in ('gpu_seconds', 'cpu_core_seconds', 'new_storage_bytes')}
    for row in ledger['charges'] + ledger['reservations']:
        for key in totals:
            totals[key] += row.get(key, 0)
    return totals


def check_reservation(ledger, reservation, existing_bytes, *, current_time=None):
    stamp = current_time or datetime.now(timezone.utc)
    if stamp >= datetime.fromisoformat(ledger['deadline_utc']):
        raise RuntimeError('campaign deadline reached')
    if any(row['id'] == reservation['id'] for row in ledger['attempts']):
        raise RuntimeError('attempt_id already registered; never overwrite or restart it')
    totals = usage_totals(ledger)
    for key in ('gpu_seconds', 'cpu_core_seconds'):
        if totals[key] + reservation[key] > ledger['limits'][key]:
            raise RuntimeError(f'parent budget exhausted: {key}')
    reserved_bytes = sum(row.get('new_storage_bytes', 0) for row in ledger['reservations'])
    if existing_bytes + reserved_bytes + reservation['new_storage_bytes'] > ledger['limits']['new_storage_bytes']:
        raise RuntimeError('parent storage budget exhausted')
    kind = reservation['kind']
    if kind in {'qualification', 'production'}:
        cap_key = f'{kind}_attempts'
        used = sum(row['kind'] == kind for row in ledger['attempts'])
        if used >= ledger['limits'][cap_key]:
            raise RuntimeError(f'parent attempt cap reached: {kind}')
        active = [row for row in ledger['reservations'] if row['kind'] in {'qualification', 'production'}]
        if len(active) >= 4:
            raise RuntimeError('initial shared solver concurrency reached')
    if kind == 'cpu' and reservation.get('cpu_task_kind') == 'conversion':
        if sum(row.get('cpu_task_kind') == 'conversion' for row in ledger['reservations']) >= 2:
            raise RuntimeError('initial shared conversion concurrency reached')
    threads = sum(row.get('cpu_threads', 1) for row in ledger['reservations'])
    if threads + reservation['cpu_threads'] > min(64, os.cpu_count() or 1):
        raise RuntimeError('shared CPU thread reservation exceeded')


def tree_bytes(root):
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                pass
    return total


def inventory():
    device_query = subprocess.run(['nvidia-smi', '--query-gpu=index,uuid,name,memory.total,memory.used',
                                   '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True)
    process_query = subprocess.run(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,process_name,used_memory',
                                    '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True)
    devices = []
    for line in device_query.stdout.splitlines():
        values = [part.strip() for part in line.split(',')]
        devices.append(dict(index=int(values[0]), uuid=values[1], name=values[2],
                            total_mib=int(values[3]), used_mib=int(values[4])))
    processes = []
    for line in process_query.stdout.splitlines():
        if not line.strip():
            continue
        values = [part.strip() for part in line.split(',')]
        processes.append(dict(uuid=values[0], pid=int(values[1]), command=values[2], memory_mib=values[3]))
    return dict(observed_at_utc=now(), devices=devices, processes=processes)


def choose_gpu(snapshot, leased_uuids, peak_mib):
    busy = {row['uuid'] for row in snapshot['processes']}
    preference = [2, 5, 6, 7]  # GPUs 1, 3, 4 strictly preserved for user wx; GPU 0 historically preserved.
    for index in preference:
        for device in snapshot['devices']:
            if device['index'] != index or device['uuid'] in leased_uuids | busy:
                continue
            # Require an idle baseline as well as the estimated peak plus margin.
            if device['used_mib'] > 256:
                continue
            if device['total_mib'] - device['used_mib'] < peak_mib * 1.25 + 1024:
                continue
            return device
    raise RuntimeError('no eligible idle GPU with enough predicted memory and a free UUID lease')


def cpu_usage():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def live_group_cpu_seconds(process_group):
    """Account currently running descendants, before wait() exposes rusage."""
    ticks = os.sysconf('SC_CLK_TCK')
    total = 0.0
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == process_group:
                total += (int(fields[11]) + int(fields[12])) / ticks
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            continue
    return total


def parse_gencase_output(text):
    result = {}
    total = re.search(r'Total particles:\s*([\d,]+)', text)
    fluid = re.search(r'Fluid\.\.*:\s*([\d,]+)', text)
    dimension = re.search(r'Data2D=\[([01])\]', text)
    if total:
        result['total_particles'] = int(total.group(1).replace(',', ''))
    if fluid:
        result['fluid_particles'] = int(fluid.group(1).replace(',', ''))
    if dimension:
        result['solver_dimension_from_gencase'] = 2 if dimension.group(1) == '1' else 3
    return result


def git_launch_state(root):
    def query(args):
        return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    return dict(commit=query(['rev-parse', 'HEAD']), status=query(['status', '--porcelain']),
                diff_sha256=hashlib.sha256(query(['diff', 'HEAD']).encode()).hexdigest())


def validate_request(request, *, approval_context=None):
    for key in ('family_id', 'case_id', 'attempt_id', 'kind', 'command', 'cwd', 'max_wall_seconds',
                'cpu_threads', 'estimated_storage_bytes', 'input_files', 'worktree_root'):
        if key not in request:
            raise ValueError(f'missing request field: {key}')
    if request['family_id'] not in {'infra', *[f'F{i}' for i in range(1, 8)]}:
        raise ValueError('unknown family_id')
    for key in ('case_id', 'attempt_id'):
        value = request[key]
        if not isinstance(value, str) or not value or any(x not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for x in value):
            raise ValueError(f'unsafe identity: {key}')
    if request['kind'] not in {'cpu', 'qualification', 'production'}:
        raise ValueError('invalid kind')
    if request['kind'] == 'cpu' and request.get('cpu_task_kind') not in CPU_KINDS:
        raise ValueError('CPU task is outside the dataset-only allowlist')
    command = request['command']
    if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command):
        raise ValueError('command must be an argv list, never shell text')
    if request['max_wall_seconds'] <= 0 or request['cpu_threads'] < 1 or request['estimated_storage_bytes'] < 0:
        raise ValueError('invalid resource request')
    if request['kind'] in {'qualification', 'production'}:
        if Path(command[0]).resolve() != SOLVER.resolve() or any(arg.startswith('-cpu') for arg in command[1:]):
            raise ValueError('solver work must use the approved GPU solver')
        if request.get('estimated_peak_gpu_mib', 0) <= 0:
            raise ValueError('solver work requires a GPU peak estimate')
        preflight = json.loads(Path(request['gencase_receipt']).read_text())
        if preflight.get('returncode', preflight.get('gencase_returncode')) != 0:
            raise ValueError('GenCase did not complete successfully')
        count = preflight.get('total_particles')
        if not isinstance(count, int) or count <= 0:
            raise ValueError('GenCase actual particle count is required')
        fluid_count = preflight.get('fluid_particles')
        if not isinstance(fluid_count, int) or fluid_count <= 0 or fluid_count > count:
            raise ValueError('GenCase must contain a positive actual fluid particle count')
        if preflight.get('solver_dimension_from_gencase') != 3:
            raise ValueError('DS-DATA-02 core requires actual 3D GenCase evidence')
        expected_hash = request.get('gencase_receipt_sha256')
        if expected_hash and sha256(request['gencase_receipt']) != expected_hash:
            raise ValueError('GenCase receipt hash differs from the registered request')
        if count > 5_000_000 and not request.get('oversize_cost_review'):
            raise ValueError('over five million particles requires explicit cost review')
    hashes = {}
    for value in request['input_files']:
        path = Path(value).resolve()
        if not path.is_file():
            raise ValueError(f'input file missing: {path}')
        hashes[str(path)] = sha256(path)
    if not hashes:
        raise ValueError('input provenance is mandatory')
    if request['kind'] == 'production':
        from ds_data02_production import INDEX, authorize
        if str(INDEX.resolve()) in hashes:
            raise ValueError('mutable approval registry must not be an immutable input; selected approval is recorded separately')
        hashes.update(authorize(request, approval_context=approval_context))
    return hashes


def stop_own_process(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def bind_gpu_visibility(command, environment, device):
    """Expose just the leased UUID; CUDA then numbers it as logical device 0."""
    command = [arg for arg in command if not arg.startswith('-gpu')]
    command.insert(1, '-gpu:0')
    environment['CUDA_VISIBLE_DEVICES'] = device['uuid']
    return command


def run_request(request_path, *, data_root=DATA_ROOT):
    data_root = Path(data_root)
    request = json.loads(Path(request_path).read_text())
    before_cpu = cpu_usage()
    approval_context = {}
    hashes = validate_request(request, approval_context=approval_context)
    attempt = f"{request['family_id']}/{request['case_id']}/{request['attempt_id']}"
    output = data_root / 'families' / attempt
    if output.exists():
        raise FileExistsError(f'attempt output already exists: {output}')
    reservation = dict(id=attempt, kind=request['kind'], cpu_task_kind=request.get('cpu_task_kind'),
                       cpu_threads=request['cpu_threads'], cpu_core_seconds=request['cpu_threads'] * request['max_wall_seconds'],
                       gpu_seconds=request['max_wall_seconds'] if request['kind'] in {'qualification', 'production'} else 0,
                       new_storage_bytes=request['estimated_storage_bytes'], reserved_at_utc=now(),
                       launcher_pid=os.getpid(), host=socket.gethostname())
    device = None
    lease_path = None
    registered = False
    proc = None
    started = None
    receipt = dict(schema='ds02.execution-receipt.v1', request=request,
                   request_sha256=sha256(request_path), input_hashes_at_launch=hashes,
                   runner_source=str(Path(__file__).resolve()), runner_sha256=sha256(__file__),
                   runner_git_at_launch=git_launch_state(Path(__file__).resolve().parents[2]),
                   git_at_launch=git_launch_state(request['worktree_root']), started_at_utc=None,
                   output_root=str(output), numerical_reference_status='approved_scope_at_launch' if request['kind'] == 'production' else 'not_assessed',
                   production_product_acceptance='not_assessed')
    if approval_context:
        receipt['scientific_approval_at_launch'] = approval_context
    try:
        with ledger_locked(data_root) as ledger:
            check_reservation(ledger, reservation, tree_bytes(data_root))
            free_disk = os.statvfs(data_root).f_bavail * os.statvfs(data_root).f_frsize
            if free_disk < request['estimated_storage_bytes'] + 2 * 1024 ** 3:
                raise RuntimeError('insufficient filesystem headroom')
            if request['kind'] in {'qualification', 'production'}:
                snapshot = inventory()
                leases = list((data_root / 'leases').glob('*.json'))
                leased_uuids = {json.loads(p.read_text())['uuid'] for p in leases}
                device = choose_gpu(snapshot, leased_uuids, request['estimated_peak_gpu_mib'])
                reservation['gpu_uuid'] = device['uuid']
                lease_path = data_root / 'leases' / (device['uuid'] + '.json')
                with lease_path.open('x') as handle:
                    json.dump(dict(uuid=device['uuid'], device_index=device['index'], attempt_id=attempt,
                                   launcher_pid=os.getpid(), host=socket.gethostname(), heartbeat_utc=now()), handle)
                receipt['gpu_inventory_at_launch'] = snapshot
                receipt['gpu'] = device
            ledger['reservations'].append(reservation)
            ledger['attempts'].append(dict(id=attempt, kind=request['kind'], status='reserved', started_at_utc=now()))
            registered = True
        output.mkdir(parents=True, exist_ok=False)
        command = request['command'][:]
        if request.get('cpu_task_kind') == 'gencase' and Path(command[0]).resolve() == (BIN_ROOT / 'GenCase_linux64').resolve():
            # GenCase defaults to 16 threads even when OMP_NUM_THREADS is set.
            command = [arg for arg in command if not arg.startswith('-threads:')]
            command.append(f"-threads:{request['cpu_threads']}")
        command = [arg.replace('{attempt_root}', str(output)) for arg in command]
        env = os.environ.copy()
        if device:
            command = bind_gpu_visibility(command, env, device)
            receipt['cuda_visible_devices'] = device['uuid']
            receipt['cuda_logical_device'] = 0
        for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            env[name] = str(request['cpu_threads'])
        env['LD_LIBRARY_PATH'] = str(BIN_ROOT) + ':' + env.get('LD_LIBRARY_PATH', '')
        receipt['command'] = command
        receipt['binary_sha256'] = sha256(command[0])
        receipt['started_at_utc'] = now()
        started = time.monotonic()
        with (output / 'stdout.log').open('w') as log:
            proc = subprocess.Popen(command, cwd=request['cwd'], env=env, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            receipt['pid'] = proc.pid
            atomic_json(output / 'execution-receipt.json', dict(receipt, status='running'))
            last_check = 0.0
            reason = None
            while proc.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > request['max_wall_seconds']:
                    reason = 'reserved_wall_time_exceeded'
                if datetime.now(timezone.utc) >= datetime.fromisoformat(json.loads((data_root / 'runtime/resource-ledger.json').read_text())['deadline_utc']):
                    reason = 'campaign_deadline_reached'
                if elapsed - last_check >= 5:
                    last_check = elapsed
                    if approval_context:
                        from ds_data02_production import revalidate_approval
                        try:
                            receipt['scientific_approval_revalidation'] = revalidate_approval(approval_context)
                        except (OSError, ValueError) as error:
                            receipt['scientific_approval_revalidation'] = dict(status='failed', error=str(error))
                            reason = 'selected_scientific_approval_changed'
                    if lease_path:
                        atomic_json(lease_path, dict(uuid=device['uuid'], device_index=device['index'],
                                                   attempt_id=attempt, launcher_pid=os.getpid(), pid=proc.pid,
                                                   process_group=proc.pid, host=socket.gethostname(), heartbeat_utc=now()))
                    if tree_bytes(output) > request['estimated_storage_bytes']:
                        reason = 'reserved_storage_exceeded'
                    if cpu_usage() - before_cpu + live_group_cpu_seconds(proc.pid) > reservation['cpu_core_seconds']:
                        reason = 'reserved_cpu_budget_exceeded'
                if reason:
                    stop_own_process(proc)
                    break
                time.sleep(0.25)
            proc.wait()
        receipt.update(returncode=proc.returncode, termination_reason=reason,
                       status='completed' if proc.returncode == 0 and reason is None else 'failed')
        if request.get('cpu_task_kind') == 'gencase':
            receipt.update(parse_gencase_output((output / 'stdout.log').read_text(errors='replace')))
            if receipt.get('total_particles', 0) <= 0:
                receipt.update(status='failed', error='GenCase actual particle count missing')
    except BaseException as error:
        if proc is not None:
            stop_own_process(proc)
        receipt.update(status='failed', error=f'{type(error).__name__}: {error}')
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            receipt['interrupted'] = True
    finally:
        elapsed = time.monotonic() - started if started is not None else 0.0
        measured_cpu = cpu_usage() - before_cpu
        receipt.update(finished_at_utc=now(), elapsed_seconds=elapsed, cpu_core_seconds=measured_cpu,
                       gpu_seconds=elapsed if device and started is not None else 0.0,
                       bytes=tree_bytes(output), stdout_sha256=sha256(output / 'stdout.log') if (output / 'stdout.log').is_file() else None,
                       input_hashes_after_run={path: sha256(path) if Path(path).is_file() else None for path in hashes})
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
        atomic_json(output / 'execution-receipt.json', receipt)
        if registered:
            with ledger_locked(data_root) as ledger:
                ledger['reservations'] = [row for row in ledger['reservations'] if row['id'] != attempt]
                ledger['charges'].append(dict(id=attempt, gpu_seconds=receipt['gpu_seconds'],
                                              cpu_core_seconds=measured_cpu, new_storage_bytes=receipt['bytes'],
                                              status=receipt['status'], finished_at_utc=receipt['finished_at_utc']))
                for row in ledger['attempts']:
                    if row['id'] == attempt:
                        row.update(status=receipt['status'], finished_at_utc=receipt['finished_at_utc'])
                # Release only after this launcher has waited for its own process.
                if lease_path and (proc is None or proc.poll() is not None):
                    lease_path.unlink(missing_ok=True)
        elif lease_path:
            lease_path.unlink(missing_ok=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'status', 'run'])
    parser.add_argument('--request', type=Path)
    args = parser.parse_args()
    if args.action == 'inventory':
        result = inventory()
    elif args.action == 'status':
        ledger = json.loads((DATA_ROOT / 'runtime/resource-ledger.json').read_text())
        result = dict(totals_with_reservations=usage_totals(ledger), actual_bytes=tree_bytes(DATA_ROOT), ledger=ledger)
    else:
        if args.request is None:
            parser.error('--request is required')
        result = run_request(args.request)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(args.action == 'run' and result['status'] != 'completed')


if __name__ == '__main__':
    raise SystemExit(main())
