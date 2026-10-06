#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
CASE = 'F7_OBSTACLE_QUINTIC_B08_A059P5'
FORBIDDEN_SUFFIXES = {'.bi4', '.h5', '.csv', '.vtk', '.dat'}

def load(rel):
    with (PKG / rel).open(encoding='utf-8') as f:
        return json.load(f)

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def check(cond, msg):
    if not cond:
        raise AssertionError(msg)

idx = load('metadata/review-index.json')
closure = load('metadata/case-visual-closure.json')
png = load('metadata/png-review-evidence.json')
sel = load('metadata/selection-snapshot.json')
protocol = load('metadata/visual-review-protocol.json')
check(idx['case_id'] == CASE and closure['case_id'] == CASE and png['case_id'] == CASE, 'case mismatch')
check(idx['decision'] == 'visual-approved-by-delegated-agent', 'decision mismatch')
check(closure['decision'] == idx['decision'], 'closure decision mismatch')
check(idx['global_credit_updated'] is False and closure['global_credit_updated'] is False, 'global credit changed')
check(closure['reviewer_personally_viewed_images'] is True and closure['root_personal_inspection_claim'] is False, 'reviewer attribution')
check(png['all_listed_images_viewed'] is True and png['contact_sheet_count'] == 26 and png['key_frame_count'] == 10, 'image counts')
check(protocol['required_views']['key_indices'] == [0,60,120,180,240,300,360,420,480,600], 'key frame indices')

# Metadata source records must be present and remain metadata/XML/PNG only.
for item in idx['source_files']:
    p = Path(item['path'])
    check(p.exists(), f'missing source file: {p}')
    check(p.suffix.lower() not in FORBIDDEN_SUFFIXES, f'forbidden source record: {p}')
    check(item['sha256'] == sha256(p), f'source digest changed: {p}')
    check(item['bytes'] == p.stat().st_size, f'source size changed: {p}')

# Actual receipts all terminal completed/0.
for r in idx['receipt_chain']:
    check(r['status'] == 'completed' and r['returncode'] == 0, f"receipt not completed/0: {r['role']}")
    p = Path(r['path'])
    check(p.exists() and sha256(p) == r['file_sha256'], f"receipt digest mismatch: {r['role']}")

c = idx['counts']
check(c == {'total': 70179, 'fixed': 27495, 'moving': 1984, 'floating': 0, 'fluid': 40700, 'dimension': 3}, 'count contract')
check(idx['full_window'] == {'frames': 601, 't_start_s': 0.0, 'nominal_t_end_s': 12.0, 'nominal_save_interval_s': 0.02, 'actual_times_preserved': True}, 'window contract')
check(idx['mass_semantics']['native_support_mass_kg'] == 325.60001628 and idx['mass_semantics']['continuum_physical_mass_kg'] == 320.1984, 'mass semantics')
check(idx['mass_semantics']['normalization_or_rescale'] is False, 'mass rescale')

scope = idx['scope']
check(scope['actual_converter']['physical_condition_sha256'] == 'a284f523a23efb3ecd309611364a2cf01b9dbe8df6420b862f4b56ca411fd2b5', 'actual scope')
check(scope['actual_converter']['producer_physical_condition_sha256'] == scope['actual_converter']['physical_condition_sha256'], 'producer scope')
check(scope['source_declared']['source_plan_condition_sha256'] == '5333dfc312df5ec01035080f013c33810d0836a5e705d3bf76a840c8edb7ad33', 'source scope')
check(scope['original_canonical_binding']['sha256'] == '6f1d487a6df36a1362a6fa9cc218c116ce61b6e191c41fa69a004fce651bdad2', 'historical scope')
check(scope['scopes_must_not_be_equated'] is True, 'scope separation')

# Root frontier/deduplication evidence is metadata-only and A059 is not counted.
check(sel['frontier_metadata']['root792_case_already_accepted'] is False, 'Root792 acceptance')
check(sel['frontier_metadata']['root792_independent_case_increment'] == 0, 'Root792 increment')
check(sel['root902_dedup_metadata']['decision_case_ids'] == ['F7_OBSTACLE_QUINTIC_B08_A043', 'F7_OBSTACLE_QUINTIC_B08_A044'], 'Root902 decisions')
check(sel['root902_dedup_metadata']['does_not_include_selected_case'] is True, 'Root902 duplicate')

