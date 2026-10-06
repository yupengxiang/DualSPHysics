#!/usr/bin/env python3
"""Metadata-only validator for F5 fresh177.

This script validates the actual JSON bed reports and disabled renderer contracts.
It reads only JSON/XML/Python/Markdown metadata and hashes only those files (plus
PVPython). H5/BI4/CSV/DAT/VTK paths are existence-checked and matched to producer
attestations, never opened or hashed.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
SCIENCE_SUFFIXES = {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz','.raw','.bin'}

def load(p: str | Path):
    return json.loads(Path(p).read_text())

def sha(p: Path) -> str:
    if p.suffix.lower() in SCIENCE_SUFFIXES:
        raise AssertionError(f'validator attempted a science-payload hash: {p}')
    return hashlib.sha256(p.read_bytes()).hexdigest()

def assert_true(v, msg):
    if not v:
        raise AssertionError(msg)

def check_report(case: str, review: dict, req: dict):
    c = review['cases'][case]
    report = load(c['progress_report'])
    assert_true(c['progress_status'] == 'completed' and c['progress_returncode'] == 0, f'{case}: receipt is not completed/0')
    assert_true(report['bound_actual_inputs']['case_id'] == c['case_id'], f'{case}: nested case identity mismatch')
    frames = report['frame_reports']
    assert_true(len(frames) == 801 and [f['frame'] for f in frames] == list(range(801)), f'{case}: not all 801 frame records')
    assert_true(report['native_identity_contract']['total_particles'] == 194427, f'{case}: wrong particle axis')
    assert_true(report['native_identity_contract']['fluid_particles'] == 31658, f'{case}: wrong fluid denominator')
    assert_true(report['native_identity_contract']['native_bed_marker_mk'] == 50, f'{case}: wrong native bed marker')
    assert_true(report['native_identity_contract']['source_bed_marker_mkbound'] == 40, f'{case}: wrong source bed marker')
    for f in frames:
        assert_true(f['current_valid_type3_fluid_count'] == 31658, f'{case}: fluid count changed at frame {f["frame"]}')
        assert_true(f['uid_tracking']['missing_initial_uid']['count'] == 0, f'{case}: missing UID')
        assert_true(f['uid_tracking']['unexpected_current_uid']['count'] == 0, f'{case}: unexpected UID')
        assert_true(f['nonfinite_position_current_fluid_count'] == 0 and f['nonfinite_mass_current_fluid_count'] == 0, f'{case}: nonfinite')
        assert_true(f['bed_domain']['x_outside_exact_profile_domain_count'] == 0 and f['bed_domain']['y_outside_actual_bed_footprint_with_x_in_domain_count'] == 0, f'{case}: outside footprint')
        assert_true(f['penetration']['one_dp']['count'] == 0 and f['penetration']['two_dp']['count'] == 0, f'{case}: diagnostic penetration bin nonzero')
    assert_true(report['dynamic_bed_diagnostic']['dynamic_acceptance'].startswith('not granted'), f'{case}: acceptance was inferred')
    assert_true(req['disabled'] is True and req['source_only'] is True and req['launch'] is False and req['launch_allowed'] is False and req['execution_allowed'] is False, f'{case}: renderer is not disabled')
    assert_true(req['future_input_hashes_null'] is True, f'{case}: future inputs not null')
    assert_true(req['expected_frames'] == 801 and req['expected_particles'] == 194427 and req['expected_contact_sheets'] == 35 and len(req['keyframe_indices']) == 9, f'{case}: render shape mismatch')
    assert_true(req['renderer_worker'].endswith('root_followup_116_f3_manifest_cli_binding_repair_v1/workers/nvme_render_successor.py'), f'{case}: wrong original116 worker')
    assert_true(req['renderer'].endswith('root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py'), f'{case}: wrong original023 renderer')
    assert_true(req['command'][1].endswith('root_stage1_delegated114_bounded_failure_logs_and128_F4_priority10_independent_adoption_944/registered_render_entry_with_bounded_diagnostics.py'), f'{case}: wrong original944 entry')
    assert_true(req['physical_penetration_pass_not_inferred_from_exit0'] is True, f'{case}: missing exit-code guard')
    assert_true(req['bed_gate']['dynamic_acceptance'] == 'not_granted', f'{case}: bed gate accepted')
    for p in req['input_files']:
        path = Path(p)
        assert_true(path.is_file(), f'{case}: missing input {p}')
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            assert_true(p in req['input_sha256'] and req['input_sha256_provenance'][p]['mode'] == 'producer_attested', f'{case}: science input is not producer-attested')
        else:
            assert_true(p in req['input_sha256'], f'{case}: metadata input is not hashed')
            assert_true(req['input_sha256'][p] == sha(path), f'{case}: stale input hash {p}')

def main():
    review = load(PKG / 'metadata/actual-bed-review.json')
    m086 = load(PKG / 'requests/M086_T095-disabled-original116-023-944-render-request.json')
    m090 = load(PKG / 'requests/M090_T085-disabled-original116-023-944-render-request.json')
    check_report('M086_T095', review, m086)
    check_report('M090_T085', review, m090)
    not_submitted = review['not_submitted']['M090_T095']
    assert_true(not_submitted['actual_progress_not_submitted'] == 1 and not_submitted['bed_report_present'] is False and not_submitted['renderer_request_created'] is False, 'M090_T095 was incorrectly bound')
    manifest = load(PKG / 'metadata/manifest.json')
    listed = set(manifest['files'])
    assert_true(str(PKG / 'metadata/manifest.json') not in listed, 'manifest self-reference')
    for p, expected in manifest['sha256'].items():
        path = Path(p)
        assert_true(path.is_file(), f'manifest missing {p}')
        assert_true(sha(path) == expected, f'manifest hash mismatch {p}')
    print('fresh177 metadata validation: PASS (2 actual all801 bed reports; M090_T095 correctly WAIT/not submitted; 2 renderer requests disabled)')

if __name__ == '__main__':
    main()
