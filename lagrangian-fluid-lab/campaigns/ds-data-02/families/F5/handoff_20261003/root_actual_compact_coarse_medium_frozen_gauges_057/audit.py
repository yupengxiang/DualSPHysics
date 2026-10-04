"""Compare every frozen native probe; preserve dry codes and native exclusions."""
import argparse
import importlib.util
import itertools
import json
from pathlib import Path

import numpy as np


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    b = json.loads(args.binding.read_text())
    r = json.loads(Path(b['registration']).read_text())
    reader = module('frozen_f5_probe_reader', b['reader'])
    telemetry = module('native_f5_telemetry', b['telemetry'])
    assert set(r['native_probe_names']) == set(reader.EXPECTED_GAUGES)
    assert r['spatial_budget_fraction'] == .05 and r['physical_depth_H_m'] == .4
    results = []
    for mechanism in b['mechanisms']:
        records = {}
        parsed = {}
        for role, item in mechanism['cases'].items():
            records[role] = telemetry.audit(item)
            assert records[role]['CFLnumber'] == .2
            assert records[role]['step_algorithm'] == '2'
            assert float(records[role]['CoefDtMin']) == .05
            assert len(list(Path(item['raw_root']).glob('Part_*.bi4'))) == 801
            parsed[role] = {}
            for name in r['native_probe_names']:
                path = Path(item['gauges'][name])
                lines = path.read_text().splitlines()
                assert lines[0] == 'time [s];swlx [m];swly [m];swlz [m];pos0x [m];pos0y [m];pos0z [m];pos2x [m];pos2y [m];pos2z [m]'
                raw = np.asarray([[float(x) for x in row.split(';')] for row in lines[1:]])
                assert raw.shape == (800, 10) and np.isfinite(raw).all()
                gauge = reader.parse_gauge_csv(path, expected_rows=800)
                offset = gauge['times'] - np.arange(800) * .02
                assert (offset >= -.5e-6).all()
                assert (offset <= records[role]['dt_max_s'] + .5e-6).all()
                parsed[role][name] = gauge
        pairs = []
        for left, right in itertools.combinations(mechanism['cases'], 2):
            comparisons = []
            for name in r['native_probe_names']:
                result = reader.compare_two_gauges(parsed[left][name], parsed[right][name],
                                                  gauge_name=name, h_ref_m=.4, tol_relative=.05)
                result['within_frozen_spatial_RMS'] = result['relative_eta_rmse'] <= .05
                result['within_frozen_spatial_maximum'] = result['relative_eta_max_abs'] <= .05
                comparisons.append(result)
            pairs.append({'left': left, 'right': right, 'gauges': comparisons,
                          'all_six_probes_within_frozen_allocation': all(
                              x['within_frozen_spatial_RMS'] and x['within_frozen_spatial_maximum']
                              for x in comparisons)})
        results.append({'mechanism': mechanism['name'], 'native_telemetry': records, 'pairs': pairs})
    output = {'schema': 'ds02.f5.actual-compact-frozen-all-probe-spatial.v1',
              'binding': b, 'registration': r, 'mechanisms': results,
              'full_solver_window_s': [0, 16], 'native_probe_grid_s': [0, 15.98],
              'normalization': 'Unchanged prior frozen probe operator: eta(t)=nativeSWL(t)-nativeSWL(0), RMS/H and maximumabs/H; raw SWL discrepancy and dry diagnostics also retained.',
              'limitations': ['All registered probes evaluated; native dry codes included without masking.',
                              'Coarse/medium comparison alone is incomplete three-resolution evidence.',
                              'Native exclusions retain unknown physical fate; no mass rescaling.',
                              'Independent integration/save, actual transport, domain, and products remain pending.'],
              'q_n': 'not_granted', 'production_approval': 'none', 'independent_case_count_increment': 0}
    with args.output.open('x') as stream:
        stream.write(json.dumps(output, indent=2) + '\n')
    print(json.dumps({x['mechanism']: x['pairs'][0]['all_six_probes_within_frozen_allocation']
                      for x in results}))


if __name__ == '__main__':
    main()
