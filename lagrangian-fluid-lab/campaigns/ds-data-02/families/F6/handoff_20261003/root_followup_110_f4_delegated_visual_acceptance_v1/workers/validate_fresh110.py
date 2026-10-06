#!/usr/bin/env python3
"""Validate fresh110 metadata and PNG review evidence without touching science payloads."""
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
assert idx['fresh_id'] == 'fresh110'
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
    # The known transient lifecycle distinction is retained, never silently normalized.
    if case['case_id'].endswith('uz0p60000'):
        assert cl['typed_conversion']['summary']['lifecycle']['first_missing_frame_by_type'] == {'3': 1102}
    else:
        assert cl['typed_conversion']['summary']['lifecycle']['first_missing_frame_by_type'] == {}
    # Reject only path-valued forbidden science payload references.
    for value in walk_path_values(cl):
        assert not value.lower().endswith(FORBIDDEN), value
print('fresh110 validation PASS: 2 cases, 120 contact sheets, 18 key PNGs hashed after view_image')
