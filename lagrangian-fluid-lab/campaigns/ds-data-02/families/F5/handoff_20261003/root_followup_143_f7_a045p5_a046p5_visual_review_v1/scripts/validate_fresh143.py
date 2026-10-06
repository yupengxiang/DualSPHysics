#!/usr/bin/env python3
"""Metadata/PNG-only verifier for fresh143; never opens BI4/H5/CSV/DAT/VTK science payloads."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
PKG = Path(__file__).resolve().parents[1]
META = PKG / 'metadata/fresh143-visual-review.json'
CASES = ('F7_OBSTACLE_QUINTIC_B08_A045P5', 'F7_OBSTACLE_QUINTIC_B08_A046P5')
EXPECTED = {'dimension': 3, 'total': 70179, 'fixed': 27495, 'moving': 1984, 'floating': 0, 'fluid': 40700}
KEYS = (0, 14, 125, 200, 300, 400, 450, 500, 550, 600)
SAFE_META_SUFFIXES = {'.json', '.xml', '.xmf', '.md', '.py'}

def sha(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text())

def check(condition, message):
    if not condition:
        raise AssertionError(message)

def type_counts(fd):
    tc = fd.get('type_counts_active', {})
    return {'fixed': int(tc.get('fixed', tc.get('0', 0))), 'moving': int(tc.get('moving', tc.get('1', 0))), 'floating': int(tc.get('floating', tc.get('2', 0))), 'fluid': int(tc.get('fluid', tc.get('3', 0))), 'unknown': int(tc.get('unknown', 0))}

d = read_json(META)
check(d['schema'] == 'ds02.f5.fresh143.f7.visual-review-handoff.v1', 'schema')
check(d['source_only_package'] and d['no_jobs_started'] and d['no_science_payload_read_or_hashed'], 'source safety')
check(d['controller']['requested'] == 24 and d['controller']['finished'] == 24 and d['controller']['completed0'] == 24 and d['controller']['pending_held'] == 0, 'controller metadata')
check(len(d['cases']) == 2, 'case count')
seen = set()
for c in d['cases']:
    case = c['case_id']
    check(case in CASES and case not in seen, f'case identity {case}')
    seen.add(case)
    a = c['actual_counts_and_solver']; check(a['dimension'] == 3 and a['total'] == 70179 and a['fixed'] == 27495 and a['moving'] == 1984 and a['floating'] == 0 and a['fluid'] == 40700, f'counts {case}')
    v = c['visual_scope']; check(len(v['all_601_saved_frame_pngs']) == 601 and len(v['all_26_contact_sheets']) == 26, f'frame/contact inventory {case}')
    check(v['reviewed_all_contact_sheets'] is True and v['reviewed_event_keyframes'] == list(KEYS), f'visual review inventory {case}')
    check(v['actual_times_preserved_exactly'] is True and v['native_identity_axis_preserved'] is True, f'time/identity {case}')
    check(c['qualification_status']['precision_status'] == 'not_accepted' and c['qualification_status']['q_n'] == 'not_granted' and c['qualification_status']['production_approval'] == 'none', f'qualification {case}')
    check(c['qualification_status']['case_credit_granted'] is False and c['qualification_status']['independent_case_count_increment'] == 0, f'credit {case}')
    check(len(c['six_segment_motion_metadata']['segments_for_this_amplitude']) == 6 and c['six_segment_motion_metadata']['native_sampled_regular'] == 'not C2', f'motion {case}')
    scope = c['scope_separation']; check(scope['canonical_equals_source_plan_claim'] is False and scope['scopes_are_kept_distinct'] is True, f'scope separation {case}')
    report_path = Path(c['actual_render_metadata']['report_path']); report = read_json(report_path); check(sha(report_path) == c['actual_render_metadata']['report_sha256'], f'report SHA {case}')
    manifest_path = Path(c['actual_render_metadata']['input_manifest']); manifest = read_json(manifest_path); check(sha(manifest_path) == report['manifest_sha256'], f'manifest SHA {case}')
    xdmf = Path(c['actual_render_metadata']['xdmf']); check(sha(xdmf) == report['xdmf_sha256_before'] == report['xdmf_sha256_after'], f'XDMF SHA {case}')
    check(report['frames'] == 601 and report['source_frames'] == 601 and report['all_frames_rendered'] is True and report['actual_times_preserved_exactly'] is True and report['native_identity_axis_preserved'] is True, f'render metadata {case}')
    check(report['nonfinite_active_states'] == 0 and c['actual_render_metadata']['all_frame_metadata_checks'] == {'missing_zero': True, 'finite_positions': True, 'finite_mass_velocity_density_pressure': True, 'identity_axis_preserved': True, 'expected_counts_match': True}, f'frame integrity {case}')
    check(manifest['case_id'] == case and manifest['expected_particles'] == 70179 and manifest['expected_frames'] == 601, f'manifest identity {case}')
    check(manifest['canonical_physical_binding_sha256'] == scope['actual_converter_scope_sha256'] == manifest['producer_physical_condition_sha256'], f'actual converter scope {case}')
    check(manifest['source_plan_condition_sha256'] == scope['source_plan_declared_condition_sha256'] == scope['source_declared_physical_condition_sha256'], f'declared source scope {case}')
    check(c['producer_chain_metadata']['actual_converter_scope_sha256'] == scope['actual_converter_scope_sha256'], f'producer scope {case}')
    check(c['producer_chain_metadata']['conversion_status'] == 'completed' and c['producer_chain_metadata']['conversion_frames'] == 601 and c['producer_chain_metadata']['conversion_particles'] == 70179, f'conversion {case}')
    for r in c['producer_chain_metadata']['stage_receipts']:
        rp = Path(r['path']); rd = read_json(rp); check(rd.get('status') == 'completed' and rd.get('returncode') == 0, f'receipt status {case}:{r["stage"]}'); check(sha(rp) == r['sha256'], f'receipt SHA {case}:{r["stage"]}')
    for item in v['all_601_saved_frame_pngs'] + v['all_26_contact_sheets'] + v['ten_event_keyframes']:
        p = Path(item['path']); check(p.exists() and p.suffix.lower() == '.png', f'missing PNG {p}'); check(sha(p) == item['sha256'], f'PNG SHA {p}')
for item in d['external_metadata_inputs']:
    p = Path(item['path']); check(p.exists() and p.suffix.lower() in SAFE_META_SUFFIXES, f'unsafe/missing metadata {p}'); check(sha(p) == item['sha256'], f'metadata SHA {p}')
    check(p.suffix.lower() not in {'.bi4', '.h5', '.csv', '.dat', '.vtk'}, f'science payload listed {p}')
print(json.dumps({'status': 'passed', 'package': str(PKG), 'cases': list(CASES), 'frames_per_case': 601, 'contacts_per_case': 26, 'keyframes_per_case': 10, 'science_payload_opened': False, 'scope_semantics_checked': True}, indent=2))
