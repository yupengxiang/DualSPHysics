"""Charge the first H050 relocation copy outside its final attempt, once."""
import hashlib
import json
import os
from pathlib import Path
import sys

P = Path(__file__).resolve().parent
ROOT = P.parents[3]
sys.path.insert(0, str(ROOT / 'lagrangian-fluid-lab/scripts'))
import ds_data02_runtime_v2 as runtime
import ds_data02_runtime_v6_batch2 as batch


def load(path):
    return json.loads(path.read_text())


def binding(path):
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': runtime.sha256(path)}


def main():
    case = 'UF_F1_MDBC_DP010_H050'
    run = Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1') / case
    prep = run / 'm4-relocation-preparation-001'
    actual = run / 'm4-actual-validation-001'
    prep_receipt = load(prep / 'execution-receipt.json')
    actual_receipt = load(actual / 'execution-receipt.json')
    evidence_path = actual / 'm4-actual-validation/results/actual-validation-receipt.json'
    evidence = load(evidence_path)
    assert prep_receipt['status'] == actual_receipt['status'] == evidence['status'] == 'completed'
    assert evidence['source_unchanged'] is True and evidence['semantic_negatives']['passed'] is True
    relocated = Path(evidence['relocation']['destination_bundle'])
    assert relocated.is_relative_to(prep) and not relocated.is_relative_to(actual)
    assert os.path.ismount('/data/nas')
    assert not any(path.is_symlink() for path in prep.rglob('*'))
    actual_prep_bytes = runtime.tree_bytes(prep)
    delta = actual_prep_bytes - prep_receipt['bytes']
    assert delta == evidence['relocation']['bytes'] == runtime.tree_bytes(relocated)
    assert 0 < delta <= actual_receipt['request']['estimated_storage_bytes'] - actual_receipt['bytes']
    admission = batch.validate_admission(P / 'batch2-runtime/root-batch-2-admission.json')
    charge_id = f'F1/{case}/m4-actual-validation-001::external-nas-copy-delta'
    report_path = P / 'batch2-runtime/H050-external-relocation-storage-reconciliation-v1.json'
    report = {
        'schema': 'ds02.upstream-first.external-storage-reconciliation.v1', 'status': 'completed',
        'case_id': case, 'charge_id': charge_id, 'reported_at_utc': actual_receipt['finished_at_utc'],
        'reason': 'PREP argv placeholder expansion fixed the future relocation path to the preparation attempt',
        'original_receipts_and_charge_rows_unchanged': True,
        'original_preparation_bytes': prep_receipt['bytes'], 'observed_preparation_tree_bytes': actual_prep_bytes,
        'additional_persistent_bytes': delta, 'relocated_bundle': str(relocated),
        'actual_relocation_evidence': binding(evidence_path),
        'original_preparation_receipt': binding(prep / 'execution-receipt.json'),
        'original_validation_receipt': binding(actual / 'execution-receipt.json'),
        'cpu_gpu_already_charged_by_original_runner': True,
        'parent_limits_and_deadline_unchanged': True,
        'within_original_validation_storage_reservation': True,
        'scientific_replay_scope': 'fresh independent NAS copy; original source case inaccessible; both rehashed payload negatives rejected',
        'forward_fix': 'run_m4_relocation_queue_v2.py rebinds final output placeholders before immutable request grant',
    }
    encoded = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
    report_hash = hashlib.sha256(encoded).hexdigest()
    with runtime.ledger_locked() as ledger:
        prior_ids, _ = batch._baseline_rows_match(ledger, admission)
        assert ledger['limits'] == admission['parent_limits'] and ledger['deadline_utc'] == admission['parent_deadline_utc']
        assert not any(row['id'] == f'F1/{case}/m4-actual-validation-001' for row in ledger['reservations'])
        original_prep_charge = next(row for row in ledger['charges'] if row['id'] == f'F1/{case}/m4-relocation-preparation-001')
        assert original_prep_charge['new_storage_bytes'] == prep_receipt['bytes']
        existing = [row for row in ledger['charges'] if row['id'] == charge_id]
        if existing:
            assert len(existing) == 1 and existing[0]['new_storage_bytes'] == delta and existing[0]['evidence_sha256'] == report_hash
        else:
            used = sum(row.get('new_storage_bytes', 0) for row in ledger['charges'] if row['id'] not in prior_ids)
            reserved = sum(row.get('new_storage_bytes', 0) for row in ledger['reservations'])
            assert used + reserved + delta <= admission['batch_limits']['additional_storage_bytes']
            ledger['charges'].append({
                'id': charge_id, 'gpu_seconds': 0.0, 'cpu_core_seconds': 0.0,
                'new_storage_bytes': delta, 'output_storage': 'upstream_nas',
                'status': 'completed_external_storage_reconciliation',
                'finished_at_utc': actual_receipt['finished_at_utc'],
                'evidence_path': str(report_path), 'evidence_sha256': report_hash,
            })
    if report_path.exists():
        assert report_path.read_bytes() == encoded
    else:
        with report_path.open('xb') as output:
            output.write(encoded)
    print(json.dumps({'charge_id': charge_id, 'additional_persistent_bytes': delta, 'report': str(report_path)}))


if __name__ == '__main__':
    main()
