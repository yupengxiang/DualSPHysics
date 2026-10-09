"""Wait for ROOT326, then close the seven remaining native join batches."""
from pathlib import Path
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
SOURCES = [
    (312, 'generic-native-extract-v4-root-forward-312-002.json', 7),
    (315, 'generic-native-extract-v2-root-forward-315-004.json', 8),
    *[(n, f'generic-native-extract-v3-root-forward-{n}-001.json', 6 if n == 321 else 8) for n in range(317, 322)],
]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def preceding_alive():
    for path in Path('/proc').iterdir():
        if not path.name.isdigit() or int(path.name) == os.getpid():
            continue
        try:
            tokens = (path / 'cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        if any(Path(t.decode(errors='replace')).name == 'continue_mass30_after_frame0_v1.py' for t in tokens):
            return True
    return False


def main():
    admission = module(S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py', 'root_missing_join_admission_v1')
    barrier = S / 'checkpoints/ROOT326_MASS30_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V1.json'
    while not barrier.exists() or preceding_alive():
        print(json.dumps({'event': 'WAITING_ACTUAL_MASS30_ROOT326_FOR_MISSING_NATIVE_JOINS',
                          'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          'native_join_launch_performed': False}), flush=True)
        time.sleep(30)
    prior = admission.load(barrier)
    assert prior['goal_complete'] is False and prior['scientific_Q_credit'] == 0
    assert prior['actual_mass_terminal_cases'] == 30
    for key in ['actual_lifecycle_terminal', 'actual_native_scope']:
        assert admission.sha(prior[key]['path']) == prior[key]['sha256']
    for item in prior['actual_mass_proofs']:
        assert admission.sha(item['actual_proof']['path']) == item['actual_proof']['sha256']
        proof = admission.load(item['actual_proof']['path'])
        assert proof['parent_reservation_released'] and proof['repeat_fee_idempotent']
    lifecycle = admission.load(prior['actual_lifecycle_terminal']['path'])
    assert lifecycle['coverage']['actual_saved_mask_cases'] == 335
    assert lifecycle['coverage']['historical_alias_unresolved'] == 1
    assert lifecycle['coverage']['failed_requires_new_attempt_cases'] == 0
    for key in ['current_registry', 'strict_current_plan', 'terminal_proof']:
        assert admission.sha(lifecycle[key]['path']) == lifecycle[key]['sha256']
    plan = Path(lifecycle['strict_current_plan']['path'])
    registry = Path(lifecycle['current_registry']['path'])
    scope = Path(prior['actual_native_scope']['path'])
    previous = barrier
    assert not admission.load(D / 'runtime/resource-ledger.json')['reservations']
    sys.path.insert(0, str(LAB / 'scripts'))
    import ds_data02_stage2_verify_generic_native_join_v6 as verifier
    import ds_data02_stage2_build_native_overlay_adapter_v5 as adapter
    import ds_data02_stage2_normalize_v6_verified_native_join_v2 as normalizer
    completed = {row['physical_case_id'] for row in admission.load(plan)['case_records'] if row['status'] == 'ACTUAL_SAVED_MASK_COMPLETED'}
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__file__': str(forward), '__name__': 'root_missing_native_join_forward_v1'}
    exec(forward.read_text(), context)
    context['sha'] = admission.sha
    for num, source_name, count in SOURCES:
        assert not admission.load(D / 'runtime/resource-ledger.json')['reservations']
        source = S / 'requests' / source_name
        q = admission.load(source)
        selected = set(q['physical_case_ids'])
        scoped, _ = verifier._load_scope_v5(scope, plan, S / 'CURRENT336.json')
        inventory = verifier._base_inventory(scope)
        assert len(selected) == count and selected <= completed
        assert not selected & (inventory['existing'] | scoped['aliases'])
        assert selected <= (inventory['bound'] | inventory['unresolved'])
        if num == 312:
            assert selected <= inventory['unresolved']
        else:
            assert selected <= inventory['bound']
        q['attempt_id'] = f'root{num}-native-v6-after-actual326-fresh-001'
        q['fresh_native_admission_scope'] = admission.ref(scope)
        q['fresh_lifecycle_terminal_registry'] = admission.ref(registry)
        q['fresh_lifecycle_terminal_plan'] = admission.ref(plan)
        q['preceding_actual_serial_handoff'] = admission.ref(previous)
        q['root_canonical_native_join_binding'] = {'namespace': num, 'selected_case_ids': sorted(selected),
                                                  'historical_alias_substitution': False, 'new_cause_allowed': num == 312,
                                                  'scientific_Q_credit': 0}
        extras = [Path(__file__), HERE / 'verify_actual_v6_join_v1.py', scope, plan, registry, previous,
                  Path(verifier.__file__), Path(adapter.__file__), Path(normalizer.__file__),
                  S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
                  S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
                  LAB / 'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py']
        extras += [LAB / 'scripts' / name for name in [
            'ds_data02_stage2_normalize_v6_verified_native_join_v1.py',
            *[f'ds_data02_stage2_verify_generic_native_join_v{n}.py' for n in range(1, 6)],
            *[f'ds_data02_stage2_build_native_overlay_adapter_v{n}.py' for n in range(1, 5)],
        ]]
        name = f'generic-native-join-v6-root-forward-{num}-after326-001.json'
        context['write'](q, source, name, extra=extras)
        request = S / 'requests' / name
        q = admission.load(request)
        scoped, _ = verifier._load_scope_v5(scope, plan, S / 'CURRENT336.json')
        manifest, manifest_ref, _ = verifier._load_worker_manifest_v5(Path(q['manifest_contract']['path']), scoped)
        verifier.v3.v2._load_request(request, Path(q['manifest_contract']['path']), manifest_ref, manifest)
        unit = admission.launch_and_wait(request, 'generic-native-join-v6', num)
        subprocess.run([PYTHON, '-B', str(HERE / 'verify_actual_v6_join_v1.py'), str(num),
                        '--request', str(request), '--scope', str(scope), '--plan', str(plan)], cwd=LAB, check=True)
        assert admission.state(unit)['SubState'] == 'dead'
        proof_path = S / f'checkpoints/GENERIC_NATIVE_JOIN_V6_ACTUAL_ROOT_VERIFICATION_{num}.json'
        proof = admission.load(proof_path)
        assert proof['parent_reservation_released'] and proof['repeat_fee_idempotent']
        assert len(proof['case_verifications']) == count and not proof['failed_cases']
        terminal = dict(proof)
        terminal['actual_join_proof'] = admission.ref(proof_path)
        terminal['selected_case_ids'] = sorted(selected)
        terminal_path = S / f'checkpoints/ROOT{num}_NATIVE_JOIN_V6_CLOSED_TERMINAL_V1.json'
        admission.new(terminal_path, terminal)
        new_scope = S / f'checkpoints/ORIGINAL118_NATIVE_JOIN_AFTER_ROOT{num}_STRICT_V5_ROLLING_OVERLAY_V1.json'
        adapter.build(scope, terminal_path, new_scope, plan, S / 'CURRENT336.json')
        verifier._load_scope_v5(new_scope, plan, S / 'CURRENT336.json')
        value = admission.load(new_scope)
        checkpoint = S / f'checkpoints/ROOT{num}_MISSING_NATIVE_JOIN_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V1.json'
        admission.new(checkpoint, {'schema': 'ds02.stage2.root-missing-native-join-serial-continuation.v1',
                                  'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                  'goal_status': 'ACTIVE_FULL_SEVEN_ITEMS', 'goal_complete': False,
                                  'preceding_actual_handoff': admission.ref(previous),
                                  'actual_lifecycle_terminal': prior['actual_lifecycle_terminal'],
                                  'actual_native_scope': admission.ref(new_scope), 'actual_native_join_proof': admission.ref(proof_path),
                                  'historical_native_cause_bound': value['historical_native_cause_bound_per_fluid_id_cases'],
                                  'canonical_native_cause_bound': value['native_cause_bound_per_fluid_id_cases'],
                                  'native_cause_unknown': value['cause_not_located_after_completed_scan_cases'],
                                  'canonical_native_joins': value['actual_typed_native_saved_frame_join_physical_cases'],
                                  'historical_alias_unresolved': len(value['unresolved_alias_case_ids']),
                                  'root_payload_content_read': False, 'scientific_Q_credit': 0,
                                  'next': 'Continue actual ROOT279 endpoint and 14 reference studies, labels, splits and portable products.'})
        p = S / 'NEXT_READY_TASKS.md'
        p.write_text('最新实际严格原生对账：`' + str(checkpoint) + '`（SHA256 ' + admission.sha(checkpoint) + '）。历史别名独立保留，物理fate/flux/dynamics/Q UNKNOWN；完整七项目标ACTIVE。\n\n' + p.read_text())
        print(json.dumps({'event': 'ACTUAL_MISSING_NATIVE_JOIN_HANDOFF', 'namespace': num, 'checkpoint': str(checkpoint),
                          'canonical_native_joins': value['actual_typed_native_saved_frame_join_physical_cases'],
                          'goal_complete': False}), flush=True)
        previous, scope = checkpoint, new_scope


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    with (D / 'runtime/root-owned-missing-native-join-after-mass30-v1.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another missing native join continuation owns this queue')
        main()
