#!/usr/bin/env python3
"""Run only the direct converter physical-owner preflight; never convert data."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, sys
from pathlib import Path

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--owner-metadata', type=Path, required=True)
    ap.add_argument('--converter', type=Path, default=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py'))
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    name = '_ds_data02_fresh121_direct_convert'
    previous = sys.modules.get(name)
    spec = importlib.util.spec_from_file_location(name, args.converter)
    if spec is None or spec.loader is None:
        raise SystemExit('unable to load converter module')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        owner = json.loads(args.owner_metadata.read_text(encoding='utf-8'))
        scope = module._physical_condition_scope(owner)
        result = {
            'schema': 'ds02.stage1.f3.fresh121.converter-metadata-preflight.runtime.v1',
            'status': 'pass',
            'converter': {'path': str(args.converter), 'sha256': sha256_file(args.converter)},
            'owner': {'path': str(args.owner_metadata), 'sha256': sha256_file(args.owner_metadata)},
            'scope_schema': scope.get('schema'),
            'scope_sha256': module.canonical_hash(scope),
            'explicit_physical_binding': 'physical_binding' in owner,
            'payload_opened': False,
            'payload_hashed': False,
        }
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
