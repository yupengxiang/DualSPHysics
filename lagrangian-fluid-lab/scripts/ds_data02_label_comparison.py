#!/usr/bin/env python3
"""Compare native labels for the same typed initial cohort and physical operators.

Saved-chord estimates and interval uncertainty are reported separately. This
diagnostic neither grants Q-N nor compares unrelated spatial particle lattices.
"""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np

from ds_data02_native_labels import digest


def _max(values):
    return float(np.max(values)) if values.size else None


def _label_binding(path, receipt_path):
    path, receipt_path = Path(path).resolve(), Path(receipt_path).resolve()
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
        raise ValueError('label receipt must be terminal and successful')
    command = receipt['command']
    if '--output' not in command or Path(command[command.index('--output')+1]).resolve() != path:
        raise ValueError('label output differs from actual receipt command')
    if '--source' not in command or '--config' not in command:
        raise ValueError('actual label command lacks source/config binding')
    inputs = receipt['input_hashes_at_launch']
    source = Path(command[command.index('--source')+1]).resolve()
    config = Path(command[command.index('--config')+1]).resolve()
    # Preserve complete source hashes and verify them now, not only file names.
    for item in (source, config):
        if inputs.get(str(item)) != digest(item):
            raise ValueError('native source/config changed since label launch')
    with h5py.File(path, 'r') as h:
        if h.attrs.get('source_hdf5_sha256') != inputs[str(source)]:
            raise ValueError('label source hash differs from launch binding')
        if json.loads(h.attrs['config_json']) != json.loads(config.read_text()):
            raise ValueError('label operators differ from actual config')
    return dict(path=str(path), sha256=digest(path), receipt=str(receipt_path),
                receipt_sha256=digest(receipt_path), source_sha256=inputs[str(source)],
                config_sha256=inputs[str(config)])


