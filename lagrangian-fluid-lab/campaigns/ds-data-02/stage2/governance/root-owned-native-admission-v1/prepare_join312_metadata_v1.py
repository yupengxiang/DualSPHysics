"""Normalize the ROOT312 source request without opening deferred payloads."""
from pathlib import Path
import hashlib
import json
import os

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
DENIED = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}


def sha(path):
    path = Path(path)
    assert path.is_file() and path.suffix.lower() not in DENIED
    before = path.stat()
    assert before.st_size <= 10 * 1024 * 1024
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    return value


def main():
    os.chdir(LAB)
    source = S / 'requests/root312-f4-multi-proof-intake-v4-root-prepared-001/root312-f4-native-extract-v4-root-forward-312-001.json'
    q = json.loads(source.read_text())
    hashes = q.get('input_hashes', q.get('input_sha256'))
    assert set(hashes) == set(q['input_files'])
    for path in q['input_files']:
        assert sha(path) == hashes[path]
    retained, moved = [], []
    for record in q['deferred_input_records']:
        path = Path(record['path'])
        st = path.stat()
        for key, value in {'bytes': st.st_size, 'st_dev': st.st_dev, 'st_ino': st.st_ino, 'mtime_ns': st.st_mtime_ns, 'ctime_ns': st.st_ctime_ns}.items():
            assert record[key] == value, (path, key)
        if str(path) in hashes:
            assert path.name in {'execution-receipt.json', 'typed-lifecycle-v4-summary.json'}
            assert record['sha256'] in {'PARENT_GUARD_COMPUTED', hashes[str(path)]}
            moved.append({'path': str(path), 'verified_static_sha256': hashes[str(path)], 'original_record': record})
        else:
            assert record['deferred'] and not record['content_opened_by_preparer']
            retained.append(record)
    assert len(moved) == 14 and len(retained) == 35
    q['deferred_input_records'] = retained
    q['deferred_input_files'] = [r['path'] for r in retained]
    q['estimated_deferred_read_bytes'] = sum(r['bytes'] for r in retained if Path(r['path']).is_file())
    q['root_static_deferred_normalization'] = {
        'source_request_sha256': sha(source), 'static_overlaps_classified_once': moved,
        'immutable_worker_manifest_unchanged': True,
        'worker_rechecks_native_and_typed_guard_records': True,
        'root_payload_content_read': False,
    }
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__file__': str(forward), '__name__': 'root312_metadata_forward'}
    exec(forward.read_text(), context)
    context['sha'] = sha
    extra = [Path(__file__), S / 'checkpoints/ROOT312_SOURCE_METADATA_INDEPENDENT_ROOT_VERIFICATION_V1.json', LAB / 'scripts/ds_data02_stage2_verify_root312_v3_metadata.py']
    extra += [LAB / 'scripts' / f'ds_data02_stage2_verify_generic_native_join_v{n}.py' for n in range(1, 6)]
    context['write'](q, source, 'generic-native-extract-v4-root-forward-312-002.json', extra=extra)


if __name__ == '__main__':
    main()
