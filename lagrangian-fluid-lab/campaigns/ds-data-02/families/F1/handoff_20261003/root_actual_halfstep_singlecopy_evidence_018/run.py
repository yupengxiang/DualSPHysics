"""Extract full F1 halfstep macros and canonical events from one verified copy."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import tempfile

import h5py
import numpy as np

LAB = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(LAB / 'scripts'))
from ds_data02_f3_nvme_input_audit_v1 import verified_copy
from ds_data02_native_labels import digest, materialize
from ds_data02_observations import extract
from ds_data02_verified_native_labels_v1 import label_closure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    b = json.loads(args.binding.read_text())
    out, source = args.output_dir, Path(b['trajectory'])
    if (out / 'native-labels.h5').exists() or (out / 'observations.json').exists():
        raise FileExistsError(out)
    receipt = json.loads(Path(b['conversion_receipt']).read_text())
    report = json.loads(Path(b['conversion_report']).read_text())
    if (receipt['status'] != 'completed' or receipt['returncode'] != 0
            or report['frames'] != 1601 or report['particles'] != 1032852
            or report['output_sha256'] != b['sha256']
            or not report['partvtk_validation']['all_passed']
            or report['typed_identity']['initial_exclusion_ledger']['count'] != 0):
        raise ValueError('Actual full halfstep typed state differs')
    parent = Path(b['scratch_parent'])
    parent.mkdir(parents=True, exist_ok=True)
    stat = os.statvfs(parent)
    if stat.f_bavail * stat.f_frsize < b['scratch_cap_bytes'] + 100 * 1024**3:
        raise ValueError('Protected NVMe capacity insufficient')
    signature = lambda p: (p.stat().st_dev, p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns)
    source_before = signature(source)
    config = json.loads(Path(b['event_config']).read_text())
    with tempfile.TemporaryDirectory(prefix='ds02-f1-halfstep-evidence-018-', dir=parent) as tmp:
        target = Path(tmp) / 'trajectory.h5'
        verified_copy(source, target, b['sha256'])
        with h5py.File(target, 'r') as h:
            times = h['time'][:]
            if (len(times) != 1601 or times[0] != 0 or times[-1] < 1.6
                    or not np.isfinite(times).all() or not np.all(np.diff(times) > 0)):
                raise ValueError('Full native 1.6 second window missing')
            if h.attrs['physical_condition_sha256'] != b['physical_condition_sha256']:
                raise ValueError('Continuum physical mother differs')
            ids = np.column_stack((h['particle_zone'][:], h['particle_id'][:]))
            fluid = h['initial_type'][:] == 3
            mass = float(np.asarray(h['initial_mass'][:], dtype=float)[fluid].sum())
        labels = Path(tmp) / 'labels.h5'
        result = materialize(target, labels, config, particle_chunk=16384)
        closure = label_closure(labels, ids, mass)
        (out / 'label-closure.json').write_text(json.dumps(closure, indent=2) + '\n')
        if not closure['passed']:
            raise ValueError('Actual canonical label closure failed')
        with h5py.File(labels, 'r+') as h:
            h.attrs['source_hdf5'] = str(source)
            h.attrs['audit_storage_protocol'] = 'One digest-verified immutable private source; unchanged canonical labels and macros'
        if target.stat().st_size + labels.stat().st_size > b['scratch_cap_bytes']:
            raise ValueError('Registered private staging cap exceeded')
        final = out / 'native-labels.h5'
        label_sha = digest(labels)
        verified_copy(labels, final, label_sha)
        result.update(path=str(final), sha256=label_sha, source_hdf5=str(source),
                      source_hdf5_sha256=b['sha256'], closure=closure, private_scratch_removed=True)
        (out / 'labels-report.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'stage': 'actual-full-canonical-label-closure', 'passed': closure['passed']}), flush=True)
        observation = extract(target, continuous_initial_mass_kg=b['continuous_mass_kg'])
        if len(observation['rows']) != 1601 or observation['quantiles'] != [.05, .5, .95]:
            raise ValueError('Unchanged full native macro extraction is incomplete')
        observation['source'] = str(source)
        observation['physical_condition_sha256'] = b['physical_condition_sha256']
        observation['audit_storage_protocol'] = {'source_sha256': b['sha256'], 'single_private_copy': True,
                                                  'reader': 'unchanged ds_data02_observations.extract'}
        if digest(target) != b['sha256'] or signature(source) != source_before:
            raise ValueError('Immutable source changed during actual evidence extraction')
    (out / 'observations.json').write_text(json.dumps(observation, indent=2) + '\n')
    print(json.dumps({'frames': 1601, 'native_initial_mass_kg': mass,
                      'q_n': 'not_granted', 'production_approval': 'none'}))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    main()
