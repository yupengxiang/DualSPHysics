"""Apply the registered F4 support detector to every native saved frame.

This additive reader uses the consumed v2 detector without calling its legacy
transport or lifecycle paths. Source membership comes from typed native mk,
not current boxes. Absent contact stays censored; exclusions stay unknown.
"""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np

from ds_data02_f4_science import (
    _calibration, _event_from_flags, _recontact_from_flags, _support_detector,
)
from ds_data02_native_labels import digest


def frame_support(position, mass, valid, fluid, markers, source_markers, protocol,
                  source_mass_scale):
    active = fluid & valid
    if np.any(active & (~np.isfinite(mass) | (mass <= 0) |
                        ~np.isfinite(position).all(axis=1))):
        raise ValueError('Active native fluid state invalid')
    selected = [active & (markers == marker) for marker in source_markers]
    if np.any(active & ~np.logical_or.reduce(selected)):
        raise ValueError('Active fluid marker lacks a registered source')
    return _support_detector(
        position[selected[0]], position[selected[1]],
        mass[selected[0]], mass[selected[1]],
        radius_m=protocol['support_radius_m'],
        minimum_pairs=protocol['minimum_cross_support_pairs'],
        minimum_mass_fraction=protocol['minimum_support_mass_fraction_of_smaller_source'],
        source_mass_scale_kg=source_mass_scale,
    )


def series(source, owner, frozen, mechanism, output):
    if output.exists():
        raise FileExistsError(output)
    paths = [source, owner, frozen]
    before = {str(path): digest(path) for path in paths}
    meta = json.loads(owner.read_text())
    contract = json.loads(frozen.read_text())['budgets'][mechanism]
    protocol = contract['current_operator_protocol']['physical_support']
    if (protocol['support_radius_m'] != .02 or
            protocol['minimum_cross_support_pairs'] != 3 or
            protocol['minimum_support_mass_fraction_of_smaller_source'] != .01):
        raise ValueError('Unsupported registered detector protocol')
    mapping = meta['typed_identity_binding']['fluid_mkfluid_to_native_mk']
    initial = meta['physical_binding']['initial_state']
    groups = {initial['source_labels']['mkfluid:' + key]: marker
              for key, marker in mapping.items()}
    if len(groups) != 2:
        raise ValueError('Exactly two registered native sources required')
    rows, unknown, source_initial_mass = [], [], {}
    with h5py.File(source, 'r') as h:
        if str(h.attrs['physical_condition_sha256']) != meta['physical_binding_sha256']:
            raise ValueError('Physical binding differs')
        times = h['time'][:]
        if (not np.isfinite(times).all() or not np.all(np.diff(times) > 0) or
                times[0] != 0 or times[-1] < 1.2 or len(times) < 1201):
            raise ValueError('Full native 0-1.2 s window required')
        fluid = h['initial_type'][:] == 3
        markers = h['initial_mk'][:]
        initial_mass = h['initial_mass'][:].astype(np.float64)
        if not fluid.any() or not np.isfinite(initial_mass[fluid]).all() or np.any(initial_mass[fluid] <= 0):
            raise ValueError('Invalid initial native mass')
        if not np.isin(markers[fluid], list(groups.values())).all():
            raise ValueError('Initial fluid source coverage incomplete')
        for label, marker in groups.items():
            source_initial_mass[label] = float(initial_mass[fluid & (markers == marker)].sum())
        if min(source_initial_mass.values()) <= 0:
            raise ValueError('Empty native source')
        # Use the same native initial source-mass scale as the registered
        # detector; no trajectory mass normalization or dp-dependent radius.
        mass_scale = min(source_initial_mass.values())
        for frame in range(len(times)):
            valid = h['valid'][frame, :].astype(bool)
            position = h['position'][frame, :].astype(np.float64)
            mass = h['mass'][frame, :].astype(np.float64)
            rows.append(frame_support(position, mass, valid, fluid, markers,
                                      list(groups.values()), protocol, mass_scale))
            unknown.append(float(initial_mass[fluid & ~valid].sum()))
    if before != {str(path): digest(path) for path in paths}:
        raise ValueError('Input mutated during contact extraction')
    flags = [row['contact'] for row in rows]
    first = _event_from_flags(times, flags)
    result = {
        'schema': 'ds02.f4.centered-native-contact.v1',
        'source_sha256': before, 'source': str(source),
        'physical_binding_sha256': meta['physical_binding_sha256'],
        'native_source_markers': groups, 'native_initial_source_mass_kg': source_initial_mass,
        'registered_protocol': protocol, 'calibration': _calibration(),
        'time_s': times.tolist(), 'support_series': rows,
        'first_contact': first, 'recontact': _recontact_from_flags(times, flags, first),
        'unknown_native_exclusion_mass_kg': unknown,
        'q_n_status': 'not_assessed', 'production_approval': 'none',
        'limitations': ['Native saved-time support observations; absent events remain right-censored',
                        'Missing native identities remain unknown, never physical exits',
                        'Spatial, independent integration/save, reconstruction and lifecycle evidence required separately'],
    }
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'frames': len(times), 'first_contact': first,
                      'unknown_mass_final_kg': unknown[-1], 'q_n_status': 'not_assessed'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'owner', 'frozen', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--mechanism', choices=('COL', 'DROP'), required=True)
    args = parser.parse_args()
    series(args.source, args.owner, args.frozen, args.mechanism, args.output)
