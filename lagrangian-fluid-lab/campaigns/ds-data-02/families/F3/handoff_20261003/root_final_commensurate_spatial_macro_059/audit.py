"""Historically registered full native spatial comparison with unchanged CELL3 macros."""
import argparse
from contextlib import ExitStack
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile

import h5py
import numpy as np

LAB = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(LAB / 'scripts'))
from ds_data02_f3_nvme_input_audit_v1 import verified_copy


def completed(path):
    receipt = json.loads(Path(path).read_text())
    if receipt['status'] != 'completed' or receipt['returncode'] != 0:
        raise ValueError('Source must be completed0: ' + str(path))


def validate(h, binding, report):
    frames, particles = binding['expected_frames'], binding['expected_particles']
    shapes = {key: (particles,) for key in
              ['particle_id', 'particle_zone', 'initial_type', 'initial_mk', 'initial_mass']}
    shapes.update({key: (frames, particles) for key in ['mass', 'type', 'mk', 'valid', 'density']})
    shapes.update({key: (frames, particles, 3) for key in ['position', 'velocity']})
    shapes['time'] = (frames,)
    for key, shape in shapes.items():
        if key not in h or h[key].shape != shape:
            raise ValueError('Missing or incorrect native dataset: ' + key)
    t = np.asarray(h['time'][:], dtype=float)
    if t[0] != 0 or t[-1] < 8.35 or not np.isfinite(t).all() or not np.all(np.diff(t) > 0):
        raise ValueError('Incomplete native physical time support')
    ids, zones = h['particle_id'][:], h['particle_zone'][:]
    if not np.all(zones == 0) or not np.array_equal(ids, np.arange(particles)):
        raise ValueError('Unexpected or duplicate native identities')
    types = h['initial_type'][:]
    if not np.all(np.isin(types, [0, 3])):
        raise ValueError('Unexpected native cohort type')
    fluid = np.flatnonzero(types == 3)
    if len(fluid) != binding['expected_fluid'] or not np.all(np.diff(fluid) == 1):
        raise ValueError('Unexpected initial fluid cohort')
    mass = np.asarray(h['initial_mass'][:])[fluid]
    # Header JSON is printed with limited decimal digits. Its native value is
    # float32, widened to float64 by the adapter; never use XML rho*dp^3 here.
    header_mass = float(np.float32(report['hash_scopes']['numerical_parameters']['decoder_header_constants']['MassFluid']))
    if not np.all(mass == header_mass) or not np.isfinite(mass).all() or np.any(mass <= 0):
        raise ValueError('Native initial mass differs from actual typed header')
    initial = frame(h, 0, fluid, mass)
    if not np.all(initial[1] == 0):
        raise ValueError('Nonzero initial velocity')
    for axis in range(3):
        if np.unique(initial[0][:, axis]).size < 2:
            raise ValueError('Fluid cohort is not volumetric in XYZ')
    return t, fluid, mass


def frame(h, index, fluid, mass):
    start, stop = int(fluid[0]), int(fluid[-1]) + 1
    valid = h['valid'][index, start:stop]
    m = h['mass'][index, start:stop]
    p = np.asarray(h['position'][index, start:stop, :], dtype=float)
    v = np.asarray(h['velocity'][index, start:stop, :], dtype=float)
    if (not np.all(valid == 1) or not np.array_equal(m, mass)
            or not np.all(h['type'][index, start:stop] == 3)
            or not np.array_equal(h['mk'][index, start:stop], h['initial_mk'][start:stop])
            or not np.isfinite(p).all() or not np.isfinite(v).all()):
        raise ValueError('Closed native fluid state changed or is invalid at frame ' + str(index))
    return p, v


