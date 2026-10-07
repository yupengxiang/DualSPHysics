#!/usr/bin/env python3
"""Validate the fresh166 metadata snapshot without touching scientific payloads."""
from __future__ import annotations
import json
from pathlib import Path
import sys

FORBIDDEN = ('.h5', '.bi4', '.csv', '.dat', '.vtk', '.vtp', '.vtu', '.pvtu', '.raw')
EXPECTED = {
    'F3_STAGE1_DP006_P0800_AY0360',
    'F3_STAGE1_DP006_P0800_AY0500',
    'F3_STAGE1_DP006_P0800_AY0570',
    'F3_STAGE1_DP006_P1200_AY0390',
    'F3_STAGE1_DP006_P1200_AY0430',
    'F3_STAGE1_DP006_P1200_AY0540',
    'F3_STAGE1_DP006_P1200_AY0570',
    'F3_STAGE1_DP006_P1200_AY0640',
    'F3_STAGE1_DP006_P1000_AY0270',
}


def fail(msg):
    raise AssertionError(msg)


def walk_strings(value, path=''):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk_strings(v, f'{path}/{k}')
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk_strings(v, f'{path}/{i}')
    elif isinstance(value, str):
        yield path, value


def main():
    here = Path(__file__).resolve().parents[1]
    snap_path = here / 'metadata' / 'f3-remaining9-pipeline-census.json'
    d = json.loads(snap_path.read_text())
    if d.get('schema') != 'ds02.f3.fresh166.remaining9.pipeline-census.v1':
        fail('wrong schema')
    scope = d.get('scope', {})
    for k in ('source_only', 'scientific_payload_read', 'scientific_payload_hashed', 'scientific_jobs_started', 'shared_state_modified', 'visual_credit_granted'):
        if scope.get(k) is not (True if k == 'source_only' else False):
            fail(f'scope guard {k}={scope.get(k)!r}')
    cases = d.get('cases', [])
    ids = {c.get('case_id') for c in cases}
    if ids != EXPECTED or len(cases) != 9:
        fail(f'case set mismatch: {sorted(ids)}')
    for c in cases:
        if c.get('family_id') != 'F3' or c.get('case_credit') != 0:
            fail(f'identity/credit guard failed: {c.get("case_id")}')
        n = c['native']; t = c['typed']; x = c['xmf']; r = c['render']; ps = c['pipeline_status']
        if not ps['native_completed0'] or n.get('expected_saved_frames') != 836:
            fail(f'native gate failed: {c["case_id"]}')
        if n.get('particles_expected') != 179208 or n.get('dimension_expected') != 3:
            fail(f'native shape gate failed: {c["case_id"]}')
        if c['case_id'].endswith('AY0270'):
            if ps['typed_completed0']:
                fail('AY0270 original unknown receipt must not be typed completed0')
            if not ps['artifact_audit_completed0_for_ay0270']:
                fail('AY0270 audit gate missing')
            if t.get('original_conversion_receipt', {}).get('returncode_field_present'):
                fail('AY0270 old receipt returncode was fabricated')
        else:
            if not ps['typed_completed0'] or t.get('typed_receipt_returncode') != 0:
                fail(f'typed gate failed: {c["case_id"]}')
        if not ps['xmf_completed0'] or x.get('frames') != 836 or x.get('particles') != 179208 or x.get('dimension') != 3:
            fail(f'XMF gate failed: {c["case_id"]}')
        tm = x['time_and_vector_metadata']
        if tm.get('actual_time_vector_count') != 836 or tm.get('time_shape') != [836] or tm.get('position_shape') != [836, 179208, 3] or tm.get('velocity_shape') != [836, 179208, 3] or not tm.get('actual_time_strictly_increasing'):
            fail(f'time/N3 gate failed: {c["case_id"]}')
        life = t['lifecycle']
        if life.get('transient_missing_frame_count') != 0 or life.get('missing_mk_event_count') != 0 or life.get('missing_type_event_count') != 0 or life.get('first_missing_frame_by_mk') != {} or life.get('first_missing_frame_by_type') != {}:
            fail(f'lifecycle gate failed: {c["case_id"]}')
        if not isinstance(x['scope_roles'].get('manifest_source_plan_condition_sha256_key_present'), bool) or not isinstance(x['scope_roles'].get('xmf_binding_source_plan_key_present'), bool):
            fail(f'null-vs-absent role gate failed: {c["case_id"]}')
        # An outer 801 envelope is allowed only when the loaded wrapper proves actual 836.
        if r['outer_envelope_is_stale_vs_loaded_wrapper']:
            if r['loaded_wrapper'].get('expected_frames') != 836 or r['loaded_wrapper'].get('expected_particles') != 179208:
                fail(f'outer/wrapper mismatch not bounded: {c["case_id"]}')
        if r['loaded_wrapper'].get('expected_frames') != 836 or r['loaded_wrapper'].get('expected_particles') != 179208:
            fail(f'loaded wrapper gate failed: {c["case_id"]}')
        proc = r['fresh_proc_observation']
        if not proc.get('exists') or not proc.get('same_start_ticks'):
            fail(f'render live observation not closed: {c["case_id"]}')
        if r.get('visual_ready_at_observation'):
            fail(f'visual credit accidentally asserted: {c["case_id"]}')
        # Every recorded metadata closure must be stable; the package records no science-file hashes.
        if not n.get('metadata_input_hash_closure_all_stable'):
            fail(f'native metadata input closure failed: {c["case_id"]}')
    for p, s in walk_strings(d):
        if any(s.lower().endswith(suf) for suf in FORBIDDEN):
            fail(f'forbidden payload path recorded at {p}: {s}')
    print('fresh166 validation PASS: 9 F3 upstream chains closed; 9 render handles live/pending; no payload IO.')


if __name__ == '__main__':
    try:
        main()
    except AssertionError as e:
        print(f'fresh166 validation FAIL: {e}', file=sys.stderr)
        raise SystemExit(1)
