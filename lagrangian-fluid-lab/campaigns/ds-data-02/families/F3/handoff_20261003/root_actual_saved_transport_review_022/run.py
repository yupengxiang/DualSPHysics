"""Apply the reviewed saved-frequency measurements to fully bound native labels."""
import argparse
import importlib.util
import json
from pathlib import Path

import h5py
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    binding = json.loads(args.binding.read_text())
    spec = importlib.util.spec_from_file_location('reviewed_saved_transport', binding['reader'])
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    canonical = json.loads(Path(binding['config']).read_text())
    windows = {}
    boundary_observations = {}
    identity = None
    signatures = {}
    for role, expected in [('nominal', 836), ('dense', 4176)]:
        item = binding[role]
        path = Path(item['labels'])
        report = json.loads(Path(item['report']).read_text())
        receipt = json.loads(Path(item['receipt']).read_text())
        if (receipt['status'] != 'completed' or receipt['returncode'] != 0
                or not report['closure']['passed']
                or report['path'] != str(path)
                or report['sha256'] != reader.digest(path)):
            raise ValueError('Completed full native labels publication required')
        signatures[str(path)] = (path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns)
        with h5py.File(path, 'r') as h:
            if not h.attrs['complete'] or json.loads(h.attrs['config_json']) != canonical:
                raise ValueError('Label completion/configuration changed')
            times = h['time'][:]
            if (len(times) != expected or times[0] != 0 or times[-1] < 8.35
                    or not np.isfinite(times).all() or not np.all(np.diff(times) > 0)):
                raise ValueError('Expected full native frame count/window missing')
            windows[role] = [float(times[0]), float(times[-1])]
            ids = np.column_stack((h['particle_zone'][:], h['particle_id'][:]))
            masses = h['initial_fluid_mass_kg'][:]
            source = h['source_label'][:]
            cohort = masses > 0
            if (len(ids) != 108000 or len(np.unique(ids, axis=0)) != 108000
                    or cohort.sum() != 34560 or not np.isfinite(masses).all()
                    or not np.all(masses >= 0) or not np.array_equal(cohort, source > 0)):
                raise ValueError('Native initial identity/mass/source cohort invalid')
            current = (ids, masses, source)
            if identity is None:
                identity = current
            elif any(not np.array_equal(a, b) for a, b in zip(identity, current)):
                raise ValueError('Exact same native UID/mass/source labels required')
            if h['destination_time_series'].shape != (expected, 108000):
                raise ValueError('Full canonical destination history missing')
            censor = h['first_passage_censor'][:][cohort]
            chord = h['first_passage_chord_time'][:][cohort]
            boundary_observations[role] = {
                event['id']: int(((censor[:, i] == 0) & (chord[:, i] > 8.35)).sum())
                for i, event in enumerate(canonical['events'])}
    result = reader.compare_f3_saved_frequency_v2(
        nominal_labels_path=Path(binding['nominal']['labels']),
        nominal_report_path=Path(binding['nominal']['report']),
        dense_labels_path=Path(binding['dense']['labels']),
        dense_report_path=Path(binding['dense']['report']),
        config_path=Path(binding['config']), output_path=args.output,
        nominal_receipt_path=Path(binding['nominal']['receipt']),
        dense_receipt_path=Path(binding['dense']['receipt']))
    # Replace unverified hardcoded step metadata with separately pinned actual reports.
    result['simulation_context']['timestep_audit_evidence'] = {
        role: {'path': binding[role]['timestep_report'],
               'actual_report': json.loads(Path(binding[role]['timestep_report']).read_text())}
        for role in ['nominal', 'dense']}
    result['simulation_context']['solver_step_parity_assessment'] = (
        'Native interval totals are separately reported; equal totals do not prove equal trajectories.')
    result['root_validation'] = {'complete_configuration_and_exact_cohort_verified': True,
        'expected_full_native_frames': {'nominal': 836, 'dense': 4176},
        'actual_label_windows_s': windows,
        'observed_chord_estimates_after_physical_endpoint': boundary_observations,
        'native_window_functional_policy': (
            'Fate/residence measurements retain each complete native label window. '
            'CDF measurements restrict to [0,8.35]; asynchronous categorical observations '
            'are labelled as such. Native endpoint overshoots are not extrapolated away.'),
        'q_n_status': 'not_assessed', 'production_approval': 'none'}
    for role in ['nominal', 'dense']:
        path = Path(binding[role]['labels'])
        if (path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns) != signatures[str(path)]:
            raise ValueError('Immutable labels changed during measurement')
        if reader.digest(path) != json.loads(Path(binding[role]['report']).read_text())['sha256']:
            raise ValueError('Label bytes changed during measurement')
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({key: {'CDFsup': value['empirical_cdf_comparison']['knot_supremum_absolute_deviation'],
                          'fate_switches': value['fate_contingency']['fate_switch_count']}
                      for key, value in result['events'].items()}))


if __name__ == '__main__':
    main()
