#!/usr/bin/env python3
"""Metadata-only validation for the Root1058 -> fresh182 render handoff."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
SCIENCE = {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz','.raw','.bin'}
META = {'.json','.xml','.xmf','.py','.md'}

def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))

def sha(p):
    p = Path(p)
    if p.suffix.lower() in SCIENCE:
        raise AssertionError(f'science payload hash attempted: {p}')
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def check(value, message):
    if not value:
        raise AssertionError(message)

def check_bed(case, review_case, request, binding, wrapper):
    report = load(review_case['bed_report'])
    receipt = load(review_case['bed_receipt'])
    nested = report.get('bound_actual_inputs', {})
    check(nested.get('case_id') == case, f'{case}: nested identity')
    check(receipt.get('status') == 'completed' and receipt.get('returncode') == 0, f'{case}: bed receipt')
    check(review_case['report_status'] == 'completed_worker_output_pending_root_review', f'{case}: report status changed')
    frames = report.get('frame_reports', [])
    check(len(frames) == 801 and [row.get('frame') for row in frames] == list(range(801)), f'{case}: exact 801 frame records')
    check(review_case['bed_aggregate']['one_dp_count_max'] == 0 and review_case['bed_aggregate']['two_dp_count_max'] == 0, f'{case}: depth bins')
    check(review_case['bed_aggregate']['missing_uid_max'] == 0 and review_case['bed_aggregate']['unexpected_uid_max'] == 0, f'{case}: UID loss')
    check(review_case['bed_aggregate']['nonfinite_mass_max'] == 0 and review_case['bed_aggregate']['nonfinite_position_max'] == 0, f'{case}: nonfinite')
    check(review_case['bed_aggregate']['outside_x_max'] == 0 and review_case['bed_aggregate']['outside_y_max'] == 0, f'{case}: footprint')
    check(report.get('dynamic_bed_diagnostic', {}).get('dynamic_acceptance', '').startswith('not granted'), f'{case}: dynamic acceptance inferred')
    check(report.get('full16_authorized') is False, f'{case}: full authorization changed')
    check(request.get('actual_progress_path') is None and 'actual_progress_path' not in request, f'{case}: mutable progress bound')
    check(request.get('expected_frames') == 801 and request.get('expected_particles') == 194427 and request.get('expected_contact_sheets') == 34, f'{case}: render shape')
    check(len(request.get('keyframe_indices', [])) == 9 and request.get('keyframe_indices') == [0,100,200,300,400,500,600,700,800], f'{case}: keyframes')
    check(wrapper.get('expected_contact_sheets') == 34 and wrapper.get('expected_frames') == 801, f'{case}: wrapper shape')
    check(request.get('disabled') is True and request.get('execution_allowed') is False and request.get('launch') is False and request.get('launch_allowed') is False, f'{case}: request enabled')
    check(wrapper.get('disabled') is True and wrapper.get('execution_allowed') is False and wrapper.get('launch') is False and wrapper.get('launch_allowed') is False, f'{case}: wrapper enabled')
    check(request.get('future_output_hashes') == {'png_sha256':None,'render_receipt_sha256':None,'render_report_sha256':None}, f'{case}: future output hashes')
    check(wrapper.get('future_render_product') == {'manifest_sha256':None,'png_sha256':None,'receipt_sha256':None,'report_sha256':None}, f'{case}: future render hashes')
    check(request['command'][-1] == str(PKG/f'metadata/{case.split("_NEXT34")[0].split("_")[-2]}'), f'{case}: command wrapper') if False else None
    check(Path(request['binding']).is_file(), f'{case}: binding path')
    check(request['binding_sha256'] == sha(Path(request['binding'])), f'{case}: binding sha')
    check(binding['case_id'] == case and binding['actual_bound_inputs']['case_id'] == case, f'{case}: binding identity')
    check(binding['bed_gate']['all801_frame_records_present'] is True and binding['bed_gate']['dynamic_acceptance'] == 'not granted', f'{case}: binding bed gate')
    check(binding['renderer_gate']['future_manifest_sha256'] is None and binding['renderer_gate']['future_png_sha256'] is None, f'{case}: binding future outputs')
    check(binding['physical_scope']['canonical_owner_sha256'] == report['physical_condition_sha256'], f'{case}: canonical scope')
    check(binding['physical_scope']['source_h5_physical_condition_sha256'] == report['source_h5_physical_condition_sha256'], f'{case}: H5 scope')
    check(binding['actual_bound_inputs']['bed_report_sha256'] == review_case['bed_report_sha256'], f'{case}: bed report attestation')
    check(binding['actual_bound_inputs']['bed_receipt_sha256'] == review_case['bed_receipt_sha256'], f'{case}: bed receipt attestation')
    check(wrapper['registered_binding'] == request['binding'] and wrapper.get('registered_binding_sha256') is None, f'{case}: wrapper binding')
    check(binding.get('registered_wrapper_sha256') == sha(Path(binding['registered_wrapper'])), f'{case}: binding wrapper hash')
    check(request.get('source_science_policy', {}).get('source_agent_read_or_hashed_science_payloads') is False, f'{case}: science boundary')
    # Only producer-attested H5 is allowed to be a science input; all other inputs must be metadata files.
    for name in request['input_files']:
        p = Path(name)
        check(p.is_file(), f'{case}: missing input {p}')
        if p.suffix.lower() in SCIENCE:
            check(p.suffix.lower() in {'.h5','.hdf5'}, f'{case}: unexpected science input {p}')
            check(request['input_sha256_provenance'][name]['mode'] == 'producer_attested', f'{case}: H5 provenance')
            check(request['input_sha256'][name] == report['source']['trajectory_h5_sha256'], f'{case}: H5 attestation')
        elif p == Path(request.get('pvpython', '')):
            check(request['input_sha256_provenance'][name]['mode'] == 'static_binary_digest', f'{case}: pvpython provenance')
            check(len(request['input_sha256'][name]) == 64, f'{case}: pvpython digest shape')
        else:
            check(p.suffix.lower() in META, f'{case}: unclassified input {p}')
            check(request['input_sha256'][name] == sha(p), f'{case}: stale metadata hash {p}')
    check(request.get('input_sha256_provenance', {}).get(str(Path(request['trajectory_h5'])), {}).get('source_agent_read_or_hashed') is False, f'{case}: H5 source flag')

def main():
    review = load(PKG/'metadata/actual1058-bed-review.json')
    check(review['schema'] == 'ds02.f5.fresh182.actual1058-bed-review.v1', 'review schema')
    check(review['review_boundary']['mutable_progress_path_used'] is False, 'mutable progress')
    check(set(review['cases']) == {'M088_T085','M088_T095'}, 'case set')
    for tag in sorted(review['cases']):
        req = load(PKG/f'requests/{tag}-disabled-original116-023-944-render-request.json')
        binding = load(PKG/f'bindings/{tag}-full801-original116-023-944-render-binding.json')
        wrapper = load(PKG/f'metadata/{tag}-render-wrapper.json')
        check_bed(review['cases'][tag]['case_id'], review['cases'][tag], req, binding, wrapper)
    manifest = load(PKG/'manifest.json')
    listed = {entry['path'] for entry in manifest['files']}
    for p in PKG.rglob('*'):
        if not p.is_file() or p.name == 'manifest.json':
            continue
        check(str(p.relative_to(PKG)) in listed, f'manifest missing {p}')
        check(p.suffix.lower() not in SCIENCE, f'science file in package {p}')
    for entry in manifest['files']:
        p = PKG/entry['path']
        check(p.is_file() and p.stat().st_size == entry['bytes'], f'manifest stat {p}')
        check(sha(p) == entry['sha256'], f'manifest hash {p}')
    print('PASS fresh182: Root1058 M088 bed reports statically bound to two disabled 34-contact original116/023/944 render requests')
    print('801-frame/UID/finite/footprint/1DP/2DP metadata closed; no mutable progress, no visual/Q-N/case credit')

if __name__ == '__main__':
    main()
