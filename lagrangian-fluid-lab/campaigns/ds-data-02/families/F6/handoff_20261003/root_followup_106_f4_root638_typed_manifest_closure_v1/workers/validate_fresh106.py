#!/usr/bin/env python3
"""Metadata-only validator for fresh106 typed-manifest closure."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
INDEX = HERE / 'metadata/root638-typed-manifest-closure.json'
MANIFEST = HERE / 'manifest.json'
SCIENCE = ('.h5', '.bi4', '.ibi4', '.csv', '.dat', '.npy', '.npz')

def check(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit('fresh106 validation failed: ' + msg)

def main() -> None:
    d = json.loads(INDEX.read_text(encoding='utf-8'))
    check(d['schema'] == 'ds02.f6.fresh106.f4-root638-typed-manifest-closure.v1', 'schema')
    check(d['fresh_id'] == 'fresh106', 'fresh id')
    check(d['base_sidecar']['base_commit'] == '2003134a', 'fresh105 base commit')
    check(d['base_sidecar']['immutable'] is True, 'base immutability')
    check(len(d['cases']) == 2, 'two cases')
    for c in d['cases']:
        m = c['xmf_manifest']
        check(m['exists'] is True, f'{c["case_id"]}: manifest')
        check(m['frames'] == 1201 and m['particles'] == 83233, f'{c["case_id"]}: manifest dimensions')
        fields = c['typed_manifest_closure']['manifest_fields']
        check(fields['typed_receipt_field'], f'{c["case_id"]}: missing typed_receipt field')
        check(fields['conversion_report_field'], f'{c["case_id"]}: missing conversion_report field')
        check(fields['typed_receipt_field_is_absolute'] is True, f'{c["case_id"]}: typed path absolute')
        check(fields['conversion_report_field_is_absolute'] is True, f'{c["case_id"]}: report path absolute')
        tr = c['typed_manifest_closure']['typed_receipt']
        cr = c['typed_manifest_closure']['conversion_report']
        check(tr['exists'] is True and tr['terminal_completed_zero'] is True, f'{c["case_id"]}: typed terminal receipt')
        check(tr['manifest_sha256_matches_metadata_file'] is True, f'{c["case_id"]}: typed SHA')
        check(cr['exists'] is True and cr['conversion_status'] == 'completed', f'{c["case_id"]}: conversion report')
        check(cr['manifest_sha256_matches_metadata_file'] is True, f'{c["case_id"]}: report SHA')
        check(cr['frames'] == 1201 and cr['particles'] == 83233 and cr['solver_dimension'] == 3, f'{c["case_id"]}: report dimensions')
        check(cr['partvtk_validation_all_passed'] is True and cr['metadata_pass'] is True, f'{c["case_id"]}: report pass')
        uid = c['typed_manifest_closure']['typed_review_uid_contract']
        check(uid['actual_full1201_N3'] is True, f'{c["case_id"]}: typed review N3')
        check('max_missing_initial_native_UIDs' in uid and 'first_missing_frame_by_mk' in cr['lifecycle'], f'{c["case_id"]}: UID closure')
        check(c['typed_manifest_closure']['closure_status']['visual_acceptance'].startswith('pending'), f'{c["case_id"]}: visual status')
    def strings(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and (key.endswith('path') or key.endswith('_field') or key == 'path'):
                    yield item
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    payload_paths = [x for x in strings(d) if Path(x).suffix.lower() in SCIENCE]
    check(not payload_paths, 'scientific payload path leaked')
    md = json.loads(MANIFEST.read_text(encoding='utf-8'))
    for entry in md['files']:
        p = HERE / entry['path']
        check(p.is_file(), f'manifest missing {entry["path"]}')
        check(hashlib.sha256(p.read_bytes()).hexdigest() == entry['sha256'], f'manifest digest {entry["path"]}')
    print('fresh106 validation PASS: actual typed receipt/report closure for both Root638 cases')

if __name__ == '__main__':
    main()
