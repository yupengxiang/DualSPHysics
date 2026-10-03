"""Run the unchanged native label operator on digest-verified private bytes."""
import argparse
import json
import os
from pathlib import Path
import signal
import tempfile

import h5py
import numpy as np

from ds_data02_f3_nvme_input_audit_v1 import verified_copy
from ds_data02_native_labels import digest, materialize


def label_closure(path, expected_ids, expected_mass):
    """Check actual identity, fate, censoring, residence and mass ledgers."""
    checks = {}
    with h5py.File(path, 'r') as h:
        time = h['time'][:]
        ids = np.column_stack((h['particle_zone'][:], h['particle_id'][:]))
        mass = h['initial_fluid_mass_kg'][:]
        fluid = mass > 0
        nt, n = h['destination_time_series'].shape
        config = json.loads(h.attrs['config_json'])
        nr, ne = len(config['destination_regions']), len(config.get('events', []))
        checks['complete'] = bool(h.attrs['complete'])
        checks['unique_identity'] = len(np.unique(ids, axis=0)) == n
        checks['exact_source_identity'] = np.array_equal(ids, expected_ids)
        checks['finite_positive_initial_cohort'] = bool(np.isfinite(mass).all() and fluid.any())
        checks['native_initial_mass'] = bool(np.isclose(mass.sum(), expected_mass, rtol=1e-10, atol=1e-9))
        checks['finite_increasing_time'] = bool(len(time) == nt and np.isfinite(time).all() and (np.diff(time) > 0).all())
        checks['source_labels_cover_initial_fluid'] = bool((h['source_label'][:][fluid] > 0).all())
        checks['final_matches_last_destination'] = np.array_equal(h['final_category'][:], h['destination_time_series'][-1])
        checks['source_final_mass_closed'] = bool(np.isclose(h['source_final_mass_kg'][:].sum(), mass.sum(), rtol=1e-10, atol=1e-9))
        brackets = h['first_passage_interval'][:]
        estimates = h['first_passage_chord_time'][:]
        censor = h['first_passage_censor'][:]
        observed = censor == 0
        checks['censor_codes'] = bool(np.isin(censor, [0, 1]).all())
        checks['finite_observed_brackets'] = bool(np.isfinite(brackets[observed]).all() and np.isfinite(estimates[observed]).all())
        checks['positive_observed_brackets'] = bool((brackets[..., 1][observed] > brackets[..., 0][observed]).all())
        checks['estimates_within_brackets'] = bool(((estimates[observed] >= brackets[..., 0][observed]-1e-12) & (estimates[observed] <= brackets[..., 1][observed]+1e-12)).all())
        checks['unobserved_brackets_nan'] = bool(np.isnan(brackets[~observed]).all() and np.isnan(estimates[~observed]).all())
        residence, unresolved = h['residence_time_s'][:], h['unresolved_interval_time_s'][:]
        checks['finite_nonnegative_residence'] = bool(np.isfinite(residence).all() and (residence >= -1e-12).all())
        checks['finite_nonnegative_unresolved'] = bool(np.isfinite(unresolved).all() and (unresolved >= -1e-12).all())
        checks['disjoint_residence_within_window'] = bool((residence.sum(axis=1)+unresolved <= time[-1]-time[0]+1e-9).all())
        fb = h['forward_backward_mass_kg'][:]
        checks['finite_monotone_directional_flux'] = bool(np.isfinite(fb).all() and (fb >= -1e-12).all() and (np.diff(fb, axis=0) >= -1e-9).all())
        checks['net_flux_difference'] = bool(np.allclose(h['cumulative_net_flux_kg'][:], fb[..., 0]-fb[..., 1], rtol=1e-9, atol=1e-8))
        checks['label_shapes'] = brackets.shape == (n, ne, 2) and residence.shape == (n, nr)
        max_residual = 0.0
        for ti in range(nt):
            dest = h['destination_time_series'][ti]
            if not np.isin(dest, np.arange(-3, nr+1)).all():
                checks['destination_codes'] = False
            for code, name in [(0, 'unknown_mass_kg'), (-1, 'numerical_loss_mass_kg'), (-2, 'invalid_state_mass_kg')]:
                max_residual = max(max_residual, abs(float(mass[dest == code].sum())-float(h[name][ti])))
            if not (dest[~fluid] == -3).all() or (dest[fluid] == -3).any():
                checks['fluid_cohort_identity'] = False
        checks.setdefault('destination_codes', True)
        checks.setdefault('fluid_cohort_identity', True)
        checks['every_frame_unknown_loss_invalid_ledger'] = max_residual <= 1e-8
        result = {'checks': checks, 'passed': all(checks.values()), 'frames': nt,
                  'identities': n, 'fluid_identities': int(fluid.sum()),
                  'initial_native_float_mass_kg': float(mass.sum()),
                  'observed_first_passages': int(observed[fluid].sum()),
                  'final_numerical_loss_mass_kg': float(h['numerical_loss_mass_kg'][-1]),
                  'final_unknown_mass_kg': float(h['unknown_mass_kg'][-1]),
                  'maximum_ledger_residual_kg': max_residual,
                  'q_n_status': 'not_assessed'}
    return result


