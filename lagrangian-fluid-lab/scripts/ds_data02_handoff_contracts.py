#!/usr/bin/env python3
"""Add explicit source contracts to unmodified, finite native trajectories.

Missing-particle cases require an independently bound native exclusion ledger;
they are not automatically declared closed. All audits use new attempt names.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from ds_data02_handoff_inventory import binding, load, sha256


UNITS = {'time': 's', 'position': 'm', 'velocity': 'm/s', 'density': 'kg/m^3',
         'mass': 'kg', 'pressure': 'Pa'}


def validate_closed_evidence(audit, report):
    lifecycle = audit.get('lifecycle', {})
    fields = ('missing_at_any_later_frame_count', 'introduced_after_initial_count',
              'revived_identity_count', 'type_changed_identity_count')
    if not lifecycle.get('full_timeline_checked') or any(lifecycle.get(k) != 0 for k in fields):
        raise ValueError('native exclusion ledger or lifecycle investigation required')
    if audit.get('structural_failures'):
        raise ValueError('existing structural failures cannot be repaired by metadata')
    if report.get('units') != UNITS:
        raise ValueError('explicit native SI evidence missing or inconsistent')
    if audit.get('solver_log', {}).get('counts', {}).get('excluded_particles') != 0:
        raise ValueError('solver exclusions cannot be declared closed')


def prepare_case(row, lab, output):
    trajectory = Path(row['trajectory'])
    report_path = trajectory.parent / 'conversion-report.json'
    audit_path = trajectory.parent / 'audit.json'
    report, audit = load(report_path), load(audit_path)
    validate_closed_evidence(audit, report)
    sources = report['source_provenance']
    xml = Path(sources['generated_xml']['path'])
    solver_receipt = Path(sources['solver_receipt']['path'])
    gencase_receipt = Path(sources['gencase_receipt']['path'])
    for role, path in [('generated_xml', xml), ('solver_receipt', solver_receipt),
                       ('gencase_receipt', gencase_receipt)]:
        if sha256(path) != sources[role]['sha256']:
            raise ValueError(f'current {role} differs from consumed conversion binding')
    parsed = ET.parse(xml).getroot()
    if parsed.find('.//geometry') is None or parsed.find('.//inout') is not None:
        raise ValueError('complete finite source geometry is required')
    solver = load(solver_receipt)
    if solver.get('status') != 'completed' or solver.get('returncode') != 0:
        raise ValueError('successful source solver receipt is required')
    solver_log = Path(audit['solver_log']['path'])
    if sha256(solver_log) != audit['solver_log']['sha256']:
        raise ValueError('solver log differs from old audit binding')
    inputs = []
    for name, expected in solver.get('input_hashes_at_launch', {}).items():
        path = Path(name)
        if path.suffix.lower() in ('.csv', '.dat') and path.is_file():
            if sha256(path) != expected:
                raise ValueError('actual forcing file changed since solver launch')
            inputs.append(binding(path))
    metadata = {
        'schema': 'ds-data-02.lifecycle-contract.v1', 'family_id': row['family_id'],
        'case_id': row['case_id'], 'coordinate_frame': report['coordinate_frame'],
        'units': report['units'], 'units_evidence': binding(report_path),
        'geometry': {'generated_xml': binding(xml),
                     'geometry_xml': ET.tostring(parsed.find('.//geometry'), encoding='unicode'),
                     'meaning': 'Actual generated case geometry; continuum initialization acceptance remains separate.'},
        'control': {'generated_xml': binding(xml), 'forcing_files': inputs,
                    'native_control_xml': [ET.tostring(node, encoding='unicode') for tag in
                                           ('motion', 'special', 'constantsdef', 'parameters')
                                           for node in parsed.findall('.//' + tag)]},
        'boundary_mode': 'closed',
        'lifecycle_interpretation': 'Finite numerical identity cohort; prior full-window evidence has zero exclusions, omissions, introductions and revivals. Open physical surfaces remain defined by actual geometry.',
        'old_audit': binding(audit_path), 'source_solver_receipt': binding(solver_receipt),
        'source_gencase_receipt': binding(gencase_receipt),
        'historical_gencase_launch_input_hashes_available': bool(load(gencase_receipt).get('input_hashes_at_launch')),
        'numerical_qualification': 'not_assessed', 'production_eligibility': 'not_evaluated',
        'prescribed_body_aggregate_pose_qualification': 'separate; native type1 states are retained',
        'trajectory': str(trajectory), 'recorded_trajectory_sha256': report['output_sha256']}
    case_output = output / row['case_id']
    case_output.mkdir(parents=True, exist_ok=False)
    contract = case_output / 'lifecycle-source-contract.json'
    contract.write_text(json.dumps(metadata, indent=2) + '\n')
    files = [trajectory, report_path, audit_path, contract, xml, solver_log, solver_receipt,
             gencase_receipt, lab / 'scripts/ds_data02_integrity.py']
    files += [Path(ref['path']) for ref in inputs]
    request = {'schema': 'ds-data-02.runner.request.v1', 'family_id': row['family_id'],
               'case_id': row['case_id'], 'attempt_id': 'root-integrity-source-contract-001',
               'kind': 'cpu', 'cpu_task_kind': 'audit', 'cpu_threads': 2,
               'max_wall_seconds': 3600, 'estimated_storage_bytes': 128 * 1024**2,
               'worktree_root': str(lab.parent), 'cwd': str(lab),
               'input_files': [str(p) for p in files],
               'command': [str(lab / '.venv/bin/python'), str(lab / 'scripts/ds_data02_integrity.py'),
                           str(trajectory), '--solver-log', str(solver_log), '--metadata-json',
                           str(contract), '--particle-chunk', '65536', '--output', '{attempt_root}/integrity.json'],
               'request_note': 'Full structural integrity with explicit source/units/finite cohort metadata; preserve original H5, audit, labels. No continuum/Q-N/domain/production qualification.'}
    path = case_output / 'audit-request.json'
    path.write_text(json.dumps(request, indent=2) + '\n')
    return {'case_id': row['case_id'], 'family_id': row['family_id'], 'status': 'new_audit_request_ready',
            'request': str(path), 'metadata': binding(contract), 'trajectory_bytes': trajectory.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--lab', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = []
    for row in load(args.inventory)['cases']:
        if row.get('integrity_status') != 'incomplete_contract':
            continue
        try:
            result.append(prepare_case(row, args.lab, args.output))
        except (OSError, ValueError, KeyError) as error:
            result.append({'case_id': row['case_id'], 'family_id': row['family_id'],
                           'status': 'requires_source_or_native_exclusion_evidence', 'reason': str(error)})
    (args.output / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'ready': sum(r['status'] == 'new_audit_request_ready' for r in result),
                      'pending': sum(r['status'] != 'new_audit_request_ready' for r in result)}))


if __name__ == '__main__':
    main()
