#!/usr/bin/env python3
"""Normalize source-only ROOT317–321 requests without reading native payloads."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
PAYLOAD = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}
SOURCES = {
    317: 'generic-native-extract-v3-root317-f2-root198-missing-join-forward-002.json',
    318: 'generic-native-extract-v3-root318-f2-root206-missing-join-forward-001.json',
    319: 'generic-native-extract-v3-root319-f2-root287-missing-join-forward-001.json',
    320: 'generic-native-extract-v3-root320-f2-root288-missing-join-forward-001.json',
    321: 'generic-native-extract-v3-root321-f2-root289-missing-join-forward-001.json',
}


def sha(path):
    p = Path(path)
    assert p.suffix.lower() not in PAYLOAD and p.stat().st_size <= 10485760
    before = p.stat()
    data = p.read_bytes()
    after = p.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    return hashlib.sha256(data).hexdigest()


def joined(scope):
    ids = set()
    for edge in scope['actual_join_proofs']:
        assert sha(edge['path']) == edge['sha256']
        p = json.loads(Path(edge['path']).read_text())
        assert p['schema'] == 'ds02.stage2.root-actual-verification.v1'
        assert p['status'].startswith('VERIFIED_ACTUAL')
        assert p['parent_reservation_released'] and p['repeat_fee_idempotent']
        rows = p.get('case_verifications')
        if rows is None:
            assert isinstance(p.get('physical_case_id'), str)
            rows = [p]
        assert isinstance(rows, list) and rows
        selected = [r['physical_case_id'] for r in rows]
        assert all(isinstance(i, str) and i for i in selected)
        assert len(selected) == len(set(selected))
        ids.update(selected)
    assert len(ids) == scope['actual_typed_native_saved_frame_join_physical_cases']
    return ids


def main():
    scope_path = S / 'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json'
    scope = json.loads(scope_path.read_text())
    old = joined(scope)
    seen = set(json.loads((S / 'requests/generic-native-extract-v2-root-forward-315-004.json').read_text())['physical_case_ids'])
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_join_queue_forward', '__file__': str(forward)}
    exec(forward.read_text(), context)
    context['sha'] = sha
    for namespace, name in SOURCES.items():
        source = S / 'requests' / name
        q = json.loads(source.read_text())
        mp = Path(q['manifest_contract']['path'])
        assert sha(mp) == q['manifest_contract']['sha256']
        m = json.loads(mp.read_text())
        selected = set(q['physical_case_ids'])
        assert q['family_id'] == 'F2' and len(selected) == (6 if namespace == 321 else 8)
        assert not selected.intersection(old | seen | set(scope['remaining_cause_not_located_case_ids']))
        assert not any('RX056_RY014_FILL080_ROT090' in i for i in selected)
        bundles = m['typed_proof_bundles']
        subset = []
        for b in bundles:
            assert not b['synthetic_merged_proof'] and sha(b['path']) == b['sha256']
            p = json.loads(Path(b['path']).read_text())
            full = [r['physical_case_id'] for r in p['case_verifications']]
            assert len(full) == len(set(full)) == b['full_case_count']
            assert set(full) == set(b['full_case_ids'])
            assert set(b['selected_case_ids']) <= set(full)
            subset.extend(b['selected_case_ids'])
        assert len(subset) == len(set(subset)) and set(subset) == selected
        raw = q['deferred_input_records']
        assert [r for r in raw if isinstance(r, str)] == ['directory names/stat only; entry content not opened'] * len(selected)
        records = [r for r in raw if isinstance(r, dict)]
        assert len(records) == 7 * len(selected)
        assert {r['path'] for r in records} == set(q['deferred_input_files'])
        for r in records:
            p = Path(r['path']); assert not p.is_symlink()
            st = p.stat()
            for key, value in [('bytes', st.st_size), ('mtime_ns', st.st_mtime_ns), ('ctime_ns', st.st_ctime_ns), ('st_dev', st.st_dev), ('st_ino', st.st_ino)]:
                assert r[key] == value, (p, key)
        q['deferred_input_records'] = [r for r in records if Path(r['path']).is_file()]
        assert len(q['deferred_input_records']) == 6 * len(selected)
        assert '-B' not in q['command']; q['command'].insert(1, '-B')
        q.update(cwd=str(LAB), worktree_root=str(LAB.parent), shared_runtime_version='v8', estimated_storage_bytes=67108864,
                 estimated_hdf5_read_bytes=0, qualification={'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'})
        q['root_credit_policy'] = {'new_original118_cause_bound_physical_cases': 0,
                                 'typed_native_join': 'only independently verified IDs absent from fresh actual proofs',
                                 'physical_fate_flux_dynamics_Q': 'UNKNOWN'}
        q['root_canonical_binding'] = {'namespace': namespace, 'source_request': str(source), 'source_sha256': sha(source),
                                       'scope_at_prepare': {'path': str(scope_path), 'sha256': sha(scope_path)},
                                       'fresh_scope_resources_nonoverlap_required_before_launch': True,
                                       'payload_content_read': False, 'launch_performed': False}
        out = S / f'requests/generic-native-extract-v3-root-forward-{namespace}-001.json'
        context['write'](q, source, out.name, extra=[Path(__file__), scope_path])
        seen.update(selected)
        print(json.dumps({'namespace': namespace, 'request': str(out), 'sha256': sha(out), 'cases': len(selected), 'new_cause_credit': 0, 'launch_performed': False}))
    assert len(seen) == 46


if __name__ == '__main__':
    main()