def run(binding_path, config_path, output_dir, scratch):
    binding = json.loads(binding_path.read_text())
    source = Path(binding['source_hdf5'])
    config = json.loads(config_path.read_text())
    receipt_path = Path(binding['conversion_receipt'])
    report_path = Path(binding['conversion_report'])
    receipt, report = json.loads(receipt_path.read_text()), json.loads(report_path.read_text())
    if digest(receipt_path) != binding['conversion_receipt_sha256'] or digest(report_path) != binding['conversion_report_sha256']:
        raise ValueError('Terminal conversion binding changed')
    if receipt['status'] != 'completed' or receipt['returncode'] != 0 or not report['partvtk_validation']['all_passed']:
        raise ValueError('Actual completed conversion with official validation required')
    if report['output_hdf5'] != str(source) or report['output_sha256'] != binding['source_hdf5_sha256']:
        raise ValueError('Source differs from converter publication')
    scratch.mkdir(parents=True, exist_ok=True)
    free = os.statvfs(scratch)
    if free.f_bavail*free.f_frsize < source.stat().st_size+100*1024**3:
        raise ValueError('Insufficient NVMe capacity')
    output_dir.mkdir(parents=True, exist_ok=True)
    final, stage = output_dir/'native-labels.h5', output_dir/'native-labels.h5.unpublished'
    if final.exists() or stage.exists():
        raise FileExistsError('Preserve existing label artifact')
    before = source.stat()
    with tempfile.TemporaryDirectory(prefix='ds02-native-labels-', dir=scratch) as temporary:
        target = Path(temporary)/'trajectory.h5'
        verified_copy(source, target, binding['source_hdf5_sha256'])
        with h5py.File(target, 'r') as h:
            ids = np.column_stack((h['particle_zone'][:], h['particle_id'][:]))
            mass = np.where(h['valid'][0].astype(bool) & (h['type'][0] == 3), h['mass'][0].astype(float), 0).sum()
        result = materialize(target, stage, config, particle_chunk=16384)
        closure = label_closure(stage, ids, mass)
        if not closure['passed']:
            (output_dir/'failed-closure.json').write_text(json.dumps(closure, indent=2)+'\n')
            raise ValueError('Labels failed independent closure; preserve unpublished artifact')
        with h5py.File(stage, 'r+') as h:
            h.attrs['source_hdf5'] = str(source.resolve())
            h.attrs['audit_storage_protocol'] = 'SHA256-identical private NVMe input; unchanged canonical label operator'
        after = source.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Immutable original changed')
        os.replace(stage, final)
    result.update(path=str(final), sha256=digest(final), source_hdf5=str(source),
                  source_hdf5_sha256=binding['source_hdf5_sha256'], closure=closure,
                  private_scratch_removed=True)
    (output_dir/'labels-report.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['binding', 'config', 'output-dir', 'scratch-parent']:
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    def stop(*_):
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop)
    print(json.dumps(run(a.binding, a.config, a.output_dir, a.scratch_parent)), flush=True)