safe = closure['safe_metadata']
check(safe['typed_and_xmf_n3'] is True and safe['typed_partvtk_all_passed'] is True, 'typed/XMF metadata')
summary = closure['report_summaries']
check(summary['gencase']['generated_xml_counts'] == c, 'GenCase counts')
check(summary['initial_native_qa']['all_cases_passed'] is True and summary['initial_native_qa']['case_passed'] is True, 'initial QA')
for k in ['actual_3d','all_13_fields_finite','all_native_densities_positive','all_native_weights_positive','fluid_count_exact','global_coordinate_unique','initial_velocity_zero_within_tolerance','no_initial_overlap','row_shape_exact','uid_exact_sorted_unique','xml_contract']:
    check(summary['initial_native_qa']['checks'][k] is True, f'QA check {k}')
check(summary['initial_native_qa']['checks']['floating_node_present'] is False, 'floating node')
check(summary['initial_native_qa']['checks']['native_type_mk_blocks'] == {
    'fixed': {'count': 27495, 'mk': 10, 'type': 0, 'uid_range_exact': True},
    'moving': {'count': 1984, 'mk': 12, 'type': 1, 'uid_range_exact': True},
    'fluid': {'count': 40700, 'mk': 2, 'type': 3, 'uid_range_exact': True},
}, 'type/Mk blocks')
check(summary['typed']['frames'] == 601 and summary['typed']['particles'] == 70179 and summary['typed']['solver_dimension'] == 3, 'typed dimensions')
check(summary['typed']['partvtk_all_passed'] is True and summary['typed']['time_strictly_increasing'] is True, 'typed metadata')
check(summary['xmf']['frames'] == 601 and summary['xmf']['particles'] == 70179, 'XMF dimensions')
check(summary['xmf']['shape_contract']['scalar_dimensions'] == '70179' and summary['xmf']['shape_contract']['vector_dimensions'] == '70179 3', 'XMF N3 shape')
check(summary['xmf']['shape_contract']['particle_axis_preserved'] is True, 'XMF particle axis')
check(summary['xmf']['canonical_equals_source_plan_claim'] is False, 'XMF scope claim')
rs = summary['render']
check(rs['frames'] == 601 and rs['source_frames'] == 601 and rs['all_frames_rendered'] is True, 'render frame contract')
check(rs['actual_times_preserved_exactly'] is True and rs['native_identity_axis_preserved'] is True, 'render time/identity')
check(rs['nonfinite_active_states'] == 0 and rs['diagnostic_only'] is False, 'render finite/diagnostic')
check(rs['frame_diagnostics_summary']['diagnostic_rows'] == 601, 'diagnostic row count')
check(rs['frame_diagnostics_summary']['maximum_missing_particles_per_frame'] == 0, 'missing particles')
check(rs['frame_diagnostics_summary']['frames_with_missing_particles'] == 0, 'missing frames')
check(rs['frame_diagnostics_summary']['all_finite_positions_and_fields'] is True, 'finite fields')
check(rs['frame_diagnostics_summary']['all_unknown_type_counts_zero'] is True, 'unknown types')
check(rs['camera']['display_only_cutaway'] is True and rs['camera']['bounds_source'] == 'native valid positions scanned through XdmfReader', 'camera provenance')

# Every viewed PNG path and digest is current; PNGs are the only binary visual artifacts retained.
for item in png['contact_sheets'] + png['key_frames']:
    p = Path(item['path'])
    check(p.exists() and p.suffix.lower() == '.png', f'missing PNG: {p}')
    check(item['viewed_with_view_image'] is True, f'not viewed: {p}')
    check(item['sha256'] == sha256(p), f'PNG digest changed: {p}')
    check(item['bytes'] == p.stat().st_size, f'PNG size changed: {p}')
check(len(png['contact_sheets']) == 26 and len(png['key_frames']) == 10, 'PNG manifest lengths')

# No forbidden payload suffix appears as a metadata source path in the package records.
for rel in ['metadata/review-index.json','metadata/case-visual-closure.json','metadata/png-review-evidence.json','metadata/selection-snapshot.json','metadata/visual-review-protocol.json']:
    text = (PKG / rel).read_text(encoding='utf-8')
    # The package explicitly records the policy, but never records a scientific payload path.
    for item in idx['source_files']:
        if Path(item['path']).suffix.lower() in FORBIDDEN_SUFFIXES:
            raise AssertionError(f'forbidden source item leaked: {item["path"]}')

print('fresh124 metadata validation: PASS')
print('case:', CASE)
print('decision:', idx['decision'])
print('viewed PNGs:', len(png['contact_sheets']), 'contact +', len(png['key_frames']), 'keys')
print('receipts completed/0:', len(idx['receipt_chain']))
print('scope actual/source/historical:', scope['actual_converter']['physical_condition_sha256'], scope['source_declared']['source_plan_condition_sha256'], scope['original_canonical_binding']['sha256'])
