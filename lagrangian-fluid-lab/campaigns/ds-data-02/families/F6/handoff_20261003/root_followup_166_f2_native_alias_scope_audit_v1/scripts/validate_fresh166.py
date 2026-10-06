#!/usr/bin/env python3
from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ('.h5', '.hdf5', '.bi4', '.csv', '.dat', '.vtk', '.vtu', '.npy', '.npz')

def load(name):
    return json.loads((ROOT / 'metadata' / name).read_text())

def walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from walk(k)
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)
    elif isinstance(x, str):
        yield x

m = load('f2-root1205-unresolved-native-alias-audit.json')
c = load('f2-render-candidate-census.json')
s = load('frozen-root1205-f2-summary.json')
assert m['family_id'] == 'F2'
assert len(m['unresolved_rows']) == 13
assert len({x['physical_case_id'] for x in m['unresolved_rows']}) == 13
assert len({x['case_id'] for x in m['unresolved_rows']}) == 13
for row in m['unresolved_rows']:
    assert row['alias_closure']['physical_case_id_is_authoritative_identity'] is True
    assert row['alias_closure']['case_id_is_not_promoted_to_physical_identity'] is True
    assert row['accepted_semantic_scope']['case_credit_already_in_authoritative_checkpoint'] == 1
    native = row['actual_native_request_scope']
    assert native['sha256'] is None
    assert native['resolved_in_root1205_index'] is False
    assert isinstance(native['candidate_receipts'], list)
    assert native['native_condition_not_filled_from_accepted_scope'] is True
    cmp = row['comparison']
    assert cmp['accepted_vs_native_equality_claim'] is False
    assert cmp['not_a_scientific_failure'] is True
    assert cmp['no_missing_field_zero_substitution'] is True
assert m['scope_policy']['new_case_credit'] == 0
assert m['scope_policy']['native_scope_null_is_preserved'] is True
assert m['candidate_receipt_summary'] == {
    'rows_with_candidate_receipts': 5,
    'candidate_receipt_count': 10,
    'candidate_receipts_are_not_resolved_native_scope': True,
}
assert m['scope_policy']['no_canonical_hash_synthesized_from_top_or_decision'] is True
assert s['f2_rows'] == 48
assert s['f2_accepted_rows'] == 32
assert s['f2_unresolved_native_request_rows'] == 13
assert c['reports_scanned'] == 35
assert c['root1205_unaccepted_f2_rows'] == 16
assert c['new_unreviewed_completed_published_count'] == 0
assert c['full_published_report_matches'][0]['already_personally_reviewed_in_fresh164'] is True
assert c['full_published_report_matches'][0]['new_personal_review_in_fresh166'] is False
assert c['f6_last_original951']['terminal_receipt_in_this_audit'] is None
for text in walk({'m': m, 'c': c, 's': s}):
    assert not any(ext in text.lower() for ext in FORBIDDEN), text
print('fresh166 validator PASS: 13 Root1205 F2 native-scope gaps preserve null and physical/case aliases; accepted/source/native scopes remain separate; no new unreviewed published render; no scientific payload references')
