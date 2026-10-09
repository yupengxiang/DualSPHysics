"""Admit the remaining thirty mass diagnostics after the actual frame-zero handoff."""
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
        if any(Path(x.decode(errors='replace')).name == 'continue_frame0_after_support_v1.py' for x in tokens):
            return True
    return False


def main():
    code = HERE / 'continue_after_serial_v1.py'
    spec = importlib.util.spec_from_file_location('root_mass30_admission_v1', code)
    admission = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(admission)
    barrier = S / 'checkpoints/ROOT314_AFTER_F6_SUPPORT_ACTUAL_FRAME0_FULL_GOAL_CONTINUATION_V1.json'
    while not barrier.exists() or preceding_alive():
        print(json.dumps({'event': 'WAITING_ACTUAL_FRAME0314_HANDOFF_FOR_MASS30', 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mass30_launch_performed': False}), flush=True)
        time.sleep(30)
    prior = admission.load(barrier)
    assert prior['goal_complete'] is False and prior['scientific_Q_credit'] == 0
    for k in ['actual_lifecycle_terminal', 'actual_native_scope', 'actual_frame0_proof']:
        assert admission.sha(prior[k]['path']) == prior[k]['sha256']
    value = admission.load(prior['actual_frame0_proof']['path'])
    assert value['parent_reservation_released'] and value['repeat_fee_idempotent']
    assert not admission.load(D / 'runtime/resource-ledger.json')['reservations']
    lifecycle = admission.load(prior['actual_lifecycle_terminal']['path'])
    assert lifecycle['coverage']['actual_saved_mask_cases'] == 335
    for k in ['current_registry', 'strict_current_plan', 'terminal_proof']:
        assert admission.sha(lifecycle[k]['path']) == lifecycle[k]['sha256']
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__file__': str(forward), '__name__': 'root_mass30_after_frame0_forward'}
    exec(forward.read_text(), context)
    context['sha'] = admission.sha
    previous = barrier
    cumulative = []
    for num, count in [(322, 1), (323, 8), (324, 8), (325, 8), (326, 5)]:
        assert not admission.load(D / 'runtime/resource-ledger.json')['reservations']
        source = S / f'requests/native-typed-mass-impact-v6-root-forward-{num}-002.json'
        q = admission.load(source)
        q['fresh_lifecycle_terminal_registry'] = lifecycle['current_registry']
        q['fresh_lifecycle_terminal_plan'] = lifecycle['strict_current_plan']
        q['preceding_actual_serial_handoff'] = admission.ref(previous)
        q['root_admission_state'] = 'AFTER_VERIFIED_PRECEDING_TERMINAL_ONE_PARENT_ONLY'
        extra = [Path(__file__), previous, Path(lifecycle['current_registry']['path']), Path(lifecycle['strict_current_plan']['path']),
                 HERE / 'verify_actual_mass30_v1.py', code,
                 S / 'checkpoints/ROOT322_326_MASS_V6_NORMALIZED_RUNTIME_READINESS_V1.json']
        name = f'native-typed-mass-impact-v6-root-forward-{num}-003.json'
        context['write'](q, source, name, extra=extra)
        request = S / 'requests' / name
        unit = admission.launch_and_wait(request, 'native-typed-mass-impact-v6', num)
        subprocess.run([PYTHON, '-B', str(HERE / 'verify_actual_mass30_v1.py'), str(request), str(num)], cwd=LAB, check=True)
        assert admission.state(unit)['SubState'] == 'dead'
        proof = S / f'checkpoints/NATIVE_TYPED_MASS_IMPACT_ACTUAL_ROOT_VERIFICATION_{num}.json'
        value = admission.load(proof)
        assert value['parent_reservation_released'] and value['repeat_fee_idempotent']
        assert value['verified_counts']['cases'] == count
        cumulative.append({'namespace': num, 'actual_proof': admission.ref(proof), 'verified_counts': value['verified_counts']})
        checkpoint = S / f'checkpoints/ROOT{num}_MASS30_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V1.json'
        admission.new(checkpoint, {'schema': 'ds02.stage2.root-mass30-serial-continuation.v1',
            'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'goal_status': 'ACTIVE_FULL_SEVEN_ITEMS', 'goal_complete': False,
            'preceding_actual_serial_handoff': admission.ref(previous), 'actual_lifecycle_terminal': prior['actual_lifecycle_terminal'],
            'actual_native_scope': prior['actual_native_scope'], 'actual_frame0_proof': prior['actual_frame0_proof'],
            'actual_mass_proofs': list(cumulative), 'actual_mass_terminal_cases': sum(x['verified_counts']['cases'] for x in cumulative),
            'scientific_Q_credit': 0, 'new_native_cause_or_join_credit': 0, 'root_payload_content_read': False,
            'next': 'Continue actual missing native joins, F1 common endpoint, 14 scientific references, labels/splits/products'})
        p = S / 'NEXT_READY_TASKS.md'
        p.write_text('最新实际质量影响串行交接：`' + str(checkpoint) + '`（SHA256 ' + admission.sha(checkpoint) + '）。按实际报告保留exact/null与失败；完整七项目标ACTIVE，科学Q仍UNKNOWN。\n\n' + p.read_text())
        print(json.dumps({'event': 'ACTUAL_MASS30_SERIAL_HANDOFF', 'namespace': num, 'checkpoint': str(checkpoint), 'cases': sum(x['verified_counts']['cases'] for x in cumulative), 'goal_complete': False}), flush=True)
        previous = checkpoint


if __name__ == '__main__':
    with (D / 'runtime/root-owned-mass30-after-frame0-v1.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another thirty-case mass continuation owns this handoff')
        main()
