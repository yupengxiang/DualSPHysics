"""One bounded scientific pass over a frozen typed state, with separate type ledgers.

This records actual arrays and missing-ID windows. Native exit causes and
numerical accuracy require separate evidence; no QN/QE credit is issued here.
"""
import argparse
import json
from pathlib import Path
import resource
import time

import h5py
import numpy as np

from ds_data02_runtime_v2 import atomic_json

TYPE_NAMES = {0: 'fixed', 1: 'moving', 2: 'floating', 3: 'fluid'}
FIELDS = ('position', 'velocity', 'density', 'mass', 'pressure')


def safe_number(value):
    return float(value) if np.isfinite(value) else None


def scan(path, *, expected_frames=None, chunk=65536):
    if isinstance(chunk, bool) or not isinstance(chunk, int) or chunk <= 0:
        raise ValueError('Particle chunk must be a positive integer')
    started = time.monotonic()
    before = path.stat()
    failures = []
    with h5py.File(path, 'r') as h:
        times = h['time'][:]
        ids, zones = h['particle_id'][:], h['particle_zone'][:]
        types, initial_mass = h['initial_type'][:], h['initial_mass'][:].astype('float64')
        n, frames = len(ids), len(times)
        if not n or not frames:
            raise ValueError('Empty particle/time axis')
        if any(v.shape != (n,) for v in [ids, zones, types, initial_mass]):
            raise ValueError('Static identity/source axis shape mismatch')
        if ids.dtype.kind not in 'iu' or zones.dtype.kind not in 'iu' or types.dtype.kind not in 'iu':
            raise ValueError('Noninteger identity/type axis')
        keys = np.rec.fromarrays([zones, ids])
        if len(np.unique(keys)) != n:
            raise ValueError('Duplicate (Zone,Idp) identity')
        if not np.isin(types, list(TYPE_NAMES)).all():
            raise ValueError('Unknown particle type code')
        if not np.isfinite(initial_mass).all() or not (initial_mass > 0).all():
            failures.append('initial_mass_nonpositive_or_nonfinite')
        if not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
            failures.append('time_nonfinite_or_nonmonotonic')
        if expected_frames is not None and frames != expected_frames:
            failures.append('catalog_frame_count_mismatch')
        for field in (*FIELDS, 'valid', 'type'):
            shape = (frames, n, 3) if field in ('position', 'velocity') else (frames, n)
            if field not in h or h[field].shape != shape:
                raise ValueError('Missing or mismatched scientific field: ' + field)
        if 'particle_id_by_frame' in h or 'particle_zone_by_frame' in h:
            raise ValueError('Per-frame identities require explicit lineage support')
        first_missing = np.full(n, -1, dtype='int32')
        first_gap_previous_state = {}
        initial_active = np.zeros(n, dtype=bool)
        previous = np.zeros(n, dtype=bool)
        ever = np.zeros(n, dtype=bool)
        revived = np.zeros(n, dtype=bool)
        last_known_frame = np.full(n, -1, dtype='int32')
        last_position = np.full((n, 3), np.nan, dtype='float64')
        last_velocity = np.full((n, 3), np.nan, dtype='float64')
        last_density = np.full(n, np.nan, dtype='float64')
        ledgers = {name: dict(type_code=code, typed_initial_count=int((types == code).sum()),
                             typed_initial_mass_kg=safe_number(initial_mass[types == code].sum()),
                             active_count=[], active_mass_kg=[], missing_count=[], missing_initial_mass_kg=[],
                             active_nonfinite={f: 0 for f in FIELDS}, active_nonpositive_mass=0,
                             active_nonpositive_density=0, type_changed_particle_frames=0)
                   for code, name in TYPE_NAMES.items()}
        macros = []
        for frame in range(frames):
            count = {k: 0 for k in ledgers}
            mass_sum = {k: 0.0 for k in ledgers}
            fluid_position, fluid_velocity = np.zeros(3), np.zeros(3)
            fluid_energy = 0.0
            for lo in range(0, n, chunk):
                hi = min(n, lo + chunk)
                raw_valid = h['valid'][frame, lo:hi]
                if not np.isin(raw_valid, [0, 1]).all():
                    raise ValueError('Invalid valid mask: nonbinary/nonfinite')
                active = raw_valid.astype(bool)
                sl = slice(lo, hi)
                if frame == 0:
                    initial_active[sl] = active
                seen = ever[sl].copy()
                first = first_missing[sl]
                for offset in np.flatnonzero((first < 0) & ~active):
                    index = lo + int(offset)
                    last = int(last_known_frame[index])
                    first_gap_previous_state[index] = dict(
                        frame=last, time_s=safe_number(times[last]) if last >= 0 else None,
                        position_m=[safe_number(v) for v in last_position[index]],
                        velocity_m_s=[safe_number(v) for v in last_velocity[index]],
                        density_kg_m3=safe_number(last_density[index]))
                first[(first < 0) & ~active] = frame
                first_missing[sl] = first
                revived[sl] |= seen & ~previous[sl] & active
                ever[sl] |= active
                previous[sl] = active
                values = {field: h[field][frame, lo:hi] for field in FIELDS}
                current_type = h['type'][frame, lo:hi]
                if current_type.dtype.kind not in 'iu':
                    raise ValueError('Noninteger per-frame type axis')
                last_known_frame[sl][active] = frame
                last_position[sl][active] = values['position'][active]
                last_velocity[sl][active] = values['velocity'][active]
                last_density[sl][active] = values['density'][active]
                for code, name in TYPE_NAMES.items():
                    selected = active & (types[sl] == code)
                    count[name] += int(selected.sum())
                    mass_sum[name] += float(np.sum(values['mass'][selected], dtype='float64'))
                    out = ledgers[name]
                    for field, val in values.items():
                        finite = np.isfinite(val).all(axis=-1) if val.ndim == 2 else np.isfinite(val)
                        out['active_nonfinite'][field] += int((selected & ~finite).sum())
                    out['active_nonpositive_mass'] += int((selected & (values['mass'] <= 0)).sum())
                    out['active_nonpositive_density'] += int((selected & (values['density'] <= 0)).sum())
                    out['type_changed_particle_frames'] += int((selected & (current_type != code)).sum())
                fluid = active & (types[sl] == 3)
                weights = values['mass'][fluid].astype('float64')
                pos, vel = values['position'][fluid].astype('float64'), values['velocity'][fluid].astype('float64')
                fluid_position += (pos * weights[:, None]).sum(axis=0)
                fluid_velocity += (vel * weights[:, None]).sum(axis=0)
                fluid_energy += float((0.5 * weights * np.sum(vel * vel, axis=-1)).sum())
            for code, name in TYPE_NAMES.items():
                cohort = types == code
                missing = cohort & ~previous
                out = ledgers[name]
                out['active_count'].append(count[name])
                out['active_mass_kg'].append(safe_number(mass_sum[name]))
                out['missing_count'].append(int(missing.sum()))
                out['missing_initial_mass_kg'].append(safe_number(initial_mass[missing].sum()))
            m = mass_sum['fluid']
            macros.append(dict(time_s=safe_number(times[frame]), active_fluid_mass_kg=safe_number(m),
                               active_fluid_com_m=[safe_number(v / m) if m > 0 else None for v in fluid_position],
                               active_fluid_mean_velocity_m_s=[safe_number(v / m) if m > 0 else None for v in fluid_velocity],
                               active_fluid_kinetic_energy_J=safe_number(fluid_energy)))
            if frame % 100 == 0:
                print(f'{path.name}: frame {frame + 1}/{frames}', flush=True)
        missing_rows = []
        for index in np.flatnonzero(first_missing >= 0):
            f = int(first_missing[index])
            last = int(last_known_frame[index])
            missing_rows.append(dict(zone=int(zones[index]), idp=int(ids[index]), type_code=int(types[index]),
                                     initial_mass_kg=safe_number(initial_mass[index]), initially_active=bool(initial_active[index]),
                                     first_missing_frame=f, first_missing_bracket_s=[safe_number(times[f - 1]) if f else None, safe_number(times[f])],
                                     first_gap_previous_state=first_gap_previous_state[int(index)],
                                     last_known_frame=last, last_known_time_s=safe_number(times[last]) if last >= 0 else None,
                                     last_known_position_m=[safe_number(v) for v in last_position[index]],
                                     last_known_velocity_m_s=[safe_number(v) for v in last_velocity[index]],
                                     last_known_density_kg_m3=safe_number(last_density[index]),
                                     missing_at_final=bool(not previous[index]), revived=bool(revived[index]),
                                     native_exit_cause='EVIDENCE_UNKNOWN', physical_fate='UNKNOWN'))
        for code, name in TYPE_NAMES.items():
            out = ledgers[name]
            cohort = types == code
            out.update(initial_active_count=int((cohort & initial_active).sum()),
                       initially_absent_count=int((cohort & ~initial_active).sum()),
                       cumulative_unique_missing=int((cohort & (first_missing >= 0)).sum()),
                       missing_at_final=int((cohort & ~previous).sum()),
                       maximum_instantaneous_missing=max(out['missing_count']),
                       missing_particle_frames=sum(out['missing_count']),
                       revived_unique_ids=int((cohort & revived).sum()),
                       births_unique_ids=int((cohort & ~initial_active & ever).sum()))
            if any(out['active_nonfinite'].values()) or any(out[k] for k in
                    ('active_nonpositive_mass', 'active_nonpositive_density', 'type_changed_particle_frames')):
                failures.append(name + '_active_field_failure')
        attrs = dict(units=json.loads(h.attrs['units_json']) if 'units_json' in h.attrs else None,
                     coordinate_frame=str(h.attrs.get('coordinate_frame', 'UNKNOWN')),
                     identity_key=str(h.attrs.get('identity_key', 'UNKNOWN')))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        failures.append('source_changed_during_scan')
    return dict(schema='ds02.stage2.scientific-scan.v1', trajectory=str(path), source_bytes=before.st_size,
                source_mtime_ns=before.st_mtime_ns, full_saved_timeline_scanned=True,
                frames=frames, particles=n, time_s=[safe_number(v) for v in times],
                metadata=attrs, type_ledgers=ledgers, missing_id_records=missing_rows,
                macros=macros, failures=failures, scan_status='SCANNED_FIELD_FAILURE' if failures else 'SCANNED',
                raw_native_alignment='NOT_ASSESSED', QI_dynamics='NOT_ASSESSED', QN='NOT_ASSESSED', QE='NOT_ASSESSED',
                input_hash_verification='See the guard runtime execution receipt for recomputed launch/end digests.',
                wall_seconds=time.monotonic() - started,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.catalog.read_text())['cases']
    matches = [r for r in rows if r['physical_case_id'] == args.case_id]
    if len(matches) != 1 or 'trajectory' not in matches[0]:
        raise ValueError('No unique accessible catalog state for requested physical case')
    row = matches[0]
    if args.output.exists():
        raise FileExistsError('Preserve completed scan: ' + str(args.output))
    report = scan(Path(row['trajectory']['path']), expected_frames=row['frames'])
    report.update(family_id=row['family_id'], physical_case_id=row['physical_case_id'])
    atomic_json(args.output, report)
    print(json.dumps(dict(case=report['physical_case_id'], status=report['scan_status'],
                         missing_fluid=report['type_ledgers']['fluid']['cumulative_unique_missing'],
                         seconds=report['wall_seconds'])))
    # Scientific failure is a recorded result, not an infrastructure error.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
