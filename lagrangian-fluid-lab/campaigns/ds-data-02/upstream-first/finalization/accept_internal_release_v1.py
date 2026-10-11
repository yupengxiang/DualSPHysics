#!/usr/bin/env python3
"""Root acceptance from actual, completed evidence; no payload scan or launch."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import h5py
import numpy

P = Path(__file__).resolve().parents[1]
ROOT = P.parents[3]
LEDGER = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json')
NAS = Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(path):
    return json.loads(Path(path).read_text())


def bind(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'missing regular metadata: {path}')
    require(path.stat().st_size < 32 * 1024**2, f'metadata size bound exceeded: {path}')
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def check(binding, payload=False):
    path = Path(binding['path'])
    require(path.is_file() and not path.is_symlink(), f'missing artifact: {path}')
    require(path.stat().st_size == binding['bytes'], f'artifact size changed: {path}')
    if not payload:
        require(bind(path)['sha256'] == binding['sha256'], f'metadata hash changed: {path}')


def main():
    outputs = [P/'M4_INTERNAL_DATASET_V1.json', P/'milestone-evidence/M4-complete-v1.json',
               P/'GOAL_COMPLETION_AUDIT_V1.json']
    require(all(not f.exists() for f in outputs), 'acceptance outputs already exist; preserve them')
    card_path = P/'M4_RELEASE_FINAL_V1.json'
    cost_path = P/'m4-cost-audit/checkpoints/M4-resource-audit-final-v1.json'
    m23_path = P/'m4/release/audit-only/M2-M3-final-evidence-v1.json'
    card, cost, m23 = load(card_path), load(cost_path), load(m23_path)
    require(card['status'] == 'completed_development_partition', 'four actual products required')
    require(card['development_partition']['eligible_condition_count'] == 4, 'four independent conditions required')
    require(card['validation_partition']['condition_count'] == 0, 'common lineage has no heldout split')
    require(cost['status'] == 'resource_audit_verified' and not cost['active_reservations'], 'cost closure required')
    acceptance = m23['acceptance']
    require(acceptance['status'] == 'verified_metadata_only_with_scientific_limits'
            and acceptance['accepted_terminal_receipts_completed_zero']
            and acceptance['accepted_terminal_receipt_request_bindings_match']
            and acceptance['scope_336_rows_7x48_and_unique_physical_ids']
            and not acceptance['real_missing_required_delivery'] and not acceptance['issues'],
            'M2/M3 final actual evidence verification required')
    ledger = load(LEDGER)
    require(not [x for x in ledger['reservations'] if '/UF_' in x['id']], 'own active reservation remains')
    require(ledger['deadline_utc'] == '2026-10-25T03:11:02+00:00', 'fixed deadline changed')
    charges = {x['id']: x for x in ledger['charges']}
    conditions, runner_checks, physical_hashes = [], [], set()
    for row in card['development_partition']['conditions']:
        case = row['case_id']
        require(row['eligible_for_development_partition'] and all(row['gates'].values()), case)
        identity = row['fields']['identity_axis']
        require(identity['frame_count'] == 241 and identity['full_initial_identity'], 'full identity/time coverage required')
        ph = row['physical_condition']['actual']['physical_condition_sha256']
        require(ph not in physical_hashes, 'duplicate physical condition')
        physical_hashes.add(ph)
        av = row['actual_validation']
        require(av['source_unchanged'] and av['isolated_replay']['denied_probes_passed'], 'actual isolation required')
        require(av['semantic_negatives']['count'] == 2 and av['semantic_negatives']['passed'], 'actual rehashed negatives required')
        bundle = row['bundle']['relocated']
        for key, value in bundle['artifacts'].items():
            check(value, payload=(key == 'normalized_hdf5'))
        check(bundle['manifest'])
        receipt_paths = [row['receipts'][k]['path'] for k in ['direct_conversion', 'enrichment', 'portable_build']]
        receipt_paths.append(str(NAS/'runs/F1'/case/'m4-actual-validation-001/execution-receipt.json'))
        for path in receipt_paths:
            receipt = load(path)
            require(receipt['status'] == 'completed' and receipt['returncode'] == 0, f'nonterminal runner: {path}')
            req = receipt['request']
            require(req['case_id'] == case, 'actual runner case mismatch')
            attempt_id = '/'.join(req[k] for k in ['family_id', 'case_id', 'attempt_id'])
            charge = charges[attempt_id]
            require(charge['status'] == 'completed', 'terminal parent charge required')
            for key, target in [('gpu_seconds', 'gpu_seconds'), ('cpu_core_seconds', 'cpu_core_seconds'), ('bytes', 'new_storage_bytes')]:
                require(math.isclose(receipt[key], charge[target], rel_tol=1e-12, abs_tol=1e-8), f'charge mismatch: {attempt_id}')
            request = bind(P/'requests'/f"{case}-{req['attempt_id']}.json")
            require(request['sha256'] == receipt['request_sha256'], 'actual request hash mismatch')
            require(receipt['input_hashes_at_launch'] == receipt['input_hashes_after_run'], 'consumed input changed')
            runner_checks.append({'id': attempt_id, 'execution_receipt': bind(path), 'request': request, 'parent_charge': charge})
        conditions.append({'case_id': case, 'initial_water_depth_m': row['planned_depth_m'],
            'physical_condition_sha256': ph, 'role': 'development', 'scientific_qualification': 'not_claimed',
            'bundle': bundle, 'fields': row['fields'], 'labels': row['labels'],
            'actual_validation': row['receipts']['actual_validation'],
            'evaluator_summary': row['reader_evaluator']['evaluator']['payload']['summary']})
    certificates = {}
    for milestone, version in [('M1', 2), ('M2', 1), ('M3', 1)]:
        path = P/f'milestone-evidence/{milestone}-complete-v{version}.json'
        certificate = load(path)
        require(certificate['status'] == 'complete' and certificate['acceptance_status'] == 'accepted', milestone)
        for artifact in certificate['artifacts']:
            require(bind(artifact['path'])['sha256'] == artifact['sha256'], f'{milestone} artifact changed')
        certificates[milestone] = bind(path)
    require(shutil.which('bwrap') is not None and Path(sys.executable).is_file(), 'runtime dependency unavailable')
    now = datetime.now(timezone.utc).isoformat()
    usage = {k: sum(x.get(k, 0) for x in ledger['charges']) for k in ['gpu_seconds', 'cpu_core_seconds', 'new_storage_bytes']}
    initial = load(P/'STATUS.json')['initial_usage']
    delta = {k: usage[k] - initial[k] for k in usage}
    dependencies = {'python': sys.executable, 'numpy_version': numpy.__version__,
                    'h5py_version': h5py.__version__, 'bubblewrap': shutil.which('bwrap')}
    index = {'schema': 'ds-data-02.upstream-first.internal-dataset.v1',
        'status': 'accepted_internal_diagnostic_version', 'accepted_at_utc': now,
        'release_id': card['release_id'], 'release': bind(card_path), 'resource_audit': bind(cost_path),
        'conditions': conditions, 'development_case_ids': [x['case_id'] for x in conditions],
        'validation_case_ids': [], 'lineage_policy': card['development_partition']['lineage_policy'],
        'mother_reference': card['mother_reference'], 'reference_pack_certificates': certificates,
        'acceptance_scope': 'Internal data engineering and model-free numerical endpoint transport diagnostics.',
        'claims': card['claims'], 'dependencies': dependencies,
        'payload_hash_policy': 'Actual charged conversion, packaging and source-denied replay bind full payload hashes; root finalization checks metadata and current HDF5 size only.'}
    outputs[0].write_text(json.dumps(index, indent=2)+'\n')
    m4 = {'schema': 'ds02.upstream-first.milestone-evidence.v1', 'milestone': 'M4',
        'status': 'complete', 'acceptance_status': 'accepted', 'checked_at_utc': now,
        'acceptance_scope': index['acceptance_scope'], 'artifacts': [bind(outputs[0]), bind(card_path), bind(cost_path)],
        'actual_terminal_runner_checks': runner_checks, 'claim_limits': card['claims']}
    outputs[1].write_text(json.dumps(m4, indent=2)+'\n')
    audit = {'schema': 'ds-data-02.upstream-first.goal-completion-audit.v1', 'status': 'verified_complete',
        'checked_at_utc': now, 'authority': bind(P/'ADOPTION.json'),
        'adopted_at_utc': '2026-10-11T03:11:02Z', 'deadline_utc': '2026-10-25T03:11:02Z',
        'milestones': {**certificates, 'M4': bind(outputs[1])},
        'independent_M2_M3_actual_evidence': bind(m23_path),
        'M1_current_csv_receipt_handoff_verification': bind(P/'m1/evidence/M1-final-handoff-root-verification-v1.json'),
        'checks': {'two_actual_upstream_reference_packs_with_main_and_aux_observations': True,
            'at_least_one_reference_is_3d': True, 'external_reader_and_own_3d_portable_delivery': True,
            'two_actual_single_physical_parameter_derivatives_and_comparisons': True,
            '336_case_seven_family_scope_index': True, 'four_independent_physical_conditions': True,
            'full_space_state_geometry_control_and_checked_transport_labels': True,
            'all_four_actual_source_denied_replays_and_two_rehashed_negatives_each': True,
            'all_four_terminal_runner_requests_parent_charges_verified': True,
            'runtime_dependencies_accessible': True, 'own_active_reservations_empty': True,
            'history_limits_and_fixed_window_preserved': True, 'scientific_limits_preserved': True},
        'parent_cumulative_usage': usage, 'this_adopted_activity_usage': delta,
        'cpu_accounting_note': 'Includes mother full-frame scan conservative 3600 CPU-second ceiling reconciliation; no fabricated measured runtime.',
        'expansion_after_completion': False, 'finalization_payload_scan_or_launch': False}
    outputs[2].write_text(json.dumps(audit, indent=2)+'\n')
    print(json.dumps({'status': audit['status'], 'case_count': len(conditions), 'activity_usage': delta}))


if __name__ == '__main__':
    main()
