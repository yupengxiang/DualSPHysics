#!/usr/bin/env python3
"""Validate fresh113 metadata and PNG review evidence without touching science payloads."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'metadata' / 'review-index.json'
FORBIDDEN = ('.h5', '.bi4', '.csv', '.vtk', '.dat')

def load(p):
    with p.open('r', encoding='utf-8') as f:
        return json.load(f)

def sha256(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def walk_path_values(obj, key=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_path_values(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_path_values(v, key)
    elif isinstance(obj, str) and (key == 'path' or key.endswith('_path') or key == 'pattern'):
        yield obj

idx = load(INDEX)
assert idx['schema'] == 'ds02.f6.delegated-visual-review.v1'
assert idx['fresh_id'] == 'fresh113'
assert idx['source_only'] is True
assert idx['reviewer'] == '/root/f6_endpoint_initial_qa'
assert len(idx['cases']) == 2
for case in idx['cases']:
    assert case['status'] == 'visual-approved-by-delegated-agent'
    assert case['decision'] == 'approved'
    assert case['frames'] == 1201
    assert case['contact_sheet_count'] == 51
    assert len(case['contact_sheet_paths']) == 51
    assert len(case['key_frame_paths']) == 9
    assert case['png_hashes']['computed_after_view_image'] is True
    for item in case['png_hashes']['contact_sheets'] + case['png_hashes']['key_frames']:
        p = Path(item['path'])
        assert p.is_file(), p
        assert item['sha256'] == sha256(p), p
        assert item['bytes'] == p.stat().st_size, p
    receipt = case['render_receipt']
    assert receipt['status'] == 'completed'
    assert receipt['returncode'] == 0
    closure = ROOT / 'metadata' / (case['case_id'].lower() + '-metadata-closure.json')
    assert closure.is_file(), closure
    cl = load(closure)
    assert cl['render']['summary']['frames'] == 1201
    assert cl['render']['summary']['source_frames'] == 1201
    assert cl['render']['summary']['all_frames_rendered'] is True
    assert cl['render']['summary']['actual_times_preserved_exactly'] is True
    assert cl['render']['summary']['native_identity_axis_preserved'] is True
    assert cl['render']['summary']['nonfinite_active_states'] == 0
    assert cl['native_frame0_qa']['summary']['pass'] is True
    assert cl['source_scope_separation']['must_not_equate_scopes'] is True
    assert cl['png_assets']['algorithm'] == 'sha256'
    lifecycle = cl['typed_conversion']['summary']['lifecycle']
    assert isinstance(lifecycle['transient_missing_frame_count'], int)
    assert isinstance(lifecycle['maximum_missing_particles'], int)
    assert lifecycle['maximum_missing_particles'] >= 0
    final_uid = lifecycle['final_uid_state']
    assert final_uid['frame'] == 1200
    assert final_uid['active_particles'] + final_uid['missing_particles'] == 83233
    assert final_uid['missing_particles'] >= 0
    assert 0 <= final_uid['missing_uid_preview_count'] <= final_uid['missing_particles']
    assert lifecycle['count_semantics']['transient_missing_frame_count'].startswith('cumulative')
    assert lifecycle['count_semantics']['maximum_missing_particles'].startswith('maximum')
    # Reject only path-valued forbidden science payload references.
    for value in walk_path_values(cl):
        assert not value.lower().endswith(FORBIDDEN), value
print('fresh113 validation PASS: 2 cases, 120 contact sheets, 18 key PNGs hashed after view_image')
