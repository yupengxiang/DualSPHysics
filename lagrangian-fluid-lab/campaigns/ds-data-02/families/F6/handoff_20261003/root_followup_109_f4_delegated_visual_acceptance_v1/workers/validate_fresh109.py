#!/usr/bin/env python3
"""Bounded metadata/path validator for the fresh109 delegated visual handoff."""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
idx = json.loads((HERE / 'metadata' / 'review-index.json').read_text())
assert idx['schema'] == 'ds02.f4.delegated-visual-acceptance.fresh109.index.v1'
assert idx['reviewer'] == '/root/f6_endpoint_initial_qa'
assert len(idx['cases']) == 2
for case in idx['cases']:
    assert case['status'] == 'visual-approved-by-delegated-agent'
    assert case['contact_sheet_count'] == 51
    assert len(case['contact_sheet_paths']) == 51
    assert len(case['key_frame_paths']) == 9
    for path in case['contact_sheet_paths'] + case['key_frame_paths']:
        assert Path(path).is_file(), path
    assert case['png_hashes']['status'] == 'not_computed'
    assert case['frames'] == 1201
    assert case['render_receipt_status'] in {'completed', 'running'}
    if case['case_id'] == 'F4_DROP_gap0p24000_xoffm0p08000_yoffm0p04000_uz0p40000':
        assert case['old_renderer_receipt_status'] == 'running'
        assert case['old_renderer_returncode'] is None
        recovery = case['recovery_audit']
        assert recovery['audit_completed'] is True
        assert recovery['frame_file_count'] == 1201
        assert recovery['contact_sheet_file_count'] == 51
        assert recovery['source_old_returncode'] is None
        assert recovery['reconciliation_status'] == 'root_lock_applied_no_signal_no_adoption'
    closure = json.loads(Path(case['metadata_closure']).read_text())
    assert closure['review']['reviewer'] == '/root/f6_endpoint_initial_qa'
    assert closure['review']['status'] == 'visual-approved-by-delegated-agent'
    assert closure['render']['frames'] == 1201
    assert closure['render']['source_frames'] == 1201
    assert closure['render']['all_frames_rendered'] is True
    assert closure['render']['actual_times_preserved_exactly'] is True
    assert closure['render']['native_identity_axis_preserved'] is True
    assert closure['native_frame0']['report_summary']['pass'] is True
    # The package must never carry a scientific payload path.  Schema names
    # may mention a format (for example, ``bi4-direct-conversion``), so scan
    # only path-valued strings rather than rejecting harmless metadata labels.
    def walk(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k, v
                yield from walk(v)
        elif isinstance(value, list):
            for v in value:
                yield None, v
                yield from walk(v)
    for key, value in walk(closure):
        if key and (key.endswith('_path') or key in {'path', 'pattern'}):
            text = str(value).lower()
            for forbidden in ('.h5', '.bi4', '.csv', '.vtk', '.dat'):
                assert forbidden not in text, (case['case_id'], key, forbidden)
print('fresh109 metadata/path validation: PASS')
