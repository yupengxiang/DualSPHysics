"""Wait-only handoff, then serial geometry and portable diagnostic parents."""
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


def predecessor_alive():
    names = {'continue_serial.py','resume_serial_v3.py','continue_after_serial_v1.py',
             'continue_mass_after_native_v1.py','continue_mass_after_native_v2.py'}
    for item in Path('/proc').iterdir():
        if not item.name.isdigit() or int(item.name) == os.getpid():
            continue
        try:
            tokens = (item / 'cmdline').read_bytes().split(b'\0')
        except (OSError, PermissionError):
            continue
        if any(Path(x.decode(errors='replace')).name in names for x in tokens):
            return True
    return False


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def assert_primary_venv_gate(admission):
    gate_path = S / 'checkpoints/ROOT242_V11_ACTUAL_LITERAL_PROJECT_VENV_MANUFACTURED_INTERFACE_VERIFICATION_V1.json'
    evidence = admission.load(gate_path)
    assert evidence['status'] == 'PASS_ACTUAL_LITERAL_PRIMARY_VENV_V11_HOOK_REAL_V8_V12_TYPED_SCORER_MANUFACTURED_FIXTURE'
    assert evidence['root_production_payload_content_read'] is False and evidence['goal_complete'] is False
    for key in ['test','literal_interpreter','pyvenv_cfg']:
        assert admission.sha(evidence[key]['path']) == evidence[key]['sha256']
    for edge in evidence['runtime_sources']:
        assert admission.sha(edge['path']) == edge['sha256']
    return admission.ref(gate_path)


def main():
    admission = load_module(S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py','root_postmass_admission_v1')
    primary_gate = assert_primary_venv_gate(admission)
    barrier = S / 'checkpoints/ROOT313_AFTER_NATIVE_ACTUAL_MASS_FULL_GOAL_CONTINUATION_V2.json'
    while not barrier.exists() or predecessor_alive():
        print(json.dumps({'event':'WAITING_ACTUAL_MASS313_HANDOFF_FOR_GEOMETRY_AND_PORTABLE',
                          'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          'geometry_launch_performed':False,'portable_launch_performed':False}),flush=True)
        time.sleep(30)
    prior = admission.load(barrier)
    assert prior['goal_complete'] is False and prior['goal_status'] == 'ACTIVE_FULL_SEVEN_ITEMS'
    for k in ['actual_lifecycle_terminal','actual_native_scope','actual_mass_proof']:
        assert admission.sha(prior[k]['path']) == prior[k]['sha256']
    mass = admission.load(prior['actual_mass_proof']['path'])
    assert mass['parent_reservation_released'] and mass['repeat_fee_idempotent']
    serial = admission.load(prior['actual_lifecycle_terminal']['path'])
    assert serial['coverage']['actual_saved_mask_cases'] == 335
    assert serial['coverage']['historical_alias_unresolved'] == 1
    for k in ['current_registry','strict_current_plan','terminal_proof']:
        assert admission.sha(serial[k]['path']) == serial[k]['sha256']
    assert not admission.load(D / 'runtime/resource-ledger.json')['reservations']
    source = S / 'requests/four-sentinel-geometry-audit-root-forward-316-001.json'
    q = admission.load(source)
    q['fresh_lifecycle_terminal_registry'] = serial['current_registry']
    q['fresh_lifecycle_terminal_plan'] = serial['strict_current_plan']
    q['preceding_actual_mass_handoff'] = admission.ref(barrier)
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__':'root_geometry316_postmass_forward','__file__':str(forward)}
    exec(forward.read_text(),context); context['sha'] = admission.sha
    verifier = S / 'reference/stage2_four_sentinel_gencase_geometry_support_verify_v2.py'
    extra = [Path(__file__), HERE / 'verify_geometry316_v1.py',verifier,
             S / 'reference/stage2_four_sentinel_gencase_geometry_support_verify_v1.py',
             S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
             S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
             LAB / 'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py',barrier,
             Path(serial['current_registry']['path']),Path(serial['strict_current_plan']['path']),
             Path(primary_gate['path'])]
    name = 'four-sentinel-geometry-audit-root-forward-316-002.json'
    context['write'](q,source,name,extra=extra)
    request = S / 'requests' / name
    manifest = Path(q['manifest_contract']['path'])
    subprocess.run([PYTHON,'-B',str(verifier),'--verify-request','--manifest',str(manifest),
                    '--request',str(request)],cwd=LAB,check=True)
    unit = admission.launch_and_wait(request,'four-sentinel-geometry-support',316)
    subprocess.run([PYTHON,'-B',str(HERE / 'verify_geometry316_v1.py'),str(request)],cwd=LAB,check=True)
    assert admission.state(unit)['SubState'] == 'dead'
    geometry = S / 'checkpoints/GEOMETRY_SUPPORT_ACTUAL_ROOT_VERIFICATION_316.json'
    gp = admission.load(geometry); assert gp['parent_reservation_released'] and gp['repeat_fee_idempotent']
    portable_request = S / 'requests/portable-typed-root242-v11-root-forward-242-001.json'
    portable = load_module(HERE / 'launch_v1.py','root_portable242_launcher_v1')
    assert_primary_venv_gate(admission)
    portable.launch(portable_request)
    subprocess.run([PYTHON,'-B',str(HERE / 'verify_actual_v1.py'),str(portable_request)],cwd=LAB,check=True)
    assert admission.state('ds02-portable-typed-v11-root-242')['SubState'] == 'dead'
    proof = S / 'checkpoints/PORTABLE_TYPED_V11_ACTUAL_ROOT_VERIFICATION_242.json'
    pp = admission.load(proof); assert pp['parent_reservation_released'] and pp['repeat_fee_idempotent']
    checkpoint = S / 'checkpoints/ROOT242_AFTER_MASS313_GEOMETRY316_PORTABLE_V11_FULL_GOAL_CONTINUATION_V2.json'
    admission.new(checkpoint, {'schema':'ds02.stage2.root-postmass-geometry-portable-continuation.v2',
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'goal_status':'ACTIVE_FULL_SEVEN_ITEMS','goal_complete':False,
        'preceding_actual_mass_handoff':admission.ref(barrier),
        'actual_lifecycle_terminal':prior['actual_lifecycle_terminal'],
        'actual_native_scope':prior['actual_native_scope'],
        'actual_geometry_support_proof':admission.ref(geometry),
        'actual_portable_runtime_proof':admission.ref(proof),
        'literal_primary_venv_manufactured_interface_gate':primary_gate,
        'new_native_cause_or_join_credit':0,'scientific_Q_credit':0,
        'portable_cold_replay_credit':'NOT_CLAIMED','root_payload_content_read':False,
        'next':'Continue ROOT276/314/279 reference prerequisites, ROOT312 and F2 joins, mass/labels/splits/14 scientific terminal studies and internal products'})
    next_path = S / 'NEXT_READY_TASKS.md'
    next_path.write_text('最新实际参考支持与可迁移接口复核点：`' + str(checkpoint) + '`（SHA256 ' + admission.sha(checkpoint) + '）。完整七项目标 ACTIVE；仅记录实际几何支持和运行时迁移接口，连续初态owner、物理资格与科学Q尚未闭合。\n\n' + next_path.read_text())
    print(json.dumps({'event':'ACTUAL_POSTMASS_GEOMETRY_PORTABLE_TERMINAL','checkpoint':str(checkpoint),'goal_complete':False}),flush=True)


if __name__ == '__main__':
    with (D / 'runtime/root-owned-postmass-geometry-portable-v1.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another geometry/portable continuation owns this handoff')
        main()
