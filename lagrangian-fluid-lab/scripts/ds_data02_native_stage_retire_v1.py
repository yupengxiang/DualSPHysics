"""Retire only verified temporary duplicates after successful Home publication.

Both copies are hashed again before any deletion. Canonical Home bytes and all
native/publication receipts are retained. The transition report is durable
before deletion, so interruption remains distinguishable from completion.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

STAGING_ROOT = Path('/tmp/ds02-native-staging')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def save(path, record):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('x') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def inventory(root):
    paths = sorted(root.rglob('*'))
    if root.is_symlink() or any(p.is_symlink() for p in paths):
        raise ValueError('Symlinks forbidden in either copy')
    return [str(p.relative_to(root)) for p in paths if p.is_file()]


def retire(publication, publication_receipt, report):
    if report.exists() or report.with_suffix(report.suffix + '.tmp').exists():
        raise FileExistsError('Transition report must be fresh')
    pub = json.loads(publication.read_text())
    cpu = json.loads(publication_receipt.read_text())
    native_path = Path(pub['terminal_receipt'])
    native = json.loads(native_path.read_text())
    if pub['schema'] != 'ds02.native-storage-publication.v1' or pub['status'] != 'completed':
        raise ValueError('Completed byte publication required')
    for receipt in (cpu, native):
        if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
            raise ValueError('Actual successful native and CPU publication receipts required')
        if receipt['input_hashes_at_launch'] != receipt['input_hashes_after_run']:
            raise ValueError('Consumed inputs changed')
    if digest(native_path) != pub['terminal_receipt_sha256']:
        raise ValueError('Native terminal receipt differs from publication')
    argv = cpu['request']['command']
    if Path(argv[argv.index('--report') + 1]).resolve() != publication.resolve():
        raise ValueError('CPU receipt did not publish this manifest')
    source = Path(pub['immutable_staging_source'])
    target = Path(pub['home_native_source'])
    allowed = STAGING_ROOT.resolve()
    if source.parent.resolve() != allowed or not source.name.startswith('f1-ecc-'):
        raise ValueError('Only explicitly scoped temporary F1 duplicates may be retired')
    if target != Path(native['output_root']) / 'solver_output' or target.resolve() == source.resolve():
        raise ValueError('Canonical target differs from native output root')
    expected = sorted(x['relative_path'] for x in pub['files'])
    if not expected or len(set(expected)) != len(expected):
        raise ValueError('Nonempty unique publication inventory required')
    for name in expected:
        p = Path(name)
        if p.is_absolute() or '..' in p.parts:
            raise ValueError('Unsafe relative publication path')
    if inventory(source) != expected or inventory(target) != expected:
        raise ValueError('Copy inventories differ from publication')
    snapshots = {}
    for index, item in enumerate(pub['files']):
        name = item['relative_path']
        for root in (source, target):
            path = root / name
            stat = path.stat()
            if stat.st_size != item['bytes'] or digest(path) != item['sha256']:
                raise ValueError('Copy bytes differ: ' + str(path))
            if root == target and stat.st_mode & 0o222:
                raise ValueError('Canonical published file must remain read-only')
            snapshots[str(path)] = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
        if index % 200 == 0:
            print(json.dumps(dict(verified_files=index + 1, total_files=len(pub['files']))), flush=True)
    for root in (source, target):
        if inventory(root) != expected:
            raise ValueError('Inventory changed during verification')
        for name in expected:
            path = root / name
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != snapshots[str(path)]:
                raise ValueError('File changed during verification')
    record = dict(schema='ds02.native-stage-retirement.v1', status='verified_before_deletion',
                  publication=str(publication), publication_sha256=digest(publication),
                  publication_execution_receipt=str(publication_receipt),
                  publication_execution_receipt_sha256=digest(publication_receipt),
                  native_terminal_receipt=str(native_path), native_terminal_receipt_sha256=digest(native_path),
                  retired_temporary_source=str(source), canonical_home_source=str(target),
                  verified_files=len(expected), verified_bytes=sum(x['bytes'] for x in pub['files']),
                  full_sha256_verified_both_copies=True, canonical_native_retained=True,
                  qualification_granted=False)
    report.parent.mkdir(parents=True, exist_ok=True)
    save(report, record)
    for name in expected:
        (source / name).unlink()
    for directory in sorted((p for p in source.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        directory.rmdir()
    source.rmdir()
    record['status'] = 'completed'
    save(report, record)
    return record


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--publication', type=Path, required=True)
    p.add_argument('--publication-receipt', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(retire(args.publication, args.publication_receipt, args.report)), flush=True)
