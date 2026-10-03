"""Extract unchanged native F1 macros from verified immutable input bytes."""
import argparse
from contextlib import ExitStack
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
from ds_data02_native_labels import digest
from ds_data02_observations import extract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    binding = json.loads(args.binding.read_text())
    report = json.loads(Path(binding['conversion_report']).read_text())
    receipt = json.loads(Path(binding['conversion_receipt']).read_text())
    original = Path(binding['original_source'])
    if (receipt['status'] != 'completed' or receipt['returncode'] != 0
            or not report['partvtk_validation']['all_passed']
            or report['output_sha256'] != binding['source_sha256']
            or report['output_hdf5'] != str(original)
            or report['frames'] != 1601
            or report['typed_identity']['initial_exclusion_ledger']['count'] != 0):
        raise ValueError('Completed full1601 no-initial-exclusion converter required')
    signature = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    original_before = signature(original.stat())
    with ExitStack() as stack:
        if binding.get('private_source'):
            source = Path(binding['private_source'])
            additional_copy = 0
        else:
            parent = Path(binding['scratch_parent'])
            parent.mkdir(parents=True, exist_ok=True)
            stat = os.statvfs(parent)
            if stat.f_bavail * stat.f_frsize < original_before[2] + 100 * 1024**3:
                raise ValueError('Insufficient protected NVMe capacity')
            owned = stack.enter_context(tempfile.TemporaryDirectory(prefix='ds02-f1-macro-', dir=parent))
            source = Path(owned) / 'trajectory.h5'
            verified_copy(original, source, binding['source_sha256'])
            additional_copy = original_before[2]
        held = stack.enter_context(source.open('rb'))
        before = os.fstat(held.fileno())
        if before.st_size != binding['source_bytes'] or before.st_mode & 0o222:
            raise ValueError('Source stage is not the expected immutable file')
        descriptor_path = Path('/proc/self/fd') / str(held.fileno())
        if digest(descriptor_path) != binding['source_sha256']:
            raise ValueError('Held source differs from completed converter digest')
        result = extract(descriptor_path, continuous_initial_mass_kg=binding['continuous_mass_kg'])
        # A file object remains accessible after a different stage owner unlinks its path.
        # Use an independent descriptor so HDF5 seeks do not affect the held digest reader.
        with os.fdopen(os.dup(held.fileno()), 'rb') as view, h5py.File(view, 'r') as h:
            times = h['time'][:]
            if (len(times) != 1601 or times[0] != 0 or times[-1] < 1.6
                    or not np.isfinite(times).all() or not np.all(np.diff(times) > 0)):
                raise ValueError('Full1.6 physical window is missing')
            initial_mass = float(np.sum(h['initial_mass'][:][h['initial_type'][:] == 3], dtype=float))
            if not np.isclose(initial_mass, result['numerical_initial_mass_kg'], rtol=1e-12, atol=1e-9):
                raise ValueError('Native initial cohort mass differs from extracted mass')
            result['physical_condition_sha256'] = str(h.attrs['physical_condition_sha256'])
        if digest(descriptor_path) != binding['source_sha256'] or signature(before) != signature(os.fstat(held.fileno())):
            raise ValueError('Held source changed during full macro extraction')
    if signature(original.stat()) != original_before:
        raise ValueError('Published source changed')
    result['source'] = str(original)
    result['audit_storage_protocol'] = {
        'reader': 'unchanged ds_data02_observations.extract, including original weighted quantiles',
        'source_sha256': binding['source_sha256'],
        'verified_before_and_after_scientific_read': True,
        'additional_private_copy_bytes': additional_copy,
        'shared_stage_lifecycle': 'held read-only inode; existing fine labels owner controls private-stage deletion',
        'original_stat_unchanged': True,
        'binding_sha256': digest(args.binding),
    }
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'frames': len(result['rows']), 'output': str(args.output),
                      'initial_native_mass_kg': result['numerical_initial_mass_kg']}))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    main()
