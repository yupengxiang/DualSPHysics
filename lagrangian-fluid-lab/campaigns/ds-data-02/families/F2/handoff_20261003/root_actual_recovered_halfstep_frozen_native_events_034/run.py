"""Execute frozen F2 events with exactly guarded native weights and bounded I/O."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import h5py
import numpy as np

LAB = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(LAB / 'scripts'))
from ds_data02_f3_nvme_input_audit_v1 import verified_copy


class DatasetReader:
    def __init__(self, dataset):
        self.dataset = dataset

    def __getattr__(self, key):
        return getattr(self.dataset, key)

    def __getitem__(self, selection):
        if isinstance(selection, tuple):
            items = list(selection)
            for index, item in enumerate(items):
                if (isinstance(item, np.ndarray) and item.ndim == 1 and item.size
                        and np.issubdtype(item.dtype, np.integer)
                        and int(item[0]) >= 0
                        and np.array_equal(item, np.arange(int(item[0]), int(item[0]) + len(item)))):
                    items[index] = slice(int(item[0]), int(item[-1]) + 1)
            selection = tuple(items)
        return self.dataset[selection]


class FileReader:
    def __init__(self, handle):
        self.handle = handle

    def __getattr__(self, key):
        return getattr(self.handle, key)

    def __contains__(self, key):
        return key in self.handle

    def __getitem__(self, key):
        dataset = self.handle[key]
        return DatasetReader(dataset) if isinstance(dataset, h5py.Dataset) else dataset

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.handle.__exit__(*args)


def source_file(path, mode='r', *args, **kwargs):
    handle = h5py.File(path, mode, *args, **kwargs)
    return FileReader(handle) if mode == 'r' else handle


def synthetic_reader_check(parent):
    """Check actual h5py selection shape, dtype and bytes on a synthetic fixture."""
    path = parent / 'synthetic-selection.h5'
    data = np.arange(8 * 12 * 3, dtype=np.float32).reshape(8, 12, 3)
    data.view(np.uint32)[1, 3, 0] = 0x7fc00123  # preserve NaN payload
    data.view(np.uint32)[1, 4, 0] = 0x80000000  # preserve signed zero
    with h5py.File(path, 'w') as f:
        f.create_dataset('data', data=data, chunks=(1, 12, 3), compression='gzip')
    with h5py.File(path, 'r') as f:
        fast = DatasetReader(f['data'])
        for rows in [np.arange(2, 7), np.array([2, 4, 7])]:
            selection = (1, rows, slice(None))
            original, selected = f['data'][selection], fast[selection]
            if (original.shape != selected.shape or original.dtype != selected.dtype
                    or original.tobytes() != selected.tobytes()):
                raise ValueError('I/O selection changed synthetic payload')
    path.unlink()


def completed(path):
    r = json.loads(Path(path).read_text())
    if r['status'] != 'completed' or r['returncode'] != 0:
        raise ValueError('Source is not completed0: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    b = json.loads(args.binding.read_text())
    recovered = json.loads(Path(b['recovered_artifact_audit']).read_text())
    if (not recovered['all_13_payload_fingerprints_reverified']
            or not recovered['input_hashes_current_match_launch']
            or recovered['original_launcher_OS_returncode'] != 'unknown; original receipt remains unchanged'
            or recovered['verified_hdf5'] != b['trajectory']
            or recovered['verified_hdf5_sha256'] != b['trajectory_sha256']):
        raise ValueError('Recovered artifact verification does not bind this exact native source')
    original_pose = Path(recovered['original_receipt'])
    if hashlib.sha256(original_pose.read_bytes()).hexdigest() != recovered['original_receipt_sha256']:
        raise ValueError('Original unfinalized pose receipt changed')
    out = args.output_dir
    if (out / 'native-weighted-labels.h5').exists():
        raise FileExistsError(out)
    for path in b['completed_receipts']:
        completed(path)
    conversion = json.loads(Path(b['conversion_report']).read_text())
    if (conversion['frames'] != b['frames'] or conversion['particles'] != 1667249
            or not conversion['partvtk_validation']['all_passed']):
        raise ValueError('Actual full native converter evidence differs')
    if b.get('pose_payload_report'):
        pose_report = json.loads(Path(b['pose_payload_report']).read_text())
        if (not pose_report['all_13_payloads_bitwise_unchanged']
                or pose_report['pose_trajectory']['sha256'] != b['trajectory_sha256']
                or pose_report['frames'] != b['frames']):
            raise ValueError('Actual completed pose payload verification differs')
    header = json.loads(Path(b['native_header_report']).read_text())['results']['fine_solver_frame0']
    native_mass = header['header_mass_fluid_double']
    spec = importlib.util.spec_from_file_location('root_f2_frozen_v8', Path(__file__).with_name('f2_rv4eq_fine_dense_full4001_event_semantics_v8.py'))
    operator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(operator)
    if native_mass != operator.NATIVE_FLOAT32_MASSFLUID_KG:
        raise ValueError('Original actual binary header differs from selected native weight')
    decoded_mass = conversion['hash_scopes']['numerical_parameters']['decoder_header_constants']['MassFluid']
    if float(np.float32(decoded_mass)) != native_mass:
        raise ValueError('Current actual saved native header differs')
    exclusions = Path(b['exclusion_csv'].replace('{attempt_root}', str(out)))
    if b.get('export_native_exclusions'):
        subprocess.run([b['partvtkout'], '-dirdata', b['native_data'], '-savecsv', str(exclusions),
                        '-saveresume', str(out / 'PartOut-resume.csv'), '-createdirs:1', '-csvsep:1'], check=True)
    parent = Path(b['scratch_parent'])
    parent.mkdir(parents=True, exist_ok=True)
    stat = os.statvfs(parent)
    if stat.f_bavail * stat.f_frsize < b['scratch_cap_bytes'] + 100 * 1024**3:
        raise ValueError('Protected NVMe floor would be crossed')
    with tempfile.TemporaryDirectory(prefix='f2-frozen-native-events-024-', dir=parent) as tmp:
        private = Path(tmp)
        synthetic_reader_check(private)
        trajectory = private / 'trajectory.h5'
        verified_copy(Path(b['trajectory']), trajectory, b['trajectory_sha256'])
        with h5py.File(trajectory, 'r') as h:
            if h['position'].shape != (b['frames'], 1667249, 3):
                raise ValueError('Full native state is missing')
            t = h['time'][:]
            if t[0] != 0 or t[-1] < 4 or not np.isfinite(t).all() or not np.all(np.diff(t) > 0):
                raise ValueError('Full physical time support is missing')
            fluid = np.flatnonzero(h['initial_type'][:] == 3)
            mass = np.asarray(h['initial_mass'][:], dtype=np.float64)[fluid]
            if len(fluid) != 196608 or not np.all(mass == native_mass):
                raise ValueError('Nonidentical actual native weights: approximate snapping forbidden')
            if float(mass.sum()) != operator.NATIVE_FLOAT32_COHORT_MASS_KG:
                raise ValueError('Actual inventory differs; approximate total snapping forbidden')
            if h.attrs['physical_condition_sha256'] != b['physical_condition_sha256']:
                raise ValueError('Physical mother binding differs')
            rigid = h['rigid_body_state'][:]
            if len(rigid) != b['frames'] or not np.isfinite(rigid['actual_angle_rad']).all():
                raise ValueError('Actual native moving pose is incomplete')
            records, exclusion_binding = operator.v6_module._parse_exclusion_csv(exclusions)
            ids = set(map(int, h['particle_id'][:][fluid]))
            if not set(records).issubset(ids):
                raise ValueError('Native exclusion ledger contains a nonfluid identity')
        operator.v6_module.h5py = SimpleNamespace(File=source_file)
        labels, report = private / 'labels.h5', private / 'observations.json'
        result = operator.observe(trajectory=trajectory, owner_metadata=Path(b['owner_metadata']),
                                  output=labels, report=report, exclusion_csv=exclusions,
                                  definition_override=Path(b['xml']),
                                  numerical_recipe_hash_override=conversion['hash_scopes']['numerical_parameters_sha256'],
                                  case_id_override=b['case_id'])
        if trajectory.stat().st_size + labels.stat().st_size > b['scratch_cap_bytes']:
            raise ValueError('Registered private storage cap exceeded')
        target = out / 'native-weighted-labels.h5'
        verified_copy(labels, target, result['output']['sha256'])
        result['trajectory']['path'] = b['trajectory']
        result['output']['path'] = str(target)
        result['root_strict_guard'] = {'binding': b, 'synthetic_contiguous_selection_bitwise_check': True,
                                       'exact_native_weights_no_approximate_snap': True,
                                       'native_exclusion_ledger': exclusion_binding,
                                       'unchanged_frozen_observe_math': True,
                                       'private_copy_deleted': True, 'q_n': 'not_granted', 'production_approval': 'none'}
    (out / 'observations.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'frames': b['frames'], 'event_counts': result['event_ledger']['counts_by_code'],
                      'native_initial_mass_kg': result['source_population']['initial_native_mass_kg']}))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    main()
