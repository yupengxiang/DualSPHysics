"""Root-only staging monitor and verified publication for direct native requests.

The solver still runs through unchanged strict runtime, with the official
binary as argv[0]. Staging changes storage only, never numerical controls.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import signal
import time

from ds_data02_strict_dispatch_v1 import run_request
from ds_data02_runtime_v2 import DATA_ROOT


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    temporary = Path(str(path) + '.partial')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def require_terminal(receipt, request_sha, source):
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
        raise ValueError('Publication requires actual successful terminal native receipt')
    if receipt.get('request_sha256') != request_sha:
        raise ValueError('Terminal native request digest differs')
    if Path(receipt['command'][2]).resolve() != source.resolve():
        raise ValueError('Native receipt output differs from registered staging source')
    if receipt['input_hashes_at_launch'] != receipt['input_hashes_after_run']:
        raise ValueError('Native inputs changed')


def publish(request_path, receipt_path, report):
    request = json.loads(request_path.read_text())
    source = Path(request['command'][2])
    receipt = json.loads(receipt_path.read_text())
    request_sha = digest(request_path)
    require_terminal(receipt, request_sha, source)
    target = Path(receipt['output_root']) / 'solver_output'
    if report.exists() or target.exists():
        raise FileExistsError('Never overwrite an existing publication')
    entries = sorted(source.rglob('*'))
    if any(p.is_symlink() for p in entries):
        raise ValueError('Symlinks are forbidden in native source publication')
    files = [p for p in entries if p.is_file()]
    if not files or sum(p.stat().st_size for p in files) > request['estimated_storage_bytes']:
        raise ValueError('Native staging output exceeds registered size or is empty')
    partial = target.with_name('solver_output.publication-partial')
    partial.mkdir(exist_ok=False)
    inventory = []
    for item in files:
        stat = item.stat()
        destination = partial / item.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256()
        with item.open('rb') as inp, destination.open('xb') as out:
            while block := inp.read(8 * 1024 * 1024):
                sha.update(block)
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        if (item.stat().st_size, item.stat().st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            raise ValueError('Native staging source changed during publication')
        if digest(destination) != sha.hexdigest():
            raise ValueError('Home copy digest differs')
        destination.chmod(0o400)
        inventory.append(dict(relative_path=str(item.relative_to(source)), bytes=stat.st_size, sha256=sha.hexdigest()))
    if sorted(str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()) != [x['relative_path'] for x in inventory]:
        raise ValueError('Native source inventory changed during publication')
    partial.rename(target)
    result = dict(schema='ds02.native-storage-publication.v1', status='completed',
        native_request=str(request_path), native_request_sha256=request_sha,
        terminal_receipt=str(receipt_path), terminal_receipt_sha256=digest(receipt_path),
        immutable_staging_source=str(source), home_native_source=str(target), files=inventory,
        full_typed_conversion_status='pending', q_n_status='not_granted')
    save(report, result)
    return result


def run(request_path, request_sha, record):
    if digest(request_path) != request_sha:
        raise ValueError('Request differs from root registration')
    request = json.loads(request_path.read_text())
    source = Path(request['command'][2])
    if source.parent != Path('/tmp/ds02-native-staging') or source.exists():
        raise ValueError('Fresh root-owned native staging directory required')
    if request['kind'] != 'qualification' or not Path(request['command'][0]).name.startswith('DualSPHysics'):
        raise ValueError('Only direct official native qualification requests supported')
    if record.exists():
        raise FileExistsError(record)
    source.parent.mkdir(exist_ok=True)
    floor = 100 * 1024**3
    free = os.statvfs(source.parent).f_bavail * os.statvfs(source.parent).f_frsize
    if free - request['estimated_storage_bytes'] < floor:
        raise ValueError('Staging reserve would cross NVMe 100 GiB floor')
    output = DATA_ROOT / 'families' / request['family_id'] / request['case_id'] / request['attempt_id']
    receipt_path = output / 'execution-receipt.json'
    state = dict(schema='ds02.native-storage-monitor.v1', request=str(request_path),
        request_sha256=request_sha, stage=str(source), status='dispatching_once',
        estimated_storage_bytes=request['estimated_storage_bytes'], nvme_floor_bytes=floor)
    save(record, state)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_request, request_path)
        while not future.done():
            used = sum(p.stat().st_size for p in source.rglob('*') if p.is_file()) if source.exists() else 0
            free = os.statvfs(source.parent).f_bavail * os.statvfs(source.parent).f_frsize
            if used > request['estimated_storage_bytes'] or free < floor:
                if receipt_path.exists():
                    live = json.loads(receipt_path.read_text())
                    if live.get('status') == 'running' and live.get('request_sha256') == request_sha:
                        try:
                            os.killpg(live['pid'], signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        state['storage_stop_reason'] = 'registered_stage_size_exceeded' if used > request['estimated_storage_bytes'] else 'nvme_free_floor_reached'
                        save(record, state)
            time.sleep(5)
        receipt = future.result()
    state.update(status='native_terminal', receipt_status=receipt['status'], returncode=receipt.get('returncode'))
    save(record, state)
    # Publication is a separate bounded CPU audit through the shared runner.
    return state


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request', type=Path, required=True)
    p.add_argument('--expected-sha256')
    p.add_argument('--publish-receipt', type=Path)
    p.add_argument('--record', type=Path, required=True)
    a = p.parse_args()
    if a.publish_receipt:
        print(json.dumps(publish(a.request, a.publish_receipt, a.record)), flush=True)
    else:
        if not a.expected_sha256:
            p.error('--expected-sha256 is required for native dispatch')
        print(json.dumps(run(a.request, a.expected_sha256, a.record)), flush=True)
