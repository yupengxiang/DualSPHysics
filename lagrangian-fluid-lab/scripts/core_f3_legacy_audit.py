#!/usr/bin/env python3
"""Bind existing F3 hard-audit semantics without altering source assets."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_runtime import digest, atomic_json
from scripts.f3_nopen_qualification import _hard_audit


def adapt_case(row, root):
    refs = row['provenance']
    payloads = {}
    for role in ('audit', 'prepared'):
        path = (root / refs[role]['path']).resolve()
        path.relative_to(root)
        if digest(path) != refs[role]['sha256']:
            raise ValueError(f'{role} source hash mismatch')
        payloads[role] = json.loads(path.read_text())
    record, audit = payloads['prepared'], payloads['audit']
    if row['case_id'] != record['id'] or row['sha256'] != audit['hdf5_sha256']:
        raise ValueError('manifest and audit identity mismatch')
    if (root / row['hdf5']).resolve() != (root / audit['hdf5']).resolve():
        raise ValueError('manifest and audit trajectory paths differ')
    _hard_audit(record, audit)  # Includes actual trajectory content hash.
    mass = audit['initial_fluid_mass_kg']
    if not (mass > 0 and audit['minimum_frame_mass_kg'] == mass == audit['maximum_frame_mass_kg']):
        raise ValueError('saved-frame native mass is not constant')
    return {'case_id': row['case_id'], 'family': 'F3', 'scope_id': row['scope_id'],
            'recipe_id': record['recipe_id'], 'physical_case_id': row['physical_case_id'],
            'lineage_group_id': row['lineage_group_id'], 'hard_integrity_pass': True,
            'trajectory_sha256': row['sha256'], 'source_evidence': refs,
            'semantics': 'Existing full-saved-window native lifecycle/finite/wall audit, rebound to actual trajectory hash; no new numerical or material qualification'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--data-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('versioned evidence output already exists')
    rows = json.loads(a.manifest.read_text())['cases']
    cases = [adapt_case(row, a.data_root.resolve()) for row in rows]
    atomic_json(a.output, {'schema': 'core.f3.legacy_hard_audit_adapter.v1',
        'manifest_sha256': digest(a.manifest), 'adapter_sha256': digest(__file__),
        'legacy_checker_sha256': digest(Path(__file__).with_name('f3_nopen_qualification.py')),
        'cases': cases, 'case_count': len(cases), 'qualification_inferred': False})
    print(json.dumps({'case_count': len(cases), 'output': str(a.output)}))


if __name__ == '__main__':
    main()
