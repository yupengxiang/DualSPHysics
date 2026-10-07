"""Incremental primary verification of completed scans without reopening HDF5."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
STAGE2 = Path(__file__).resolve().parents[1]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    previous = load(args.previous)
    catalog_node = previous['current_catalog']
    assert sha(catalog_node['path']) == catalog_node['sha256']
    current = load(catalog_node['path'])
    indexed = {(r['family_id'], r['physical_case_id']): (i, r) for i, r in enumerate(current['cases'])}
    records = list(previous['verified_cases'])
    known = {(r['family_id'], r['physical_case_id']) for r in records}
    assert len(known) == previous['distinct_completed_cases']
    for record in records:
        assert sha(record['scan']) == record['scan_sha256']
        assert sha(record['receipt']) == record['receipt_sha256']
    ledger = load(DATA / 'runtime/resource-ledger.json')
    charges = {r['id']: r for r in ledger['charges']}
    reservations = {r['id'] for r in ledger['reservations']}
    new_records = []
    for family in ('F3', 'F5', 'F7'):
        for receipt_path in sorted((DATA / 'families' / family / 'STAGE2_CURRENT336_SCIENCE').glob('*/execution-receipt.json')):
            receipt = load(receipt_path)
            if receipt.get('status') != 'completed':
                continue
            scan_path = receipt_path.parent / 'scientific-scan.json'
            scan = load(scan_path)
            key = (scan['family_id'], scan['physical_case_id'])
            if key in known:
                continue
            index, row = indexed[key]
            request = receipt['request']
            request_path = STAGE2 / 'requests/science-v4' / family / (request['attempt_id'] + '.json')
            assert sha(request_path) == receipt['request_sha256']
            assert load(request_path) == request
            assert receipt['returncode'] == 0 and receipt.get('termination_reason') is None
            before = receipt['input_hashes_at_launch']
            assert before == receipt['input_hashes_after_run']
            expected = {str(Path(p).resolve()): digest for p, digest in request['input_sha256'].items()}
            assert before == expected
            h5_path = Path(row['trajectory']['path']).resolve()
            h5_key = str(h5_path)
            assert before[h5_key] == row['trajectory']['producer_declared_sha256']
            for path, digest in before.items():
                if Path(path).suffix.lower() in {'.h5', '.hdf5'}:
                    assert path == h5_key
                else:
                    assert sha(path) == digest
            assert scan['trajectory'] == row['trajectory']['path']
            stat = h5_path.stat()
            assert stat.st_size == scan['source_bytes'] == row['trajectory']['bytes']
            assert stat.st_mtime_ns == scan['source_mtime_ns'] == row['trajectory']['mtime_ns']
            assert scan['frames'] == row['frames'] and scan['particles'] == row['particles']
            times = scan['time_s']
            assert scan['full_saved_timeline_scanned'] and len(times) == row['frames']
            assert all(math.isfinite(t) for t in times) and all(b > a for a, b in zip(times, times[1:]))
            assert [times[0], times[-1]] == row['actual_time_window_s']
            assert '--catalog' in receipt['command']
            catalog_path = receipt['command'][receipt['command'].index('--catalog') + 1]
            assert before[str(Path(catalog_path).resolve())] == catalog_node['sha256']
            assert receipt['command'][receipt['command'].index('--case-id') + 1] == key[1]
            terminal = receipt['terminal_storage_guard']
            size = sum(p.stat().st_size for p in receipt_path.parent.rglob('*') if p.is_file())
            ident = '/'.join((family, request['case_id'], request['attempt_id']))
            assert terminal['status'] == 'passed' and terminal['measurement'] == 'fixed_point_including_final_receipt'
            assert size == receipt['bytes'] == terminal['actual_bytes'] == charges[ident]['new_storage_bytes']
            assert ident not in reservations
            fluid = scan['type_ledgers']['fluid']
            record = {
                'family_id': family, 'physical_case_id': key[1], 'current_case_index': index,
                'trajectory': h5_key, 'trajectory_verified_sha256': before[h5_key],
                'scan': str(scan_path), 'scan_sha256': sha(scan_path),
                'receipt': str(receipt_path), 'receipt_sha256': sha(receipt_path),
                'scan_status': scan['scan_status'], 'frames': scan['frames'],
                'fluid_ledger': {k: v for k, v in fluid.items() if not isinstance(v, list)},
                'field_failures': scan['failures'], 'QI_dynamics': scan['QI_dynamics'],
                'QN': scan['QN'], 'QE': scan['QE'], 'exact_CURRENT_path_and_declared_sha_match': True,
                'parent_current_prepost_SHA_verified_input_count': len(before),
                'terminal_tree_receipt_charge_bytes': size,
            }
            new_records.append(record)
            records.append(record)
            known.add(key)
    for record in new_records:
        assert sha(record['scan']) == record['scan_sha256'] and sha(record['receipt']) == record['receipt_sha256']
    result = {
        'schema': 'ds02.stage2.scientific-audit-independent-verification.v10',
        'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'distinct_completed_cases': len(known), 'by_family': dict(Counter(r['family_id'] for r in records)),
        'verification_scope': previous['verification_scope'], 'current_catalog': catalog_node,
        'verified_cases': records,
        'inherited_previous_evidence': {'path': str(args.previous.resolve()), 'sha256': sha(args.previous),
                                       'unchanged_scan_and_receipt_SHA_verified': len(previous['verified_cases'])},
        'newly_verified_cases': len(new_records), 'goal_complete': False,
    }
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in ('distinct_completed_cases', 'by_family', 'newly_verified_cases')}))


if __name__ == '__main__':
    main()
