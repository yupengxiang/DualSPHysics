"""Preserve ROOT308's pre-reservation path failure and resume fresh requests.

Only bounded metadata is read here. Scientific workers and independent
verifiers remain frozen. New requests use absolute static paths and the
already tested V10 runner closure. No old request or receipt is rewritten.
"""
from pathlib import Path
import copy
import datetime
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
LAB = S.parents[2]
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
sys.path.insert(0, str(LAB / 'scripts'))
from ds_data02_runtime_v8 import ledger_locked
from ds_data02_runtime_v10_git_bound import _validate_with_closure


def admission():
    path = S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py'
    spec = importlib.util.spec_from_file_location('root308_frozen_admission', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reconcile_failure(a):
    unit = 'ds02-generic-native-extract-v2-f4-root-308'
    path = S / 'requests/generic-native-extract-v2-root-forward-308-003.json'
    q = a.load(path)
    raw = subprocess.check_output(['systemctl', '--user', 'show', unit, '-p',
        'SubState', '-p', 'MainPID', '-p', 'Result', '-p', 'ExecMainStatus',
        '-p', 'CPUUsageNSec', '-p', 'TasksCurrent', '-p', 'ControlGroup'], text=True)
    st = dict(line.split('=', 1) for line in raw.splitlines())
    assert st['SubState'] == 'failed' and st['Result'] == 'exit-code'
    assert st['MainPID'] == '0' and st['ExecMainStatus'] == '1'
    assert st['TasksCurrent'] in {'0', '[not set]'}
    if st['ControlGroup']:
        assert st['ControlGroup'].endswith(unit + '.service')
        procs = Path('/sys/fs/cgroup') / st['ControlGroup'].lstrip('/') / 'cgroup.procs'
        assert not procs.exists() or not procs.read_text().strip()
    base = D / 'families' / q['family_id'] / q['case_id'] / q['attempt_id']
    assert not base.exists(), 'pre-reservation failure unexpectedly created outputs'
    journal = subprocess.check_output(['journalctl', '--user', '-u', unit,
                                      '-n', '60', '--no-pager', '-o', 'short-iso'], text=True)
    assert len(journal.encode()) < 1048576
    assert 'input file missing: /home/jade/campaigns/' in journal
    ident = '/'.join(q[k] for k in ['family_id', 'case_id', 'attempt_id'])
    ep = S / 'accounting/ROOT308_PRE_RESERVATION_PATH_FAILURE_EVIDENCE_V1.json'
    pp = S / 'checkpoints/ROOT308_PRE_RESERVATION_FAILED_CPU_RECONCILIATION_V1.json'
    if not ep.exists():
        a.new(ep, {'schema': 'ds02.stage2.pre-reservation-parent-failure.v1',
            'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'request': a.ref(path), 'unit': unit, 'systemd': st, 'journal': journal,
            'attempt_root_absent': True, 'runtime_receipt_reconstructed': False,
            'root_payload_content_read': False, 'scientific_credit': 0})
    e = a.load(ep)
    assert e['request'] == a.ref(path) and e['systemd'] == st
    charge = {'id': ident, 'gpu_seconds': 0.0,
        'cpu_core_seconds': int(st['CPUUsageNSec']) / 1e9,
        'new_storage_bytes': 0, 'status': 'failed', 'finished_at_utc': e['utc'],
        'accounting_source': 'actual_systemd_pre_reservation_failure_cpu',
        'failure_evidence': a.ref(ep)}
    with ledger_locked(D) as ledger:
        before = copy.deepcopy(ledger)
        assert not ledger['reservations']
        previous = [c for c in ledger['charges'] if c['id'] == ident]
        if previous:
            assert previous == [charge]
            assert len([r for r in ledger['attempts'] if r['id'] == ident and r['status'] == 'failed']) == 1
            assert ledger == before
        else:
            assert not any(r['id'] == ident for r in ledger['attempts'])
            ledger['charges'].append(charge)
            ledger['attempts'].append({'id': ident, 'kind': 'cpu', 'status': 'failed',
                'started_at_utc': e['utc'], 'finished_at_utc': e['utc'],
                'reservation_registered': False,
                'termination_reason': 'relative_static_path_resolved_against_wrong_launcher_cwd'})
            assert ledger['limits'] == before['limits']
            assert ledger['deadline_utc'] == before['deadline_utc']
            assert ledger['charges'][:-1] == before['charges']
    if not pp.exists():
        a.new(pp, {'schema': 'ds02.stage2.pre-reservation-failure-reconciliation.v1',
            'request': a.ref(path), 'failure_evidence': a.ref(ep), 'charge': charge,
            'reservation_registered': False, 'reservations_empty': True,
            'runtime_receipt_reconstructed': False, 'scientific_credit': 0,
            'root_payload_content_read': False, 'goal_complete': False})
    return pp


def prepare(a, num, family, version, scope, registry, plan, failure):
    source = S / f'requests/generic-native-extract-v{version}-root-forward-{num}-003.json'
    if num == 309:
        source = S / f'requests/generic-native-extract-v{version}-root-forward-{num}-002.json'
    q = a.load(source)
    assert set(q['physical_case_ids']) <= set(a.load(scope)['remaining_cause_not_located_case_ids'])
    q['attempt_id'] = f'root{num}-native-absolute-path-v10-fresh-004'
    q['fresh_native_admission_scope'] = a.ref(scope)
    q['fresh_lifecycle_terminal_registry'] = a.ref(registry)
    q['fresh_lifecycle_terminal_plan'] = a.ref(plan)
    q['root_failed_attempt_lineage'] = a.ref(failure)
    q['root_runner_version'] = 'V10_GIT_INPUT_SCOPE_ONLY'
    mapping = {p: str((LAB / p).resolve()) for p in q['input_files'] if not Path(p).is_absolute()}
    def rebound(value):
        if isinstance(value, str): return mapping.get(value, value)
        if isinstance(value, list): return [rebound(v) for v in value]
        if isinstance(value, dict): return {mapping.get(k, k): rebound(v) for k, v in value.items()}
        return value
    q = rebound(q)
    closure = [LAB / 'scripts' / name for name in [
        'ds_data02_runtime_v10_git_bound.py', 'ds_data02_runtime_v9_git_bound.py',
        'ds_data02_runtime_v8.py', 'ds_data02_runtime_v6.py', 'ds_data02_runtime_v2.py',
        'ds_data02_git_launch_state_v1.py', 'ds_data02_git_launch_state_v2.py',
        'ds_data02_git_launch_state_v3.py']]
    extras = [source, scope, registry, plan, failure, *HERE.glob('*.py'), *closure]
    q['input_files'] = list(dict.fromkeys(q['input_files'] + list(map(str, extras))))
    old = q['input_sha256']
    hashes = {p: a.sha(p) for p in q['input_files']}
    for p, h in old.items(): assert hashes[p] == h, p
    q['input_sha256'] = q['input_hashes'] = hashes
    q['root_path_recovery'] = {'source_request': a.ref(source),
        'absolute_static_path_map': mapping, 'scientific_worker_changed': False,
        'root_payload_content_read': False}
    _validate_with_closure(q)
    out = S / f'requests/generic-native-extract-v{version}-root-forward-{num}-004.json'
    a.new(out, q)
    return out


def launch(a, qp, name, num):
    q = a.load(qp)
    ledger = a.load(D / 'runtime/resource-ledger.json')
    assert not ledger['reservations']
    now = datetime.datetime.now(datetime.timezone.utc)
    assert now + datetime.timedelta(seconds=q['max_wall_seconds'] + 45) < datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert sum(c.get('cpu_core_seconds', 0) for c in ledger['charges']) + q['cpu_threads'] * q['max_wall_seconds'] < ledger['limits']['cpu_core_seconds']
    disk = os.statvfs('/home/jade')
    assert disk.f_bavail * disk.f_frsize - q['estimated_storage_bytes'] >= ledger['limits']['home_min_free_bytes']
    for p, h in q['input_sha256'].items(): assert a.sha(p) == h
    unit = f'ds02-{name}-root-{num}'
    if a.state(unit)['SubState'] == 'failed':
        subprocess.run(['systemctl', '--user', 'reset-failed', unit], check=True)
    assert not (D / 'families' / q['family_id'] / q['case_id'] / q['attempt_id']).exists()
    code = ('import sys,os,json;sys.path.insert(0,' + repr(str(LAB / 'scripts')) + ');'
        'from ds_data02_runtime_v10_git_bound import run_request;r=run_request(' + repr(str(qp)) +
        ',data_root=' + repr(str(D)) + ',parent_pid=os.getppid());print(json.dumps(r));'
        'raise SystemExit(0 if r["status"]=="completed" else 1)')
    cmd = ['systemd-run', '--user', '--unit=' + unit, '--working-directory=' + str(LAB),
        '--property=Type=exec', '--property=RemainAfterExit=yes',
        '--property=RuntimeMaxSec=' + str(q['max_wall_seconds'] + 30),
        '--property=TimeoutStopSec=45', '--property=KillMode=mixed',
        '--property=CPUAccounting=yes', '--property=MemoryAccounting=yes',
        '--property=MemoryMax=' + str(q['max_memory_bytes'])]
    cmd += ['--setenv=' + k + '=1' for k in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS']]
    subprocess.run(cmd + [PYTHON, '-B', '-I', '-c', code], check=True)
    while True:
        st = a.state(unit)
        if st['SubState'] != 'running': break
        print(json.dumps({'event': 'RUNNING_NATIVE_V10_ABSOLUTE_PARENT', 'namespace': num,
                          'unit': unit, 'CPU_core_seconds': int(st['CPUUsageNSec']) / 1e9}), flush=True)
        time.sleep(30)
    assert st['SubState'] == 'exited' and st['MainPID'] == '0' and st['Result'] == 'success', st
    return unit


def main():
    a = admission()
    original, registry, plan = a.await_serial_terminal()
    failure = reconcile_failure(a)
    assert reconcile_failure(a) == failure
    scope = S / 'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT274_ACTUAL_SERIAL_OVERLAY_V1.json'
    cp = a.load(S / 'checkpoints/ROOT274_AFTER_SERIAL_ACTUAL_NATIVE_FULL_GOAL_CONTINUATION_V1.json')
    assert cp['actual_native_scope'] == a.ref(scope) and cp['native_cause_cases'] == 101
    assert a.sha(cp['latest_actual_proof']['path']) == cp['latest_actual_proof']['sha256']
    for num, family, version in [(308, 'F4', 2), (309, 'F6', 1)]:
        qp = prepare(a, num, family, version, scope, registry, plan, failure)
        unit = launch(a, qp, f'generic-native-extract-v{version}-{family.lower()}', num)
        subprocess.run([PYTHON, '-B', str(a.HERE / 'verify_actual_native_v1.py'),
            str(num), family, str(version), str(qp), str(scope), a.sha(scope)], cwd=LAB, check=True)
        assert a.state(unit)['SubState'] == 'dead'
        scope = a.overlay(num, family, version, scope)
        a.checkpoint(num, original, scope, S / f'checkpoints/GENERIC_NATIVE_EXTRACT_{family}_V{version}_ACTUAL_ROOT_VERIFICATION_{num}.json')
    qp = S / 'requests/native-selected-source-snapshot-root-forward-310-001.json'
    unit = a.launch_and_wait(qp, 'native-selected-source-snapshot', 310)
    subprocess.run([PYTHON, '-B', str(a.HERE / 'verify_snapshot310_v1.py')], cwd=LAB, check=True)
    assert a.state(unit)['SubState'] == 'dead'
    a.checkpoint(310, original, scope, S / 'checkpoints/F1_S2_TEN_SELECTED_SOURCE_SNAPSHOT_ACTUAL_ROOT_VERIFICATION_310.json')


if __name__ == '__main__':
    with (D / 'runtime/root-owned-native308-path-recovery-v1.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main()
