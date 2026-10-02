#!/usr/bin/env python3
"""Add all observed finite-face crossings to immutable F7 native histories.

The generic observer supplies source/destination, residence and unknown-mass
ledgers. This adapter retains every observed crossing and checks its signed
mass against that observer. Unobserved crossings between saves remain unknown.
"""
import argparse
import json
import os
from pathlib import Path

import h5py
import numpy as np

from ds_data02_native_labels import digest, finite_crossing, materialize, validate_config

EVENT_DTYPE = np.dtype([
    ('particle_index', '<u4'), ('zone', '<i8'), ('idp', '<u4'),
    ('source_zone', '<i2'), ('event_index', '<u2'), ('direction', 'i1'),
    ('frame_before', '<u4'), ('frame_after', '<u4'),
    ('time_before_s', '<f8'), ('time_after_s', '<f8'),
    ('chord_time_s', '<f8'), ('crossing_position_m', '<f8', (3,)),
    ('initial_mass_kg', '<f8'),
])


def observe(source, output, config, particle_chunk=8192):
    source, output = Path(source), Path(output)
    validate_config(config)
    if output.exists():
        raise FileExistsError(output)
    # Intermediate labels have never been published or consumed. Only the
    # fully reconciled artifact is renamed to the requested final destination.
    staging = output.with_name(output.name + '.all-events-staging')
    if staging.exists():
        raise FileExistsError(staging)
    source_hash = digest(source)
    materialize(source, staging, config, particle_chunk=particle_chunk)
    with h5py.File(source, 'r') as h, h5py.File(staging, 'r+') as out:
        out.attrs['complete'] = False
        time = h['time'][:]
        nt, n = h['valid'].shape
        ne = len(config['events'])
        records = out.create_dataset('all_observed_crossings', (0,),
                                     maxshape=(None,), dtype=EVENT_DTYPE,
                                     chunks=(8192,), compression='gzip')
        counts = np.zeros((n, ne), dtype=np.uint32)
        flux = np.zeros((nt, ne, 2), dtype=np.float64)
        halfwidth = np.zeros(ne)
        for lo in range(0, n, particle_chunk):
            hi = min(n, lo + particle_chunk)
            sl = slice(lo, hi)
            positions = h['position'][:, sl].astype(np.float64)
            valid = h['valid'][:, sl].astype(bool)
            fluid = valid[0] & (h['type'][0, sl] == 3)
            mass = h['mass'][0, sl].astype(np.float64)
            ids, zones = h['particle_id'][sl], h['particle_zone'][sl]
            sources = out['source_label'][sl]
            for ti in range(1, nt):
                p0, p1 = positions[ti - 1], positions[ti]
                paired = (fluid & valid[ti - 1] & valid[ti] &
                          np.isfinite(p0).all(axis=1) & np.isfinite(p1).all(axis=1))
                for ei, event in enumerate(config['events']):
                    fwd, bwd, tau = finite_crossing(p0, p1, event)
                    fwd &= paired
                    bwd &= paired
                    selected = np.flatnonzero(fwd | bwd)
                    if not len(selected):
                        continue
                    rows = np.zeros(len(selected), dtype=EVENT_DTYPE)
                    rows['particle_index'] = selected + lo
                    rows['zone'], rows['idp'] = zones[selected], ids[selected]
                    rows['source_zone'], rows['event_index'] = sources[selected], ei
                    rows['direction'] = np.where(fwd[selected], 1, -1)
                    rows['frame_before'], rows['frame_after'] = ti - 1, ti
                    rows['time_before_s'], rows['time_after_s'] = time[ti - 1], time[ti]
                    rows['chord_time_s'] = time[ti - 1] + tau[selected] * (time[ti] - time[ti - 1])
                    rows['crossing_position_m'] = p0[selected] + tau[selected, None] * (p1[selected] - p0[selected])
                    rows['initial_mass_kg'] = mass[selected]
                    start = len(records)
                    records.resize((start + len(rows),))
                    records[start:] = rows
                    counts[selected + lo, ei] += 1
                    flux[ti, ei, 0] += mass[fwd].sum()
                    flux[ti, ei, 1] += mass[bwd].sum()
                    halfwidth[ei] = max(halfwidth[ei], (time[ti] - time[ti - 1]) / 2)
        cumulative = np.cumsum(flux, axis=0)
        if not np.allclose(cumulative, out['forward_backward_mass_kg'][:], rtol=1e-12, atol=1e-10):
            raise ValueError('all crossing rows disagree with generic signed mass ledger')
        observed_first = out['first_passage_censor'][:] == 0
        if not np.array_equal(observed_first, counts > 0):
            raise ValueError('first passage and all-crossing identity counts disagree')
        out.create_dataset('total_crossing_count', data=counts, compression='gzip')
        out.create_dataset('cyclic_recrossing_count', data=np.maximum(counts.astype(np.int64) - 1, 0), compression='gzip')
        out['source_zone'] = out['source_label']
        out['first_crossing_interval'] = out['first_passage_interval']
        out['first_crossing_time_s'] = out['first_passage_chord_time']
        report = {
            'schema': 'ds02.f7.full-native-crossing-observer.v1',
            'source_hdf5': str(source), 'source_hdf5_sha256': source_hash,
            'frames': nt, 'identities': n, 'all_observed_crossing_rows': len(records),
            'event_ids': [e['id'] for e in config['events']],
            'event_crossing_counts': counts.sum(axis=0).tolist(),
            'maximum_all_event_half_bracket_s': halfwidth.tolist(),
            'initial_fluid_mass_kg': float(out.attrs['initial_fluid_mass_kg']),
            'final_unknown_region_mass_kg': float(out['unknown_mass_kg'][-1]),
            'final_native_exclusion_mass_kg': float(out['numerical_loss_mass_kg'][-1]),
            'checks': {'all_rows_signed_flux_reconciled': True, 'first_passage_identity_counts_reconciled': True},
            'q_n_status': 'not_assessed', 'production_eligibility': 'none',
            'limitations': ['saved-frame linear chords; hidden recrossings unresolved',
                            'stationary finite observation faces; moving paddle physical wall crossings require separate pose audit',
                            'native excluded identities remain unknown physical fate'],
        }
        out.attrs['all_crossings_semantics'] = 'Every observed consecutive valid saved chord; table unordered across particle chunks'
        out.attrs['event_time_semantics'] = 'all saved brackets plus chord estimates; hidden recrossings unresolved'
        out.attrs['schema'] = 'ds02.f7.native-event-labels.v2'
        out.attrs['complete'] = True
    if digest(source) != source_hash:
        raise RuntimeError('source changed during observation; staging preserved')
    os.replace(staging, output)
    report['path'], report['sha256'] = str(output), digest(output)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'config', 'report'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--particle-chunk', type=int, default=8192)
    a = p.parse_args()
    result = observe(a.source, a.output, json.loads(a.config.read_text()), a.particle_chunk)
    a.report.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
