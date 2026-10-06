#!/usr/bin/env python3
"""Validate F5 fresh194 metadata and producer-rendered PNG evidence only.

This validator opens JSON/XML metadata and published PNG derivatives. It never
opens H5, BI4, CSV, DAT, VTK, solver output, or any raw science array.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path
PKG = Path(__file__).resolve().parents[1]
SCIENCE_SUFFIXES = {'.h5', '.bi4', '.csv', '.dat', '.vtk', '.vtu', '.hdf5'}
CASE = 'F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M090_T100_NEXT34'
ATTEMPT = 'root-stage1-f5-m090_t100-actual1115-bed0-full801-original116023-frozen-progress-root1137'
COUNT = {'total_particles':194427,'fixed_particles':158559,'moving_particles':4210,'fluid_particles':31658,'floating_particles':0,'solver_dimension':3,'frames':801}
CANONICAL = '5c3b16aed84e97676e21d4f8da32573abd0530e85c50db0746715488a366ee38'
LEGACY = '76a77461e54d8828c785a50c77614e6851d9d4f3a93905d57e3d8d4b58c12181'
SOURCE_DEF = '3bf7321b3abc747ee6580c3c4cea961ee5c2960539df0cba0b56adbbf8dcd696'
SOURCE_PLAN_FILE = '366adc5200604490871116a0a5b8503c9bef4bfb1e72195df94995605fa7d324'

def check(cond, msg):
    if not cond:
        raise SystemExit('FAIL: ' + msg)

def load(rel):
    return json.loads((PKG / rel).read_text())

def digest(path):
    path = Path(path)
    check(path.suffix.lower() not in SCIENCE_SUFFIXES, 'science suffix in hash target: '+str(path))
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def metadata(item, role):
    path = Path(item['path'])
    check(path.suffix.lower() not in SCIENCE_SUFFIXES, 'science suffix in '+role)
    check(path.is_file(), 'missing '+role+': '+str(path))
    check(digest(path) == item['sha256'], 'metadata hash '+role)
    return path

actual = load('metadata/actual-render-metadata.json')
bed_meta = load('metadata/bed-audit-metadata.json')
closure = load('metadata/physical-stage-closure.json')
png = load('metadata/png-visual-evidence.json')
decision = load('metadata/visual-decision.json')
up = load('metadata/upstream-evidence.json')
manifest = load('manifest.json')
for role, item in up['upstream_chain'].items():
    metadata(item, role)
for role, item in [('execution_receipt',actual['execution_receipt']),('render_report',actual['render_report']),('publish_receipt',actual['publish_receipt']),('bed_execution_receipt',bed_meta['execution_receipt']),('bed_report',bed_meta['report'])]:
    metadata(item, role)
receipt = json.loads(Path(actual['execution_receipt']['path']).read_text())
report = json.loads(Path(actual['render_report']['path']).read_text())
publish = json.loads(Path(actual['publish_receipt']['path']).read_text())
bed = json.loads(Path(bed_meta['report']['path']).read_text())
check(actual['case_id'] == CASE and actual['attempt_id'] == ATTEMPT, 'case/render identity')
check(receipt.get('status') == 'completed' and receipt.get('returncode') == 0, 'terminal render receipt')
check(Path(receipt.get('output_root','')).name == ATTEMPT, 'receipt output root identity')
check(report.get('schema') == 'ds02.stage1.paraview-full-animation-integrity.v1', 'render report schema')
check(report.get('frames') == 801 and report.get('source_frames') == 801 and report.get('all_frames_rendered') is True, 'full render metadata')
check(report.get('actual_times_preserved_exactly') is True and report.get('native_identity_axis_preserved') is True, 'time/identity metadata')
check(report.get('nonfinite_active_states') == 0, 'render nonfinite metadata')
check(report.get('numerical_precision_status') == 'not accepted', 'precision status retained')
check(publish.get('status') == 'published_after_atomic_rename', 'publish status')
check(publish.get('attempt_id') == ATTEMPT and publish.get('case_id') == CASE, 'publish identity')
check(publish.get('report_sha256_after_rebind') == actual['render_report']['sha256'], 'publish report binding')
check(publish.get('renderer_delegated_to_root023') is True, 'renderer provenance')
check(actual['render_integrity']['counts'] == COUNT and closure['counts'] == COUNT, 'actual count closure')
check(actual['source_agent_science_payload_io']['raw_h5_bi4_csv_dat_vtk_read'] is False and actual['source_agent_science_payload_io']['raw_h5_bi4_csv_dat_vtk_hash'] is False, 'source payload boundary')
check(up['scope_roles']['canonical_native_source_plan_sha256'] == CANONICAL, 'canonical scope')
check(up['scope_roles']['typed_legacy_h5_scope_sha256'] == LEGACY, 'legacy scope')
check(up['scope_roles']['source_definition_bed_declared_plan_sha256'] == SOURCE_DEF, 'source definition scope')
check(up['scope_roles']['source_plan_file_sha256'] == SOURCE_PLAN_FILE, 'source plan file scope')
check(up['scope_roles']['roles_remain_distinct'] is True and up['scope_roles']['cross_resolution_claim'] is False, 'scope separation')
check(png['contact_sheet_count'] == 34 and len(png['contact_sheets']) == 34 and png['all_actual_contact_sheets_reviewed'] is True, '34 contact sheets')
check(png['keyframe_indices'] == [0,100,200,300,400,500,600,700,800] and len(png['keyframes']) == 9 and png['all_nine_keyframes_reviewed'] is True, '9 keyframes')
producer = {x['relative_path']: x for x in publish['files_excluding_receipt']}
for item in png['contact_sheets'] + png['keyframes']:
    path = Path(item['path'])
    check(path.suffix.lower() == '.png', 'visual evidence must be PNG')
    check(path.is_file(), 'missing PNG '+str(path))
    check(path.stat().st_size == item['bytes'], 'PNG size changed '+str(path))
    check(digest(path) == item['sha256'], 'PNG hash changed '+str(path))
    check(item['relative_path'] in producer, 'PNG absent from producer receipt '+item['relative_path'])
    check(producer[item['relative_path']]['sha256'] == item['producer_receipt_sha256'], 'producer PNG hash '+item['relative_path'])
    check(producer[item['relative_path']]['bytes'] == item['bytes'], 'producer PNG bytes '+item['relative_path'])
frames = bed.get('frame_reports', [])
check(len(frames) == 801, 'bed report 801 frames')
for expected, f in enumerate(frames):
    check(f.get('frame') == expected, 'bed frame sequence')
    check(f['current_valid_type3_fluid_count'] == 31658, 'bed fluid denominator')
    check(f['particle_axis_count'] == 194427, 'bed particle axis')
    check(f['nonfinite_position_current_fluid_count'] == 0 and f['nonfinite_mass_current_fluid_count'] == 0, 'bed finite rows')
    check(f['uid_tracking']['missing_initial_uid']['count'] == 0 and f['uid_tracking']['unexpected_current_uid']['count'] == 0, 'bed UID tracking')
    check(f['bed_domain']['x_outside_exact_profile_domain_count'] == 0 and f['bed_domain']['y_outside_actual_bed_footprint_with_x_in_domain_count'] == 0, 'bed footprint')
    check(f['penetration']['one_dp']['count'] == 0 and f['penetration']['two_dp']['count'] == 0, 'diagnostic depth bins')
check(bed_meta['report_flags']['diagnostic_only'] is True and bed_meta['report_flags']['full16_authorized_in_report'] is False, 'bed diagnostic limits')
check(closure['dynamic_bed_summary']['sub_dp_depth_inferred'] is False and closure['dynamic_bed_summary']['precision_acceptance_not_inferred'] is True, 'bed/precision limits')
check(decision['decision']['standalone_first_stage_visual_approved'] is True, 'visual decision')
check(decision['decision']['strict_container_guarantee'] is False and decision['decision']['numerical_precision_accepted'] is False, 'visual limits')
check(decision['decision']['independent_case_count_increment'] == 0 and decision['decision']['root_global_credit_written'] is False, 'credit gate')
required = ['README.md','metadata/actual-render-metadata.json','metadata/bed-audit-metadata.json','metadata/physical-stage-closure.json','metadata/png-visual-evidence.json','metadata/upstream-evidence.json','metadata/visual-decision.json','scripts/validate_fresh194.py']
listed = {x['path']: x for x in manifest['files']}
for rel in required:
    path = PKG / rel
    check(path.is_file(), 'package file '+rel)
    check(rel in listed, 'manifest entry '+rel)
    check(path.stat().st_size == listed[rel]['bytes'], 'manifest bytes '+rel)
    check(digest(path) == listed[rel]['sha256'], 'manifest hash '+rel)
check(manifest['manifest_excludes_self'] is True and manifest['source_only'] is True and manifest['science_payloads_copied'] is False, 'manifest guards')
print('PASS fresh194: M090_T100 Root1137 34 contacts + 9 keyframes; metadata/PNG only')
print('Standalone first-stage visual approval; precision/sub-DP/strict-container/Q-N/case credit remain false')
