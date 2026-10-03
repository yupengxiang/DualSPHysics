"""Measure native interval counters for completed F5/F6 reference solvers."""
import argparse
import csv
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def audit(item):
    receipt = json.loads(Path(item['receipt']).read_text())
    if receipt['status'] != 'completed' or receipt['returncode'] != 0:
        raise ValueError('Completed0 actual native solver required')
    with Path(item['run_parts']).open() as stream:
        rows = [r for r in csv.DictReader(stream, delimiter=';') if r.get('Part', '').isdigit()]
    if (len(rows) != item['expected_frames']
            or [int(r['Part']) for r in rows] != list(range(item['expected_frames']))):
        raise ValueError('Missing or noncontiguous native saved parts')
    times = [float(r['TimeStep [s]']) for r in rows]
    if (not all(math.isfinite(t) for t in times) or times[0] != 0
            or times[-1] < item['time_max_s'] or not all(a < b for a, b in zip(times, times[1:]))):
        raise ValueError('Missing full native window')
    integers = lambda key: [int(r[key].replace(',', '')) for r in rows]
    steps, clamps, exclusions = [integers(key) for key in ['Steps', 'DTsMin', 'NpOut']]
    if any(n < 0 for values in [steps, clamps, exclusions] for n in values):
        raise ValueError('Negative native interval counter')
    active = [r for r in rows if float(r['DtMin [s]']) > 0]
    if not active or sum(steps) <= 0:
        raise ValueError('No active native integration telemetry')
    dt_min = min(float(r['DtMin [s]']) for r in active)
    dt_max = max(float(r['DtMax [s]']) for r in active)
    if not math.isfinite(dt_min) or not math.isfinite(dt_max) or not 0 < dt_min <= dt_max:
        raise ValueError('Invalid native integration timestep range')
    root = ET.parse(item['generated_xml']).getroot()
    params = {n.get('key'): n.get('value') for n in root.findall('.//execution/parameters/parameter')}
    cfl_node = root.find('.//execution/constants/cflnumber')
    intervals = [b-a for a, b in zip(times, times[1:])]
    symplectic = params.get('StepAlgorithm') == '2'
    return {'family_id': item['family_id'], 'case_id': item['case_id'],
            'frames': len(rows), 'actual_native_window_s': [times[0], times[-1]],
            'total_interval_steps': sum(steps), 'steps_initial_row': steps[0],
            'steps_after_initial_row': sum(steps[1:]),
            'total_DT_min_adjustments': sum(clamps),
            'interval_rows_with_DT_min_adjustments': sum(n > 0 for n in clamps),
            'maximum_DT_min_adjustments_in_one_saved_interval': max(clamps),
            'symplectic_floor_incidence_fraction': sum(clamps)/(2*sum(steps)) if symplectic else None,
            'denominator': '2*sum actual interval Steps, Symplectic only; not a solver-time fraction',
            'step_algorithm': params.get('StepAlgorithm'),
            'dt_min_s': dt_min, 'dt_max_s': dt_max,
            'native_NpOut_interval_sum': sum(exclusions),
            'native_exclusion_fate': 'unknown; no physical spill inferred',
            'CFLnumber': None if cfl_node is None else float(cfl_node.get('value')),
            'CoefDtMin': params.get('CoefDtMin'), 'DtFixed': params.get('DtFixed'),
            'DtMin': params.get('DtMin'), 'xml_nominal_TimeOut': params.get('TimeOut'),
            'actual_solver_command': receipt['request']['command'],
            'native_save_interval_min_s': min(intervals), 'native_save_interval_max_s': max(intervals),
            'maximum_save_halfwidth_s': max(intervals)/2,
            'causal_claim': 'none; telemetry can eliminate a clamp hypothesis but does not prove another cause',
            'q_n_status': 'not_assessed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    binding = json.loads(args.binding.read_text())
    results = [audit(item) for item in binding['cases']]
    result = {'schema': 'ds02.actual-F5-F6-native-interval-telemetry.v1',
              'cases': results, 'source_binding': binding,
              'q_n_status': 'not_assessed', 'production_approval': 'none',
              'limitations': ['No common new clamp incidence acceptance threshold is invented.',
                              'Every family retains its own registered accuracy budgets.',
                              'Native omission counters do not establish physical particle fates.']}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({r['case_id']: r['total_DT_min_adjustments'] for r in results}))


if __name__ == '__main__':
    main()
