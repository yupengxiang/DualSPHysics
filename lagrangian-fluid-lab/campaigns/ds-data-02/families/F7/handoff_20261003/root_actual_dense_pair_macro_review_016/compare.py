"""Compare full native F7 macro curves using the original registered scales."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

OPERATORS = ['active_mass_kg', 'com_x_m', 'com_y_m', 'com_z_m', 'kinetic_energy_j']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def curve(path, grid):
    data = json.loads(Path(path).read_text())
    times = np.asarray(data['time_s'], dtype=float)
    values = np.asarray(data['values'], dtype=float)
    if (data['operators'] != OPERATORS or times.ndim != 1
            or values.shape != (len(times), 5) or len(times) < 2
            or not np.isfinite(times).all() or not np.isfinite(values).all()
            or not np.all(np.diff(times) > 0) or times[0] != 0 or times[-1] < 12):
        raise ValueError('Invalid or incomplete full-window macro series: ' + str(path))
    if np.any(values[:, 0] <= 0) or np.any(values[:, 4] < 0):
        raise ValueError('Invalid active mass or kinetic energy')
    sampled = np.column_stack([np.interp(grid, times, values[:, i]) for i in range(5)])
    return data, sampled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    binding = json.loads(args.binding.read_text())
    grid = np.linspace(0, 12, 601)
    loaded = {}
    for role in ['baseline', 'candidate']:
        item = binding[role]
        receipt = json.loads(Path(item['receipt']).read_text())
        observation = json.loads(Path(item['observation']).read_text())
        if receipt['status'] != 'completed' or receipt['returncode'] != 0:
            raise ValueError('Macro extraction did not finish successfully')
        if (observation['q_i_status'] != 'Q-I-structure-pass'
                or not observation['copy_verified_before_scientific_audit']
                or not observation['original_stat_unchanged']
                or observation['macro']['sha256'] != digest(item['macro'])):
            raise ValueError('Macro extraction source or integrity evidence mismatch')
        loaded[role] = curve(item['macro'], grid)
    scale_data, scale_curve = curve(binding['original_scale_reference'], grid)
    physical = loaded['baseline'][0]['physical_condition_sha256']
    if any(item[0]['physical_condition_sha256'] != physical for item in loaded.values()):
        raise ValueError('Physical mother differs between integration references')
    if scale_data['physical_condition_sha256'] != physical:
        raise ValueError('Original scale reference has different physical mother')
    normalizers = json.loads(Path(binding['normalizers']).read_text())
    scales = np.asarray([normalizers['continuous_initial_mass_kg'],
                         *normalizers['com_axis_scales_m'], np.max(scale_curve[:, 4])])
    if not np.isfinite(scales).all() or np.any(scales <= 0):
        raise ValueError('Invalid original reference scales')
    baseline = loaded['baseline'][1]
    candidate = loaded['candidate'][1]
    delta = candidate - baseline
    errors = np.abs(delta) / scales
    metrics = {name: {'scale': float(scales[i]),
                      'max_scaled_error': float(errors[:, i].max()),
                      'rms_scaled_error': float(np.sqrt(np.mean(errors[:, i] ** 2))),
                      'max_absolute_difference': float(np.abs(delta[:, i]).max())}
               for i, name in enumerate(OPERATORS)}
    metrics['kinetic_time_mean'] = {'scaled_error': float(abs(np.trapz(delta[:, 4], grid)) / 12 / scales[4])}
    metrics['kinetic_peak'] = {'scaled_error': float(abs(candidate[:, 4].max() - baseline[:, 4].max()) / scales[4])}
    result = {'schema': 'ds02.f7.actual-dense-pair-fixed-scale-macro.v1',
              'binding': str(args.binding), 'binding_sha256': digest(args.binding),
              'physical_condition_sha256': physical, 'window_s': [0, 12],
              'grid_step_s': .02, 'grid_points': len(grid),
              'original_scale_reference': binding['original_scale_reference'],
              'original_scale_reference_sha256': digest(binding['original_scale_reference']),
              'normalizers': normalizers, 'metrics': metrics,
              'macro_budget_pass': bool(np.all(errors.max(axis=0) <= normalizers['macro_relative_budget'])),
              'q_n_status': 'not_assessed', 'production_approval': 'none',
              'limitations': ['Native exclusions remain unknown physical fates.',
                              'Descriptive integration comparison; spatial, transport and save acceptance remain separate.',
                              'Original spatial kinetic energy negative evidence remains retained.']}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'macro_budget_pass': result['macro_budget_pass']}))


if __name__ == '__main__':
    main()
