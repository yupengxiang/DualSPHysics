"""Wait for actual F6 support, then admit one four-sentinel frame-zero parent."""
from pathlib import Path
import datetime
import fcntl
import importlib.util
import json
import os
import subprocess
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'


def preceding_alive():
    for item in Path('/proc').iterdir():
        if not item.name.isdigit() or int(item.name) == os.getpid():
            continue
        try:
            tokens = (item / 'cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        if any(Path(x.decode(errors='replace')).name == 'continue_after_portable_v1.py' for x in tokens):
            return True
    return False


def main():
    code = S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py'
    spec = importlib.util.spec_from_file_location('root_frame0_admission_v1', code)
    admission = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(admission)
    barrier = S / 'checkpoints/ROOT276_AFTER_PORTABLE_ACTUAL_INITIAL_SUPPORT_FULL_GOAL_CONTINUATION_V1.json'
    while not barrier.exists() or preceding_alive():
        print(json.dumps({'event': 'WAITING_ACTUAL_SUPPORT276_HANDOFF_FOR_FRAME0314', 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'frame0_launch_performed': False}), flush=True)
        time.sleep(30)
    prior = admission.load(barrier)
    assert prior['goal_complete'] is False and prior['scientific_Q_credit'] == 0
    for k in ['actual_lifecycle_terminal', 'actual_native_scope', 'actual_support_proof']:
        assert admission.sha(prior[k]['path']) == prior[k]['sha256']
    value = admission.load(prior['actual_support_proof']['path'])
    assert value['parent_reservation_released'] and value['repeat_fee_idempotent']
    assert not admission.load(D / 'runtime/resource-ledger.json')['reservations']
    lifecycle = admission.load(prior['actual_lifecycle_terminal']['path'])
    assert lifecycle['coverage']['actual_saved_mask_cases'] == 335
    for k in ['current_registry', 'strict_current_plan', 'terminal_proof']:
        assert admission.sha(lifecycle[k]['path']) == lifecycle[k]['sha256']
    source = S / 'requests/four-sentinel-frame0-audit-root-forward-314-001.json'
    q = admission.load(source)
    old = str(S / 'reference/stage2_four_sentinel_frame0_support_audit_v2.py')
    new = str(S / 'reference/stage2_four_sentinel_frame0_support_audit_v4.py')
    assert q['command'].count(old) == 1
    q['command'] = [new if x == old else x for x in q['command']]
    q['completed_diagnostic_with_failed_cases'] = 'PRESERVE_FAILED_UNKNOWN_ROWS_NO_SCIENTIFIC_Q'
    q['fresh_lifecycle_terminal_registry'] = lifecycle['current_registry']
    q['fresh_lifecycle_terminal_plan'] = lifecycle['strict_current_plan']
    q['preceding_actual_support_handoff'] = admission.ref(barrier)
    verifier = S / 'reference/stage2_four_sentinel_frame0_support_verify_v5.py'
    subprocess.run([PYTHON, '-B', str(verifier), '--verify-manifest', '--manifest', q['manifest_contract']['path']], cwd=LAB, check=True)
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__file__': str(forward), '__name__': 'root314_after_support_forward'}
    exec(forward.read_text(), context)
    context['sha'] = admission.sha
    extra = [Path(__file__), HERE / 'verify_frame0314_v1.py', code, Path(new), barrier,
             S / 'checkpoints/ROOT314_V4_THIN_ENTRY_SOURCE_READINESS_ROOT_V1.json',
             Path(lifecycle['current_registry']['path']), Path(lifecycle['strict_current_plan']['path']),
             S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
             S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
             LAB / 'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py']
    extra += [S / 'reference' / f'stage2_four_sentinel_frame0_support_verify_v{n}.py' for n in range(1, 6)]
    name = 'four-sentinel-frame0-audit-root-forward-314-002.json'
    context['write'](q, source, name, extra=extra)
    request = S / 'requests' / name
    unit = admission.launch_and_wait(request, 'four-sentinel-frame0-support', 314)
    subprocess.run([PYTHON, '-B', str(HERE / 'verify_frame0314_v1.py'), str(request)], cwd=LAB, check=True)
    assert admission.state(unit)['SubState'] == 'dead'
    proof = S / 'checkpoints/FRAME0_SUPPORT_ACTUAL_ROOT_VERIFICATION_314.json'
    value = admission.load(proof)
    assert value['parent_reservation_released'] and value['repeat_fee_idempotent']
    checkpoint = S / 'checkpoints/ROOT314_AFTER_F6_SUPPORT_ACTUAL_FRAME0_FULL_GOAL_CONTINUATION_V1.json'
    admission.new(checkpoint, {'schema': 'ds02.stage2.root-frame0-after-support-continuation.v1',
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'goal_status': 'ACTIVE_FULL_SEVEN_ITEMS', 'goal_complete': False,
        'preceding_actual_support_handoff': admission.ref(barrier), 'actual_lifecycle_terminal': prior['actual_lifecycle_terminal'],
        'actual_native_scope': prior['actual_native_scope'], 'actual_frame0_proof': admission.ref(proof),
        'verified_case_counts': value['verified_case_counts'], 'scientific_Q_credit': 0,
        'root_payload_content_read': False, 'next': 'Continue source-bound mass impact, native joins, F1 common endpoint, actual 14 reference studies, labels/splits/products'})
    p = S / 'NEXT_READY_TASKS.md'
    p.write_text('最新实际四哨点首帧诊断：`' + str(checkpoint) + '`（SHA256 ' + admission.sha(checkpoint) + '）。保留PASS/UNKNOWN/FAILED和缺失身份，不授予科学Q资格；完整七项目标ACTIVE。\n\n' + p.read_text())
    print(json.dumps({'event': 'ACTUAL_FRAME0314_HANDOFF_TERMINAL', 'checkpoint': str(checkpoint), 'goal_complete': False}), flush=True)


if __name__ == '__main__':
    with (D / 'runtime/root-owned-frame0-after-support-v1.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another frame-zero continuation owns this handoff')
        main()
