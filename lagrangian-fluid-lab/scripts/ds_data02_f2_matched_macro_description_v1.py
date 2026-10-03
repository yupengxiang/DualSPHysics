"""Describe complete matched F2 fluid macros on verified actual source bytes.

This is observational evidence. Only the previously registered retained-mass
comparison receives its existing 5% diagnostic; COM/energy receive no new gate.
"""
import argparse
import json
from pathlib import Path
import shutil
import signal
import tempfile

import h5py
import numpy as np

from ds_data02_f3_nvme_input_audit_v1 import verified_copy
from ds_data02_f7_reference_macro_v1 import frame_macro
from ds_data02_native_labels import digest


def observe(path, binding):
    with h5py.File(path, 'r') as h:
        time = h['time'][:]
        fluid = h['initial_type'][:] == 3
        if len(time) != 401 or time[0] != 0 or time[-1] < 4 or not (np.diff(time) > 0).all():
            raise ValueError('Actual complete 401-frame 0..4 s window required')
        if not np.isfinite(time).all() or int(fluid.sum()) != binding['fluid_particles']:
            raise ValueError('Actual native initial fluid cohort differs')
        first = h['mass'][0].astype(float)
        if not h['valid'][0].astype(bool)[fluid].all() or not np.isfinite(first[fluid]).all() or (first[fluid] <= 0).any():
            raise ValueError('Incomplete or invalid initial native fluid mass')
        initial_mass = float(first[fluid].sum())
        if abs(initial_mass - 24.576) > 1e-4:
            raise ValueError('Initial native fluid mass differs from frozen continuum')
        rows = []
        missing_mass = []
        for ti in range(len(time)):
            for lo in range(0, len(fluid), 65536):
                sl = slice(lo, lo + 65536)
                if not fluid[sl].any():
                    continue
                active = h['valid'][ti, sl].astype(bool) & fluid[sl]
                if (h['type'][ti, sl][active] != 3).any():
                    raise ValueError('Initial fluid identity changes native type')
            rows.append(frame_macro(h, ti, fluid))
            missing_mass.append(float(first[fluid & ~h['valid'][ti].astype(bool)].sum()))
        rows = np.asarray(rows)
        if not np.allclose(rows[:, 0] + missing_mass, initial_mass, rtol=1e-8, atol=1e-7):
            raise ValueError('Native active plus missing cohort mass ledger does not close')
    return dict(time_s=time.tolist(), values=rows.tolist(), missing_initial_cohort_mass_kg=missing_mass,
                initial_native_float_mass_kg=initial_mass, initial_continuum_mass_kg=24.576,
                operators=['active_mass_kg', 'com_x_m', 'com_y_m', 'com_z_m', 'kinetic_energy_j'])


def run(config, output, scratch):
    if output.exists():
        raise FileExistsError('Preserve completed description')
    bindings = json.loads(config.read_text())
    sources = bindings['references']
    scratch.mkdir(parents=True, exist_ok=True)
    maximum = max(Path(v['source_hdf5']).stat().st_size for v in sources.values())
    if shutil.disk_usage(scratch).free < maximum + 100 * 2**30:
        raise ValueError('Private copy requires source size plus 100 GiB free')
    series = {}
    with tempfile.TemporaryDirectory(prefix='ds02-f2-matched-macro-', dir=scratch) as temporary:
        for role, binding in sources.items():
            source = Path(binding['source_hdf5'])
            receipt = json.loads(Path(binding['conversion_receipt']).read_text())
            report = json.loads(Path(binding['conversion_report']).read_text())
            if (receipt.get('status'), receipt.get('returncode')) != ('completed', 0):
                raise ValueError('Actual terminal conversion required')
            if report['output_hdf5'] != str(source) or report['output_sha256'] != binding['source_hdf5_sha256']:
                raise ValueError('Source does not match completed publication')
            if not report['partvtk_validation']['all_passed'] or report['solver_dimension']['solver_dimension'] != 3:
                raise ValueError('Actual official validation and 3D required')
            target = Path(temporary) / 'source.h5'
            verified_copy(source, target, binding['source_hdf5_sha256'])
            result = observe(target, binding)
            result.update(source=str(source), source_sha256=binding['source_hdf5_sha256'],
                          conversion_receipt=str(binding['conversion_receipt']),
                          conversion_receipt_sha256=digest(binding['conversion_receipt']),
                          conversion_report=str(binding['conversion_report']),
                          conversion_report_sha256=digest(binding['conversion_report']))
            series[role] = result
            target.unlink()
            print(json.dumps({'role': role, 'frames': len(result['time_s']),
                              'initial_native_mass': result['initial_native_float_mass_kg']}), flush=True)
    grid = np.linspace(0, 4, 401)
    def interpolate(d):
        values = np.asarray(d['values'])
        return np.column_stack([np.interp(grid, d['time_s'], values[:, i]) for i in range(5)])
    base = interpolate(series['fine'])
    comparisons = {}
    for role in ['coarse', 'medium']:
        candidate = interpolate(series[role])
        delta = candidate - base
        mass_error = abs(candidate[-1, 0] - base[-1, 0]) / 24.576
        comparisons[role + '_vs_fine'] = dict(
            max_absolute_difference=np.max(abs(delta), axis=0).tolist(),
            rms_difference=np.sqrt(np.mean(delta**2, axis=0)).tolist(),
            final_retained_mass_difference_over_continuum=mass_error,
            original_retained_mass_5pct_diagnostic_pass=bool(mass_error <= 0.05),
            com_energy_acceptance='not_assessed; no new favorable threshold introduced')
    result = dict(schema='ds02.f2.matched-macro-description.v1', background=bindings['background'],
                  physical_scope_binding=bindings['physical_scope_binding'], references=series,
                  comparisons=comparisons, interpolation_grid_s=grid.tolist(),
                  mass_policy='Actual native per-frame mass; initial missing cohort preserved separately; no normalization',
                  source_protocol='One checksum-verified private copy at a time; original read-only; unchanged native frame_macro',
                  event_q_n='not_granted; original matched save temporal allocation remains unmet',
                  q_n_status='not_assessed', production_approval='none', independent_case_count_increment=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.open('x').write(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['config', 'output', 'scratch-parent']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    def stop(*_):
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop)
    run(args.config, args.output, args.scratch_parent)
