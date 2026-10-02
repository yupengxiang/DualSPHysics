"""Use the unchanged F4 detector on one checksum-identical private NVMe copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile

from ds_data02_f3_nvme_input_audit_v1 import verified_copy
from ds_data02_f4_centered_contact_v1 import series


def signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def rebind(value, temporary, original):
    if isinstance(value, str):
        return original if value == temporary else value
    if isinstance(value, list):
        return [rebind(item, temporary, original) for item in value]
    if isinstance(value, dict):
        return {rebind(key, temporary, original): rebind(item, temporary, original)
                for key, item in value.items()}
    return value


def run(config_path, output, scratch):
    config = json.loads(config_path.read_text())
    source = Path(config['source_hdf5'])
    before = signature(source)
    if output.exists():
        raise FileExistsError(output)
    scratch.mkdir(parents=True, exist_ok=True)
    usage = os.statvfs(scratch)
    if usage.f_bavail * usage.f_frsize < before[2] + 100 * 1024**3:
        raise ValueError('NVMe scratch requires source size plus 100 GiB free')
    with tempfile.TemporaryDirectory(prefix='ds02-f4-contact-', dir=scratch) as owned:
        temporary = Path(owned) / 'trajectory.h5'
        actual = verified_copy(source, temporary, config['source_hdf5_sha256'])
        print(json.dumps({'stage': 'verified-copy', 'source_sha256': actual}), flush=True)
        staged = Path(owned) / 'native-contact-series.json'
        series(temporary, Path(config['owner']), Path(config['frozen']),
               config['mechanism'], staged)
        result = rebind(json.loads(staged.read_text()), str(temporary), str(source))
        if signature(source) != before:
            raise ValueError('Original source changed during read-only contact audit')
        if result['source_sha256'].get(str(source)) != actual:
            raise ValueError('Scientific reader source binding differs from verified copy')
    result['audit_storage_protocol'] = {
        'source_hdf5': str(source), 'audited_copy_sha256': actual,
        'copy_verified_before_scientific_reader': True, 'original_stat_unchanged': True,
        'private_scratch_removed': True,
        'reader': 'unchanged ds_data02_f4_centered_contact_v1.series',
        'config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only the final report, with all private path keys/values rebound.
    with output.open('x') as writer:
        writer.write(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('config', 'output', 'scratch-parent'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    def stop_owned(*_):
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop_owned)
    result = run(args.config, args.output, args.scratch_parent)
    print(json.dumps({'first_contact': result['first_contact'],
                      'q_n_status': result['q_n_status']}), flush=True)
