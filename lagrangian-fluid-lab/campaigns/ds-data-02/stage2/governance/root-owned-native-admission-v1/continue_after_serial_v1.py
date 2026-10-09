#!/usr/bin/env python3
"""Root-owned handoff from serial lifecycle audits to ready native evidence.

Wait for the actual ROOT307 terminal registry, then admit one bounded parent
at a time. No payload is read by this orchestrator. Native numerical cause
credit is updated only after the independent verifier and complete CPU
reconciliation; physical fate, flux, dynamics and scientific Q stay UNKNOWN.
Any failed guard or verification stops this continuation for root review.
"""
from pathlib import Path
import collections
import datetime
import fcntl
import hashlib
import json
import os
import subprocess
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
PAYLOAD = {'.bi4', '.obi4', '.ibi4', '.h5', '.hdf5', '.vtk', '.jsonl'}


def sha(path):
    path = Path(path)
    assert path.suffix.lower() not in PAYLOAD and path.stat().st_size <= 10485760
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    path = Path(path)
    assert path.suffix.lower() not in PAYLOAD and path.stat().st_size <= 10485760
    return json.loads(path.read_text())


def ref(path):
    return {'path': str(path), 'sha256': sha(path)}


def new(path, value):
    assert not path.exists()
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def state(unit):
    raw = subprocess.check_output(['systemctl', '--user', 'show', unit, '-p', 'SubState',
                                  '-p', 'MainPID', '-p', 'Result', '-p', 'CPUUsageNSec'], text=True)
    return dict(line.split('=', 1) for line in raw.splitlines())


def serial_monitor_alive():
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            tokens = (entry / 'cmdline').read_bytes().split(b'\0')
        except (OSError, PermissionError):
            continue
        if any(Path(token.decode(errors='replace')).name in ['continue_serial.py', 'resume_serial_v3.py'] for token in tokens):
            return True
    return False


def await_serial_terminal():
    checkpoint = S / 'checkpoints/ROOT307_LIFECYCLE_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V1.json'
    while not checkpoint.exists() or serial_monitor_alive():
        print(json.dumps({'event': 'WAITING_ACTUAL_SERIAL307_HANDOFF', 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          'native_launch_performed': False}), flush=True)
        time.sleep(30)
    value = load(checkpoint)
    assert value['coverage']['actual_saved_mask_cases'] == 335
    assert value['coverage']['historical_alias_unresolved'] == 1
    assert value['coverage']['pending_no_credit_cases'] == 0
    assert value['goal_complete'] is False
    for key in ['current_registry', 'strict_current_plan', 'terminal_proof']:
        assert sha(value[key]['path']) == value[key]['sha256']
    proof = load(value['terminal_proof']['path'])
    assert proof['parent_reservation_released'] and proof['repeat_fee_idempotent']
    assert not load(D / 'runtime/resource-ledger.json')['reservations']
    return checkpoint, Path(value['current_registry']['path']), Path(value['strict_current_plan']['path'])


def prepare_native(num, family, version, source, scope_path, registry, plan):
    q = load(source)
    scope = load(scope_path)
    selected = set(q['physical_case_ids'])
    assert selected <= set(scope['remaining_cause_not_located_case_ids'])
    completed = {row['physical_case_id'] for row in load(plan)['case_records'] if row['status'] == 'ACTUAL_SAVED_MASK_COMPLETED'}
    assert selected <= completed
    q['fresh_native_admission_scope'] = ref(scope_path)
    q['fresh_lifecycle_terminal_registry'] = ref(registry)
    q['fresh_lifecycle_terminal_plan'] = ref(plan)
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_native_serial_forward', '__file__': str(forward)}
    exec(forward.read_text(), context)
    context['sha'] = sha
    context['write'](q, source, f'generic-native-extract-v{version}-root-forward-{num}-003.json',
                     extra=[scope_path, registry, plan, *HERE.glob('*.py')])
    return S / f'requests/generic-native-extract-v{version}-root-forward-{num}-003.json'