def compare(baseline_path, reference_path):
    """Return diagnostics with per-event physical mass, timing and censoring."""
    before = [digest(baseline_path), digest(reference_path)]
    with h5py.File(baseline_path, 'r') as a, h5py.File(reference_path, 'r') as b:
        for h in (a, b):
            if h.attrs.get('schema') != 'ds-data-02.native-labels.v1' or not h.attrs.get('complete'):
                raise ValueError('complete native labels required')
        config = json.loads(a.attrs['config_json'])
        if config != json.loads(b.attrs['config_json']):
            raise ValueError('physical operators differ')
        for key in ('particle_id', 'particle_zone', 'source_label'):
            if not np.array_equal(a[key][:], b[key][:]):
                raise ValueError('same typed cohort and sources required')
        mass = a['initial_fluid_mass_kg'][:]
        if not np.array_equal(mass, b['initial_fluid_mass_kg'][:]):
            raise ValueError('initial physical mass differs')
        fluid = mass > 0
        total = float(mass.sum())
        if total <= 0 or not np.isfinite(mass).all() or np.any(mass < 0):
            raise ValueError('invalid cohort mass')
        ta, tb = a['time'][:], b['time'][:]
        for time in (ta, tb):
            if len(time) < 2 or not np.isfinite(time).all() or np.any(np.diff(time) <= 0):
                raise ValueError('invalid label timeline')
        if abs(ta[0]-tb[0]) > 1e-9 or abs(ta[-1]-tb[-1]) > max(np.diff(ta).max(), np.diff(tb).max()):
            raise ValueError('time windows differ')
        indices = np.searchsorted(tb, ta)
        hi = np.minimum(indices, len(tb)-1)
        lo = np.maximum(indices-1, 0)
        nearest = np.where(abs(tb[hi]-ta) < abs(tb[lo]-ta), hi, lo)
        offsets = abs(tb[nearest]-ta)
        # Adaptive steps overshoot nominal save times. Keep actual offsets and
        # the surrounding mass-flux envelope rather than claiming exact saves.
        event_rows = []
        for ei, event in enumerate(config['events']):
            ca, cb = a['first_passage_censor'][:, ei], b['first_passage_censor'][:, ei]
            if not np.isin(ca[fluid], [0, 1]).all() or not np.isin(cb[fluid], [0, 1]).all():
                raise ValueError('unsupported event censor code')
            both = fluid & (ca == 0) & (cb == 0)
            pa, pb = a['first_passage_interval'][:, ei, :][both], b['first_passage_interval'][:, ei, :][both]
            ea, eb = a['first_passage_chord_time'][:, ei][both], b['first_passage_chord_time'][:, ei][both]
            for interval, estimate in ((pa, ea), (pb, eb)):
                if not np.isfinite(interval).all() or not np.isfinite(estimate).all() or np.any(interval[:, 1] < interval[:, 0]) or np.any(estimate < interval[:, 0]) or np.any(estimate > interval[:, 1]):
                    raise ValueError('observed event lacks valid saved bracket')
            delta = abs(ea-eb)
            gap = np.maximum(0, np.maximum(pa[:, 0]-pb[:, 1], pb[:, 0]-pa[:, 1]))
            possible = np.maximum(abs(pa[:, 0]-pb[:, 1]), abs(pa[:, 1]-pb[:, 0]))
            flux_a, flux_b = a['forward_backward_mass_kg'][:, ei, :], b['forward_backward_mass_kg'][:, ei, :]
            fa, fb = flux_a[:], flux_b[:]
            if not np.isfinite(fa).all() or not np.isfinite(fb).all() or np.any(np.diff(fa, axis=0) < -1e-9) or np.any(np.diff(fb, axis=0) < -1e-9):
                raise ValueError('cumulative directional flux must be finite and nondecreasing')
            envelope = np.maximum(abs(fa-fb[lo]), abs(fa-fb[hi]))
            event_rows.append(dict(event_id=event['id'], both_observed_mass_kg=float(mass[both].sum()),
                baseline_only_observed_mass_kg=float(mass[fluid & (ca == 0) & (cb != 0)].sum()),
                reference_only_observed_mass_kg=float(mass[fluid & (ca != 0) & (cb == 0)].sum()),
                jointly_censored_mass_kg=float(mass[fluid & (ca != 0) & (cb != 0)].sum()),
                chord_time_max_absolute_difference_s=_max(delta),
                chord_time_mass_weighted_mean_absolute_difference_s=float(np.dot(delta, mass[both])/mass[both].sum()) if both.any() else None,
                saved_interval_minimum_required_max_difference_s=_max(gap),
                saved_interval_worst_possible_max_difference_s=_max(possible),
                baseline_max_saved_bracket_width_s=_max(pa[:, 1]-pa[:, 0]),
                reference_max_saved_bracket_width_s=_max(pb[:, 1]-pb[:, 0]),
                cumulative_forward_backward_max_difference_kg=float(abs(fa-fb[nearest]).max()),
                timestamp_bracket_forward_backward_max_difference_bound_kg=float(envelope.max()),
                terminal_forward_backward_difference_kg=(fa[-1]-fb[-1]).tolist(),
                terminal_forward_backward_baseline_kg=fa[-1].tolist(), terminal_forward_backward_reference_kg=fb[-1].tolist()))
        ra, rb = a['residence_time_s'][:][fluid], b['residence_time_s'][:][fluid]
        if not np.isfinite(ra).all() or not np.isfinite(rb).all() or np.any(ra < 0) or np.any(rb < 0):
            raise ValueError('invalid physical residence seconds')
        residence_delta = abs(ra-rb)
        final_a, final_b = a['final_category'][:], b['final_category'][:]
        # Each cohort member is classified once; table L1 counts migrations twice.
        final_mass = float(mass[fluid & (final_a != final_b)].sum())
        result = dict(schema='ds02.native-label-comparison.v1', initial_fluid_mass_kg=total,
            baseline_saved_frames=len(ta), reference_saved_frames=len(tb),
            max_actual_timestamp_alignment_difference_s=float(offsets.max()), events=event_rows,
            residence=[dict(destination_id=region['id'], max_absolute_difference_s=float(residence_delta[:, ri].max()),
                mass_weighted_mean_absolute_difference_s=float(np.dot(residence_delta[:, ri], mass[fluid])/total))
                for ri, region in enumerate(config['destination_regions'])],
            final_destination_disagreement_mass_kg=final_mass,
            final_destination_disagreement_mass_fraction=final_mass/total,
            source_final_table_l1_difference_kg=float(abs(a['source_final_mass_kg'][:]-b['source_final_mass_kg'][:]).sum()),
            temporal_diagnostics={key: float(abs(a[key][:]-b[key][:][nearest]).max())
                for key in ('unknown_mass_kg', 'numerical_loss_mass_kg', 'invalid_state_mass_kg')},
            q_n_status='not_granted', independent_production_case_increment=0,
            limitations=['saved intervals do not bound hidden recrossings within each interval',
                'chord residence interpolation has no continuous-path guarantee',
                'censor changes retain their physical mass and are not omitted from timing assessment',
                'this is one same-lattice temporal diagnostic; spatial and parameter-domain qualification remain required'])
    if before != [digest(baseline_path), digest(reference_path)]:
        raise RuntimeError('labels mutated during comparison')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('baseline', 'reference', 'baseline_receipt', 'reference_receipt', 'output'):
        p.add_argument('--'+key.replace('_', '-'), type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('preserve consumed comparison artifact')
    bindings = dict(baseline=_label_binding(args.baseline, args.baseline_receipt), reference=_label_binding(args.reference, args.reference_receipt))
    result = compare(args.baseline, args.reference)
    result['bindings'] = bindings
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps(dict(output=str(args.output), q_n_status='not_granted')))
