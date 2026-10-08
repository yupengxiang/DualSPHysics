#!/usr/bin/env python3
"""Materialize numerical-history labels for one fixed-identity F2-S1 case.

Events are finite-aperture intersections of saved-frame linear chords. They
are interval observations, not exact continuous material paths. Moving event
frames, births, and adaptive identities require separate support and are
rejected rather than silently interpreted in a stationary frame.  This
forward-only operator also stores per-particle forward/backward crossing
counts so repeated crossings and cancellation can be measured without a
second trajectory read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import os

import h5py
import numpy as np


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def validate_config(config):
    if config.get('frame_kind') != 'fixed_solver_frame':
        raise ValueError('moving event frames need actual saved transforms')
    if not config.get('coordinate_frame'):
        raise ValueError('explicit coordinate_frame is required')
    assignment = config.get('source_assignment', 'initial_regions')
    if assignment not in ('initial_regions', 'native_initial_mk'):
        raise ValueError('unsupported source_assignment')
    if assignment == 'native_initial_mk':
        mks = [row.get('native_mk') for row in config.get('source_regions', [])]
        if not mks or any(not isinstance(mk, int) or isinstance(mk, bool) or mk < 0 for mk in mks) or len(set(mks)) != len(mks):
            raise ValueError('native source mk must be explicit nonnegative unique integers')
    for key in ('source_regions', 'destination_regions'):
        rows = config.get(key, [])
        if not rows or len(rows) > 32000:
            raise ValueError(f'{key} must define finite regions')
        if len({r['id'] for r in rows}) != len(rows):
            raise ValueError('region ids must be unique')
        for row in rows:
            bounds = np.asarray(row['bounds'], dtype=float)
            if bounds.shape != (3, 2) or not np.isfinite(bounds).all() or not (bounds[:, 1] > bounds[:, 0]).all():
                raise ValueError('region bounds must be finite nonempty 3D boxes')
        for i, row in enumerate(rows):
            a = np.asarray(row['bounds'])
            for other in rows[i+1:]:
                b = np.asarray(other['bounds'])
                if (np.minimum(a[:, 1], b[:, 1]) > np.maximum(a[:, 0], b[:, 0])).all():
                    raise ValueError('region boxes overlap; use an explicit disjoint partition')
    events = config.get('events', [])
    if len({r['id'] for r in events}) != len(events):
        raise ValueError('event ids must be unique')
    for event in events:
        bounds = np.asarray(event['aperture_bounds'], dtype=float)
        if event['axis'] not in (0, 1, 2) or not np.isfinite(event['value']):
            raise ValueError('invalid event plane')
        if bounds.shape != (2, 2) or not np.isfinite(bounds).all() or not (bounds[:, 1] > bounds[:, 0]).all():
            raise ValueError('event aperture must have two finite transverse bounds')


def locate(points, regions):
    result = np.zeros(len(points), dtype=np.int16)
    for index, row in enumerate(regions, 1):
        bounds = np.asarray(row['bounds'])
        mask = ((points >= bounds[:, 0]) & (points < bounds[:, 1])).all(axis=1)
        if np.any(mask & (result != 0)):
            raise ValueError('region boxes overlap at observed particles')
        result[mask] = index
    return result


def initial_sources(h, config, sl, fluid, positions):
    if config.get('source_assignment', 'initial_regions') == 'initial_regions':
        result = locate(positions, config['source_regions'])
    else:
        if 'initial_mk' not in h or h['initial_mk'].shape != h['particle_id'].shape:
            raise ValueError('native source assignment requires initial_mk on typed identity axis')
        mks = h['initial_mk'][sl]
        result = np.zeros(len(fluid), dtype=np.int16)
        for code, source in enumerate(config['source_regions'], 1):
            result[mks == source['native_mk']] = code
        if np.any(fluid & (result == 0)):
            raise ValueError('initial fluid has no registered native mk source')
    result[~fluid] = 0
    return result


def finite_crossing(p0, p1, event):
    axis = event['axis']
    a, b = p0[:, axis] - event['value'], p1[:, axis] - event['value']
    forward, backward = (a < 0) & (b >= 0), (a >= 0) & (b < 0)
    tau = np.divide(-a, b-a, out=np.zeros(len(a)), where=b != a)
    crossing = p0 + tau[:, None] * (p1-p0)
    transverse = [i for i in range(3) if i != axis]
    bounds = np.asarray(event['aperture_bounds'])
    inside = ((crossing[:, transverse] >= bounds[:, 0]) &
              (crossing[:, transverse] < bounds[:, 1])).all(axis=1)
    return forward & inside, backward & inside, tau


def chord_box_fraction(p0, p1, bounds):
    """Fraction of each saved-frame chord inside a finite axis-aligned box."""
    lower, upper = np.zeros(len(p0)), np.ones(len(p0))
    for axis, (lo, hi) in enumerate(bounds):
        delta = p1[:, axis] - p0[:, axis]
        moving = delta != 0
        a = np.divide(lo-p0[:, axis], delta, out=np.zeros(len(p0)), where=moving)
        b = np.divide(hi-p0[:, axis], delta, out=np.ones(len(p0)), where=moving)
        lower = np.maximum(lower, np.where(moving, np.minimum(a, b), 0))
        upper = np.minimum(upper, np.where(moving, np.maximum(a, b), 1))
        excluded = ~moving & ((p0[:, axis] < lo) | (p0[:, axis] >= hi))
        upper[excluded] = -1
    return np.maximum(0, upper-lower)


def materialize(source, output, config, *, particle_chunk=65536):
    validate_config(config)
    lifecycle_model = config.get('lifecycle_model', 'closed')
    if lifecycle_model not in ('closed', 'open'):
        raise ValueError('lifecycle_model must be explicitly closed or open')
    source, output = Path(source), Path(output)
    if output.exists() or output.resolve() == source.resolve():
        raise FileExistsError('labels must be written to a new artifact')
    partial = output.with_suffix(output.suffix + '.partial')
    if partial.exists():
        raise FileExistsError('unfinished label artifact exists; retain and inspect it')
    if particle_chunk < 1:
        raise ValueError('particle_chunk must be positive')
    output.parent.mkdir(parents=True, exist_ok=True)
    regions, events = config['destination_regions'], config.get('events', [])
    nr, ne = len(regions), len(events)
    source_hash = digest(source)
    with h5py.File(source, 'r') as h, h5py.File(partial, 'x') as out:
        for key in ('time', 'particle_id', 'particle_zone', 'position', 'valid', 'mass', 'type'):
            if key not in h:
                raise ValueError(f'missing native field: {key}')
        frame = h.attrs.get('coordinate_frame')
        if isinstance(frame, bytes):
            frame = frame.decode()
        if frame != config['coordinate_frame']:
            raise ValueError('label event frame differs from trajectory frame')
        time = h['time'][:]
        if len(time) < 2 or not np.isfinite(time).all() or not (np.diff(time) > 0).all():
            raise ValueError('time must be finite and strictly increasing')
        nt, nparticles = h['valid'].shape
        if nt != len(time) or h['position'].shape != (nt, nparticles, 3):
            raise ValueError('native trajectory shape mismatch')
        keys = np.column_stack((h['particle_zone'][:], h['particle_id'][:]))
        if keys.shape != (nparticles, 2) or len(np.unique(keys, axis=0)) != nparticles:
            raise ValueError('duplicate or inconsistent typed identity keys')
        out.attrs.update(schema='ds-data-02.native-labels.v1', source_hdf5_sha256=source_hash,
                         source_hdf5=str(source.resolve()), config_json=json.dumps(config, sort_keys=True),
                         coordinate_frame=config['coordinate_frame'], complete=False,
                         semantics='native numerical identity histories; saved-frame linear chords',
                         residence_semantics='piecewise-linear chord occupancy; interpolation error unassessed',
                         event_time_semantics='saved-frame bracket plus chord estimate; continuous hidden crossings unresolved',
                         lifecycle_model=lifecycle_model,
                         q_n_status='not_assessed', model_invoked=False)
        out.create_dataset('time', data=time)
        out.create_dataset('particle_id', data=h['particle_id'][:])
        out.create_dataset('particle_zone', data=h['particle_zone'][:])
        def ds(name, shape, dtype, fillvalue=0):
            # Small 1D axes and empty event axes need no chunk/compression.
            return out.create_dataset(name, shape=shape, dtype=dtype, fillvalue=fillvalue,
                                      **({'compression': 'gzip'} if all(shape) else {}))
        source_ds = ds('source_label', (nparticles,), 'i2')
        dest_ds = ds('destination_time_series', (nt, nparticles), 'i2')
        final_ds = ds('final_category', (nparticles,), 'i2')
        failure_ds = ds('failure_reason', (nparticles,), 'i1')
        first = ds('first_passage_interval', (nparticles, ne, 2), 'f8', np.nan)
        estimate = ds('first_passage_chord_time', (nparticles, ne), 'f8', np.nan)
        censor = ds('first_passage_censor', (nparticles, ne), 'i1', 1)
        crossings = ds('event_crossing_counts', (nparticles, ne, 2), 'i4')
        residence = ds('residence_time_s', (nparticles, nr), 'f8')
        unresolved = ds('unresolved_interval_time_s', (nparticles,), 'f8')
        origin_mass = ds('initial_fluid_mass_kg', (nparticles,), 'f8')
        flux = np.zeros((nt, ne, 2), dtype=float)
        unknown = np.zeros(nt)
        lost = np.zeros(nt)
        invalid = np.zeros(nt)
        mass_table = np.zeros((len(config['source_regions'])+1, nr+3))
        total_initial = 0.0
        for begin in range(0, nparticles, particle_chunk):
            end = min(nparticles, begin+particle_chunk)
            sl = slice(begin, end)
            chunk_valid = h['valid'][:, sl].astype(bool)
            chunk_type = h['type'][:, sl]
            chunk_pos = h['position'][:, sl].astype(float)
            chunk_mass = h['mass'][:, sl].astype(float)
            chunk_dest = np.zeros((nt, end-begin), dtype=np.int16)

            initial_valid = chunk_valid[0]
            fluid = initial_valid & (chunk_type[0] == 3)
            mass = np.where(fluid, chunk_mass[0], 0).astype(float)
            if not np.isfinite(mass).all() or np.any(mass[fluid] <= 0):
                raise ValueError('initial fluid mass must be finite and positive')
            initial_pos = chunk_pos[0]
            if not np.isfinite(initial_pos[fluid]).all():
                raise ValueError('initial fluid position invalid')
            sources = initial_sources(h, config, sl, fluid, initial_pos)
            source_ds[sl], origin_mass[sl] = sources, mass
            total_initial += float(mass.sum())
            prev_pos = None
            prev_good = None
            disappeared = np.zeros(end-begin, dtype=bool)
            residence_local = np.zeros((end-begin, nr))
            unresolved_local = np.zeros(end-begin)
            bracket = np.full((end-begin, ne, 2), np.nan)
            first_estimate = np.full((end-begin, ne), np.nan)
            censor_local = np.ones((end-begin, ne), dtype=np.int8)
            crossing_local = np.zeros((end-begin, ne, 2), dtype=np.int32)
            for ti, timestamp in enumerate(time):
                valid = chunk_valid[ti]
                current_type = chunk_type[ti]
                if np.any(~fluid & valid & (current_type == 3)):
                    raise ValueError('births require lifecycle label support')
                if np.any(fluid & valid & (current_type != 3)):
                    raise ValueError('fluid identity changes type')
                if np.any(disappeared & fluid & valid):
                    raise ValueError('lost fluid identity reappeared without lineage')
                disappeared |= fluid & ~valid
                pos = chunk_pos[ti]
                current_mass = chunk_mass[ti]
                good = fluid & valid & np.isfinite(pos).all(axis=1) & np.isfinite(current_mass) & (current_mass > 0)
                if np.any(good & ~np.isclose(current_mass, mass, rtol=1e-5, atol=0)):
                    raise ValueError('variable mass requires adaptive lifecycle support')
                destination = locate(pos, regions)
                destination[~fluid] = -3
                destination[fluid & ~valid] = -1
                destination[fluid & valid & ~good] = -2
                chunk_dest[ti] = destination
                unknown[ti] += mass[good & (destination == 0)].sum()
                lost[ti] += mass[fluid & ~valid].sum()
                invalid[ti] += mass[fluid & valid & ~good].sum()
                if ti:
                    paired = prev_good & good
                    dt = timestamp-time[ti-1]
                    unresolved_local += (fluid & ~paired)*dt
                    for ri, region in enumerate(regions):
                        fraction = chord_box_fraction(prev_pos, pos, region['bounds'])
                        residence_local[:, ri] += np.where(paired, fraction*dt, 0)
                    for ei, event in enumerate(events):
                        forward, backward, tau = finite_crossing(prev_pos, pos, event)
                        forward &= paired
                        backward &= paired
                        flux[ti, ei, 0] += mass[forward].sum()
                        flux[ti, ei, 1] += mass[backward].sum()
                        crossing_local[:, ei, 0] += forward.astype(np.int32)
                        crossing_local[:, ei, 1] += backward.astype(np.int32)
                        selected = (forward | backward) & np.isnan(bracket[:, ei, 0])
                        bracket[selected, ei, 0] = time[ti-1]
                        bracket[selected, ei, 1] = timestamp
                        first_estimate[selected, ei] = time[ti-1]+tau[selected]*dt
                        censor_local[selected, ei] = 0
                prev_pos, prev_good = pos, good
            dest_ds[:, sl] = chunk_dest
            first[sl], estimate[sl], censor[sl] = bracket, first_estimate, censor_local
            crossings[sl] = crossing_local
            residence[sl], unresolved[sl], final_ds[sl] = residence_local, unresolved_local, destination
            failure_ds[sl] = np.where(~fluid, 4, np.where(destination == -1, 1,
                                     np.where(destination == -2, 2, np.where(destination == 0, 3, 0))))
            for si in range(mass_table.shape[0]):
                for code in range(-2, nr+1):
                    mass_table[si, code+2] += mass[(sources == si) & (destination == code)].sum()
        if total_initial <= 0:
            raise ValueError('trajectory has no initial fluid mass')
        out.create_dataset('forward_backward_mass_kg', data=np.cumsum(flux, axis=0))
        out.create_dataset('cumulative_net_flux_kg', data=np.cumsum(flux[:, :, 0]-flux[:, :, 1], axis=0))
        out.create_dataset('unknown_mass_kg', data=unknown)
        out.create_dataset('numerical_loss_mass_kg', data=lost)
        out.create_dataset('missing_identity_mass_kg', data=lost)
        out.create_dataset('invalid_state_mass_kg', data=invalid)
        out.create_dataset('source_final_mass_kg', data=mass_table)
        out.attrs.update(initial_fluid_mass_kg=total_initial,
                         destination_codes=json.dumps({'-3':'noninitial_fluid','-2':'invalid_state',
                                                        '-1':'numerical_loss','0':'unknown',
                                                        **{str(i):r['id'] for i,r in enumerate(regions,1)}}),
                         first_passage_censor_codes='0=observed_saved_chord;1=not_observed_or_censored',
                         crossing_count_semantics='per-particle saved-chord crossings; column 0=forward, column 1=backward',
                         missing_identity_semantics=('numerical_loss' if lifecycle_model == 'closed' else 'open-lifecycle censoring; physical fate UNKNOWN'),
                         failure_reason_codes=('0=none;1=numerical_loss;2=invalid_state;3=unclassified_region;4=noninitial_fluid' if lifecycle_model == 'closed' else '0=none;1=missing_identity_censored;2=invalid_state;3=unclassified_region;4=noninitial_fluid'),
                         source_final_columns='invalid_state,numerical_loss,unknown,then destination_regions',
                         complete=True)
    if digest(source) != source_hash:
        raise RuntimeError('native source mutated during labeling; keep partial artifact')
    os.replace(partial, output)
    return dict(path=str(output), sha256=digest(output), initial_fluid_mass_kg=total_initial,
                frames=nt, identities=nparticles, q_n_status='not_assessed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--particle-chunk', type=int, default=65536)
    args = parser.parse_args()
    print(json.dumps(materialize(args.source, args.output, json.loads(args.config.read_text()),
                                 particle_chunk=args.particle_chunk), indent=2))


if __name__ == '__main__':
    main()
