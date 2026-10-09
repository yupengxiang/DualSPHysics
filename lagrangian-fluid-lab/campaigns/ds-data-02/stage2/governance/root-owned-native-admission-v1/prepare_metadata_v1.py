#!/usr/bin/env python3
"""Normalize delegated native requests without reading scientific payloads.

This is parent admission metadata preparation only. The existing serial
lifecycle monitor remains the sole active payload scheduler. These outputs
must receive a fresh resource/scope check before any later launch.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
STAGE = LAB / 'campaigns/ds-data-02/stage2'
PAYLOAD = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}


def sha(path):
    path = Path(path)
    assert path.suffix.lower() not in PAYLOAD
    assert path.stat().st_size <= 10485760
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', type=int, choices=[308, 309], required=True)
    parser.add_argument('--actual-plan', type=Path, required=True)
    parser.add_argument('--actual-registry', type=Path, required=True)
    args = parser.parse_args()
    n = args.namespace
    version, family, count, producer = (2, 'F4', 4, 280) if n == 308 else (1, 'F6', 6, 281)
    source = STAGE / f'requests/generic-native-extract-v{version}-root-forward-{n}-001.json'
    q = json.loads(source.read_text())
    assert q['family_id'] == family and len(q['physical_case_ids']) == count
    assert q['cpu_threads'] == 1 and q['max_memory_bytes'] == 4294967296
    assert q['command'][0] == '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
    assert '-B' not in q['command']
    q['command'].insert(1, '-B')
    records = q['deferred_input_records']
    strings = [r for r in records if isinstance(r, str)]
    assert strings == ['directory names/stat only; entry content not opened'] * count
    path_records = [r for r in records if isinstance(r, dict)]
    assert len(path_records) == 7 * count
    assert {r['path'] for r in path_records} == set(q['deferred_input_files'])
    for r in path_records:
        p = Path(r['path'])
        assert not p.is_symlink()
        st = p.stat()
        for key, val in [('bytes', st.st_size), ('mtime_ns', st.st_mtime_ns),
                         ('ctime_ns', st.st_ctime_ns), ('st_dev', st.st_dev), ('st_ino', st.st_ino)]:
            assert r[key] == val, (r['path'], key)
    q['deferred_input_records'] = [r for r in path_records if Path(r['path']).is_file()]
    assert len(q['deferred_input_records']) == 6 * count
    scope_path = STAGE / 'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json'
    scope = json.loads(scope_path.read_text())
    assert set(q['physical_case_ids']) <= set(scope['remaining_cause_not_located_case_ids'])
    assert q['case_scope']['historical_118_exact_count'] == count
    assert q['case_scope']['diagnostic_case_count'] == 0
    plan = json.loads(args.actual_plan.read_text())
    eligible = {r['physical_case_id'] for r in plan['case_records'] if r['status'] == 'ACTUAL_SAVED_MASK_COMPLETED'}
    assert set(q['physical_case_ids']) <= eligible
    proof = STAGE / f'checkpoints/TYPED_LIFECYCLE_BATCH_{family}_ACTUAL_ROOT_VERIFICATION_{producer}.json'
    v = json.loads(proof.read_text())
    assert v['parent_reservation_released'] and v['repeat_fee_idempotent'] and not v['failed_cases']
    assert set(q['physical_case_ids']) == {r['physical_case_id'] for r in v['case_verifications']}
    assert sha(proof) == json.loads(Path(q['manifest_contract']['path']).read_text())['terminal_proof']['sha256']
    if n == 308:
        assert str(LAB / 'scripts/ds_data02_stage2_build_generic_native_extract_v1.py') in q['input_files']
    q.update(shared_runtime_version='v8', estimated_storage_bytes=67108864, cwd=str(LAB),
             kind='cpu', cpu_task_kind='audit', qualification={'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'},
             launch_allowed=True, execution_allowed=True)
    q['root_deferred_record_normalization'] = {
        'source_nonpath_strings_count': count, 'file_stat_records': 6 * count,
        'directory_stat_records': count, 'all_exact_deferred_paths_covered': True,
        'source_records_preserved_in_source_request': True, 'payload_content_read': False,
    }
    q['root_prepare_actual_nonoverlap'] = {
        'actual_plan': {'path': str(args.actual_plan), 'sha256': sha(args.actual_plan)},
        'actual_registry': {'path': str(args.actual_registry), 'sha256': sha(args.actual_registry)},
        'scope': {'path': str(scope_path), 'sha256': sha(scope_path)},
        'fresh_scope_and_resources_required_before_launch': True,
        'launch_performed': False,
    }
    forward_path = STAGE / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_native_metadata_forward', '__file__': str(forward_path)}
    exec(forward_path.read_text(), context)
    context['sha'] = sha
    context['write'](q, source, f'generic-native-extract-v{version}-root-forward-{n}-002.json',
                     extra=[scope_path, proof, args.actual_plan, args.actual_registry, Path(__file__)])
    output = STAGE / f'requests/generic-native-extract-v{version}-root-forward-{n}-002.json'
    q = json.loads(output.read_text())
    sys.path.insert(0, str(LAB / 'scripts'))
    from ds_data02_runtime_v8 import _light_validate
    _light_validate(q, data_root=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02'))
    for p, expected in q['input_sha256'].items():
        assert sha(p) == expected, p
    print(json.dumps({'namespace': n, 'request': str(output), 'sha256': sha(output),
                      'cases': count, 'deferred_files': 6 * count, 'launch_performed': False,
                      'payload_content_read': False, 'scientific_credit': 0}))


if __name__ == '__main__':
    main()
