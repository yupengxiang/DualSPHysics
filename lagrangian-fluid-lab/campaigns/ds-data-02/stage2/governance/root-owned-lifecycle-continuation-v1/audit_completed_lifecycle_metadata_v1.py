"""Independently check a frozen lifecycle terminal's metadata/accounting joins.

The frozen per-case verifier owns scientific checks. This integration audit
opens bounded metadata only and preserves failed attempts and UNKNOWN Q.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PAYLOAD = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}


def read(path):
    path = Path(path)
    assert path.suffix.lower() not in PAYLOAD and path.is_file()
    before = path.stat()
    assert before.st_size <= 10485760
    raw = path.read_bytes()
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    return raw


def load(path):
    assert Path(path).suffix.lower() == '.json'
    return json.loads(read(path))


def sha(path):
    return hashlib.sha256(read(path)).hexdigest()


def ref(path):
    return {'path': str(Path(path).absolute()), 'sha256': sha(path)}


def audit(num):
    checkpoint = S / f'checkpoints/ROOT{num}_LIFECYCLE_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V1.json'
    c = load(checkpoint)
    assert c['goal_complete'] is False
    for key in ['current_registry', 'strict_current_plan', 'terminal_proof']:
        assert sha(c[key]['path']) == c[key]['sha256']
    p = load(c['terminal_proof']['path'])
    assert p['schema'] == 'ds02.stage2.root-actual-verification.v1'
    assert p['status'].startswith('VERIFIED_ACTUAL_')
    assert p['parent_reservation_released'] and p['repeat_fee_idempotent'] and not p['failed_cases']
    assert p['scientific_qualification'] == {'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'}
    assert p['parent_actual_prepost_content_hashes_equal']
    for key in ['request', 'manifest', 'report', 'receipt', 'systemd_evidence', 'terminal_cpu_reconciliation']:
        assert sha(p[key]) == p[key + '_sha256']
    q = load(p['request'])
    receipt = load(p['receipt'])
    assert receipt['request'] == q and receipt['request_sha256'] == p['request_sha256']
    assert receipt['status'] == 'completed'
    rows = p['case_verifications']
    ids = [r['physical_case_id'] for r in rows]
    assert len(ids) == len(set(ids)) and set(ids) == set(q['physical_case_ids'])
    for row in rows:
        for key in ['case_manifest', 'receipt', 'summary']:
            assert sha(row[key]) == row[key + '_sha256']
        assert row['source_H5_prepost_known_SHA_and_current_stat_equal']
    registry = load(c['current_registry']['path'])
    producer = next(r for r in registry['producers'] if r['producer_id'] == f'ROOT{num}')
    assert producer['status'] == 'COMPLETED' and set(producer['case_ids']) == set(ids)
    historical_failures = [r['producer_id'] for r in registry['producers'] if r['status'] == 'FAILED']
    reconciliation = load(p['terminal_cpu_reconciliation'])
    ledger = load(D / 'runtime/resource-ledger.json')
    charges = {r['id']: r for r in ledger['charges']}
    parent = charges[p['parent_charge']['id']]
    delta = charges[reconciliation['supplemental_charge_id']]
    assert parent == p['parent_charge']
    assert abs(parent['cpu_core_seconds'] + delta['cpu_core_seconds'] - p['full_systemd_cpu_seconds']) < 1e-6
    assert not any(r['id'] == parent['id'] for r in ledger['reservations'])
    unit = f"ds02-typed-lifecycle-batch-v1-{q['family_id'].lower()}-root-{num}"
    raw = subprocess.check_output(['systemctl', '--user', 'show', unit, '-p', 'SubState', '-p', 'MainPID'], text=True)
    state = dict(line.split('=', 1) for line in raw.splitlines())
    assert state['SubState'] == 'dead' and state['MainPID'] == '0'
    output = S / f'checkpoints/ROOT{num}_ACTUAL_LIFECYCLE_METADATA_INDEPENDENT_CLOSURE_V1.json'
    assert not output.exists()
    value = {'schema': 'ds02.stage2.root-lifecycle-metadata-independent-closure.v1',
             'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'status': 'PASS_ACTUAL_TERMINAL_METADATA_ACCOUNTING_AND_SOURCE_JOINS',
             'checkpoint': ref(checkpoint), 'terminal_proof': ref(c['terminal_proof']['path']),
             'auditor': ref(Path(__file__)), 'coverage': c['coverage'],
             'actual_batch_case_ids': ids, 'historical_failed_producers_preserved': historical_failures,
             'full_systemd_cpu_seconds': p['full_systemd_cpu_seconds'],
             'checks': {'case_summary_receipt_manifest_SHA_closed': True,
                        'original_charge_plus_supplement_equals_full_cpu': True,
                        'parent_reservation_released': True, 'repeat_fee_idempotent': True,
                        'unit_dead': True, 'scientific_per_case_verifier': 'FROZEN_ROOT_TERMINAL_VERIFIER'},
             'root_payload_content_read': False, 'scientific_Q_credit': 0,
             'goal_complete': False, 'next': 'Continue the full seven-item task and actual dependent queue.'}
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'closure': ref(output), 'actual_cases': c['coverage']['actual_saved_mask_cases'],
                      'full_CPU_seconds': p['full_systemd_cpu_seconds']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('namespace', type=int)
    audit(parser.parse_args().namespace)
