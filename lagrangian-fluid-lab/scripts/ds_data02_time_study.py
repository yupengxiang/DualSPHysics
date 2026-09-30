#!/usr/bin/env python3
"""Measure actual native step bounds and prepare independent F1 time controls.

RunPARTs stores interval extrema, not the distribution of every internal step.
No median integration step or numerical qualification is inferred here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
from scripts import ds_data02_f1 as f1


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def measure(path):
    with Path(path).open() as stream:
        rows = list(csv.DictReader((line for line in stream if line.strip() and not line.startswith('#')), delimiter=';'))
    samples = [r for r in rows if float(r['TimeStep [s]']) > 0]
    if not samples:
        raise ValueError('no positive-time integration evidence')
    minimum = min(float(r['DtMin [s]']) for r in samples)
    maximum = max(float(r['DtMax [s]']) for r in samples)
    if minimum <= 0 or maximum < minimum:
        raise ValueError('invalid native step bounds')
    if any(int(r['NpOut'].replace(',', '')) for r in samples):
        raise ValueError('excluded-particle baseline is not a stable time-study anchor')
    return dict(native_minimum_dt_s=minimum, native_maximum_dt_s=maximum,
                internal_step_count=sum(int(r['Steps'].replace(',', '')) for r in samples),
                final_time_s=float(samples[-1]['TimeStep [s]']), saved_frame_count=len(rows),
                minimum_interval_steps=min(int(r['Steps'].replace(',', '')) for r in samples),
                median_internal_dt_s=None,
                measurement_semantics='min/max are actual per-save-interval extrema; every-step distribution unavailable',
                source=str(Path(path).resolve()), source_sha256=digest(path))


def prepare_f1(receipt_path, output):
    receipt_path = Path(receipt_path).resolve()
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
        raise ValueError('time study requires a completed baseline')
    if receipt.get('request', {}).get('case_id') != 'F1_REF_ECC_NOMINAL_FINE':
        raise ValueError('baseline must be the identical F1 fine eccentric physical reference')
    csv_paths = list(receipt_path.parent.rglob('RunPARTs.csv'))
    if len(csv_paths) != 1:
        raise ValueError('baseline RunPARTs is ambiguous or missing')
    evidence = measure(csv_paths[0])
    if evidence['final_time_s'] < 1.6:
        raise ValueError('F1 eccentric baseline does not cover the complete event')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('never overwrite a registered time-study directory')
    output.mkdir(parents=True)
    requests = []
    for mode in ('half_actual_dt', 'dense_save'):
        case_id = 'F1_REF_ECC_NOMINAL_FINE_' + mode.upper()
        case = f1.make_case('eccentric_obstacle', 'fine', case_id=case_id,
                            physical_case_id='F1_REF_ECC_NOMINAL', paired_background_id='F1_REF_PAIR_NOMINAL')
        case['study_role'] = mode
        case['time_study_baseline_receipt'] = str(receipt_path)
        case['time_study_baseline_receipt_sha256'] = digest(receipt_path)
        case['baseline_actual_internal_steps'] = evidence
        case['physical_case_count_increment'] = 0
        case['qualification_claim'] = 'none; comparison and event evidence still required'
        if mode == 'half_actual_dt':
            case['solver_parameters']['DtFixed'] = evidence['native_minimum_dt_s'] / 2
        else:
            case['solver_parameters']['TimeOut'] = '0.001'
            case['event_window']['save_interval_s'] = 0.001
        row = f1.write_case(case, output / 'definitions')
        request = dict(family_id='F1', case_id=case_id, attempt_id='gencase-time-study-001',
                       kind='cpu', cpu_task_kind='gencase',
                       command=[str(f1.DEFAULT_READ_ONLY_LAB / 'vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64'),
                                str(Path(row['definition_path']).with_suffix('')), '{attempt_root}/' + case_id, '-save:all'],
                       cwd=str(f1.DEFAULT_READ_ONLY_LAB / 'vendor/official/DualSPHysics_v5.4/bin/linux'),
                       worktree_root=str(LAB.parent), max_wall_seconds=120, cpu_threads=4,
                       estimated_storage_bytes=268435456,
                       input_files=[row['definition_path'], row['metadata_path'], str(Path(__file__).resolve()),
                                    str(Path(f1.__file__).resolve()), str(receipt_path), str(csv_paths[0])])
        path = output / (mode + '-gencase.json')
        path.write_text(json.dumps(request, indent=2) + '\n')
        requests.append(str(path))
    (output / 'study.json').write_text(json.dumps(dict(schema='ds02.time-study-registration.v1',
        physical_case_id='F1_REF_ECC_NOMINAL', independent_physical_case_increment=0,
        baseline_receipt=str(receipt_path), baseline_receipt_sha256=digest(receipt_path),
        baseline_measurement=evidence, requests=requests,
        comparison_requirements=['same continuous geometry/initial state/control and full 1.6s window',
            'fixed variant actual dt maximum <= half baseline measured minimum, with native step counts',
            'dense-save variant retains native adaptive settings; output count is not internal step count',
            'compare preregistered macro observables and event intervals against frozen budgets',
            'spatial qualification remains independent and pending']), indent=2) + '\n')
    return requests


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-receipt', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--measure', type=Path)
    args = parser.parse_args()
    if args.measure:
        print(json.dumps(measure(args.measure), indent=2))
    else:
        print(json.dumps(prepare_f1(args.baseline_receipt, args.output), indent=2))
