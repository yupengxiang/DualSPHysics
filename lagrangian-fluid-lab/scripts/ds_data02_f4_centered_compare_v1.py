"""Compare full native macro curves using preregistered continuum scales."""
import argparse
import json
from pathlib import Path

import numpy as np
from ds_data02_native_labels import digest


def compare(candidate, reference, owner, frozen, mechanism, output):
    if output.exists():
        raise FileExistsError(output)
    paths = [candidate, reference, owner, frozen]
    hashes = {str(p): digest(p) for p in paths}
    a, b, meta, contract = [json.loads(p.read_text()) for p in paths]
    assert a['physical_binding_sha256'] == b['physical_binding_sha256'] == meta['physical_binding_sha256']
    assert a['operators'] == b['operators']
    scale = contract['budgets'][mechanism]['original_scale_contract']
    length, speed = scale['L_m'], scale['U_m_per_s']
    masses = meta['physical_binding']['initial_state']['continuum_mass_by_source_kg']
    ta, tb = np.asarray(a['time_s']), np.asarray(b['time_s'])
    assert np.all(np.diff(ta) > 0) and np.all(np.diff(tb) > 0)
    assert ta[0] == tb[0] == 0 and min(ta[-1], tb[-1]) >= 1.2
    t = np.unique(np.append(tb[(tb >= 0) & (tb <= 1.2)], 1.2))
    assert t[0] == 0 and t[-1] == 1.2 and len(t) >= 1200
    rows = {}
    for group in b['source_series']:
        mass = sum(masses.values()) if group == 'all_fluid' else masses[group]
        denominators = np.array([mass, length, length, length, mass*speed, mass*speed, mass*speed, mass*speed**2, length, length, length])
        va, vb = np.asarray(a['source_series'][group]), np.asarray(b['source_series'][group])
        assert np.isfinite(va).all() and np.isfinite(vb).all()
        aa = np.column_stack([np.interp(t, ta, va[:, i]) for i in range(va.shape[1])])
        bb = np.column_stack([np.interp(t, tb, vb[:, i]) for i in range(vb.shape[1])])
        absolute = np.max(np.abs(aa-bb), axis=0)
        fraction = absolute/denominators
        rows[group] = {key: {'max_absolute_difference': float(absolute[i]), 'frozen_denominator': float(denominators[i]), 'error_fraction': float(fraction[i]), 'within_macro_budget': bool(fraction[i] <= scale['macro_error_budget_fraction'])} for i, key in enumerate(a['operators'])}
    assert hashes == {str(p): digest(p) for p in paths}
    result = {'schema': 'ds02.f4.centered-macro-comparison.v1', 'candidate': str(candidate), 'reference': str(reference), 'source_sha256': hashes, 'physical_binding_sha256': a['physical_binding_sha256'], 'actual_time_alignment': 'linear interpolation on reference native times in full 0-1.2 s window, including interpolated physical endpoint 1.2', 'time_samples': len(t), 'comparison': rows, 'macro_budget_fraction': scale['macro_error_budget_fraction'], 'all_observed_macro_items_within_budget': all(x['within_macro_budget'] for row in rows.values() for x in row.values()), 'q_n_status': 'not_assessed', 'production_approval': 'none', 'limitations': ['Two-resolution comparisons are observations; full three-resolution reference and independent time/save evidence remain required', 'Contact, reconstruction, transport, censored events and numerical exclusion closure remain separate', 'Frozen continuum denominators do not rescale trajectory mass; source extrema retained']}
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'all_observed_macro_items_within_budget': result['all_observed_macro_items_within_budget'], 'q_n_status': 'not_assessed'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ('candidate', 'reference', 'owner', 'frozen', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--mechanism', choices=['COL', 'DROP'], required=True)
    args = parser.parse_args()
    compare(args.candidate, args.reference, args.owner, args.frozen, args.mechanism, args.output)
