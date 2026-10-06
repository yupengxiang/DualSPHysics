#!/usr/bin/env python3
"""Read-only failed receipt/stat inventory for fresh147.

The worker opens only execution-receipt.json files and bounded JSON output metadata.
It never opens, hashes, copies, removes, or modifies scientific payloads.
"""
from __future__ import annotations
import argparse
import json
import os
from collections import Counter
from pathlib import Path

FORBIDDEN_SUFFIXES = {'.bi4', '.h5', '.hdf5', '.csv', '.dat', '.vtk', '.vtu', '.jsonl', '.ibi4', '.obi4'}
DOWNSTREAM_TAGS = ('typed', 'render', 'xmf', 'xdmf')

def stat_attempt(root: Path) -> dict:
    files = dirs = total = 0
    suffixes: Counter[str] = Counter()
    suffix_bytes: Counter[str] = Counter()
    for base, dirnames, filenames in os.walk(root, followlinks=False):
        dirs += len(dirnames)
        for name in filenames:
            path = Path(base) / name
            try:
                st = path.lstat()
            except OSError:
                continue
            if path.is_symlink():
                continue
            files += 1
            total += st.st_size
            suffix = path.suffix.lower() or '<noext>'
            suffixes[suffix] += 1
            suffix_bytes[suffix] += st.st_size
    return {'files': files, 'dirs': dirs, 'bytes': total,
            'suffix': dict(sorted(suffixes.items())),
            'suffix_bytes': dict(sorted(suffix_bytes.items()))}

def failed_receipts(data_root: Path) -> list[dict]:
    out = []
    for receipt in data_root.glob('families/*/**/execution-receipt.json'):
        try:
            record = json.loads(receipt.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        status = record.get('status')
        returncode = record.get('returncode', record.get('rc'))
        failed = status == 'failed' or (isinstance(returncode, (int, float)) and not isinstance(returncode, bool) and returncode != 0)
        if not failed:
            continue
        attempt = receipt.parent
        relative = attempt.relative_to(data_root).as_posix()
        # The scan is intentionally bounded to the requested storage candidates.
        tag = next((tag for tag in DOWNSTREAM_TAGS if tag in str(attempt).lower()), 'other')
        stats = stat_attempt(attempt)
        out.append({'relative_attempt': relative,
                     'attempt_dir': str(attempt),
                     'receipt': str(receipt),
                     'status': status,
                     'returncode': returncode,
                     'termination_reason': record.get('termination_reason'),
                     'error': record.get('error'),
                     'started_at_utc': record.get('started_at_utc'),
                     'finished_at_utc': record.get('finished_at_utc'),
                     'tag': tag,
                     'stat': stats})
    return out

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rows = failed_receipts(args.data_root)
    result = {
        'schema': 'ds02.failed-artifact-stat-inventory.fresh147.v1',
        'data_root': str(args.data_root),
        'read_policy': 'execution-receipt.json and directory stat metadata only',
        'scientific_payloads_opened': False,
        'scientific_payloads_hashed': False,
        'deletion_performed': False,
        'failed_receipt_count': len(rows),
        'tag_counts': dict(Counter(row['tag'] for row in rows)),
        'rows': rows,
    }
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f"wrote {args.out}: {len(rows)} failed receipt rows; no deletion")

if __name__ == '__main__':
    main()
