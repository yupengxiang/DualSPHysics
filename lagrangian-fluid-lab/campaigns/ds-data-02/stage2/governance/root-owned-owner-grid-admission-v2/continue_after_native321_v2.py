"""Wait for actual ROOT321, then serially construct nine owner-grid initial states."""
from pathlib import Path
import argparse
import datetime
import fcntl
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


def preceding_alive():
    for path in Path('/proc').iterdir():
        if not path.name.isdigit() or int(path.name) == os.getpid():
            continue
        try:
            tokens = (path / 'cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        if any(Path(token.decode(errors='replace')).name == 'continue_after_mass30_v1.py' for token in tokens):
            return True
    return False


def main():
    sys.path.insert(0, str(HERE))
    import prepare_actual_gencase_v2 as preparation
    import launch_actual_gencase_v2 as launcher
    admission = preparation.module(S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py', 'root_nine_gencase_admission')
    barrier = S / 'checkpoints/ROOT321_MISSING_NATIVE_JOIN_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V1.json'
    while not barrier.exists() or preceding_alive():
        print(json.dumps(dict(event='WAITING_ACTUAL_NATIVE_ROOT321_FOR_NINE_GENCASE',
                              utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                              gencase_launch_performed=False)), flush=True)
        time.sleep(30)
    prior = admission.load(barrier)
    assert prior['goal_complete'] is False and prior['scientific_Q_credit'] == 0
    assert prior['canonical_native_joins'] == prior['canonical_native_cause_bound'] == 117
    assert prior['native_cause_unknown'] == 0 and prior['historical_alias_unresolved'] == 1
    for key in ['actual_lifecycle_terminal', 'actual_native_scope', 'actual_native_join_proof']:
        assert admission.sha(prior[key]['path']) == prior[key]['sha256']
    terminal = admission.load(prior['actual_native_join_proof']['path'])
    assert terminal['parent_reservation_released'] and terminal['repeat_fee_idempotent']
    source_dir = S / 'requests/three-sentinel-owner-grid-gencase-v3-primary-admission-source-001'
    manifest_path = source_dir / 'owner-grid-gencase-root-admission-manifest-v3.json'
    manifest = admission.load(manifest_path)
    assert manifest['schema'] == 'ds02.stage2.root-nine-gencase-admission-source.v3'
    assert manifest['status'] == 'SOURCE_METADATA_PREFLIGHTED_PENDING_ACTUAL_NATIVE321'
    assert len(manifest['producer_requests']) == 9
    source_keys = [item['row_key'] for item in manifest['producer_requests']]
    assert source_keys == [f'{sid}:{grid}' for sid in ['F2-S2', 'F3-S1', 'F5-S1'] for grid in ['original', 'coarse', 'fine']]
    previous = barrier
    products = []
    actual = []
    common_dir = S / 'governance/root-owned-lifecycle-continuation-v1'
    extras = [*HERE.glob('*.py'), manifest_path, S / 'governance/root-owned-owner-grid-admission-v1/prepare_actual_gencase_v1.py',
              S / 'requests/f3-owner-grid-staged-gencase-v3-primary-source-prepared-001/f3-staged-gencase-request-manifest-v3.json',
              S / 'requests/f3-owner-grid-exact-forcing-rebind-v1-primary-source-prepared-001/f3-forcing-rebind-manifest-v1.json',
              common_dir / 'root_common_verification.py', common_dir / 'root_cpu_verification_footer.py',
              common_dir / 'root_forward_metadata.py',
              LAB / 'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py']
    for namespace, item in zip(range(337, 346), manifest['producer_requests']):
        assert not admission.load(D / 'runtime/resource-ledger.json')['reservations']
        source = Path(item['path'])
        assert admission.sha(source) == item['sha256']
        request = preparation.prepare(source, namespace, previous, extras)
        launcher.launch_and_wait(request, namespace)
        subprocess.run([PYTHON, '-B', str(HERE / 'verify_actual_gencase_v2.py'), str(namespace),
                        '--request', str(request)], cwd=LAB, check=True)
        proof_path = S / f'checkpoints/ROOT{namespace}_OWNER_GRID_GENCASE_ACTUAL_ROOT_VERIFICATION_V2.json'
        proof = admission.load(proof_path)
        assert proof['parent_reservation_released'] and proof['repeat_fee_idempotent']
        q = admission.load(request)
        product = dict(proof['products'], sentinel_id=q['sentinel_id'], grid_label=q['grid_label'],
                       row_key=q['row_key'], physical_case_id=q['physical_case_id'], family_id=q['family_id'],
                       case_id=q['case_id'], attempt_id=q['attempt_id'], planned_output_root=q['output_root'],
                       producer_request=admission.ref(request), actual_producer_proof=admission.ref(proof_path),
                       status='ACTUAL_GENCASE_PRODUCTS_AWAIT_INITIAL_SUPPORT_AUDIT')
        product['actual_auxiliary_runtime_closure'] = q['root_exact_auxiliary_closure']
        product['actual_staged_worker_report'] = proof.get('staged_worker_report')
        product['actual_control_cwd'] = str(Path(q['output_root']) / 'inputs/F3_S1' / q['grid_label']) if q['root_canonical_gencase_binding']['staged_worker'] else q['cwd']
        products.append(product)
        actual.append(dict(namespace=namespace, request=admission.ref(request), actual_proof=admission.ref(proof_path)))
        checkpoint = S / f'checkpoints/ROOT{namespace}_OWNER_GRID_GENCASE_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V2.json'
        admission.new(checkpoint, dict(schema='ds02.stage2.root-owner-grid-gencase-serial-continuation.v1',
            utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), goal_status='ACTIVE_FULL_SEVEN_ITEMS',
            goal_complete=False, preceding_actual_handoff=admission.ref(previous),
            actual_native_terminal=admission.ref(barrier), actual_lifecycle_terminal=prior['actual_lifecycle_terminal'],
            actual_gencase_count=len(actual), actual_gencase_proofs=list(actual),
            initial_support_audited=False, root_native_vtk_payload_content_read=False, scientific_Q_credit=0,
            next='Continue serial GenCase producers, then actual initial-support/native-mass audit and reference studies'))
        previous = checkpoint
        print(json.dumps(dict(event='ACTUAL_GENCASE_PRODUCER_CLOSED', namespace=namespace,
                              actual_gencase_count=len(actual), goal_complete=False)), flush=True)
    output_dir = S / 'requests/three-sentinel-owner-grid-actual-gencase-products-v2-root345-001'
    assert not output_dir.exists()
    output_dir.mkdir()
    product_map = output_dir / 'owner-grid-actual-gencase-product-map-v2.json'
    admission.new(product_map, dict(schema='ds02.stage2.three-sentinel.owner-grid-gencase-product-map.v2',
        status='NINE_ACTUAL_GENCASE_PRODUCTS_DEFERRED_NATIVE_HASH_INITIAL_AUDIT_REQUIRED',
        owner_report=manifest['owner_report'], products=products, actual_terminal=admission.ref(previous),
        generated_native_payload_read_by_root=False, scientific_Q_credit=0, goal_complete=False))
    checkpoint = S / 'checkpoints/ROOT345_NINE_GENCASE_ACTUAL_PRODUCTS_HANDOFF_V2.json'
    admission.new(checkpoint, dict(schema='ds02.stage2.root-nine-gencase-actual-products-handoff.v1',
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), actual_serial_terminal=admission.ref(previous),
        actual_native_terminal=admission.ref(barrier), actual_product_map=admission.ref(product_map),
        actual_gencase_count=9, initial_support_audited=False, scientific_Q_credit=0, goal_complete=False,
        next='Prepare fresh actual initial-support request from this exact product map; native masses require native-header producer'))
    ready = S / 'NEXT_READY_TASKS.md'
    ready.write_text('九个 GenCase 实际初态构造终态：`' + str(checkpoint) + '`（SHA256 ' + admission.sha(checkpoint) + '）；原生质量/初态支持仍待实际审计，科学Q UNKNOWN，完整七项目标ACTIVE。\n\n' + ready.read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    with (D / 'runtime/root-owned-nine-gencase-after-native321-v2.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another owner-grid GenCase continuation owns this queue')
        main()
