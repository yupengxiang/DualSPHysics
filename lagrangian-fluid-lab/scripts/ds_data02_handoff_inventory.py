#!/usr/bin/env python3
"""Inspect existing handoff evidence without rewriting or requalifying products.

Report hashes are recomputed. Large trajectory hashes remain recorded bindings,
not fresh checksum verification. This inventory is not a full trajectory audit.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def integrity_status(report):
    """Solver count agreement never substitutes for integrity requirements."""
    if not isinstance(report, dict):
        return 'not_audited'
    required = ('q_i_status', 'missing_requirements', 'structural_failures',
                'solver_log_consistency')
    if any(key not in report for key in required):
        return 'incomplete_report'
    if report['structural_failures']:
        return 'structural_failure'
    if report['missing_requirements']:
        return 'incomplete_contract'
    if report['q_i_status'] != 'Q-I-structure-pass':
        return 'not_passed'
    if report['solver_log_consistency'].get('status') != 'pass':
        return 'solver_binding_failure'
    if report.get('f6_physics_status') not in (None, 'pass'):
        return 'family_physics_failure'
    return 'existing_report_structure_pass'


def binding(path):
    path = Path(path)
    return {'path': str(path), 'sha256': sha256(path), 'bytes': path.stat().st_size}


def inspect_case(family, entry, data_root):
    import h5py
    case = entry['case_id']
    case_root = data_root / 'families' / family / case
    label = Path(entry['output'])
    label_receipt = entry.get('receipt') or {}
    if not label_receipt:
        p = label.parent / 'execution-receipt.json'
        if p.is_file():
            label_receipt = load(p)
    trajectory = label_receipt.get('source_trajectory')
    if not trajectory and label.is_file():
        with h5py.File(label, 'r') as handle:
            trajectory = handle.attrs.get('source_trajectory')
    candidates = sorted(case_root.glob('full-typed-native-conversion-*/trajectory.h5'))
    if not trajectory:
        if len(candidates) == 1:
            trajectory = str(candidates[0])
        else:
            return {'family_id': family, 'case_id': case,
                    'chain_status': 'trajectory_binding_missing_or_ambiguous',
                    'candidate_paths': [str(p) for p in candidates],
                    'q_n_status': 'not_assessed', 'production_acceptance': False}
    trajectory = Path(trajectory)
    row = {'family_id': family, 'case_id': case, 'trajectory': str(trajectory),
           'trajectory_exists': trajectory.is_file(), 'label_exists': label.is_file(),
           'q_n_status': 'not_assessed', 'production_acceptance': False,
           'trajectory_checksum_freshly_verified': False}
    if not trajectory.is_file():
        return row
    report_path = trajectory.parent / 'conversion-report.json'
    report = load(report_path) if report_path.is_file() else {}
    audit_path = trajectory.parent / 'audit.json'
    audit = load(audit_path) if audit_path.is_file() else None
    row.update(integrity_status=integrity_status(audit),
               q_i_report_status=audit.get('q_i_status') if audit else None,
               missing_requirements=audit.get('missing_requirements', []) if audit else [],
               structural_failures=audit.get('structural_failures', []) if audit else [],
               conversion_report=binding(report_path) if report else None,
               audit_report=binding(audit_path) if audit else None)
    recorded_hash = report.get('output_sha256')
    label_source_hash = label_receipt.get('source_trajectory_sha256')
    row['recorded_trajectory_sha256'] = recorded_hash
    row['label_source_hash_agrees_with_conversion_report'] = (
        bool(recorded_hash and label_source_hash) and recorded_hash == label_source_hash)
    if label.is_file():
        actual_label_hash = sha256(label)
        row['label_current_sha256'] = actual_label_hash
        row['label_receipt_output_hash_matches'] = (
            bool(label_receipt.get('output_sha256'))
            and actual_label_hash == label_receipt['output_sha256'])
    with h5py.File(trajectory, 'r') as handle:
        row['frames'] = len(handle['time'])
        row['particles'] = handle['position'].shape[1]
        row['time_start_s'] = float(handle['time'][0])
        row['time_end_s'] = float(handle['time'][-1])
        row['declared_physical_condition_sha256'] = str(handle.attrs.get('physical_condition_sha256', ''))
        row['conversion_complete'] = bool(handle.attrs.get('conversion_complete', False))
    row['source_bindings'] = []
    for role, ref in report.get('source_provenance', {}).items():
        if not isinstance(ref, dict) or 'path' not in ref or 'sha256' not in ref:
            continue
        source = Path(ref['path'])
        check = {'role': role, 'path': str(source), 'exists': source.is_file()}
        if source.is_file():
            check['current_sha256_matches'] = sha256(source) == ref['sha256']
        row['source_bindings'].append(check)
    return row


def inventory(lab, data_root):
    cases = []
    summaries = []
    for family in ('F1', 'F2', 'F3', 'F5', 'F6', 'F7'):
        path = lab / 'campaigns/ds-data-02/families' / family / 'stage8_labels_summary.json'
        if not path.is_file():
            continue
        summaries.append(binding(path))
        for entry in load(path):
            try:
                cases.append(inspect_case(family, entry, data_root))
            except (OSError, ValueError, KeyError, TypeError) as error:
                cases.append({'family_id': family, 'case_id': entry.get('case_id'),
                              'inspection_error': str(error), 'production_acceptance': False})
    duplicates = defaultdict(list)
    for case in cases:
        value = case.get('declared_physical_condition_sha256')
        if value:
            duplicates[(case['family_id'], value)].append(case['case_id'])
    return {'schema': 'ds02.handoff-evidence-inventory.v1',
            'observed_at_utc': datetime.now(timezone.utc).isoformat(),
            'scope': 'existing reports, small-file checksums and HDF5 metadata; no full trajectory rescan',
            'summaries': summaries, 'cases': cases,
            'case_count': len(cases),
            'integrity_status_counts': dict(Counter(c.get('integrity_status', 'inspection_incomplete') for c in cases)),
            'duplicate_declared_physical_bindings': [
                {'family_id': key[0], 'sha256': key[1], 'cases': value}
                for key, value in duplicates.items() if len(value) > 1],
            'duplicates_interpretation': 'Repeated declared bindings require actual geometry/control/initial-state review; distinct names do not establish distinct physics.',
            'qualified_independent_production_cases': 0,
            'scientific_qualification_granted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.lab, args.data_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'case_count': result['case_count'],
                      'integrity_status_counts': result['integrity_status_counts'],
                      'duplicate_binding_groups': len(result['duplicate_declared_physical_bindings'])}))


if __name__ == '__main__':
    main()
