"""Source-bound heave and initial body-lattice diagnostics, without Q-N claims."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from ds_data02_finite_faces_v1 import bound_vtk_points


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_heave(path):
    rows = list(csv.DictReader(Path(path).open(), delimiter=';'))
    time = np.array([float(row['time [s]']) for row in rows])
    heave = np.array([float(row['heave [m]']) for row in rows])
    if (len(rows) != 241 or time[0] != 0 or time[-1] < 12 or
            not np.isfinite(time).all() or not np.isfinite(heave).all() or
            not np.all(np.diff(time) > 0) or
            [int(row['part']) for row in rows] != list(range(241))):
        raise ValueError('Complete finite 241-frame rigid-state window required')
    return time, heave


def compare(first, second, denominator):
    if denominator <= 0 or not np.isfinite(denominator):
        raise ValueError('Positive frozen original-reference scale required')
    grid = np.linspace(0, 12, 241)
    for time, values in (first, second):
        if time[0] > grid[0] or time[-1] < grid[-1]:
            raise ValueError('Extrapolation forbidden')
    delta = np.interp(grid, *first) - np.interp(grid, *second)
    return {'rmse_m': float(np.sqrt(np.mean(delta**2))),
            'max_abs_m': float(np.max(np.abs(delta))),
            'rmse_relative_to_frozen_dp025_peak': float(np.sqrt(np.mean(delta**2)) / denominator)}


def run(config_path, output):
    config = json.loads(config_path.read_text())
    paths = {str(config_path), config['frozen_comparison']}
    for mechanism in config['rigid_csv'].values():
        for source in mechanism.values():
            paths.update([source['csv'], source['receipt']])
    for row in config['initial_body_sources']:
        paths.update([row['xml'], row['bound_vtk']])
    before = {p: digest(p) for p in sorted(paths)}
    frozen = json.loads(Path(config['frozen_comparison']).read_text())
    if frozen['macro_budget_relative_rmse'] != .05:
        raise ValueError('Original frozen 5% budget differs')
    result = {'schema': 'ds02.f6.actual-heave-body-lattice-diagnostic.v1',
              'source_sha256': before, 'window_s': [0, 12], 'heave': {},
              'initial_body_lattice': [], 'q_n_status': 'not_assessed',
              'production_approval': 'none',
              'limitations': ['Heave is one observable, not full numerical qualification',
                             'Body point-centroid offsets are observations; causal hydrodynamic attribution remains untested',
                             'N*dp^3 is a lattice-count proxy, not measured displaced volume',
                             'Original coarse and repaired medium/fine source recipes are reported explicitly; matching discretization requires review']}
    for mechanism, sources in config['rigid_csv'].items():
        arrays = {}
        for role, source in sources.items():
            receipt = json.loads(Path(source['receipt']).read_text())
            if (receipt.get('status'), receipt.get('returncode')) != ('completed', 0):
                raise ValueError('Terminal successful rigid extraction required')
            arrays[role] = read_heave(source['csv'])
        scale = frozen['comparisons'][mechanism + '_fine_vs_dp025']['heave_m']['reference_peak_abs']
        if abs(float(abs(arrays['coarse'][1]).max()) - scale) > 1e-12:
            raise ValueError('Coarse source differs from frozen peak')
        pairs = {a + '_vs_' + b: compare(arrays[a], arrays[b], scale)
                 for a, b in [('coarse', 'medium'), ('medium', 'fine'), ('coarse', 'fine')]}
        for row in pairs.values():
            row['within_heave_5pct_budget'] = row['rmse_relative_to_frozen_dp025_peak'] <= .05
        result['heave'][mechanism] = {'original_dp025_peak_m': scale, 'pairs': pairs}
    for source in config['initial_body_sources']:
        root = ET.parse(source['xml']).getroot()
        dp = float(root.find('./execution/constants/dp').get('value'))
        group = root.find('./execution/particles/floating')
        declared = root.find('./casedef/floatings/floating/center')
        center = np.array([float(declared.get(axis)) for axis in 'xyz'])
        points, types = bound_vtk_points(source['bound_vtk'])
        body = points[types == 2]
        if len(body) != int(group.get('count')):
            raise ValueError('Native floating identity count differs')
        result['initial_body_lattice'].append({
            'role': source['role'], 'source': source, 'dp_m': dp,
            'type2_count': len(body), 'point_min_m': body.min(0).tolist(),
            'point_max_m': body.max(0).tolist(), 'point_centroid_m': body.mean(0).tolist(),
            'declared_rigid_center_m': center.tolist(),
            'point_centroid_minus_declared_center_m': (body.mean(0) - center).tolist(),
            'count_times_dp_cubed_proxy_m3': len(body)*dp**3})
    if before != {p: digest(p) for p in sorted(paths)}:
        raise ValueError('Consumed source changed during diagnosis')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.open('x').write(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.config, args.output)
    print(json.dumps(result['heave']))
