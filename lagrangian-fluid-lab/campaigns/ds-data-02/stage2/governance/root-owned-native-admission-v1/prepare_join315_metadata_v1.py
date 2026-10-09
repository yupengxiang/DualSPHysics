#!/usr/bin/env python3
"""Prepare eight already-cause-bound F2 cases for a new precise native join."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
STAGE = LAB / 'campaigns/ds-data-02/stage2'
PAYLOAD = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}


def sha(path):
    path = Path(path)
    assert path.suffix.lower() not in PAYLOAD and path.stat().st_size <= 10485760
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = STAGE / 'requests/generic-native-extract-v2-root315-f2-missing-join-forward-003.json'
    q = json.loads(source.read_text())
    manifest = Path(q['manifest_contract']['path']); assert sha(manifest) == q['manifest_contract']['sha256']
    m = json.loads(manifest.read_text())
    assert q['family_id'] == 'F2' and len(q['physical_case_ids']) == 8
    scope_path = STAGE / 'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json'
    scope = json.loads(scope_path.read_text())
    existing_joins = set()
    for edge in scope['actual_join_proofs']:
        path = Path(edge['path']); assert sha(path) == edge['sha256']
        proof = json.loads(path.read_text())
        assert proof['schema'] == 'ds02.stage2.root-actual-verification.v1'
        assert proof['status'].startswith('VERIFIED_ACTUAL')
        assert proof['parent_reservation_released'] and proof['repeat_fee_idempotent']
        # Four earlier proofs bind one case at the top level. Later batch
        # proofs carry case_verifications. Reject all other layouts.
        if 'case_verifications' in proof:
            rows = proof['case_verifications']
            assert isinstance(rows, list) and rows
        else:
            assert isinstance(proof.get('physical_case_id'), str)
            rows = [proof]
        ids = [row['physical_case_id'] for row in rows]
        assert all(isinstance(case_id, str) and case_id for case_id in ids)
        assert len(ids) == len(set(ids))
        existing_joins.update(ids)
    assert len(existing_joins) == scope['actual_typed_native_saved_frame_join_physical_cases'] == 47
    selected = set(q['physical_case_ids'])
    assert not selected.intersection(existing_joins)
    assert not selected.intersection(scope['remaining_cause_not_located_case_ids'])
    bundles = m['typed_proof_bundles']; assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle['synthetic_merged_proof'] is False and bundle['full_case_count'] == 8
    assert set(bundle['selected_case_ids']) == selected == set(bundle['full_case_ids'])
    assert sha(bundle['path']) == bundle['sha256']
    raw_records = q['deferred_input_records']
    assert [r for r in raw_records if isinstance(r, str)] == ['directory names/stat only; entry content not opened'] * 8
    records = [r for r in raw_records if isinstance(r, dict)]
    assert len(records) == 56
    assert {r['path'] for r in records} == set(q['deferred_input_files'])
    for r in records:
        p = Path(r['path']); assert not p.is_symlink()
        s = p.stat()
        for key, val in [('bytes', s.st_size), ('mtime_ns', s.st_mtime_ns),
                         ('ctime_ns', s.st_ctime_ns), ('st_dev', s.st_dev), ('st_ino', s.st_ino)]:
            assert r[key] == val, (p, key)
    q['deferred_input_records'] = [r for r in records if Path(r['path']).is_file()]
    assert len(q['deferred_input_records']) == 48
    assert '-B' not in q['command']; q['command'].insert(1, '-B')
    q.update(cwd=str(LAB), worktree_root=str(LAB.parent), shared_runtime_version='v8',
             estimated_storage_bytes=67108864, estimated_hdf5_read_bytes=0,
             qualification={'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'})
    q['root_credit_policy'] = {'new_original118_cause_bound_physical_cases': 0,
                              'typed_native_join': 'only independent actual cases absent from fresh actual join proofs',
                              'physical_fate_flux_dynamics_Q': 'UNKNOWN'}
    q['claim_boundary']['historical118_cause_credit'] = 'NO_NEW_CAUSE_COUNT_PREVIOUS_SCOPE_ALREADY_BOUND'
    q['root_canonical_binding'] = {'namespace': 315, 'source_request': str(source),
                                   'source_sha256': sha(source), 'scope_at_prepare': {'path': str(scope_path), 'sha256': sha(scope_path)},
                                   'fresh_scope_resources_nonoverlap_required_before_launch': True,
                                   'payload_content_read': False, 'launch_performed': False}
    forward = STAGE / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_join_metadata_forward', '__file__': str(forward)}
    exec(forward.read_text(), context); context['sha'] = sha
    output = STAGE / 'requests/generic-native-extract-v2-root-forward-315-004.json'
    context['write'](q, source, output.name, extra=[Path(__file__), scope_path,
                                                  LAB / 'scripts/ds_data02_stage2_build_generic_native_extract_v1.py'])
    print(json.dumps({'namespace': 315, 'request': str(output), 'sha256': sha(output),
                      'cases': 8, 'new_cause_credit': 0, 'payload_content_read': False, 'launch_performed': False}))


if __name__ == '__main__':
    main()
