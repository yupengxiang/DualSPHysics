#!/usr/bin/env python3
from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ('.h5', '.hdf5', '.bi4', '.csv', '.dat', '.vtk', '.vtu', '.npy', '.npz')
HEX64 = re.compile(r'^[0-9a-f]{64}$')

def load(name):
    return json.loads((ROOT/'metadata'/name).read_text())

def walk_strings(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from walk_strings(k)
            yield from walk_strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk_strings(v)
    elif isinstance(x, str):
        yield x

m = load('f2-first8-first24-final48-membership.json')
n = load('f2-native-request-role-separation.json')
c = load('frozen-checkpoint186-f2-summary.json')
r = load('f2-render-candidate-census.json')
assert m['schema'].endswith('membership.v1')
assert m['family_id'] == 'F2'
assert m['selection_policy']['not_sorted_or_inferred'] is True
assert m['selection_policy']['no_resolution_replica_counting'] is True
assert m['selection_policy']['no_retry_alias_counting'] is True
assert m['subset_proof'] == {
    'first8_count': 8,
    'first24_count': 24,
    'final48_count': 48,
    'first8_subset_first24': True,
    'first24_subset_final48': True,
    'final48_equals_root1205_f2_roster': True,
    'new_case_credit': 0,
}
g = m['groups']
for name, expected in [('first8', 8), ('first24', 24), ('final48', 48)]:
    rows = g[name]
    assert len(rows) == expected, (name, len(rows))
    assert len({x['case_id'] for x in rows}) == expected
    assert len({x['physical_case_id'] for x in rows}) == expected
    for x in rows:
        assert x['scope_roles_are_not_equated']['equality_claim'] is False
        assert 'accepted_semantic_snapshot' in x
        assert 'native_request_actual_snapshot' in x
        assert x['native_request_actual_snapshot'].keys() >= {'sha256', 'role', 'candidate_receipt_count', 'resolved_in_full336_index'}
ids8 = {x['physical_case_id'] for x in g['first8']}
ids24 = {x['physical_case_id'] for x in g['first24']}
ids48 = {x['physical_case_id'] for x in g['final48']}
assert ids8 <= ids24 <= ids48
assert len(ids48 - ids24) == 24
assert len(ids24 - ids8) == 16
assert m['declared_stage_contracts']['first8']['prospective_total'] == 8
assert m['declared_stage_contracts']['first24']['prospective_total'] == 24
assert m['declared_stage_contracts']['final48']['generated_source_conditions'] == 24
assert m['declared_stage_contracts']['final48']['existing_24_conditions_preserved'] is True
assert m['declared_stage_contracts']['final48']['actual_physical_cases_completed'] == 0
assert m['declared_stage_contracts']['final48']['new_conditions_not_qualified_or_visual_accepted'] is True
assert c['checkpoint'] == 186
assert c['f2_accepted_case_count_from_declared_roster'] == 32
assert len(c['f2_accepted_cases']) == 32
assert n['native_request_scope_is_not_accepted_decision_scope'] is True
assert n['native_request_scope_is_not_source_declared_scope'] is True
assert len(n['rows']) == 48
assert r['new_unaccepted_completed_published_after_fresh164_count'] == 0
assert r['completed_and_published_unaccepted_count'] == 1
assert r['personal_visual_review_priority']['new_case_found'] is False
for s in walk_strings({'m':m, 'n':n, 'c':c, 'r':r}):
    assert not any(s.lower().endswith(ext) or ext+'/' in s.lower() for ext in FORBIDDEN), s
print('fresh165 validator PASS: explicit F2 first8/first24/final48 sets are 8/24/48 with strict subsets; checkpoint186 F2 accepted=32; native-request, accepted, and source scopes remain separate; no new unreviewed completed/published render; no forbidden scientific payload references')
