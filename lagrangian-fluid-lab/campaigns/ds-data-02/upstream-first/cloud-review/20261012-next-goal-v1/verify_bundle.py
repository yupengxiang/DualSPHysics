#!/usr/bin/env python3
"""Verify this metadata handoff; never replay numerical payloads."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def verify(root: Path, repository_root: Path | None = None) -> dict:
    index = json.loads((root / 'EVIDENCE_INDEX.json').read_text())
    seen = set()
    total = 0
    for item in index['files']:
        name = item['export_path']
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or name in seen:
            raise ValueError(f'unsafe or duplicate export path: {name}')
        seen.add(name)
        path = root.joinpath(*relative.parts)
        base = root
        if not path.exists() and repository_root and relative.parts[0] == 'repository':
            path = repository_root.joinpath(*relative.parts[1:])
            base = repository_root
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base.resolve()):
            raise ValueError(f'missing or unsafe file: {name}')
        if path.stat().st_size != item['bytes']:
            raise ValueError(f'byte count mismatch: {name}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'SHA256 mismatch: {name}')
        total += item['bytes']
    return {'status': 'verified_metadata_bundle', 'files': len(seen),
            'indexed_bytes': total, 'numerical_payload_replayed': False,
            'source_commit': index['source_commit'],
            'reference_hash_mismatches_preserved': sum(
                x['status'] == 'mismatch_preserved' for x in index['reference_hash_checks'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(Path(__file__).resolve().parent, args.repository_root), indent=2))
