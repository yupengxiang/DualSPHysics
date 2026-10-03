import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import h5py
import numpy as np

KEYS = ['time', 'particle_id', 'particle_zone', 'initial_type', 'initial_mk',
        'initial_mass', 'mass', 'type', 'mk', 'valid', 'position', 'velocity', 'density']


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 ** 2), b''):
            h.update(block)
    return h.hexdigest()


def copy_verified(source, target, expected=None):
    h = hashlib.sha256()
    with Path(source).open('rb') as src, Path(target).open('xb') as dst:
        for block in iter(lambda: src.read(8 * 1024 ** 2), b''):
            h.update(block);dst.write(block)
    sha = h.hexdigest()
    if expected is not None and sha != expected:
        raise ValueError('Source copy bytes differ from registered digest')
    if digest(target) != sha:
        raise ValueError('Published copy bytes differ')
    return sha


def payload_fingerprints(path):
    results = {}
    with h5py.File(path, 'r') as f:
        for key in KEYS:
            ds = f[key]
            if ds.dtype.hasobject:
                raise ValueError('Mandatory native payload must be numeric')
            h = hashlib.sha256()
            if ds.ndim == 1:
                for start in range(0, ds.shape[0], 131072):
                    h.update(ds[start:start + 131072].tobytes(order='C'))
            else:
                for frame in range(ds.shape[0]):
                    h.update(ds[frame:frame + 1].tobytes(order='C'))
            results[key] = {'shape': list(ds.shape), 'dtype': ds.dtype.str, 'values_sha256': h.hexdigest()}
            print('actual complete payload fingerprint', key, flush=True)
    return results


def main():
    p = argparse.ArgumentParser();p.add_argument('--binding', required=True);p.add_argument('--output-dir', required=True)
    args = p.parse_args();b = json.loads(Path(args.binding).read_text());out = Path(args.output_dir)
    receipt = json.loads(Path(b['conversion_receipt']).read_text())
    if receipt['status'] != 'completed' or receipt['returncode'] != 0 or receipt['input_hashes_at_launch'] != receipt['input_hashes_after_run']:
        raise ValueError('Immutable completed0 full converter required')
    report = json.loads(Path(b['conversion_report']).read_text())
    if report['output_sha256'] != b['source_sha256'] or report['frames'] != 4001 or report['particles'] != 1667249:
        raise ValueError('Actual converter report differs from binding')
    scratch = Path(b['scratch_parent']);scratch.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(scratch).free - b['scratch_cap_bytes'] < b['nvme_min_free_bytes']:
        raise ValueError('Single copy would cross NVMe floor')
    target = out / 'trajectory-with-actual-pose.h5'
    if target.exists() or (out / 'pose-payload-report.json').exists():
        raise FileExistsError('Never overwrite an existing attempt product')
    with tempfile.TemporaryDirectory(prefix='root-full4001-pose-', dir=scratch) as private:
        augmented = Path(private) / 'trajectory-with-actual-pose.h5'
        copy_sha = copy_verified(b['source_h5'], augmented, b['source_sha256'])
        with h5py.File(augmented, 'r') as f:
            if f['position'].shape != (4001, 1667249, 3):
                raise ValueError('Full expected native state dimensions required')
            times = f['time'][:]
            if times[0] != 0 or times[-1] < 4 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
                raise ValueError('Missing full actual time window')
            fluid = f['initial_type'][:] == 3
            weights = f['initial_mass'][:][fluid].astype(np.float64)
            if fluid.sum() != 196608 or not np.all(weights == b['native_initial_particle_mass_kg']):
                raise ValueError('Actual native fluid cohort/mass differs')
            uid = np.stack([f['particle_zone'][:], f['particle_id'][:]], axis=1)
            if len(np.unique(uid, axis=0)) != 1667249:
                raise ValueError('Nonunique actual typed native identities')
        before = payload_fingerprints(augmented)
        sys.path.insert(0, str(Path(b['helper']).parent))
        spec = importlib.util.spec_from_file_location('unchanged_actual_pose', b['helper'])
        helper = importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        motion = helper._parse_motion_control(Path(b['motion']), Path(b['xml']))
        if motion is None:
            raise ValueError('No actual copied rotation control')
        match = re.search(r'CaseNmoving\s*=\s*([0-9,]+)', Path(b['run_out']).read_text(), re.I)
        if match is None:
            raise ValueError('No actual native moving population')
        population = int(match[1].replace(',', ''))
        pose = helper._write_rigid_body_state(augmented, {'motion_control_spec': motion,
                                             'population': {'case_nmoving': population}}, times.tolist())
        if pose['status'] != 'pass' or pose['frames'] != 4001 or not pose['all_moving_nodes_present'] or pose['moving_node_count'] != population:
            raise ValueError('Incomplete actual moving-node pose')
        after = payload_fingerprints(augmented)
        if before != after:
            raise ValueError('Mandatory native payload changed during pose augmentation')
        if augmented.stat().st_size > b['scratch_cap_bytes']:
            raise ValueError('Augmented file exceeds registered scratch limit')
        published_sha = copy_verified(augmented, target)
        target.chmod(0o400)
        if digest(b['source_h5']) != copy_sha:
            raise ValueError('Original immutable source changed during pose analysis')
    result = {'schema': 'ds02.f2.actual-full4001-native-pose-and-bitwise-payload.v1',
              'frames': 4001, 'particles': 1667249, 'fluid_particles': 196608,
              'native_window_s': [float(times[0]), float(times[-1])], 'pose': pose,
              'source_trajectory': {'path': b['source_h5'], 'sha256': copy_sha},
              'pose_trajectory': {'path': str(target), 'sha256': published_sha},
              'mandatory_payload_fingerprints': before, 'all_13_payloads_bitwise_unchanged': True,
              'native_initial_mass_kg': float(weights.sum()), 'xml_decimal_benchmark_mass_kg': 24.576,
              'normalization': 'none', 'physical_condition_sha256': b['physical_condition_sha256'],
              'private_copy_deleted': True, 'q_n': 'not_granted', 'production_approval': 'none'}
    (out / 'pose-payload-report.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
