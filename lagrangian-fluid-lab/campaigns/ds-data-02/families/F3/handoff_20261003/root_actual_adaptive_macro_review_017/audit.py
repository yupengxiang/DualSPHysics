"""Full-window adaptive CELL3 macro comparison with the historical operator."""
import argparse
import importlib.util
import json
from pathlib import Path
import signal
import sys
import tempfile

import h5py
import numpy as np

LAB = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(LAB / 'scripts'))
from ds_data02_f3_nvme_input_audit_v1 import verified_copy


def validate(h):
    required = ['particle_id', 'particle_zone', 'initial_type', 'initial_mass',
                'position', 'velocity', 'mass', 'valid', 'time']
    if any(k not in h for k in required):
        raise ValueError('Missing mandatory native state')
    t = np.asarray(h['time'][:], dtype=float)
    if (len(t) != 836 or t[0] != 0 or t[-1] < 8.35
            or not np.isfinite(t).all() or not np.all(np.diff(t) > 0)):
        raise ValueError('Incomplete or invalid full836 native time support')
    fluid = np.flatnonzero(h['initial_type'][:] == 3)
    if len(fluid) != 34560:
        raise ValueError('Unexpected fluid cohort')
    return t, fluid


def frame(h, index, fluid, initial_mass):
    start, stop = int(fluid[0]), int(fluid[-1]) + 1
    local = fluid - start
    valid = np.asarray(h['valid'][index, start:stop])[local]
    m = np.asarray(h['mass'][index, start:stop])[local]
    p = np.asarray(h['position'][index, start:stop, :], dtype=float)[local]
    v = np.asarray(h['velocity'][index, start:stop, :], dtype=float)[local]
    if (not np.all(valid == 1) or not np.array_equal(m, initial_mass)
            or not np.isfinite(p).all() or not np.isfinite(v).all()
            or not np.isfinite(m).all() or np.any(m <= 0)):
        raise ValueError('Closed cohort active state or mass changed; preserve failed evidence')
    return p, v


def state(h, times, fluid, mass, target, cache):
    right = min(int(np.searchsorted(times, target, side='right')), len(times) - 1)
    left = max(0, right - 1)
    for index in [left, right]:
        if index not in cache:
            cache[index] = frame(h, index, fluid, mass)
    for index in list(cache):
        if index not in [left, right]:
            del cache[index]
    fraction = (target - times[left]) / (times[right] - times[left])
    if not 0 <= fraction <= 1:
        raise ValueError('Physical-grid extrapolation forbidden')
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
    spec = importlib.util.spec_from_file_location('frozen_cell3_operator', binding['operator'])
    operator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(operator)
    parent = Path(binding['scratch_parent'])
    parent.mkdir(parents=True, exist_ok=True)
    import os
    stat = os.statvfs(parent)
    needed = sum(Path(binding[r]['trajectory']).stat().st_size for r in ['baseline', 'half'])
    if stat.f_bavail * stat.f_frsize < needed + 100 * 1024**3:
        raise ValueError('Insufficient protected NVMe capacity')
    for role in ['baseline', 'half']:
        receipt = json.loads(Path(binding[role]['receipt']).read_text())
        if receipt['status'] != 'completed' or receipt['returncode'] != 0:
            raise ValueError('Source conversion is not completed0')
    with tempfile.TemporaryDirectory(prefix='ds02-f3-macro-pair-', dir=parent) as tmp:
        paths = {}
        for role in ['baseline', 'half']:
            paths[role] = Path(tmp) / (role + '.h5')
            verified_copy(Path(binding[role]['trajectory']), paths[role], binding[role]['sha256'])
        with h5py.File(paths['baseline'], 'r') as a, h5py.File(paths['half'], 'r') as b:
            ta, fluid = validate(a)
            tb, other = validate(b)
            for key in ['particle_id', 'particle_zone', 'initial_type', 'initial_mass']:
                if not np.array_equal(a[key][:], b[key][:]):
                    raise ValueError('Initial identity or typed mass differs: ' + key)
            if not np.array_equal(fluid, other):
                raise ValueError('Initial fluid cohort differs')
            if a.attrs['physical_condition_sha256'] != b.attrs['physical_condition_sha256']:
                raise ValueError('Physical condition differs')
            mass = np.asarray(a['initial_mass'][:])[fluid]
            total = float(mass.astype(float).sum())
            pa, va = frame(a, 0, fluid, mass)
            pb, vb = frame(b, 0, fluid, mass)
            if not np.array_equal(pa, pb) or not np.array_equal(va, vb):
                raise ValueError('Initial native state differs')
            grid = np.linspace(0, 8.35, 836)
            history = []
            caches = [{}, {}]
            for target in grid:
                sa = state(a, ta, fluid, mass, target, caches[0])
                sb = state(b, tb, fluid, mass, target, caches[1])
                oa = operator.observe_arrays(*sa, mass, total)
                ob = operator.observe_arrays(*sb, mass, total)
                row = operator.compare(oa, ob)
                if not all(np.isfinite(x) and x >= 0 for x in row.values()):
                    raise ValueError('Invalid macro discrepancy')
                history.append({'time_s': float(target), **row})
            metrics = {}
            for name in history[0]:
                if name == 'time_s':
                    continue
                values = np.asarray([r[name] for r in history])
                metrics[name] = {'maximum_deviation': float(values.max()),
                                 'time_at_maximum_s': float(grid[int(values.argmax())]),
                                 'rms_deviation': float(np.sqrt(np.mean(values**2))),
                                 'within_registered_time_budget': bool(values.max() <= protocol['time_output_error_budget'])}
    result = {'schema': 'ds02.f3.actual-adaptive-macro-comparison.v1',
              'binding': binding, 'window_s': [0, 8.35], 'grid_points': 836,
              'initial_native_mass_kg': total, 'metrics': metrics, 'history': history,
              'macro_time_budget': protocol['time_output_error_budget'],
              'macro_time_budget_pass': all(x['within_registered_time_budget'] for x in metrics.values()),
              'copy_verified_before_use': True, 'private_scratch_removed': True,
              'q_n_status': 'not_assessed', 'production_approval': 'none',
              'limitations': ['Historical spatial gate does not transfer to new adaptive recipe.',
                              'UID passage-bracket non-overlap is not a save-error gate or causal proof.',
                              'Historical fixed-dt dense output is not equivalent to new adaptive dense output.',
                              'Pressure, wall forces and free-surface qualification remain separate.']}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'macro_time_budget_pass': result['macro_time_budget_pass']}))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    main()
