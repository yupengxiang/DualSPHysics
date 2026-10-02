"""Bound native saved-chord passage quantiles without discarding censored mass."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np
from ds_data02_native_labels import digest


def quantile_bounds(intervals, weights, observed, unresolved, end, fractions):
    weights = np.asarray(weights, dtype=float)
    intervals = np.asarray(intervals, dtype=float)
    observed = np.asarray(observed, dtype=bool)
    unresolved = np.asarray(unresolved, dtype=bool)
    if not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError('Positive finite original native weights required')
    if np.any(observed & (~np.isfinite(intervals).all(axis=1) | (intervals[:, 0] > intervals[:, 1]))):
        raise ValueError('Invalid observed interval')
    # An unresolved history receives the widest bound even if a later saved
    # chord was observed. This preserves uncertainty rather than inventing
    # an earlier first passage. Fully observed no-crossing histories are
    # right-censored at the registered end of the native operator window.
    lower = np.where(unresolved, 0.0, np.where(observed, intervals[:, 0], end))
    upper = np.where(observed & ~unresolved, intervals[:, 1], np.inf)
    mass = float(weights.sum())

    def rank(values, fraction):
        order = np.argsort(values, kind='stable')
        index = np.searchsorted(np.cumsum(weights[order]), fraction * mass, side='left')
        return float(values[order[min(index, len(order) - 1)]])

    result = []
    for fraction in fractions:
        if not 0 < fraction < 1:
            raise ValueError('Quantile fractions must be within (0,1)')
        low, high = rank(lower, fraction), rank(upper, fraction)
        result.append({'fraction': fraction, 'lower_s': low,
                       'upper_s': high if np.isfinite(high) else None,
                       'status': 'bounded' if np.isfinite(high) else 'censored_or_unidentified'})
    return result


def summarize(path, end, fractions):
    with h5py.File(path, 'r') as h:
        if not h.attrs.get('complete', False):
            raise ValueError('Incomplete labels')
        time = np.asarray(h['time'][:], dtype=float)
        if not np.isfinite(time).all() or np.any(np.diff(time) <= 0) or time[0] != 0 or time[-1] < end:
            raise ValueError('Incomplete native time window')
        all_mass = np.asarray(h['initial_fluid_mass_kg'][:], dtype=float)
        if not np.isfinite(all_mass).all() or np.any(all_mass < 0):
            raise ValueError('Invalid initial native mass axis')
        fluid = all_mass > 0  # Retain fluid with unassigned source regions too.
        mass = all_mass[fluid]
        if not len(mass) or not np.isclose(mass.sum(), h.attrs['initial_fluid_mass_kg'], rtol=1e-12):
            raise ValueError('Initial fluid cohort mass does not close')
        unresolved = np.asarray(h['unresolved_interval_time_s'][:], dtype=float)[fluid] > 0
        source = np.asarray(h['source_label'][:])[fluid]
        config = json.loads(h.attrs['config_json'])
        events = []
        for index, event in enumerate(config['events']):
            interval = np.asarray(h['first_passage_interval'][:, index, :], dtype=float)[fluid]
            observed = np.asarray(h['first_passage_censor'][:, index])[fluid] == 0
            events.append({'event_id': event['id'],
                           'observed_mass_kg': float(mass[observed].sum()),
                           'censored_mass_kg': float(mass[~observed].sum()),
                           'quantiles': quantile_bounds(interval, mass, observed, unresolved, end, fractions)})
        return {'source': str(path), 'source_sha256': digest(path), 'frames': len(time),
                'initial_native_fluid_mass_kg': float(mass.sum()),
                'unassigned_initial_source_mass_kg': float(mass[source <= 0].sum()),
                'unresolved_history_mass_kg': float(mass[unresolved].sum()), 'events': events,
                'config': config, 'source_hdf5_sha256': str(h.attrs['source_hdf5_sha256'])}


def compare(contract, output):
    if output.exists():
        raise FileExistsError(output)
    c = json.loads(contract.read_text())
    paths = [Path(c[k]) for k in ['baseline', 'variant']]
    budget_path = Path(c['budget'])
    budget = json.loads(budget_path.read_text())
    sources = {str(p): digest(p) for p in [contract, budget_path, *paths]}
    for p in paths:
        if sources[str(p)] != c['expected_label_sha256'][str(p)]:
            raise ValueError('Labels differ from registered source digest')
    a, b = [summarize(p, c['window_end_s'], c['quantile_fractions']) for p in paths]
    if a['config'] != b['config']:
        raise ValueError('Different native event operators')
    allowance = budget['physical_scale']['save_or_integration_event_budget_s']
    comparisons = []
    for left, right in zip(a['events'], b['events']):
        assert left['event_id'] == right['event_id']
        for x, y in zip(left['quantiles'], right['quantiles']):
            bounded = x['upper_s'] is not None and y['upper_s'] is not None
            minimum = max(0.0, x['lower_s'] - y['upper_s'], y['lower_s'] - x['upper_s']) if bounded else None
            maximum = max(abs(x['lower_s'] - y['upper_s']), abs(x['upper_s'] - y['lower_s'])) if bounded else None
            status = 'unidentified_due_to_censoring'
            if bounded:
                status = 'fail_even_allowing_intervals' if minimum > allowance else ('within_allocation_for_all_interval_choices' if maximum <= allowance else 'unresolved_within_brackets')
            comparisons.append({'event_id': left['event_id'], 'fraction': x['fraction'],
                                'baseline': x, 'variant': y, 'minimum_separation_s': minimum,
                                'maximum_separation_s': maximum, 'allocation_s': allowance, 'status': status})
    if any(digest(Path(p)) != value for p, value in sources.items()):
        raise ValueError('Consumed labels or contract changed')
    result = {'schema': 'ds02.f7.native-passage-quantile-bounds.v1', 'source_sha256': sources,
              'baseline': a, 'variant': b, 'comparisons': comparisons,
              'semantics': 'Whole initial native fluid mass CDF of first observed saved-chord crossings; never conditional on observed mass alone.',
              'uncertainty': 'Any unresolved history receives [0,infinity]; fully observed no-crossing native histories are right-censored. Hidden recrossings between saves remain outside the saved-chord operator.',
              'qualification_claim': 'none; diagnostics only, current actual integration and save evidence required separately',
              'production_approval': 'none'}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(comparisons), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--contract', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    compare(args.contract, args.output)
