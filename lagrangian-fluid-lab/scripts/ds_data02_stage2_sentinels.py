"""Prepare 14 existing reference cases from actual XML, argv, and native step logs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from ds_data02_runtime_v2 import atomic_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(sentinel, row):
    xml = Path(row['source_bindings']['generated_xml']['path'])
    root = ET.parse(xml).getroot()
    constants = {n.tag: dict(n.attrib) for n in root.findall('./execution/constants/*')}
    parameters = {n.attrib['key']: n.attrib['value'] for n in root.findall('./execution/parameters/parameter')}
    solver_receipt = Path(row['source_bindings']['solver_receipt']['path'])
    receipt = json.loads(solver_receipt.read_text())
    raw = Path(row['raw_root']['path'])
    runparts = raw.parent / 'RunPARTs.csv'
    lines = [s for s in runparts.read_text().splitlines() if s.strip() and not s.lstrip().startswith('#')]
    parts = list(csv.DictReader(lines, delimiter=';'))
    min_steps = [float(r['DtMin [s]']) for r in parts if float(r['DtMin [s]']) > 0]
    max_steps = [float(r['DtMax [s]']) for r in parts if float(r['DtMax [s]']) > 0]
    actual_dp = float(constants['dp']['value'])
    actual_cfl = float(constants['cflnumber']['value'])
    mismatches = []
    if actual_dp != sentinel['actual_dp_m']:
        mismatches.append('proposed_baseline_dp_differs_from_generated_XML')
    if actual_cfl != sentinel['baseline_cfl']:
        mismatches.append('proposed_baseline_CFL_differs_from_generated_XML')
    if len(parts) != row['frames']:
        mismatches.append('native_saved_frame_count_differs_from_typed')
    xml_hash = digest(xml)
    if xml_hash != row['source_bindings']['generated_xml']['sha256']:
        mismatches.append('generated_XML_hash_changed')
    h = constants.get('h', {}).get('value')
    controls = []
    for name, expected in receipt.get('input_hashes_at_launch', {}).items():
        path = Path(name)
        if path.suffix.lower() in ('.csv', '.dat'):
            controls.append(dict(path=name, producer_declared_sha256=expected,
                                 recomputed_sha256=digest(path) if path.is_file() else None))
    return dict(sentinel_id=sentinel['sentinel_id'], family_id=row['family_id'],
                physical_case_id=row['physical_case_id'], status='INPUT_REVIEWED' if not mismatches else 'INPUT_MISMATCH',
                mismatches=mismatches, generated_xml=dict(path=str(xml), recomputed_sha256=xml_hash),
                raw_constants=constants, raw_parameters=parameters,
                actual_dp_m=actual_dp, actual_cfl=actual_cfl, actual_h_over_dp=float(h)/actual_dp if h else None,
                actual_solver_command=receipt.get('command'),
                historical_native_status=receipt.get('status'), historical_native_returncode=receipt.get('returncode'),
                historical_launch_code=receipt.get('runner_git_at_launch'),
                controls=controls, coordinate_frame=row['header']['coordinate_frame'], units=row['header']['units'],
                native_step_evidence=dict(path=str(runparts), recomputed_sha256=digest(runparts),
                    saved_rows=len(parts), minimum_positive_step_s=min(min_steps) if min_steps else None,
                    maximum_positive_step_s=max(max_steps) if max_steps else None,
                    DTsMin_sum=sum(int(r['DTsMin'].replace(',', '')) for r in parts),
                    interpretation='Saved-interval native min/max and minimum-step counters; not a half-CFL experiment.'),
                proposed_spacing_m=sentinel['proposed_spacing_m'], proposed_dense_cadence_s=sentinel['proposed_dense_cadence_s'],
                proposed_half_cfl=sentinel['proposed_half_cfl'], numerical_credit='NOT_ASSESSED',
                next_gate='Actual initial-state equivalence and observer calibration before any new reference launch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--matrix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve completed reference preparation')
    catalog = {r['physical_case_id']: r for r in json.loads(args.catalog.read_text())['cases']}
    rows = []
    for sentinel in json.loads(args.matrix.read_text())['sentinels']:
        try:
            rows.append(inspect(sentinel, catalog[sentinel['source_physical_case_id']]))
        except (OSError, KeyError, ValueError) as error:
            rows.append(dict(sentinel_id=sentinel['sentinel_id'], status='EVIDENCE_UNKNOWN', error=str(error)))
    result = dict(schema='ds02.stage2.sentinel-input-review.v1', sentinels=rows,
                  scope='Actual generated recipe, launch argv, source hashes and native step logs; no initial-state/raw-typed alignment or numerical qualification yet.')
    atomic_json(args.output, result)
    print(json.dumps(dict(sentinels=len(rows), statuses={s:sum(r['status']==s for r in rows) for s in {r['status'] for r in rows}})))


if __name__ == '__main__':
    main()