def launch_and_wait(request_path, name, num):
    q = load(request_path)
    ledger = load(D / 'runtime/resource-ledger.json')
    assert not ledger['reservations']
    now = datetime.datetime.now(datetime.timezone.utc)
    deadline = datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert now + datetime.timedelta(seconds=q['max_wall_seconds'] + 45) < deadline
    assert sum(c.get('cpu_core_seconds', 0) for c in ledger['charges']) + q['cpu_threads'] * q['max_wall_seconds'] < ledger['limits']['cpu_core_seconds']
    disk = os.statvfs(ledger['limits']['home_path'])
    assert disk.f_bavail * disk.f_frsize - q['estimated_storage_bytes'] >= ledger['limits']['home_min_free_bytes']
    assert not (D / 'families' / q['family_id'] / q['case_id'] / q['attempt_id']).exists()
    for path, expected in q['input_sha256'].items():
        assert sha(path) == expected, path
    code = ('import sys,os,json;sys.path.insert(0,' + repr(str(LAB / 'scripts')) + ');'
            'from ds_data02_runtime_v8 import run_request;r=run_request(' + repr(str(request_path)) +
            ',data_root=' + repr(str(D)) + ',parent_pid=os.getppid());print(json.dumps(r));'
            'raise SystemExit(0 if r["status"]=="completed" else 1)')
    unit = f'ds02-{name}-root-{num}'
    command = ['systemd-run', '--user', '--unit=' + unit, '--property=Type=exec',
               '--property=RemainAfterExit=yes', '--property=RuntimeMaxSec=' + str(q['max_wall_seconds'] + 30),
               '--property=TimeoutStopSec=45', '--property=KillMode=mixed', '--property=CPUAccounting=yes',
               '--property=MemoryAccounting=yes', '--property=MemoryMax=' + str(q['max_memory_bytes'])]
    command += ['--setenv=' + key + '=1' for key in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS']]
    command += [PYTHON, '-B', '-I', '-c', code]
    subprocess.run(command, check=True)
    while True:
        current = state(unit)
        if current['SubState'] != 'running':
            break
        print(json.dumps({'event': 'RUNNING_NATIVE_PARENT', 'namespace': num, 'unit': unit,
                          'CPU_core_seconds': int(current['CPUUsageNSec']) / 1e9}), flush=True)
        time.sleep(30)
    assert current['SubState'] == 'exited' and current['MainPID'] == '0' and current['Result'] == 'success', current
    return unit


def overlay(num, family, version, previous):
    proof_path = S / f'checkpoints/GENERIC_NATIVE_EXTRACT_{family}_V{version}_ACTUAL_ROOT_VERIFICATION_{num}.json'
    proof = load(proof_path)
    assert proof['parent_reservation_released'] and proof['repeat_fee_idempotent']
    value = load(previous)
    ids = set(proof['newly_bound_case_ids'])
    remaining = set(value['remaining_cause_not_located_case_ids'])
    assert ids <= remaining
    assert len(ids) == len(proof['case_verifications'])
    value['actual_join_proofs'].append(ref(proof_path))
    value['at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    value['supersedes'] = ref(previous)
    value['native_cause_bound_per_fluid_id_cases'] += len(ids)
    value['cause_not_located_after_completed_scan_cases'] -= len(ids)
    value['actual_typed_native_saved_frame_join_physical_cases'] += len(ids)
    value['remaining_cause_not_located_case_ids'] = sorted(remaining - ids)
    value['new_' + family + '_join_case_ids'] = sorted(ids)
    for row in proof['case_verifications']:
        value['newly_bound_cases'].append({
            'physical_case_id': row['physical_case_id'], 'family_id': family,
            'previous_classification': 'CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN',
            'classification': 'NATIVE_CAUSE_BOUND_PER_FLUID_ID',
            'fluid_identity_count': row['target_fluid_identity_count'],
            'native_cause_categories': row['native_cause_categories'],
            'source_native_motive_categories': row['native_cause_categories'],
            'evidence': str(proof_path), 'evidence_sha256': sha(proof_path),
            'case_report': row['report'], 'case_report_sha256': row['report_sha256'],
            'saved_frame_join': {'saved_frame_matches': row['saved_frame_matches'], 'saved_frame_mismatches': 0,
                                'saved_frame_unknown': 0, 'physical_time': 'saved brackets only; continuous UNKNOWN'},
        })
    assert value['native_cause_bound_per_fluid_id_cases'] + len(value['remaining_cause_not_located_case_ids']) == 118
    assert value['cause_not_located_after_completed_scan_cases'] == len(value['remaining_cause_not_located_case_ids'])
    value['next'] = 'Close remaining actual native joins, physical impact, 14 reference studies, labels/splits/products; full goal ACTIVE and scientific Q UNKNOWN'
    out = S / f'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT{num}_ACTUAL_SERIAL_OVERLAY_V1.json'
    new(out, value)
    return out


def checkpoint(num, serial_checkpoint, scope_path, proof_path):
    ledger = load(D / 'runtime/resource-ledger.json')
    scope = load(scope_path)
    out = S / f'checkpoints/ROOT{num}_AFTER_SERIAL_ACTUAL_NATIVE_FULL_GOAL_CONTINUATION_V1.json'
    value = {'schema': 'ds02.stage2.root-native-after-serial-actual-continuation.v1',
             'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'goal_status': 'ACTIVE_FULL_SEVEN_ITEMS',
             'goal_complete': False, 'actual_lifecycle_terminal': ref(serial_checkpoint), 'actual_saved_mask_cases': 335,
             'historical_alias_unresolved': 1, 'actual_native_scope': ref(scope_path),
             'native_cause_cases': scope['native_cause_bound_per_fluid_id_cases'],
             'native_cause_unknown': scope['cause_not_located_after_completed_scan_cases'],
             'native_typed_join_cases': scope['actual_typed_native_saved_frame_join_physical_cases'],
             'latest_actual_proof': ref(proof_path), 'root_payload_content_read': False,
             'scientific_qualification': {'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'},
             'resources': {'CPU_core_hours': sum(c.get('cpu_core_seconds', 0) for c in ledger['charges']) / 3600,
                           'GPU_hours': sum(c.get('gpu_seconds', 0) for c in ledger['charges']) / 3600,
                           'attempt_counts': dict(collections.Counter(c['kind'] for c in ledger['attempts'])),
                           'reservations': ledger['reservations'], 'limits': ledger['limits'], 'deadline_utc': ledger['deadline_utc']},
             'remaining_full_goal': ['remaining F4 native joins and per-ID mass impact', '14 sentinel scientific reference terminal studies',
                                     'mass-weighted event/material labels with unknown/error/censoring', 'physical-condition splits and seven family cards',
                                     'portable internal products, independent replay and access/license', 'bounded conditional mechanism coverage']}
    assert not ledger['reservations']
    new(out, value)
    next_path = S / 'NEXT_READY_TASKS.md'
    next_path.write_text('最新实际原生取证恢复点：`' + str(out) + '`（SHA256 ' + sha(out) + '）。完整七项目标 ACTIVE；各项实际覆盖以绑定证据为准，科学Q仍UNKNOWN。\n\n' + next_path.read_text())
    print(json.dumps({'event': 'ACTUAL_NATIVE_HANDOFF_CHECKPOINT', 'namespace': num, 'path': str(out),
                      'native_cause_cases': value['native_cause_cases'], 'native_cause_unknown': value['native_cause_unknown'],
                      'native_typed_join_cases': value['native_typed_join_cases'], 'goal_complete': False}), flush=True)


def main():
    serial_checkpoint, registry, plan = await_serial_terminal()
    scope_path = S / 'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json'
    for num, family, version in [(274, 'F6', 1), (308, 'F4', 2), (309, 'F6', 1)]:
        source = S / f'requests/generic-native-extract-v{version}-root-forward-{num}-002.json'
        request = prepare_native(num, family, version, source, scope_path, registry, plan)
        unit = launch_and_wait(request, f'generic-native-extract-v{version}-{family.lower()}', num)
        subprocess.run([PYTHON, '-B', str(HERE / 'verify_actual_native_v1.py'), str(num), family, str(version),
                        str(request), str(scope_path), sha(scope_path)], cwd=LAB, check=True)
        assert state(unit)['SubState'] == 'dead'
        scope_path = overlay(num, family, version, scope_path)
        proof_path = S / f'checkpoints/GENERIC_NATIVE_EXTRACT_{family}_V{version}_ACTUAL_ROOT_VERIFICATION_{num}.json'
        checkpoint(num, serial_checkpoint, scope_path, proof_path)
    snapshot_request = S / 'requests/native-selected-source-snapshot-root-forward-310-001.json'
    unit = launch_and_wait(snapshot_request, 'native-selected-source-snapshot', 310)
    subprocess.run([PYTHON, '-B', str(HERE / 'verify_snapshot310_v1.py')], cwd=LAB, check=True)
    assert state(unit)['SubState'] == 'dead'
    checkpoint(310, serial_checkpoint, scope_path, S / 'checkpoints/F1_S2_TEN_SELECTED_SOURCE_SNAPSHOT_ACTUAL_ROOT_VERIFICATION_310.json')
    print(json.dumps({'event': 'READY_NATIVE_CONTINUATION_TERMINAL', 'goal_complete': False,
                      'remaining_work': 'admit corrected ROOT279/276, ROOT312/313/311/242 and all remaining full-goal branches'}), flush=True)


if __name__ == '__main__':
    # The lock is administrative state only and never resets resource limits.
    # Keep its file descriptor alive for the complete queue handoff.
    with (D / 'runtime/root-owned-native-after-serial-v1.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another root native continuation already owns this handoff')
        main()
