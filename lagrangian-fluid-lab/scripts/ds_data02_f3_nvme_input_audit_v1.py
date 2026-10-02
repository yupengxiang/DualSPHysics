"""Audit checksum-identical transient NVMe copies with the existing F3 reader."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile

from ds_data02_f3_macro_input_audit_v2 import audit_input


def verified_copy(source, target, expected):
    before = source.stat()
    signature = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    digest = hashlib.sha256()
    with source.open('rb') as reader, target.open('xb') as writer:
        for block in iter(lambda: reader.read(8 * 1024**2), b''):
            digest.update(block)
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())
    actual = digest.hexdigest()
    if signature(before) != signature(source.stat()) or actual != expected:
        raise ValueError('Source changed or differs from registered digest: ' + str(source))
    target.chmod(0o400)
    return actual


def run(config, output, scratch_parent):
    if output.exists():
        raise FileExistsError(output)
    rows = json.loads(config.read_text())['source_hdf5_bindings']
    scratch_parent.mkdir(parents=True, exist_ok=True)
    maximum = max(Path(row['path']).stat().st_size for row in rows.values())
    usage = os.statvfs(scratch_parent)
    if usage.f_bavail * usage.f_frsize < maximum + 100 * 1024**3:
        raise ValueError('NVMe scratch requires source size plus 100 GiB free')
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {'schema': 'ds02.f3.nvme-macro-input-audit.v1', 'inputs': [],
              'source_bindings_config': str(config),
              'source_bindings_config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
              'claim_boundary': 'Full finite/positive active fluid audit only; no Q-N or production',
              'q_n_status': 'not_assessed', 'status': 'running',
              'copy_protocol': 'One source at a time; SHA256 checked during sequential copy before auditing; originals read-only; exact same v2 scientific audit',
              'scratch_parent': str(scratch_parent)}
    with tempfile.TemporaryDirectory(prefix='ds02-f3-audit-', dir=scratch_parent) as temporary:
        for role, binding in rows.items():
            source = Path(binding['path'])
            target = Path(temporary) / (role + '.h5')
            actual = verified_copy(source, target, binding['sha256'])
            row = audit_input(target, particle_chunk=65536)
            row['path'] = str(source)
            row['audited_copy_sha256'] = actual
            row['registered_source_sha256'] = binding['sha256']
            row['role'] = role
            target.unlink()
            row['transient_copy_deleted_after_audit'] = True
            result['inputs'].append(row)
            # Independent progress evidence survives a later bounded failure.
            output.with_suffix('.partial.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({'role': role, 'frames': row['frames'], 'status': row['status']}), flush=True)
    result['status'] = 'pass' if all(row['status'] == 'pass' for row in result['inputs']) else 'failed'
    result['private_scratch_directory_removed'] = True
    output.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('config', 'output', 'scratch-parent'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    # Ensure owned temporary files are cleaned on the runner's SIGTERM.
    def stop_owned_audit(*_):
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop_owned_audit)
    result = run(args.config, args.output, args.scratch_parent)
    raise SystemExit(0 if result['status'] == 'pass' else 2)
