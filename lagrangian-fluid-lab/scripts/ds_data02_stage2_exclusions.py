"""Reconcile full typed missing-fluid identities with native PartOut/RunPARTs."""
import argparse
from collections import Counter
import json
from pathlib import Path

from ds_data02_handoff_exclusions import read_partout, read_runparts
from ds_data02_runtime_v2 import atomic_json


def reconcile(scan, records, runparts):
    failures = []
    times = scan['time_s']
    native_times = [r['time_s'] for r in runparts['rows']]
    if len(times) != len(native_times):
        failures.append('native_saved_timeline_length_mismatch')
        max_time_delta = None
    else:
        max_time_delta = max(abs(a - b) for a, b in zip(times, native_times))
        if max_time_delta > 1e-8 * max(1, max(times)):
            failures.append('native_saved_time_mismatch')
    fluid = [r for r in scan['missing_id_records'] if r['type_code'] == 3]
    by_id = {}
    for r in fluid:
        by_id.setdefault(r['idp'], []).append(r)
    joined, unresolved, used = [], [], set()
    for raw in records:
        matches = by_id.get(raw['idp'], [])
        if len(matches) != 1:
            unresolved.append(dict(native_record=raw, reason='missing_or_ambiguous_typed_fluid_identity'))
            continue
        r = matches[0]
        key = (r['zone'], r['idp'])
        if key in used:
            unresolved.append(dict(native_record=raw, reason='duplicate_native_identity'))
            continue
        used.add(key)
        if r['first_missing_frame'] != raw['part_out']:
            unresolved.append(dict(native_record=raw, typed_record=r, reason='first_missing_frame_mismatch'))
            continue
        joined.append(dict(r, native_exit_cause='NUMERICAL_' + raw['motive'].upper() + '_EXCLUSION',
                           native_record=raw, physical_fate='UNKNOWN', legal_outflow_proven=False))
    if len(joined) != len(fluid):
        failures.append('not_all_missing_fluid_ids_joined')
    if unresolved:
        failures.append('unresolved_native_records')
    counts = Counter(r['motive_code'] for r in records)
    totals = runparts['totals']
    if totals['NpOut'] != len(records) or any(totals[k] != counts[v] for k, v in
            [('NpOutPos', 1), ('NpOutRho', 2), ('NpOutMov', 3)]):
        failures.append('PartOut_RunPARTs_motive_counts_mismatch')
    ledger = scan['type_ledgers']['fluid']
    if ledger['revived_unique_ids'] or ledger['births_unique_ids'] or ledger['initially_absent_count']:
        failures.append('lifecycle_beyond_simple_numerical_exclusion')
    return dict(schema='ds02.stage2.native-exclusion-reconciliation.v1',
                family_id=scan['family_id'], physical_case_id=scan['physical_case_id'],
                status='CAUSES_RECONCILED' if not failures else 'EVIDENCE_UNKNOWN',
                failures=failures, native_saved_time_max_delta_s=max_time_delta,
                initial_fluid_mass_kg=ledger['typed_initial_mass_kg'],
                native_motive_counts=dict(position=counts[1], density=counts[2], movement=counts[3]),
                runparts_totals=totals, typed_unique_missing=len(fluid), joined_count=len(joined),
                joined_initial_mass_kg=sum(r['initial_mass_kg'] for r in joined),
                missing_fluid_ids=joined, unresolved_native_records=unresolved,
                physical_fate='UNKNOWN; numerical exclusion is not proof of physical spill',
                dynamical_impact='NOT_ASSESSED; requires a paired reference or repair experiment',
                QN='NOT_ASSESSED', QE='NOT_ASSESSED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan', type=Path, required=True)
    parser.add_argument('--partout', type=Path, required=True)
    parser.add_argument('--runparts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve existing evidence')
    result = reconcile(json.loads(args.scan.read_text()), read_partout(args.partout), read_runparts(args.runparts))
    atomic_json(args.output, result)
    print(json.dumps(dict(status=result['status'], joined=result['joined_count'],
                         motives=result['native_motive_counts'], failures=result['failures'])))


if __name__ == '__main__':
    main()
