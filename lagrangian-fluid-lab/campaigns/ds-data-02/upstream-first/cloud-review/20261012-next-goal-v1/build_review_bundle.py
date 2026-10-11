#!/usr/bin/env python3
"""Build a bounded immutable metadata export and ZIP; no raw payload reads."""
import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import verify_bundle

CAMPAIGN = Path('lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first')
NAS = Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first')
LOCAL_LAB = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab')
MAX_FILE = 4 * 1024**2
MAX_TOTAL = 64 * 1024**2
MAX_FILES = 1500
SUFFIXES = {'.json', '.md', '.py', '.sh', '.xml', '.txt', '.csv', '.log', '.f'}
SEEDS = ['DELIVERY_INDEX_V1.json', 'GOAL_COMPLETION_AUDIT_V2.json',
         'F1_REFERENCE_PACK_V4.json', 'F5_REFERENCE_PACK_V2.json',
         'M2_PORTABLE_DATA_CARD.json', 'M2_EXTERNAL_PACK.json',
         'M3_DERIVATIVE_PACK.json', 'M4_RELEASE_FINAL_V1.json',
         'M4_INTERNAL_DATASET_V1.json',
         'milestone-evidence/M1-complete-v2.json',
         'milestone-evidence/M2-complete-v1.json',
         'milestone-evidence/M3-complete-v1.json',
         'milestone-evidence/M4-complete-v1.json',
         'm4-cost-audit/checkpoints/M4-resource-audit-final-v1.json',
         'm1/f1/evidence/bridge-comparison-001-v2-failure.json',
         'batch2-runtime/H060-direct001-scratch-failure-and-v2-repair.json',
         'batch2-runtime/H050-external-relocation-storage-reconciliation-v1.json',
         'batch2-runtime/H052-nativequeue001-metadata-stop-v1.json',
         'F1_COMPARISON_001_VETO.json']


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, required=True)
    parser.add_argument('--zip-output', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repository_root.resolve()
    here = Path(__file__).resolve().parent
    index_path = here / 'EVIDENCE_INDEX.json'
    if index_path.exists() or args.zip_output.exists():
        raise SystemExit('Refusing to overwrite an existing index or archive; create a new version.')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', 'codex/ds-data-02-stage2..HEAD'], cwd=repo, text=True).splitlines()
    tracked = set(subprocess.check_output(['git', 'ls-files'], cwd=repo, text=True).splitlines())
    files = {}
    locations = {}
    omitted = {}
    checks = []
    total = 0

    def classify(path):
        if path.is_relative_to(here):
            return path.relative_to(here).as_posix(), 'handoff'
        if path.is_relative_to(repo):
            rel = path.relative_to(repo).as_posix()
            if rel not in tracked:
                return None
            return 'repository/' + rel, 'repository'
        if path.is_relative_to(NAS):
            return 'evidence/nas/' + path.relative_to(NAS).as_posix(), 'nas'
        if path.is_relative_to(LOCAL_LAB):
            return 'evidence/local-lab/' + path.relative_to(LOCAL_LAB).as_posix(), 'local_lab'
        return None

    def add(path, reason):
        nonlocal total
        path = Path(path)
        key = str(path)
        if key in locations:
            files[locations[key]]['selected_by'].add(reason)
            return True
        if not path.is_absolute():
            return False
        # Filter payloads before opening or hashing them.
        if path.suffix.lower() not in SUFFIXES and path.name != 'Run.out':
            omitted[key] = 'payload_or_non_text_extension'
            return False
        binding = classify(path)
        if not binding:
            omitted[key] = 'outside_export_roots_or_untracked'
            return False
        export, kind = binding
        if path.is_symlink() or not path.is_file():
            omitted[key] = 'not_regular_or_missing'
            return False
        size = path.stat().st_size
        if size > MAX_FILE:
            omitted[key] = 'file_exceeds_4_MiB_metadata_bound'
            return False
        if len(files) >= MAX_FILES or total + size > MAX_TOTAL:
            raise ValueError('metadata export exceeds fixed total/files bound')
        data = path.read_bytes()
        if len(data) != size:
            raise ValueError(f'file changed during export: {path}')
        if kind in {'nas', 'local_lab'}:
            target = here / export
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError(f'refusing to overwrite {target}')
            target.write_bytes(data)
            source = target
        else:
            source = path
        files[export] = {'export_path': export, 'original_path': key,
                         'kind': kind, 'bytes': size, 'sha256': hash_bytes(data),
                         'selected_by': {reason}, '_source': source}
        locations[key] = export
        total += size
        return True

    for rel in sorted(set(changed) | {'AGENTS.md'}):
        add(repo / rel, 'completed_delivery_branch')
    queue = deque((repo / CAMPAIGN / seed, 0) for seed in SEEDS)
    visited = set()

    def walk(value, owner, depth, trail='$'):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
                path = Path(value['path'])
                if path.is_absolute() and add(path, str(owner)):
                    actual = files[locations[str(path)]]
                    checks.append({'referrer': str(owner), 'field': trail,
                                   'export_path': actual['export_path'],
                                   'declared_sha256': value['sha256'],
                                   'exported_sha256': actual['sha256'],
                                   'status': 'match' if value['sha256'] == actual['sha256']
                                   else 'mismatch_preserved'})
            for key, item in value.items():
                walk(item, owner, depth, trail + '.' + str(key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, owner, depth, trail + '[' + str(i) + ']')
        elif isinstance(value, str) and value.startswith('/'):
            path = Path(value)
            if add(path, str(owner)) and path.suffix == '.json' and depth < 3:
                queue.append((path, depth + 1))

    while queue:
        path, depth = queue.popleft()
        if str(path) in visited:
            continue
        visited.add(str(path))
        if add(path, 'authoritative_seed_or_linked_metadata'):
            walk(json.loads(path.read_text()), path, depth)

    # Always preserve actual integrity evidence used for the final adapter check.
    for case in ['UF_F1_MDBC_DAMBREAK3D', 'UF_F1_MDBC_DP015_BASE']:
        add(NAS / 'runs/F1' / case / 'native-integrity-001/integrity.json',
            'native_projection_actual_input')
    dataset = json.loads((repo / CAMPAIGN / 'M4_INTERNAL_DATASET_V1.json').read_text())
    portable = json.loads((repo / CAMPAIGN / 'M2_PORTABLE_DATA_CARD.json').read_text())
    bundle_roots = [Path(row['bundle']['root']) for row in dataset['conditions']]
    bundle_roots += [Path(portable['build_path']), Path(portable['relocated_path'])]
    for root in bundle_roots:
        if not root.is_relative_to(NAS) or root.is_symlink() or not root.is_dir():
            raise ValueError(f'unsafe or missing accepted bundle root: {root}')
        for path in sorted(root.rglob('*')):
            if path.is_file():
                add(path, 'accepted_bundle_small_metadata_and_runtime')
    for path in sorted(here.iterdir()):
        if path.is_file():
            add(path, 'reviewer_entrypoint')

    index = {'schema': 'ds-data-02.upstream-first.cloud-review-index.v1',
             'created_at_utc': datetime.now(timezone.utc).isoformat(),
             'source_commit': commit, 'source_branch': 'codex/upstream-first',
             'repository_url': 'https://github.com/yupengxiang/DualSPHysics',
             'policy': 'Small metadata only; original bytes unchanged; no independent cloud numerical replay.',
             'bounds': {'max_file_bytes': MAX_FILE, 'max_total_bytes': MAX_TOTAL,
                        'max_files': MAX_FILES, 'linked_json_depth': 3},
             'files': [{k: sorted(v) if k == 'selected_by' else v
                        for k, v in row.items() if k != '_source'}
                       for _, row in sorted(files.items())],
             'reference_hash_checks': checks,
             'omitted_references': [{'original_path': k, 'reason': v}
                                    for k, v in sorted(omitted.items())]}
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n')
    verified = verify_bundle.verify(here, repo)
    args.zip_output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.zip_output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, row in sorted(files.items()):
            data = row['_source'].read_bytes()
            if hash_bytes(data) != row['sha256']:
                raise ValueError(f'file changed before archiving: {name}')
            archive.writestr(name, data)
        archive.write(index_path, 'EVIDENCE_INDEX.json')
    with zipfile.ZipFile(args.zip_output) as archive:
        if archive.testzip() is not None:
            raise ValueError('archive CRC validation failed')
        if set(archive.namelist()) != set(files) | {'EVIDENCE_INDEX.json'}:
            raise ValueError('unexpected archive members')
        for name, row in files.items():
            if hash_bytes(archive.read(name)) != row['sha256']:
                raise ValueError(f'archive SHA256 mismatch: {name}')
    receipt = {**verified, 'zip_path': str(args.zip_output.resolve()),
               'zip_bytes': args.zip_output.stat().st_size,
               'zip_sha256': hash_bytes(args.zip_output.read_bytes()),
               'index_sha256': hash_bytes(index_path.read_bytes()),
               'zip_member_count': len(files) + 1, 'all_zip_member_hashes_checked': True,
               'no_solver_or_payload_replay_launched': True}
    output = args.zip_output.with_suffix('.receipt.json')
    if output.exists():
        raise ValueError(f'refusing to overwrite {output}')
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
