"""Describe actual gauge disagreement without changing the frozen observations."""
import argparse
import csv
import importlib.util
import itertools
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np


def native_gauge(path, node):
    with Path(path).open() as stream:
        rows = list(csv.DictReader(stream, delimiter=';'))
    names = ['time [s]', 'swlz [m]', 'pos0x [m]', 'pos0y [m]', 'pos0z [m]',
             'pos2x [m]', 'pos2y [m]', 'pos2z [m]']
    values = np.array([[float(row[name]) for name in names] for row in rows])
    if len(values) != 800 or not np.isfinite(values).all():
        raise ValueError('Expected all 800 finite native gauge rows')
    times = values[:, 0]
    if times[0] != 0 or times[-1] < 15.98 or not np.all(np.diff(times) > 0):
        raise ValueError('Native gauge does not cover exact observed window')
    p0 = [float(node.find('point0').get(k)) for k in ['x', 'y', 'z']]
    p2 = [float(node.find('point2').get(k)) for k in ['x', 'y', 'z']]
    if (not np.allclose(values[:, 2:5], p0, atol=1e-7, rtol=0)
            or not np.allclose(values[:, 5:8], p2, atol=1e-7, rtol=0)):
        raise ValueError('Native probe geometry differs from execution XML')
    return times, values[:, 1], p0, p2


def vertical_mesh_intersections(path, xy):
    # These campaign meshes are ASCII STL; do not substitute a guessed slope.
    vertices = []
    for line in Path(path).read_text().splitlines():
        words = line.split()
        if words and words[0] == 'vertex':
            vertices.append([float(x) for x in words[1:]])
    if not vertices or len(vertices) % 3:
        raise ValueError('Missing complete ASCII STL triangles')
    hits = []
    for tri in np.asarray(vertices).reshape(-1, 3, 3):
        matrix = np.column_stack((tri[1, :2]-tri[0, :2], tri[2, :2]-tri[0, :2]))
        if abs(np.linalg.det(matrix)) < 1e-12:
            continue
        u, v = np.linalg.solve(matrix, np.asarray(xy)-tri[0, :2])
        if min(u, v, 1-u-v) >= -1e-10:
            hits.append(float((1-u-v)*tri[0, 2]+u*tri[1, 2]+v*tri[2, 2]))
    return sorted(set(round(z, 12) for z in hits))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    binding = json.loads(args.binding.read_text())
    spec = importlib.util.spec_from_file_location('frozen_gauge_reader', binding['frozen_reader'])
    frozen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    grid = np.linspace(0, 15.98, 800)
    results = {}
    for mechanism, series in binding['mechanisms'].items():
        parsed = {}
        geometry = {}
        reported = json.loads(Path(series['prior_report']).read_text())
        for role, item in series['cases'].items():
            receipt = json.loads(Path(item['receipt']).read_text())
            if receipt['status'] != 'completed' or receipt['returncode'] != 0:
                raise ValueError('Actual completed0 native solver required')
            root = ET.parse(item['generated_xml']).getroot()
            constants = root.find('.//execution/constants')
            dp = float(constants.find('dp').get('value'))
            h = float(constants.find('h').get('value'))
            mf = float(constants.find('massfluid').get('value'))
            nodes = {n.get('name'): n for n in root.findall('.//gauges/swl')}
            if set(nodes) != set(item['gauges']):
                raise ValueError('Probe list does not match execution XML')
            parsed[role] = {}
            geometry[role] = {'dp_m': dp, 'generated_h_m': h, 'h_over_dp': h/dp,
                              'kernel_support_2h_m': 2*h, 'xml_massfluid_kg': mf,
                              'native_gauges': {}}
            for name, path in item['gauges'].items():
                times, z, p0, p2 = native_gauge(path, nodes[name])
                parsed[role][name] = (times, z, p0, p2)
                hits = vertical_mesh_intersections(series['bed_stl'], p0[:2])
                geometry[role]['native_gauges'][name] = {
                    'point0_m': p0, 'point2_m': p2, 'initial_native_swlz_m': float(z[0]),
                    'actual_native_window_s': [float(times[0]), float(times[-1])],
                    'STL_vertical_intersections_z_m': hits,
                    'baseline_below_highest_STL_intersection_m': max(hits)-p0[2] if hits else None,
                    'interpretation': 'Vertical scan endpoints; below-bed point0 alone does not prove an invalid probe.'}
        pairs = {}
        for left, right in itertools.combinations(['coarse', 'medium', 'fine'], 2):
            pair = left+'_vs_'+right
            pairs[pair] = {}
            for name in parsed[left]:
                tl, zl, p0l, _ = parsed[left][name]
                tr, zr, p0r, _ = parsed[right][name]
                l, r = np.interp(grid, tl, zl), np.interp(grid, tr, zr)
                initial_offset = float(zl[0]-zr[0])
                # Preserve the frozen operator: eta=z-z(initial), all 800 samples.
                delta = (l-zl[0])-(r-zr[0])
                floor_l, floor_r = l <= p0l[2]+1e-4, r <= p0r[2]+1e-4
                cohorts = {'both_above_floor': ~floor_l & ~floor_r,
                           'one_at_floor': floor_l ^ floor_r,
                           'both_at_floor': floor_l & floor_r}
                sse = float(np.sum(delta**2))
                decomposition = {}
                for label, mask in cohorts.items():
                    count = int(mask.sum())
                    subset_sse = float(np.sum(delta[mask]**2))
                    decomposition[label] = {'samples': count, 'sum_squared_difference_m2': subset_sse,
                        'fraction_of_total_SSE': subset_sse/sse if sse else None,
                        'contribution_to_global_MSE_m2': subset_sse/len(grid),
                        'conditional_RMSE_m': float(np.sqrt(subset_sse/count)) if count else None}
                rmse = float(np.sqrt(sse/len(grid)))
                old = reported['pairwise_comparisons'][pair]['gauges'][name]
                if (not np.isclose(rmse, old['normalized_eta_rmse_m'], atol=1e-12, rtol=1e-12)
                        or not np.isclose(initial_offset, old['initial_offset_m'], atol=1e-12, rtol=0)):
                    raise ValueError('Diagnostic changed frozen observed samples or initial offset')
                pairs[pair][name] = {'observed_initial_offset_m': initial_offset,
                    'global_frozen_eta_RMSE_m': rmse, 'global_frozen_eta_RMSE_over_H': rmse/.4,
                    'unchanged_original_5pct_gate': old['pass_5pct_overall'],
                    'cohorts': decomposition, 'causal_claim': 'none; conditional error contribution is descriptive.'}
        results[mechanism] = {'execution_geometry': geometry, 'pairs': pairs}
    result = {'schema': 'ds02.F5.actual-native-gauge-cohort-diagnostic.v1',
              'source_binding': binding, 'observed_window_s': [0, 15.98],
              'full_solver_window_s': [0, 16], 'mechanisms': results,
              'q_n_status': 'not_assessed', 'production_approval': 'none',
              'limitations': ['Native gauge-floor status is not proof of physical dryness or absence of every fluid particle.',
                              'Conditional subsets do not replace the original all-sample budget.',
                              'A probe starts below the bed to scan for a mass threshold transition.',
                              'No assumed boundary thickness, initial node shift, or causal repair is inferred.']}
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({mech: data['pairs']['medium_vs_fine']['WG3'] for mech, data in results.items()}))


if __name__ == '__main__':
    main()
