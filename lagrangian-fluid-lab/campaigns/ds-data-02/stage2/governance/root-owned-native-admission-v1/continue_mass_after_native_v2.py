#!/usr/bin/env python3
"""Wait for the actual serial/native handoff before admitting one mass audit with the complete root verifier closure."""
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


def load_admission():
    path = HERE / 'continue_after_serial_v1.py'
    spec = importlib.util.spec_from_file_location('root_native_admission_mass313_source_v1', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preceding_continuation_alive():
    names = {'continue_serial.py', 'resume_serial_v3.py', 'continue_after_serial_v1.py'}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            tokens = (entry / 'cmdline').read_bytes().split(b'\0')
        except (OSError, PermissionError):
            continue
        if any(Path(token.decode(errors='replace')).name in names for token in tokens):
            return True
    return False


def main():
    admission = load_admission()
    barrier = S / 'checkpoints/ROOT310_AFTER_SERIAL_ACTUAL_NATIVE_FULL_GOAL_CONTINUATION_V1.json'
    while not barrier.exists() or preceding_continuation_alive():
        print(json.dumps({'event': 'WAITING_ACTUAL_ROOT310_NATIVE_HANDOFF_FOR_MASS313_V2', 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mass_launch_performed': False}), flush=True)
        time.sleep(30)
    handoff = admission.load(barrier)
    assert handoff['actual_saved_mask_cases'] == 335 and handoff['historical_alias_unresolved'] == 1
    assert handoff['goal_complete'] is False
    for key in ['actual_lifecycle_terminal', 'actual_native_scope', 'latest_actual_proof']:
        assert admission.sha(handoff[key]['path']) == handoff[key]['sha256']
    snapshot_proof = admission.load(handoff['latest_actual_proof']['path'])
    assert snapshot_proof['parent_reservation_released'] and snapshot_proof['repeat_fee_idempotent']
    serial = admission.load(handoff['actual_lifecycle_terminal']['path'])
    for key in ['current_registry', 'strict_current_plan', 'terminal_proof']:
        assert admission.sha(serial[key]['path']) == serial[key]['sha256']
    assert not admission.load(D / 'runtime/resource-ledger.json')['reservations']
    source = S / 'requests/native-typed-mass-impact-root-forward-313-005.json'
    q = admission.load(source)
    q['fresh_lifecycle_terminal_registry'] = serial['current_registry']
    q['fresh_lifecycle_terminal_plan'] = serial['strict_current_plan']
    q['fresh_native_admission_scope'] = handoff['actual_native_scope']
    q['preceding_actual_native_handoff'] = admission.ref(barrier)
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_mass313_fresh_forward', '__file__': str(forward)}
    exec(forward.read_text(), context)
    context['sha'] = admission.sha
    name = 'native-typed-mass-impact-root-forward-313-006.json'
    verifier = LAB / 'scripts/ds_data02_stage2_verify_native_typed_mass_impact_v5.py'
    context['write'](q, source, name, extra=[Path(__file__), HERE / 'continue_after_serial_v1.py', HERE / 'verify_actual_mass313_v1.py', verifier, barrier,
                     Path(serial['current_registry']['path']), Path(serial['strict_current_plan']['path']), Path(handoff['actual_native_scope']['path']),
                     S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
                     S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
                     LAB / 'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py'])
    request = S / 'requests' / name
    unit = admission.launch_and_wait(request, 'native-typed-mass-impact', 313)
    subprocess.run([PYTHON, '-B', str(HERE / 'verify_actual_mass313_v1.py'), str(request)], cwd=LAB, check=True)
    assert admission.state(unit)['SubState'] == 'dead'
    proof = S / 'checkpoints/NATIVE_TYPED_MASS_IMPACT_ACTUAL_ROOT_VERIFICATION_313.json'
    value = admission.load(proof)
    assert value['parent_reservation_released'] and value['repeat_fee_idempotent']
    cp = S / 'checkpoints/ROOT313_AFTER_NATIVE_ACTUAL_MASS_FULL_GOAL_CONTINUATION_V2.json'
    admission.new(cp, {'schema': 'ds02.stage2.root-mass-after-native-actual-continuation.v2',
                  'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'goal_status': 'ACTIVE_FULL_SEVEN_ITEMS', 'goal_complete': False,
                  'actual_lifecycle_terminal': handoff['actual_lifecycle_terminal'], 'preceding_actual_native_handoff': admission.ref(barrier),
                  'actual_native_scope': handoff['actual_native_scope'], 'actual_mass_proof': admission.ref(proof), 'verified_counts': value['verified_counts'],
                  'new_native_cause_credit': 0, 'new_native_join_credit': 0, 'physical_fate_flux_dynamics_Q': 'UNKNOWN',
                  'root_payload_content_read': False, 'next': 'continue remaining joins, reference studies, labels, splits, portable products and all seven goal items'})
    next_path = S / 'NEXT_READY_TASKS.md'
    next_path.write_text('最新实际质量影响复核点：`' + str(cp) + '`（SHA256 ' + admission.sha(cp) + '）。完整七项目标 ACTIVE；按实际报告保留成功与失败案例，物理去向、通量、动力学及Q仍UNKNOWN。\n\n' + next_path.read_text())
    print(json.dumps({'event': 'ACTUAL_MASS313_CONTINUATION_TERMINAL', 'checkpoint': str(cp), 'sha256': admission.sha(cp), 'goal_complete': False}), flush=True)


if __name__ == '__main__':
    with (D / 'runtime/root-owned-mass-after-native-v1.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another mass continuation owns this handoff')
        main()
