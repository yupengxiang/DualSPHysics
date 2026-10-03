"""Compare all DROP contact brackets with the original DROP budgets."""
import argparse
from itertools import combinations
import json
import math
from pathlib import Path


def separation(first, second):
    x, y = first, second
    if (len(x) != 2 or len(y) != 2 or not all(math.isfinite(v) for v in x + y)
            or x[0] >= x[1] or y[0] >= y[1]):
        raise ValueError('Invalid observed contact brackets')
    return max(0., x[0] - y[1], y[0] - x[1]), max(abs(x[0] - y[1]), abs(x[1] - y[0]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    binding = json.loads(args.binding.read_text())
    contract = json.loads(Path(binding['frozen']).read_text())['budgets']['DROP']
    whole = contract['original_scale_contract']['event_time_error_budget_s']
    save = whole * contract['original_scale_contract']['temporal_allocation_each_fraction']
    reports = {}
    for role, item in binding['resolutions'].items():
        report = json.loads(Path(item['report']).read_text())
        receipt = json.loads(Path(item['receipt']).read_text())
        if receipt['status'] != 'completed' or receipt['returncode'] != 0:
            raise ValueError('Unfinished actual contact extraction')
        times = report['time_s']
        if (len(times) != 1201 or times[0] != 0 or times[-1] < 1.2
                or not all(math.isfinite(t) for t in times)
                or not all(a < b for a, b in zip(times, times[1:]))):
            raise ValueError('Missing full1201 native timeline')
        if report['registered_protocol'] != contract['current_operator_protocol']['physical_support']:
            raise ValueError('Different contact operator or support threshold')
        if report['first_contact']['status'] != 'observed':
            raise ValueError('Observed initial contact required; retain censoring separately')
        reports[role] = report
    if len({r['physical_binding_sha256'] for r in reports.values()}) != 1:
        raise ValueError('Continuous physical mothers differ')
    comparisons = {}
    for first, second in combinations(reports, 2):
        a, b = reports[first]['first_contact'], reports[second]['first_contact']
        low, high = separation(a['bracket_s'], b['bracket_s'])
        comparisons[first + '_vs_' + second] = {
            'first_contact': [a, b], 'minimum_possible_separation_s': low,
            'maximum_possible_separation_s': high,
            'whole_DROP_event_budget_s': whole,
            'observed_right_endpoint_difference_s': abs(a['time_s'] - b['time_s']),
            'status': ('fail_even_allowing_saved_brackets' if low > whole
                       else 'within_whole_budget_for_all_bracket_values' if high <= whole
                       else 'unresolved_by_saved_brackets'),
            'save_half_width_s': [(r['bracket_s'][1] - r['bracket_s'][0]) / 2 for r in [a, b]],
            'registered_each_save_allocation_s': save,
            'native_exclusions_remain_unknown': True,
            'final_unknown_native_mass_kg': [reports[k]['unknown_native_exclusion_mass_kg'][-1] for k in [first, second]],
        }
    result = {'schema': 'ds02.f4.actual-three-dp-DROP-contact-comparison.v1',
              'window_s': [0, 1.2], 'registered_mechanism': 'DROP',
              'binding': binding, 'comparisons': comparisons,
              'recontact_by_resolution': {k: v['recontact'] for k, v in reports.items()},
              'q_n_status': 'not_assessed', 'production_approval': 'none',
              'limitations': ['Discrete saved support-onset intervals; no unsaved contact reconstruction.',
                              'Unresolved bracket overlap is not a numerical-reference pass.',
                              'Complete macros, transport, reconstruction and independent integration/save remain separate.']}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v['status'] for k, v in comparisons.items()}))


if __name__ == '__main__':
    main()
