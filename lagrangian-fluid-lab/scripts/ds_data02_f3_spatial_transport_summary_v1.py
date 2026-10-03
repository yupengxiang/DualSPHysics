"""Describe independently bound spatial transport populations without a gate."""
import argparse
import itertools
import json
from pathlib import Path

import h5py
import numpy as np

from ds_data02_native_labels import digest


def quantiles(values, weights):
    if not len(values):
        return None
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    cumulative = np.cumsum(weights)/weights.sum()
    return {str(q): float(values[min(np.searchsorted(cumulative, q), len(values)-1)]) for q in [.05, .5, .95]}


def event_cdf(times, weights, points, initial_mass):
    """Unobserved mass stays censored; it is never placed at a finite time."""
    order = np.argsort(times)
    cumulative = np.r_[0.0, np.cumsum(weights[order])]/initial_mass
    return cumulative[np.searchsorted(times[order], points, side='right')]


def run(manifest_path, output):
    m = json.loads(manifest_path.read_text())
    if output.exists():
        raise FileExistsError(output)
    populations, results, config = {}, {}, None
    for role, binding in m['labels'].items():
        for name in ['path', 'receipt']:
            if digest(binding[name]) != binding[name+'_sha256']:
                raise ValueError('Immutable label or actual receipt differs')
        r = json.loads(Path(binding['receipt']).read_text())
        if r['status'] != 'completed' or r['returncode'] != 0:
            raise ValueError('Actual successful label materialization required')
        with h5py.File(binding['path'], 'r') as h:
            if not h.attrs['complete'] or h.attrs['source_hdf5_sha256'] != binding['source_hdf5_sha256']:
                raise ValueError('Incomplete or differently bound label artifact')
            c = json.loads(h.attrs['config_json'])
            if config is None:
                config = c
            elif config != c:
                raise ValueError('Spatial physical observation operators differ')
            mass = h['initial_fluid_mass_kg'][:]
            fluid = mass > 0
            total = float(mass.sum())
            if total <= 0 or not np.isfinite(mass).all():
                raise ValueError('Invalid native source mass')
            time = h['time'][:]
            if len(time) != 836 or time[0] != 0 or time[-1] < 8.35 or not (np.diff(time) > 0).all():
                raise ValueError('Actual complete historical spatial window required')
            populations[role] = []
            events = []
            for ei, event in enumerate(config['events']):
                observed = fluid & (h['first_passage_censor'][:, ei] == 0)
                times = h['first_passage_chord_time'][:, ei][observed]
                weights = mass[observed]
                brackets = h['first_passage_interval'][:, ei, :][observed]
                if not np.isfinite(times).all() or not np.isfinite(brackets).all():
                    raise ValueError('Observed passage is not finite')
                populations[role].append((times, weights, total))
                events.append({'id': event['id'], 'observed_identities': int(observed.sum()),
                               'observed_mass_kg': float(weights.sum()),
                               'observed_mass_fraction': float(weights.sum()/total),
                               'censored_initial_mass_fraction': float(mass[fluid & ~observed].sum()/total),
                               'conditional_mass_weighted_chord_quantiles_s': quantiles(times, weights),
                               'maximum_observed_saved_bracket_width_s': float(np.diff(brackets, axis=1).max()) if len(times) else None})
            results[role] = {'binding': binding, 'identities': len(mass), 'fluid_identities': int(fluid.sum()),
                             'actual_stored_initial_mass_kg': total, 'window_s': [float(time[0]), float(time[-1])],
                             'events': events, 'source_final_mass_fraction': (h['source_final_mass_kg'][:]/total).tolist(),
                             'terminal_directional_flux_kg': h['forward_backward_mass_kg'][-1].tolist(),
                             'residence_mass_weighted_quantiles_s': [quantiles(h['residence_time_s'][:, i][fluid], mass[fluid]) for i in range(len(config['destination_regions']))]}
    pairs = {}
    for a, b in itertools.combinations(populations, 2):
        rows = []
        for ei, event in enumerate(config['events']):
            ta, wa, ma = populations[a][ei]
            tb, wb, mb = populations[b][ei]
            end = min(results[a]['window_s'][1], results[b]['window_s'][1])
            points = np.unique(np.r_[0.0, ta[ta <= end], tb[tb <= end], end])
            delta = np.abs(event_cdf(ta, wa, points, ma)-event_cdf(tb, wb, points, mb))
            rows.append({'id': event['id'], 'maximum_unconditional_observed_mass_CDF_difference': float(delta.max()),
                         'common_observation_window_end_s': end,
                         'mass_CDF_interpretation': 'Observed first-passage mass divided by each actual initial fluid mass; censored particles retain censored status',
                         'identity_pairing': False})
        pairs[a+'_vs_'+b] = rows
    result = {'schema': 'ds02.f3.spatial-transport-description.v1', 'populations': results,
              'pairwise_diagnostics': pairs, 'q_n_granted': False, 'production_granted': False,
              'claim_boundary': 'Descriptive spatial distribution evidence only; no newly invented acceptance threshold; different spatial identities are never paired',
              'source_mass_policy': 'Actual stored per-particle mass retained; dimensionless fractions are descriptive observables, not changes to trajectory mass'}
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'pairwise_diagnostics': pairs, 'q_n_granted': False}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    run(a.manifest, a.output)
