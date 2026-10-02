#!/usr/bin/env python3
"""Read every saved F7 frame with contiguous I/O; compare fixed 0-12s macros."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np

from ds_data02_native_labels import digest


def frame_macro(h, frame, initial_fluid, chunk=65536):
    total = 0.0
    weighted = np.zeros(3)
    kinetic = 0.0
    for lo in range(0, len(initial_fluid), chunk):
        sl = slice(lo, min(len(initial_fluid), lo + chunk))
        if not initial_fluid[sl].any():
            continue
        # Contiguous reads avoid HDF5's large fancy-index selection cost.
        valid = h['valid'][frame, sl].astype(bool)
        mass = h['mass'][frame, sl].astype(np.float64)
        pos = h['position'][frame, sl].astype(np.float64)
        vel = h['velocity'][frame, sl].astype(np.float64)
        good = initial_fluid[sl] & valid
        if np.any(good & (~np.isfinite(mass) | (mass <= 0) |
                          ~np.isfinite(pos).all(axis=1) | ~np.isfinite(vel).all(axis=1))):
            raise ValueError('active fluid state invalid; cannot silently omit from macros')
        m, p, v = mass[good], pos[good], vel[good]
        total += float(m.sum())
        weighted += (m[:, None] * p).sum(axis=0)
        kinetic += float(.5 * np.sum(m * np.sum(v * v, axis=1)))
    if total <= 0:
        raise ValueError('no active fluid mass')
    return [total, *(weighted / total).tolist(), kinetic]


def series(source, output):
    if output.exists():
        raise FileExistsError(output)
    before = digest(source)
    with h5py.File(source, 'r') as h:
        times = h['time'][:]
        if not np.isfinite(times).all() or not np.all(np.diff(times) > 0) or times[0] != 0 or times[-1] < 12:
            raise ValueError('source lacks full 0-12s increasing native timeline')
        fluid = h['initial_type'][:] == 3
        values = [frame_macro(h, frame, fluid) for frame in range(len(times))]
        physical = str(h.attrs['physical_condition_sha256'])
    if digest(source) != before:
        raise ValueError('source mutated during full-frame macro extraction')
    result = {'schema': 'ds02.f7.native-macro-series.v1', 'source': str(source),
              'source_sha256': before, 'physical_condition_sha256': physical,
              'operators': ['active_mass_kg', 'com_x_m', 'com_y_m', 'com_z_m', 'kinetic_energy_j'],
              'time_s': times.tolist(), 'values': values, 'q_n_status': 'not_assessed'}
    output.write_text(json.dumps(result, indent=2) + '\n')
    return result


def compare(baseline, candidates, normalizers, output):
    if output.exists():
        raise FileExistsError(output)
    base = json.loads(baseline.read_text())
    norm = json.loads(normalizers.read_text())
    grid = np.linspace(0, 12, 601)
    def interpolate(d):
        t, v = np.asarray(d['time_s']), np.asarray(d['values'])
        if t[0] != 0 or t[-1] < 12:
            raise ValueError('macro series does not cover full physical window')
        return np.column_stack([np.interp(grid, t, v[:, i]) for i in range(v.shape[1])])
    b = interpolate(base)
    scales = np.array([norm['continuous_initial_mass_kg'], *norm['com_axis_scales_m'], np.max(b[:, 4])])
    if not np.isfinite(scales).all() or (scales <= 0).any():
        raise ValueError('invalid frozen physical normalizers')
    comparisons = {}
    for path in candidates:
        d = json.loads(path.read_text())
        if d['physical_condition_sha256'] != base['physical_condition_sha256']:
            raise ValueError('physical mother differs between references')
        v = interpolate(d)
        errors = np.abs(v - b) / scales
        metrics = {key: {'max_scaled_error': float(errors[:, i].max()),
                         'rms_scaled_error': float(np.sqrt(np.mean(errors[:, i] ** 2))),
                         'scale': float(scales[i])} for i, key in enumerate(base['operators'])}
        metrics['kinetic_time_mean'] = {'scaled_error': float(abs(np.trapz(v[:, 4] - b[:, 4], grid)) / 12 / scales[4])}
        metrics['kinetic_peak'] = {'scaled_error': float(abs(v[:, 4].max() - b[:, 4].max()) / scales[4])}
        # Full paths preserve every reference even when all files share a name.
        comparisons[str(path)] = {'source': d['source'], 'source_sha256': d['source_sha256'], 'metrics': metrics,
                                  'macro_budget_pass': bool((errors.max(axis=0) <= norm['macro_relative_budget']).all())}
    result = {'schema': 'ds02.f7.fixed-window-macro-comparison.v1', 'baseline': str(baseline),
              'baseline_sha256': digest(baseline), 'normalizers': norm, 'normalizers_sha256': digest(normalizers),
              'window_s': [0, 12], 'grid_step_s': .02, 'comparisons': comparisons,
              'q_n_status': 'not_assessed', 'limitation': 'Macro evidence only; transport/spatial reconstruction and independent time/save studies remain required'}
    output.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    s = sub.add_parser('series');s.add_argument('--source', type=Path, required=True);s.add_argument('--output', type=Path, required=True)
    c = sub.add_parser('compare');c.add_argument('--baseline', type=Path, required=True);c.add_argument('--candidate', type=Path, action='append', required=True)
    c.add_argument('--normalizers', type=Path, required=True);c.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    r = series(a.source, a.output) if a.mode == 'series' else compare(a.baseline, a.candidate, a.normalizers, a.output)
    print(json.dumps({'mode': a.mode, 'output': str(a.output), 'q_n_status': r['q_n_status']}))


if __name__ == '__main__':
    main()
