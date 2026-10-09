#!/usr/bin/env python3
"""Bind ROOT310 selected-file snapshot to the actual ROOT277/278 metadata.

Metadata preparation only; no selected BI4 is opened or hashed here. The
serial lifecycle scheduler must release its reservation before this request
can receive a fresh admission check and be launched.
"""
from pathlib import Path
import hashlib
import json
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'


def sha(p):
    p = Path(p)
    assert p.suffix.lower() not in {'.bi4', '.obi4', '.ibi4', '.vtk', '.h5', '.hdf5', '.jsonl'}
    assert p.stat().st_size <= 10485760
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    source = S / 'requests/root310-selected-native-snapshot-source-prepared-001/source-request.json'
    q = json.loads(source.read_text())
    assert q['estimated_native_read_passes'] == 1 and q['deferred_input_file_count'] == 10
    assert len(q['selected_native_bindings']) == 10
    assert '-B' not in q['command']
    q['command'].insert(1, '-B')
    q.update(cpu_threads=1, omp_threads=1, max_wall_seconds=1800,
             max_memory_bytes=1073741824, estimated_storage_bytes=67108864,
             shared_runtime_version='v8', cwd=str(LAB), launch_allowed=True,
             execution_allowed=True, qualification={'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'})
    q['estimated_deferred_read_bytes'] = q['estimated_native_read_bytes']
    q['estimated_deferred_read_passes'] = 1
    q['root_admission_policy'] = {
        'metadata_only_preparation': True, 'launch_performed': False,
        'serial_lifecycle_reservation_must_be_released_before_launch': True,
        'fresh_deadline_budget_and_storage_check_required': True,
        'initial_content_hashes_obtained_only_by_reserved_snapshot_worker': True,
        'source_files_not_decoded': True, 'scientific_credit': 0,
    }
    extra = [Path(__file__), S / 'requests/root279-pair-native-source-v2-prepared-001/manifest.json',
             S / 'requests/root271-actual-pair-intake-root277278-001/pair-intake.json']
    for n, mode in [(277, 'SAME'), (278, 'HALF')]:
        proof = S / f'checkpoints/F1_S2_DP020_{mode}_CFL_SAVEDT_BOUNDED_ACTUAL_ROOT_VERIFICATION_{n}.json'
        p = json.loads(proof.read_text())
        assert p['parent_reservation_released'] and p['repeat_fee_idempotent']
        assert sha(p['request']) == p['request_sha256']
        assert sha(p['receipt']) == p['receipt_sha256']
        extra.extend([proof, Path(p['request']), Path(p['receipt'])])
    for record in q['selected_native_bindings']:
        path = Path(record['path'])
        assert path.suffix.lower() == '.bi4' and not path.is_symlink()
        st = path.stat()
        observed = {'dev': st.st_dev, 'ino': st.st_ino, 'bytes': st.st_size,
                    'mtime_ns': st.st_mtime_ns, 'ctime_ns': st.st_ctime_ns}
        assert observed == record['stat_at_prepare']
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_snapshot310_forward', '__file__': str(forward)}
    exec(forward.read_text(), context)
    context['sha'] = sha
    context['write'](q, source, 'native-selected-source-snapshot-root-forward-310-001.json', extra=extra)
    output = S / 'requests/native-selected-source-snapshot-root-forward-310-001.json'
    q = json.loads(output.read_text())
    for path, expected in q['input_sha256'].items():
        assert sha(path) == expected
    print(json.dumps({'request': str(output), 'sha256': sha(output),
                      'selected_file_count': 10, 'estimated_read_bytes': q['estimated_deferred_read_bytes'],
                      'launch_performed': False, 'payload_content_read': False}))


if __name__ == '__main__':
    main()