def state(h, times, fluid, mass, target, cache):
    if target < times[0] or target > times[-1]:
        raise ValueError('Physical-grid extrapolation forbidden')
    right = min(int(np.searchsorted(times, target, side='right')), len(times) - 1)
    left = right - 1
    for index in [left, right]:
        if index not in cache:
            cache[index] = frame(h, index, fluid, mass)
    for index in list(cache):
        if index not in [left, right]:
            del cache[index]
    fraction = (target - times[left]) / (times[right] - times[left])
    if not 0 <= fraction <= 1:
        raise ValueError('Unbracketed physical target')
    return tuple(cache[left][i] + fraction * (cache[right][i] - cache[left][i]) for i in [0, 1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    binding = json.loads(args.binding.read_text())
    protocol = json.loads(Path(binding['protocol']).read_text())
    registration = json.loads(Path(binding['registration']).read_text())
    assert registration['additional_refinement_ladder_dp_m'] == [.006,.005,.0045]
    assert registration['spatial_budget_fraction'] == protocol['reference_error_budget'] == .05
    assert registration['physical_window_s'] == [0,8.35] and registration['physical_grid_points'] == 836
    budget = protocol['reference_error_budget']
    spec = importlib.util.spec_from_file_location('frozen_cell3_operator', binding['operator'])
    operator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(operator)
    roles = list(binding['sources'])
    pairs = [(roles[i], roles[j]) for i in range(len(roles)) for j in range(i + 1, len(roles))]
    parent = Path(binding['scratch_parent'])
    parent.mkdir(parents=True, exist_ok=True)
    needed = sum(Path(b['trajectory']).stat().st_size for b in binding['sources'].values())
    stat = os.statvfs(parent)
    if stat.f_bavail * stat.f_frsize < needed + 100 * 1024**3:
        raise ValueError('Insufficient protected NVMe capacity')
    reports = {}
    for role, b in binding['sources'].items():
        completed(b['receipt'])
        reports[role] = json.loads(Path(b['report']).read_text())
        r = reports[role]
        for key in ['gencase_receipt', 'solver_receipt']:
            source = r['source_provenance'][key]
            if hashlib.sha256(Path(source['path']).read_bytes()).hexdigest() != source['sha256']:
                raise ValueError('Upstream source receipt changed: ' + key)
            completed(source['path'])
        if (r['conversion_status'] != 'completed' or r['output_sha256'] != b['sha256']
                or r['frames'] != b['expected_frames'] or r['particles'] != b['expected_particles']
                or r['solver_dimension']['solver_dimension'] != 3
                or not r['partvtk_validation']['all_passed']
                or [v['frame'] for v in r['partvtk_validation']['frames']] != [0, 418, 835]):
            raise ValueError('Incomplete actual typed conversion evidence: ' + role)
    if len({r['hash_scopes']['physical_condition_sha256'] for r in reports.values()}) != 1:
        raise ValueError('Continuum physical binding differs')
    history = {'-vs-'.join(pair): [] for pair in pairs}
    initial_mass, native_times = {}, {}
    with tempfile.TemporaryDirectory(prefix='ds02-f3-spatial-027-', dir=parent) as tmp, ExitStack() as stack:
        handles, inputs, caches = {}, {}, {role: {} for role in roles}
        for role, b in binding['sources'].items():
            target = Path(tmp) / (role + '.h5')
            verified_copy(Path(b['trajectory']), target, b['sha256'])
            handles[role] = stack.enter_context(h5py.File(target, 'r'))
            if handles[role].attrs['physical_condition_sha256'] != reports[role]['hash_scopes']['physical_condition_sha256']:
                raise ValueError('HDF5 physical binding differs from report')
            inputs[role] = validate(handles[role], b, reports[role])
            t, fluid, mass = inputs[role]
            initial_mass[role] = float(mass.astype(float).sum())
            native_times[role] = {'first_s': float(t[0]), 'last_s': float(t[-1]), 'frames': len(t)}
            # Check every native frame, including the terminal overshoot,
            # rather than relying only on samples on the physical grid.
            for index in range(len(t)):
                frame(handles[role], index, fluid, mass)
            print(json.dumps({'stage': 'full-native-fluid-state-verified', 'role': role}), flush=True)
        grid = np.linspace(0, 8.35, binding['grid_points'])
        for index, target in enumerate(grid):
            observed = {}
            for role in roles:
                t, fluid, mass = inputs[role]
                p, v = state(handles[role], t, fluid, mass, target, caches[role])
                observed[role] = operator.observe_arrays(p, v, mass, initial_mass[role])
            for a, b in pairs:
                row = operator.compare(observed[a], observed[b])
                if not all(np.isfinite(x) and x >= 0 for x in row.values()):
                    raise ValueError('Invalid macro discrepancy')
                history[a + '-vs-' + b].append({'time_s': float(target), **row})
            if index % 100 == 0:
                print(json.dumps({'stage': 'physical-grid-macros', 'index': index}), flush=True)
        metrics = {}
        for pair, rows in history.items():
            metrics[pair] = {}
            for name in rows[0]:
                if name == 'time_s':
                    continue
                values = np.asarray([r[name] for r in rows])
                metrics[pair][name] = {'maximum_deviation': float(values.max()),
                                      'time_at_maximum_s': float(grid[int(values.argmax())]),
                                      'rms_deviation': float(np.sqrt(np.mean(values**2))),
                                      'within_frozen_spatial_budget': bool(values.max() <= budget)}
    result = {'schema': 'ds02.f3.actual-adaptive-spatial-macro.v1', 'binding': binding,
              'window_s': [0, 8.35], 'grid_points': binding['grid_points'],
              'initial_native_mass_kg': initial_mass, 'native_times': native_times,
              'metrics': metrics, 'history': history, 'frozen_spatial_budget': budget,
              'pair_macro_budget_pass': {pair: all(v['within_frozen_spatial_budget'] for v in rows.values())
                                         for pair, rows in metrics.items()},
              'copy_verified_before_use': True, 'private_scratch_removed': True,
              'q_n_status': 'not_granted', 'production_approval': 'none',
              'limitations': ['Final bounded .006/.005/.0045 full native spatial ladder; all prior coarse failures retained; macro evidence alone does not grant the whole parameter domain.',
                              'Automatic EOS sound speed and native B vary with dp; this is the preserved automatic numerical recipe.',
                              'Native weights remain unchanged. Histograms are fractions of each actual initial native fluid inventory.',
                              'No UID pairing across dp; no constant-r Richardson extrapolation; no CDF qualification gate.',
                              'Transport observables, parameter domain, second mechanism background and external verification remain separate.']}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'pair_macro_budget_pass': result['pair_macro_budget_pass']}))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    main()
