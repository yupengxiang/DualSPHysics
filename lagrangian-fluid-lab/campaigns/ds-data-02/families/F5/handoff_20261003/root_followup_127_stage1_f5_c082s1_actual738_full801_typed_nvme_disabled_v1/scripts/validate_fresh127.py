#!/usr/bin/env python3
"""Metadata-only validator for fresh127.

It never opens BI4/H5/CSV/DAT/VTK science payloads. Producer-attested hashes
for those paths are checked for presence and provenance; JSON/XML/Python and
other static request inputs are checked byte-for-byte.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCIENCE_SUFFIXES = {'.bi4', '.h5', '.csv', '.dat', '.vtk'}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


def fail(msg: str):
    raise SystemExit('fresh127 validation failed: ' + msg)


def check_request(path: Path):
    req = load(path)
    for key in ('family_id','case_id','attempt_id','kind','cpu_task_kind','command','cwd','max_wall_seconds','cpu_threads','estimated_storage_bytes','input_files','input_sha256','worktree_root'):
        if key not in req: fail(f'{path.name}: missing {key}')
    if req['family_id'] != 'F5' or req['kind'] != 'cpu' or req['cpu_task_kind'] != 'conversion': fail(f'{path.name}: wrong Root142 CPU identity')
    if not req['disabled'] or req['execution_allowed'] or req['launch_allowed'] or req['conversion_allowed'] or req['solver_allowed']: fail(f'{path.name}: typed request is enabled')
    if req['source_only'] is not True or req['arrays_allowed'] or req['array_edit_allowed']: fail(f'{path.name}: source/array policy')
    if req['cpu_threads'] != 2 or req['estimated_peak_gpu_mib'] != 0: fail(f'{path.name}: CPU resource shape')
    if req['nvme_policy']['shared_conversion_concurrency_cap'] != 2 or req['nvme_policy']['staging_limit_bytes'] != 25769803776: fail(f'{path.name}: NVME cap/floor')
    dep = req['actual_native_dependency']
    receipt_path = Path(dep['receipt']); request_path = Path(dep['request'])
    if not receipt_path.is_file() or not request_path.is_file(): fail(f'{path.name}: missing actual Root738 metadata')
    receipt = load(receipt_path); native = load(request_path)
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0: fail(f'{path.name}: native is not completed/0')
    if sha(receipt_path) != dep['receipt_sha256']: fail(f'{path.name}: native receipt digest')
    if sha(request_path) != dep['request_file_sha256']: fail(f'{path.name}: native request file digest')
    if dep['producer_request_sha256'] != receipt.get('request_sha256'): fail(f'{path.name}: producer request SHA')
    if req['depends_on_attempt'] != native['attempt_id'] or dep['attempt_id'] != native['attempt_id']: fail(f'{path.name}: native attempt binding')
    if req['expected_counts'] != native['actual_counts'] or req['actual_counts'] != native['actual_counts']: fail(f'{path.name}: actual count binding')
    if req['physical_condition_sha256'] != native['physical_condition_sha256']: fail(f'{path.name}: canonical physical hash')
    if req['actual_native_status'] != 'completed/0': fail(f'{path.name}: status label')
    if req['future_output_hashes'] != {'conversion_report_sha256': None, 'trajectory_h5_sha256': None, 'typed_receipt_sha256': None, 'xmf_manifest_sha256': None, 'bed_audit_report_sha256': None, 'render_manifest_sha256': None, 'render_receipt_sha256': None}: fail(f'{path.name}: future hash policy')
    if req['promotion_gate']['remaining10_release']['enabled'] or req['promotion_gate']['endpoint_chain']['current_visual_gate']: fail(f'{path.name}: downstream gate released')
    declared = req['input_sha256']
    if str(Path(__file__).resolve()) not in declared: fail(f'{path.name}: validator not digest-bound')
    for raw in req['input_files']:
        if '<root-bind:' in raw: fail(f'{path.name}: unresolved placeholder in input_files')
        p = Path(raw)
        if not p.exists(): fail(f'{path.name}: missing input {p}')
        key = str(p.resolve())
        if key not in declared: fail(f'{path.name}: missing digest {p}')
        suffix = p.suffix.lower()
        provenance = req['input_sha256_provenance'].get(key, '')
        if suffix in SCIENCE_SUFFIXES or suffix in {'.log', '.out'}:
            if 'producer-attested' not in provenance and 'future-registered' not in provenance:
                fail(f'{path.name}: science/log provenance missing for {p}')
        else:
            actual = sha(p)
            if actual != declared[key]: fail(f'{path.name}: digest mismatch {p}')
    return {'request': str(path), 'attempt_id': req['attempt_id'], 'native_status': receipt['status'], 'native_returncode': receipt['returncode'], 'input_count': len(req['input_files']), 'typed_disabled': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, default=ROOT / 'metadata/fresh127-validator-report.json')
    args = parser.parse_args()
    manifest = load(ROOT / 'manifest.json')
    if 'manifest.json' in manifest['files'] or 'metadata/fresh127-validator-report.json' in manifest['files']:
        fail('manifest/report self-reference')
    for rel, expected in manifest['files'].items():
        p = ROOT / rel
        if not p.is_file(): fail(f'manifest missing {rel}')
        if sha(p) != expected: fail(f'manifest digest mismatch {rel}')
    rows = [check_request(p) for p in sorted((ROOT / 'requests').glob('*-full801-typed-nvme-request.json'))]
    if len(rows) != 2: fail('expected exactly two endpoint typed requests')
    tags = {Path(r['request']).stem.split('-full801')[0] for r in rows}
    if tags != {'M085_T080','M115_T100'}: fail('wrong endpoint set')
    report = {'schema':'ds02.f5.c082s1.fresh127-validator-report.v1','status':'pass','source_agent_did_not_read_or_hash_science_payloads':True,'manifest_self_excluded':True,'rows':rows}
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))

if __name__ == '__main__': main()
