"""Wait for the actual portable handoff, then admit one F6 support parent."""
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
    names = {'continue_after_mass_v1.py','continue_after_mass_v2.py'}
    for item in Path('/proc').iterdir():
        if not item.name.isdigit() or int(item.name) == os.getpid():continue
        try:tokens = (item / 'cmdline').read_bytes().split(b'\0')
        except OSError:continue
        if any(Path(x.decode(errors='replace')).name in names for x in tokens):return True
    return False


def main():
    code = S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py'
    spec = importlib.util.spec_from_file_location('root_reference_admission_v1',code)
    admission = importlib.util.module_from_spec(spec);spec.loader.exec_module(admission)
    barrier = S / 'checkpoints/ROOT242_AFTER_MASS313_GEOMETRY316_PORTABLE_V11_FULL_GOAL_CONTINUATION_V2.json'
    while not barrier.exists() or preceding_alive():
        print(json.dumps({'event':'WAITING_ACTUAL_PORTABLE242_HANDOFF_FOR_F6_SUPPORT276',
                          'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'support_launch_performed':False}),flush=True)
        time.sleep(30)
    prior = admission.load(barrier)
    assert prior['goal_complete'] is False and prior['scientific_Q_credit'] == 0
    for k in ['actual_lifecycle_terminal','actual_native_scope','actual_geometry_support_proof','actual_portable_runtime_proof']:
        assert admission.sha(prior[k]['path']) == prior[k]['sha256']
    portable = admission.load(prior['actual_portable_runtime_proof']['path'])
    assert portable['parent_reservation_released'] and portable['repeat_fee_idempotent']
    assert not admission.load(D / 'runtime/resource-ledger.json')['reservations']
    lifecycle = admission.load(prior['actual_lifecycle_terminal']['path'])
    assert lifecycle['coverage']['actual_saved_mask_cases'] == 335
    for k in ['current_registry','strict_current_plan','terminal_proof']:
        assert admission.sha(lifecycle[k]['path']) == lifecycle[k]['sha256']
    source = S / 'requests/reference-audit-root-forward-276-001.json'
    q = admission.load(source)
    q['fresh_lifecycle_terminal_registry'] = lifecycle['current_registry']
    q['fresh_lifecycle_terminal_plan'] = lifecycle['strict_current_plan']
    q['preceding_actual_portable_handoff'] = admission.ref(barrier)
    verifier = S / 'reference/stage2_f6_initial_native_support_verify_v4.py'
    manifest = Path(q['manifest_contract']['path'])
    subprocess.run([PYTHON,'-B',str(verifier),'--verify','--manifest',str(manifest)],cwd=LAB,check=True)
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__file__':str(forward),'__name__':'root276_postportable_forward'}
    exec(forward.read_text(),context); context['sha'] = admission.sha
    extra = [Path(__file__), HERE / 'verify_support276_v1.py',code,barrier,
             Path(lifecycle['current_registry']['path']),Path(lifecycle['strict_current_plan']['path']),
             S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
             S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
             LAB / 'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py']
    extra += [S / 'reference' / f'stage2_f6_initial_native_support_verify_v{n}.py' for n in range(1,5)]
    name = 'reference-audit-root-forward-276-002.json'
    context['write'](q,source,name,extra=extra)
    request = S / 'requests' / name
    unit = admission.launch_and_wait(request,'f6-initial-native-support-v8',276)
    subprocess.run([PYTHON,'-B',str(HERE / 'verify_support276_v1.py'),str(request)],cwd=LAB,check=True)
    assert admission.state(unit)['SubState'] == 'dead'
    proof = S / 'checkpoints/INITIAL_SUPPORT_V8_ACTUAL_ROOT_VERIFICATION_276.json'
    value = admission.load(proof); assert value['parent_reservation_released'] and value['repeat_fee_idempotent']
    checkpoint = S / 'checkpoints/ROOT276_AFTER_PORTABLE_ACTUAL_INITIAL_SUPPORT_FULL_GOAL_CONTINUATION_V1.json'
    admission.new(checkpoint,{'schema':'ds02.stage2.root-reference-after-portable-continuation.v1',
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'goal_status':'ACTIVE_FULL_SEVEN_ITEMS','goal_complete':False,
        'preceding_actual_portable_handoff':admission.ref(barrier),'actual_lifecycle_terminal':prior['actual_lifecycle_terminal'],
        'actual_native_scope':prior['actual_native_scope'],'actual_support_proof':admission.ref(proof),
        'verified_case_counts':value['verified_case_counts'],'scientific_Q_credit':0,
        'root_payload_content_read':False,'next':'Continue ROOT314/279 references, ROOT312/F2 native joins, exact/null mass impact, labels/splits and 14 scientific reference terminal studies'})
    p = S / 'NEXT_READY_TASKS.md'
    p.write_text('最新实际F6初态支持复核点：`' + str(checkpoint) + '`（SHA256 ' + admission.sha(checkpoint) + '）。按实际报告保留PASS/UNKNOWN/FAILED，不授予动力学或科学Q资格；完整七项目标ACTIVE。\n\n' + p.read_text())
    print(json.dumps({'event':'ACTUAL_F6_SUPPORT276_HANDOFF_TERMINAL','checkpoint':str(checkpoint),'goal_complete':False}),flush=True)


if __name__ == '__main__':
    with (D / 'runtime/root-owned-support-after-portable-v1.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('another F6 support continuation owns this handoff')
        main()
