#!/usr/bin/env python3
"""Validate fresh099 without opening scientific payloads."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def load(rel):
    return json.loads((ROOT / rel).read_text())

idx = load('metadata/visual-frontier-index.json')
d = load('decisions/F3_STAGE1_DP006_P0800_AY0250.json')
e = load('metadata/root796_render_evidence.json')
assert idx['batch_size'] == 1
assert idx['status'] == 'visual-approved-by-delegated-agent'
assert idx['independent_case_increment'] == 0
assert d['status'] == 'visual-approved-by-delegated-agent'
assert d['family_id'] == 'F3'
assert d['claim_limits']['production_approval_grant'] is False
assert d['claim_limits']['q_n_grant'] is False
assert d['claim_limits']['numerical_precision_grant'] is False
assert d['claim_limits']['pitch_domain_grant'] is False
assert d['claim_limits']['independent_case_count_increment'] == 0
assert d['source_payload_policy']['science_payload_read_or_hashed_by_source_package'] is False

report_ref = e['render']['report']
manifest_ref = e['xmf']['manifest']
report_path = Path(report_ref['path'])
manifest_path = Path(manifest_ref['path'])
assert report_path.is_file() and sha(report_path) == report_ref['sha256']
assert manifest_path.is_file() and sha(manifest_path) == manifest_ref['sha256']
report = json.loads(report_path.read_text())
manifest = json.loads(manifest_path.read_text())
assert report['frames'] == 836 and report['source_frames'] == 836
assert report['all_frames_rendered'] is True
assert report['actual_times_preserved_exactly'] is True
assert report['native_identity_axis_preserved'] is True
assert report['nonfinite_active_states'] == 0
assert len(report['outputs']['contact_sheets']) == 35
assert report['manifest_sha256'] == manifest_ref['sha256']
assert manifest['frames'] == 836 and manifest['particles'] == 179208 and manifest['dimension'] == 3
assert manifest['physical_condition_sha256'] == d['physical_condition_sha256']
assert manifest['actual_converter_physical_condition_scope_sha256'] == d['physical_condition_sha256']
assert manifest['source_and_actual_scopes_are_distinct'] is True
assert manifest['independent_case_count_increment'] == 0

for frame in report['frame_diagnostics']:
    assert frame['active'] == 179208
    assert frame['missing'] == 0
    assert frame['finite_positions_active'] is True
    assert all(v['finite_active'] is True and v['nonfinite_active'] == 0 for v in frame['finite_fields'].values())
    assert frame['type_counts_active'] == {'fixed': 111708, 'moving': 0, 'floating': 0, 'fluid': 67500, 'unknown': 0}

for kind in ('native', 'typed', 'xmf', 'render'):
    r = e[kind]['receipt']
    p = Path(r['path'])
    assert p.is_file() and sha(p) == r['sha256'], (kind, p)
    rd = json.loads(p.read_text())
    assert rd['status'] == 'completed' and rd['returncode'] == 0, (kind, rd.get('status'), rd.get('returncode'))

for item in e['render']['contact_sheets'] + e['render']['keyframe_images']:
    p = Path(item['path'])
    assert p.is_file(), p
    assert sha(p) == item['sha256'], p
    assert not any(s in str(p).lower() for s in ('.h5', '.bi4', '.csv', '.dat', '.vtk'))
assert len(e['render']['contact_sheets']) == 35
assert e['render']['keyframes_reviewed'] == [0, 1, 65, 115, 200, 300, 400, 500, 600, 700, 800, 835]
assert e['render']['all_frames_rendered'] is True
assert e['render']['active_particle_count_all_frames'] == [179208]
assert e['render']['missing_particle_count_all_frames'] == [0]
assert e['render']['nonfinite_position_flags_all_frames'] == [True]
assert e['render']['nonfinite_field_flags_all_frames'] == [True]

# Guard the package itself against accidental scientific-payload path claims.
for p in ROOT.rglob('*'):
    if p.is_file() and p.suffix.lower() in {'.h5', '.bi4', '.csv', '.dat', '.vtk'}:
        raise AssertionError(f'scientific payload unexpectedly included: {p}')
print('fresh099 F3 Root796 corner visual metadata + PNG hash validation: PASS')
