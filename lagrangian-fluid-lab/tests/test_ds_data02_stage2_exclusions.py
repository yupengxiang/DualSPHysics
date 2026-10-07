from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_stage2_exclusions import reconcile


def example():
    scan = dict(family_id='F2', physical_case_id='pour', time_s=[0., 1.],
                missing_id_records=[dict(idp=7, zone=0, type_code=3, first_missing_frame=1, initial_mass_kg=2.)],
                type_ledgers=dict(fluid=dict(typed_initial_mass_kg=100., revived_unique_ids=0,
                                             births_unique_ids=0, initially_absent_count=0)))
    native = [dict(idp=7, part_out=1, motive_code=2, motive='density')]
    runparts = dict(rows=[dict(time_s=0.), dict(time_s=1.)],
                    totals=dict(NpOut=1, NpOutPos=0, NpOutRho=1, NpOutMov=0))
    return scan, native, runparts


def test_known_numerical_cause_does_not_grant_physical_fate_or_precision():
    r = reconcile(*example())
    assert r['status'] == 'CAUSES_RECONCILED'
    assert r['missing_fluid_ids'][0]['native_exit_cause'] == 'NUMERICAL_DENSITY_EXCLUSION'
    assert r['missing_fluid_ids'][0]['physical_fate'] == 'UNKNOWN'
    assert not r['missing_fluid_ids'][0]['legal_outflow_proven']
    assert r['QN'] == 'NOT_ASSESSED'


def test_ambiguous_zone_cannot_be_invented():
    scan, records, parts = example()
    scan['missing_id_records'].append(dict(scan['missing_id_records'][0], zone=1))
    r = reconcile(scan, records, parts)
    assert r['status'] == 'EVIDENCE_UNKNOWN'
    assert r['joined_count'] == 0


def test_wrong_first_gap_and_wrong_native_counts_stay_unknown():
    scan, records, parts = example()
    records[0]['part_out'] = 0
    parts['totals']['NpOut'] = 2
    r = reconcile(scan, records, parts)
    assert r['status'] == 'EVIDENCE_UNKNOWN'
    assert 'PartOut_RunPARTs_motive_counts_mismatch' in r['failures']
