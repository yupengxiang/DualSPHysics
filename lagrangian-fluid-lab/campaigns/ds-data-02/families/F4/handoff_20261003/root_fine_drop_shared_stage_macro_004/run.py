"""Run the unchanged F4 macro reader on a held, verified private source inode."""
import argparse
import json
import os
from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(LAB / 'scripts'))
import ds_data02_f4_centered_macros_v1 as reader
from ds_data02_native_labels import digest


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
    if (receipt['status'] != 'completed' or receipt['returncode'] != 0
            or not report['partvtk_validation']['all_passed']
            or report['output_sha256'] != binding['source_sha256']
            or report['output_hdf5'] != binding['original_source']):
        raise ValueError('Actual completed converter publication does not match binding')
    original = Path(binding['original_source'])
    signature = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    original_before = signature(original.stat())
    # Holding the descriptor preserves the exact immutable inode if the contact
    # worker completes and removes its own temporary directory during this read.
    # This worker neither deletes nor changes that worker's stage or lifecycle.
    with Path(binding['private_source']).open('rb') as held:
        before = os.fstat(held.fileno())
        if before.st_size != binding['source_bytes'] or before.st_mode & 0o222:
            raise ValueError('Private source is not the expected read-only stage')
        descriptor_path = Path('/proc/self/fd') / str(held.fileno())
        original_digest = reader.digest
        calls = []

        def checked_digest(path):
            value = original_digest(path)
            if str(path) == str(descriptor_path):
                if value != binding['source_sha256']:
                    raise ValueError('Private source differs from completed converter digest')
                calls.append(value)
            return value

        reader.digest = checked_digest
        try:
            reader.series(descriptor_path, Path(binding['owner']), args.output)
        finally:
            reader.digest = original_digest
        after = os.fstat(held.fileno())
        if len(calls) != 2 or signature(before) != signature(after):
            raise ValueError('Unchanged macro reader did not verify the held source twice')
    if signature(original.stat()) != original_before:
        raise ValueError('Original published source changed')
    result = json.loads(args.output.read_text())
    result['source'] = str(original)
    result['audit_storage_protocol'] = {
        'reader': 'unchanged ds_data02_f4_centered_macros_v1.series',
        'source_sha256_verified_before_and_after_scientific_read': True,
        'original_source_unchanged': True,
        'input_policy': 'read-only reuse of actual contact worker immutable private source inode',
        'source_inode_held_through_entire_read': True,
        'additional_private_copy_bytes': 0,
        'private_stage_lifecycle_owner': 'existing F4 contact003 worker; macro worker never deletes it',
        'binding_sha256': digest(args.binding),
    }
    # The intermediate report has no downstream consumers yet. Publish the
    # final provenance only when the strict worker has finished successfully.
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
