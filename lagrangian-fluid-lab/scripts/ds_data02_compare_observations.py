#!/usr/bin/env python3
"""Compare physical-scale macro observations without claiming full Q-N.

Saved samples may differ by an internal integration step. Match registered
nominal save bins, retain the exact timestamp offset, and bound its effect
using the full-state maximum particle speed for coordinate moments. Energy
and quantile comparisons remain diagnostics until temporal uncertainty is
established for their operators. Never normalize away represented mass loss.
"""
import argparse
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def bins(rows, cadence, max_offset):
    times = np.asarray([row['time_s'] for row in rows])
    keys = np.rint(times / cadence).astype(int)
    if (np.diff(times) <= 0).any() or len(set(keys.tolist())) != len(keys):
        raise ValueError('time samples are repeated, nonmonotone or ambiguous')
    if np.max(np.abs(times - keys * cadence)) > max_offset:
        raise ValueError('saved timestamp exceeds registered nominal-bin tolerance')
    return keys


def fluid_max_speed(h):
    maximum = 0.0
    for ti in range(len(h['time'])):
        valid = h['valid'][ti].astype(bool) & (h['type'][ti] == 3)
        speed = np.linalg.norm(h['velocity'][ti][valid], axis=1)
        if not np.isfinite(speed).all():
            raise ValueError('nonfinite native velocity')
        maximum = max(maximum, float(np.max(speed)))
    return maximum


def static_physical_control(attrs):
    """Restrict this comparator to explicit static-wall native histories.

    Existing control hashes include numerical settings. Keep those immutable
    and derive a separately named semantic binding for static comparisons.
    Moving controls need a parsed physical motion operator, not hash stripping.
    """
    motion = json.loads(attrs['motion_control_semantics_json'])
    if not motion.get('element_empty'):
        raise ValueError('moving control comparison requires an explicit physical motion operator')
    binding = json.loads(attrs['control_binding_json'])
    event = {k: v for k, v in binding['event_window'].items() if k != 'save_interval_s'}
    return {k: binding[k] for k in ('control_family_id', 'initial_state', 'parameter_values')} | {
        'event_window': event, 'physical_motion': 'empty generated XML motion element'}


def compare(reference_path, candidate_path, *, H0, continuous_mass, cadence, max_offset):
    reference, candidate = [json.loads(Path(p).read_text()) for p in (reference_path, candidate_path)]
    if H0 <= 0 or continuous_mass <= 0 or cadence <= 0 or max_offset < 0:
        raise ValueError('invalid physical comparison scales')
    keys = [bins(d['rows'], cadence, max_offset) for d in (reference, candidate)]
    if not np.array_equal(*keys):
        raise ValueError('comparison does not cover identical complete nominal time bins')
    sources = [Path(d['source']) for d in (reference, candidate)]
    native_initial_equal = None
    with h5py.File(sources[0], 'r') as a, h5py.File(sources[1], 'r') as b:
        if a.attrs['coordinate_frame'] != b.attrs['coordinate_frame']:
            raise ValueError('coordinate frames differ')
        geometry_hash = a.attrs.get('geometry_sha256')
        if not geometry_hash or geometry_hash != b.attrs.get('geometry_sha256'):
            raise ValueError('continuous physical geometry bindings differ or are missing')
        physical_controls = [static_physical_control(h.attrs) for h in (a, b)]
        if physical_controls[0] != physical_controls[1]:
            raise ValueError('physical initial state or control bindings differ')
        same_ids = all(np.array_equal(a[k][:], b[k][:]) for k in ('particle_zone', 'particle_id'))
        if same_ids and a['position'].shape[1] == b['position'].shape[1]:
            native_initial_equal = all(np.array_equal(a[k][0], b[k][0]) for k in
                                       ('position', 'velocity', 'mass', 'type', 'valid'))
        max_speed = max(fluid_max_speed(a), fluid_max_speed(b))
    time_differences = np.abs(np.asarray([s['time_s'] for s in reference['rows']]) -
                              np.asarray([s['time_s'] for s in candidate['rows']]))
    def difference(field):
        x, y = [np.asarray([row[field] for row in d['rows']]) for d in (reference, candidate)]
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError('nonfinite macro observable')
        return np.abs(x - y)
    com = difference('center_of_mass_m')
    quantile = difference('coordinate_quantiles_m')
    energy = difference('kinetic_energy_J')
    temporal_coordinate_margin = time_differences * max_speed
    return dict(schema='ds02.macro-reference-comparison.v1',
        evidence=[dict(observations=str(p.resolve()), observations_sha256=sha(p),
                       native_h5=str(s.resolve()), native_h5_sha256=sha(s))
                  for p, s in zip(map(Path, (reference_path, candidate_path)), sources)],
        normalization=dict(H0_m=H0, continuous_initial_mass_kg=continuous_mass,
                           gravitational_energy_J=continuous_mass * 9.81 * H0,
                           numerical_initial_mass_kg=[d['numerical_initial_mass_kg'] for d in (reference, candidate)]),
        physical_geometry_sha256=str(geometry_hash),
        static_physical_control_binding=physical_controls[0],
        same_native_initial_state=native_initial_equal,
        saved_nominal_bin_count=len(keys[0]), maximum_actual_timestamp_difference_s=float(time_differences.max()),
        maximum_full_state_fluid_speed_m_s=max_speed,
        center_of_mass_max_absolute_difference_xyz_m=np.max(com, axis=0).tolist(),
        center_of_mass_max_difference_over_H0=float(np.max(com) / H0),
        center_of_mass_difference_plus_time_offset_bound_over_H0=float(np.max(com + temporal_coordinate_margin[:, None]) / H0),
        quantile_max_absolute_difference_axis_quantile_m=np.max(quantile, axis=0).tolist(),
        quantile_max_difference_over_H0=float(np.max(quantile) / H0),
        kinetic_energy_max_absolute_difference_J=float(energy.max()),
        kinetic_energy_max_difference_over_continuous_MgH0=float(energy.max() / (continuous_mass * 9.81 * H0)),
        fluid_mass_max_absolute_difference_kg=float(difference('fluid_mass_kg').max()),
        limitations=['COM coordinate alignment uses an empirical full-saved-state speed bound; between-snapshot speed maxima remain unverified',
                     'Quantiles and energy retain actual timestamp offsets; their temporal operator uncertainty remains pending',
                     'Spatial refinement, transport operators, event timing and parameter-domain evidence remain separate requirements'],
        q_n_status='not_granted', inference='descriptive numerical evidence only')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--H0', type=float, required=True)
    p.add_argument('--continuous-mass', type=float, required=True)
    p.add_argument('--cadence', type=float, required=True)
    p.add_argument('--max-time-offset', type=float, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('comparison already exists')
    result = compare(args.reference, args.candidate, H0=args.H0, continuous_mass=args.continuous_mass,
                     cadence=args.cadence, max_offset=args.max_time_offset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
