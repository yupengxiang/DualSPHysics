"""Retry ROOT274, preserving oomd evidence, then continue the frozen queue."""
from pathlib import Path
import fcntl
import importlib.util
import json
import os
import subprocess

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
LAB = S.parents[2]
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
ADMISSION = S / 'governance/root-owned-native-admission-v1'


def main():
    spec = importlib.util.spec_from_file_location('root274_frozen_admission', ADMISSION / 'continue_after_serial_v1.py')
    a = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(a)
    original_cp, registry, plan = a.await_serial_terminal()
    failure = S / 'checkpoints/ROOT274_ORPHAN_FAILED_PARENT_RECONCILIATION_V1.json'
    evidence = S / 'accounting/ROOT274_ORPHAN_SYSTEMD_FAILURE_EVIDENCE_V1.json'
    f = a.load(failure)
    assert f['reservation_released'] and f['scientific_or_saved_mask_credit'] == 0
    assert f['runtime_receipt_reconstructed'] is False
    assert a.state('ds02-generic-native-extract-v1-f6-root-274')['SubState'] == 'dead'
    assert not a.load(a.D / 'runtime/resource-ledger.json')['reservations']
    source = S / 'requests/generic-native-extract-v1-root-forward-274-003.json'
    q = a.load(source)
    q.update(case_id='ROOT274_F6_GENERIC_NATIVE_EXTRACT_V1_OOMD_RECOVERY',
             attempt_id='root274-f6-native-after-oomd-new-attempt-004',
             max_memory_bytes=8589934592, estimated_peak_memory_bytes=8589934592,
             root_failed_attempt_lineage=a.ref(failure),
             root_failure_systemd_evidence=a.ref(evidence),
             root_memory_recovery_reason='New 8GiB envelope after actual oomd SIGKILL of 4GiB unit; unchanged scientific extractor, no oomd policy override')
    memory = {k: int(v.split()[0]) * 1024 for k, v in (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines()) if v.split() and v.split()[0].isdigit()}
    assert memory['MemAvailable'] > 4 * q['max_memory_bytes']
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__file__': str(forward), '__name__': 'root274_recovery_forward'}
    exec(forward.read_text(), context)
    context['sha'] = a.sha
    actual = S / 'requests/generic-native-extract-v1-root-forward-274-004.json'
    context['write'](q, source, actual.name, extra=[failure, evidence, *HERE.glob('*.py')])
    scope = S / 'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json'
    unit = a.launch_and_wait(actual, 'generic-native-extract-v1-f6', 274)
    subprocess.run([PYTHON, '-B', str(HERE / 'verify_actual_v2.py'), '274', 'F6', '1', str(actual), str(scope), a.sha(scope)], cwd=LAB, check=True)
    assert a.state(unit)['SubState'] == 'dead'
    scope = a.overlay(274, 'F6', 1, scope)
    a.checkpoint(274, original_cp, scope, S / 'checkpoints/GENERIC_NATIVE_EXTRACT_F6_V1_ACTUAL_ROOT_VERIFICATION_274.json')
    for num, family, version in [(308, 'F4', 2), (309, 'F6', 1)]:
        source = S / f'requests/generic-native-extract-v{version}-root-forward-{num}-002.json'
        actual = a.prepare_native(num, family, version, source, scope, registry, plan)
        unit = a.launch_and_wait(actual, f'generic-native-extract-v{version}-{family.lower()}', num)
        subprocess.run([PYTHON, '-B', str(ADMISSION / 'verify_actual_native_v1.py'), str(num), family, str(version), str(actual), str(scope), a.sha(scope)], cwd=LAB, check=True)
        assert a.state(unit)['SubState'] == 'dead'
        scope = a.overlay(num, family, version, scope)
        a.checkpoint(num, original_cp, scope, S / f'checkpoints/GENERIC_NATIVE_EXTRACT_{family}_V{version}_ACTUAL_ROOT_VERIFICATION_{num}.json')
    actual = S / 'requests/native-selected-source-snapshot-root-forward-310-001.json'
    unit = a.launch_and_wait(actual, 'native-selected-source-snapshot', 310)
    subprocess.run([PYTHON, '-B', str(ADMISSION / 'verify_snapshot310_v1.py')], cwd=LAB, check=True)
    assert a.state(unit)['SubState'] == 'dead'
    a.checkpoint(310, original_cp, scope, S / 'checkpoints/F1_S2_TEN_SELECTED_SOURCE_SNAPSHOT_ACTUAL_ROOT_VERIFICATION_310.json')
    print(json.dumps({'event': 'ROOT274_RECOVERY_NATIVE_QUEUE_TERMINAL', 'goal_complete': False}), flush=True)


if __name__ == '__main__':
    data = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
    with (data / 'runtime/root-owned-native274-oomd-recovery-v1.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main()
