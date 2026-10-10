"""Independently close one actual GenCase parent without reading native outputs."""
from pathlib import Path
import argparse
import importlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')


def main(namespace, request):
    assert Path.cwd() == LAB
    sys.path.insert(0, str(HERE))
    from prepare_actual_gencase_v2 import module, stat_record
    admission = module(S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py', 'root_owner_grid_terminal_admission')
    common_path = S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    assert (D / 'runtime/resource-ledger.json').stat().st_size <= 10485760
    context = {'__name__': 'root_owner_grid_actual_closure', '__file__': str(common_path)}
    exec(common_path.read_text(), context)
    context.update(sha=admission.sha, load=admission.load)
    q, base, receipt, proof = context['common'](request)
    assert q['cpu_task_kind'] == 'gencase' and q['cpu_threads'] == 1
    assert q['root_canonical_gencase_binding']['namespace'] == namespace
    assert q['output_root'] == str(base) == receipt['output_root']
    assert q['execution_allowed'] and not q['source_only'] and not q['launch_disabled']
    assert receipt['returncode'] == 0
    controls = q['root_exact_auxiliary_closure']
    for row in controls:
        assert stat_record(row['path']) == row['stat']
        assert receipt['input_hashes_at_launch'][row['path']] == row['sha256']
        assert receipt['input_hashes_after_run'][row['path']] == row['sha256']
    staged_report = None
    if q['root_canonical_gencase_binding']['staged_worker']:
        report_path = base / 'report/f3-staged-gencase-worker-v1.json'
        staged_report = admission.load(report_path)
        assert staged_report['schema'] == 'ds02.stage2.three-sentinel.f3-staged-gencase-worker.v3'
        assert staged_report['status'] == 'COMPLETED'
        assert staged_report['request_path'] == str(request)
        assert staged_report['request_file_sha256'] == admission.sha(request)
        assert staged_report['request']['sha256'] == admission.sha(request)
        assert staged_report['sentinel_id'] == q['sentinel_id'] and staged_report['grid_label'] == q['grid_label']
        assert staged_report['child']['returncode'] == 0
        for key in ['post_error', 'candidate_post_error', 'staged_def_post_error', 'product_error']:
            assert staged_report[key] is None
        owner = q['staged_gencase_worker']['owner_forcing']
        def worker_stat(path):
            v = stat_record(path)
            return dict(device=v['st_dev'], inode=v['st_ino'], bytes=v['bytes'],
                        mtime_ns=v['mtime_ns'], ctime_ns=v['ctime_ns'])
        original = staged_report['source_original']
        for phase in ['pre', 'post']:
            part = original[phase]
            assert part['path'] == owner['path'] and part['sha256'] == owner['sha256']
            assert part['stat_before'] == part['stat_after'] == owner['stat_after'] == worker_stat(owner['path'])
        copy = staged_report['staged_source']
        copy_path = base / 'inputs/F3_S1' / q['grid_label'] / 'CaseSloshingAccData.csv'
        assert copy_path.is_file() and not copy_path.is_symlink()
        for phase in ['pre', 'post']:
            part = copy[phase]
            assert part['path'] == str(copy_path) and part['sha256'] == owner['sha256']
            assert part['stat_before'] == part['stat_after'] == worker_stat(copy_path)
        assert copy['source_inode'] != copy['new_inode'] == copy['post']['stat_after']['inode']
        candidate = q['staged_gencase_worker']['candidate_def']
        copied_def = base / 'inputs/F3_S1' / q['grid_label'] / Path(candidate['path']).name
        assert copied_def.is_file() and not copied_def.is_symlink()
        definition = staged_report['candidate_def']
        post_def = staged_report['staged_def_post']
        assert definition['path'] == post_def['path'] == str(copied_def)
        assert definition['source_sha256'] == definition['staged_sha256'] == post_def['sha256'] == candidate['sha256'] == admission.sha(copied_def)
        assert definition['staged_stat_before'] == definition['staged_stat_after'] == post_def['stat_before'] == post_def['stat_after'] == worker_stat(copied_def)
        assert copied_def.stat().st_ino != Path(candidate['path']).stat().st_ino
        expected_argv = [q['gencase']['binary']['path'], str(copied_def.with_suffix('')), str(base / 'generated'), '-save:all', '-threads:1']
        assert staged_report['actual_argv'] == staged_report['child']['argv'] == expected_argv
        assert staged_report['actual_cwd'] == staged_report['child']['cwd'] == str(copied_def.parent)
        proof['staged_worker_report'] = admission.ref(report_path)
        proof['exact_staged_forcing_and_definition_prepost_SHA_and_stat'] = True
    expected = {'generated_xml': 'generated.xml', 'fluid_vtk': 'generated_Fluid.vtk',
                'bound_vtk': 'generated_Bound.vtk', 'native_bi4': 'generated.bi4',
                'gencase_receipt': 'execution-receipt.json'}
    products = {}
    for key, filename in expected.items():
        path = base / filename
        assert path.is_file() and not path.is_symlink() and path.stat().st_size > 0
        assert q['output']['products'][key]['path'] == str(path)
        if staged_report is not None and key != 'gencase_receipt':
            actual = staged_report['products'][key]
            assert actual['path'] == str(path) and actual['status'] == 'PRESENT'
            assert actual['stat'] == worker_stat(path)
        products[key] = dict(path=str(path), stat=stat_record(path),
                             sha256=admission.sha(path) if key in {'generated_xml', 'gencase_receipt'} else None,
                             native_payload_content_read_by_root=False,
                             hash_status='BOUND_SMALL_METADATA' if key in {'generated_xml', 'gencase_receipt'} else 'ACTUAL_PRODUCT_STAT_ONLY_INITIAL_SUPPORT_PARENT_HASH_REQUIRED')
    proof.update(status='VERIFIED_ACTUAL_OWNER_GRID_GENCASE_PRODUCTS_NO_SCIENTIFIC_Q',
                 sentinel_id=q['sentinel_id'], grid_label=q['grid_label'],
                 physical_case_id=q['physical_case_id'], products=products,
                 exact_auxiliary_runtime_prepost_hashes_closed=True,
                 generated_native_vtk_payload_read_by_root=False,
                 native_initial_mass='UNKNOWN_REQUIRES_ACTUAL_NATIVE_HEADER_AUDIT',
                 next='Bind actual producer paths and receipts into a fresh initial-support manifest; continue full goal ACTIVE')
    footer_path = S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py'
    footer = footer_path.read_text().replace('1073741824', str(q['max_memory_bytes'])).replace(
        'F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json',
        f'ROOT{namespace}_OWNER_GRID_GENCASE_ACTUAL_ROOT_VERIFICATION_V2.json')
    context.update(q=q, b=base, r=receipt, p=proof, qp=request, num=str(namespace),
                   name='owner-grid-gencase-v3', subprocess=subprocess, importlib=importlib)
    exec(footer, context)
    assert admission.state(f'ds02-owner-grid-gencase-v3-root-{namespace}')['SubState'] == 'dead'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('namespace', type=int)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    main(args.namespace, args.request.absolute())
