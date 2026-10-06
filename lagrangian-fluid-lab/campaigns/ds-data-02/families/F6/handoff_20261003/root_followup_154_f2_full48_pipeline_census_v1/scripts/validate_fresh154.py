#!/usr/bin/env python3
"""Validate the frozen fresh154 metadata census without touching external data."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CENSUS = ROOT / 'metadata' / 'f2-first48-census.json'


def fail(message):
    raise AssertionError(message)


def main():
    data = json.loads(CENSUS.read_text(encoding='utf-8'))
    checks = []
    if data.get('schema') != 'ds02.f6.fresh154.f2-full48-pipeline-census.v1':
        fail('wrong census schema')
    checks.append('schema')
    cases = data.get('cases')
    if not isinstance(cases, list) or len(cases) != 24:
        fail('first48 must contain exactly 24 cases')
    case_ids = [c.get('case_id') for c in cases]
    physical_ids = [c.get('physical_case_id') for c in cases]
    if len(set(case_ids)) != 24 or len(set(physical_ids)) != 24:
        fail('case or physical IDs are duplicated')
    checks.append('unique_24')
    accepted = [c for c in cases if c.get('accepted_at_checkpoint')]
    unaccepted = [c for c in cases if not c.get('accepted_at_checkpoint')]
    if len(accepted) != data.get('first48_accepted_count') or len(unaccepted) != data.get('first48_unaccepted_count'):
        fail('accepted/unaccepted counts disagree with case rows')
    if len(unaccepted) != 19:
        fail('fresh154 expected 19 unaccepted first48 cases at the frozen checkpoint')
    checks.append('dedup_against_checkpoint')

    # Every selected gap is a real unaccepted case and satisfies its declared
    # stage predicate. Live registrations are never treated as gaps.
    selected = data.get('selected_gaps', [])
    if len(selected) > 5:
        fail('more than five selected gaps')
    by_physical = {c['physical_case_id']: c for c in cases}
    for gap in selected:
        c = by_physical.get(gap.get('physical_case_id'))
        if c is None or c.get('accepted_at_checkpoint'):
            fail('selected gap is absent or already accepted')
        st = c['stages']
        kind = gap.get('gap_kind')
        if kind == 'typed157_completed_without_xmf_registration':
            if st['typed']['status'] != 'completed0' or st['xmf']['status'] != 'missing':
                fail('typed-complete/XMF-missing predicate failed')
        elif kind == 'typed157_missing_before_xmf':
            if st['typed']['status'] != 'missing' or st['xmf']['status'] != 'missing':
                fail('typed-missing/XMF-missing predicate failed')
        elif kind == 'xmf_completed_without_render_registration':
            if st['xmf']['status'] != 'completed0' or st['render']['status'] != 'missing':
                fail('XMF-complete/render-missing predicate failed')
        else:
            fail('unknown gap kind: ' + repr(kind))
    checks.append('selected_gap_predicates')

    # Snapshot stage counts must cover every row and only use known states.
    for stage, counts in data.get('stage_counts', {}).items():
        if sum(counts.values()) != 24:
            fail(f'{stage} stage counts do not cover 24 cases')
        if any(state not in {'completed0', 'missing', 'live', 'registered_live', 'registered_no_terminal', 'failed', 'unknown'} for state in counts):
            fail(f'{stage} has unknown state')
    checks.append('stage_counts')

    policy = data.get('policy', {})
    if policy.get('scientific_payloads_read_or_hashed') is not False:
        fail('scientific payload policy is not false')
    if policy.get('jobs_started') is not False or policy.get('shared_state_modified') is not False:
        fail('fresh154 claims a job/shared mutation')
    if policy.get('new_case_credit') != 0:
        fail('fresh154 claims case credit')
    checks.append('source_only_policy')

    # These are the five registrations explicitly supplied by the parent task.
    recent = data.get('source_inputs', {}).get('recent_root_registrations', {})
    if set(recent) != {'1116', '1117', '1118', '1119', '1120'}:
        fail('recent Root registration set is incomplete')
    checks.append('recent_registration_inventory')

    # Frozen census paths must not point at prohibited scientific payload files.
    bad = []
    forbidden = ('.bi4', '.h5', '.csv', '.dat', '.vtk')
    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str):
            low = value.lower()
            if any(low.endswith(ext) for ext in forbidden):
                bad.append(value)
    walk(data.get('cases'))
    walk(data.get('selected_gaps'))
    if bad:
        fail('scientific payload path recorded in census: ' + bad[0])
    checks.append('no_science_payload_paths')

    print(json.dumps({'status': 'PASS', 'schema': data['schema'], 'checks': checks,
                      'selected_gap_count': len(selected), 'first48_unaccepted_count': len(unaccepted)},
                     indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, json.JSONDecodeError) as exc:
        print('fresh154 validation FAILED:', exc, file=sys.stderr)
        raise SystemExit(1)
