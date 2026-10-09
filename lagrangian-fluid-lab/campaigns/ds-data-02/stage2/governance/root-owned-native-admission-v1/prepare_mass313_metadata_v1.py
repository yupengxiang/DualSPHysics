#!/usr/bin/env python3
"""Close parent/runtime inputs for the seventeen-case mass diagnostic."""
from pathlib import Path
import hashlib
import json

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
    source = STAGE / 'requests/root313-native-typed-mass-impact-root-forward-313-004.json'
    q = json.loads(source.read_text())
    assert q['family_id'] == 'INFRA'
    q['source_family_id'] = q['family_id']
    q['family_id'] = 'infra'
    manifest = Path(q['manifest_contract']['path'])
    assert sha(manifest) == q['manifest_contract']['sha256']
    bundles = q['source_proofs']
    assert [(r['bundle_id'], r['case_count']) for r in bundles] == [('ROOT258', 7), ('ROOT264', 3), ('ROOT268', 7)]
    ids = [case for r in bundles for case in r['case_ids']]
    assert len(ids) == len(set(ids)) == 17
    assert q['cpu_threads'] == 1 and q['max_memory_bytes'] == 4294967296
    assert q['max_wall_seconds'] == 3600
    deferred = q['deferred_input_contracts']
    assert len(deferred) == 17 and len(q['deferred_input_files']) == 17
    assert {r['path'] for r in deferred} == set(q['deferred_input_files'])
    for r in deferred:
        p = Path(r['path']); assert not p.is_symlink()
        s = p.stat()
        for key, val in [('bytes', s.st_size), ('mtime_ns', s.st_mtime_ns),
                         ('ctime_ns', s.st_ctime_ns), ('st_dev', s.st_dev), ('st_ino', s.st_ino)]:
            assert r[key] == val, (p, key)
    assert '-B' not in q['command']
    q['command'].insert(1, '-B')
    q['deferred_input_records'] = deferred
    q.update(cwd=str(LAB), worktree_root=str(LAB.parent), estimated_storage_bytes=16777216,
             estimated_hdf5_read_bytes=0, qualification={'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'})
    q['root_canonical_binding'] = {
        'namespace': 313, 'case_count': 17, 'source_request': str(source), 'source_sha256': sha(source),
        'fresh_resource_and_nonoverlap_check_required': True,
        'launch_performed': False, 'payload_content_read': False,
        'mass_credit': 'UNKNOWN until actual typed initial_mass_kg evidence',
    }
    forward = STAGE / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_mass_metadata_forward', '__file__': str(forward)}
    exec(forward.read_text(), context)
    context['sha'] = sha
    output = STAGE / 'requests/native-typed-mass-impact-root-forward-313-005.json'
    context['write'](q, source, output.name, extra=[Path(__file__)])
    saved = json.loads(output.read_text())
    for path, digest in saved['input_sha256'].items():
        assert sha(path) == digest, path
    print(json.dumps({'namespace': 313, 'request': str(output), 'sha256': sha(output),
                      'cases': 17, 'deferred_files': 17, 'payload_content_read': False,
                      'launch_performed': False}))


if __name__ == '__main__':
    main()
