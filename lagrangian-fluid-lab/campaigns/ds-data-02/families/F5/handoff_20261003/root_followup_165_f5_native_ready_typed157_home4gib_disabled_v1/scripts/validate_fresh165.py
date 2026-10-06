#!/usr/bin/env python3
"""Metadata-only validator for F5 fresh165.

This validator deliberately never opens opaque science payloads (.bi4/.dat/.h5/
.csv/.vtk/...). It validates producer attestations, current JSON/XML/Python
source hashes, disabled Root142 request closure, and actual upstream receipts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

SAFE = {'.json','.xml','.py','.md','.sh','.toml','.ini'}
SCIENCE = {'.bi4','.dat','.h5','.csv','.vtk','.vtu','.pvtu','.png','.jpg','.jpeg','.npy','.npz','.bin'}
EXPECTED = {'total_particles':194427,'fixed_particles':158559,'moving_particles':4210,'floating_particles':0,'fluid_particles':31658,'solver_dimension':3,'data2d':False}
WORKER_SHA = '37fe7eaff4405e9ba6d9b7f666a53d7c02ee65fc6f30992fc1a8fdb0d8a61b11'
PACKAGE_ID = 'F5_fresh165_native_ready_typed157_home4gib_disabled'

def fail(msg):
    raise AssertionError(msg)

def load(p):
    return json.loads(Path(p).read_text())

def sha_safe(p):
    p = Path(p)
    if p.suffix.lower() not in SAFE:
        fail(f'unsafe hash requested: {p}')
    return hashlib.sha256(p.read_bytes()).hexdigest()

def norm_counts(c):
    x = c.get('xml_particle_counts', {})
    return {
        'total_particles': int(c.get('total_particles', c.get('actual_total_particles'))),
        'fixed_particles': int(c.get('fixed_particles', x.get('fixed'))),
        'moving_particles': int(c.get('moving_particles', x.get('moving'))),
        'floating_particles': int(c.get('floating_particles', x.get('floating'))),
        'fluid_particles': int(c.get('fluid_particles', x.get('fluid'))),
        'solver_dimension': int(c.get('solver_dimension', 3)),
        'data2d': bool(c.get('data2d', False)),
    }

def require_worker_hash(actual, expected=WORKER_SHA):
    if actual != expected:
        fail(f'worker hash mismatch: {actual} != {expected}')
    return True

def validate_input_closure(req):
    files = req['input_files']; hashes = req['input_sha256']; prov = req['input_sha256_provenance']; cats = req['input_sha256_categories']
    if len(files) != len(set(files)):
        fail('duplicate input_files')
    if set(files) != set(hashes) or set(files) != set(prov) or set(files) != set(cats):
        fail('input files/hash/provenance/category sets differ')
    for raw in files:
        p = Path(raw)
        if not p.is_absolute():
            fail(f'input path is not absolute: {raw}')
        if not p.exists():
            fail(f'input path missing: {raw}')
        value = hashes[raw]
        category = cats[raw]
        if p.is_dir():
            if value is not None:
                fail(f'directory input must not have an opaque hash: {raw}')
            continue
        if p.suffix.lower() in SCIENCE:
            if not value or not ('producer' in prov[raw] or 'attest' in prov[raw] or category == 'producer_payload_attestation'):
                fail(f'science input lacks producer attestation: {raw}')
            # Deliberately no read/hash here.
            continue
        if p.suffix.lower() in SAFE:
            if value != sha_safe(p):
                fail(f'current source/metadata hash mismatch: {raw}')
            continue
        # Executables and other registered binary tools are opaque to this source worker.
        if not value:
            fail(f'registered binary lacks attestation: {raw}')

def validate_one(pkg, req_path):
    req = load(req_path)
    tag = req['tag']
    bind_path = Path(req['physical_binding_path'])
    bind = load(bind_path)
    require_worker_hash(req['command_provenance']['worker_sha256'])
    if req['schema'] != 'ds02.runner-request.v2' or req['family_id'] != 'F5': fail(f'{tag}: schema/family')
    for k,v in {'disabled':True,'source_only':True,'launch':False,'launch_allowed':False,'execution_allowed':False,'conversion_allowed':False,'solver_allowed':False,'arrays_allowed':False,'array_edit_allowed':False}.items():
        if req.get(k) != v: fail(f'{tag}: {k}={req.get(k)!r}')
    if req['kind'] != 'cpu' or req['cpu_task_kind'] != 'conversion' or req['cpu_threads'] != 2: fail(f'{tag}: CPU contract')
    for field in ['root_actual_launch_source','root_actual_launch_source_sha256','root_inventory_policy_source','root_inventory_policy_source_sha256','root_inventory_policy_sha256','root_inventory_profile','worktree_root','actual_native_receipt','actual_native_request','native_output_root','native_solver_data_root']:
        if not req.get(field): fail(f'{tag}: missing Root142/native alias {field}')
    if req['shared_conversion_concurrency_cap'] != 1: fail(f'{tag}: conversion serialization')
    if req['estimated_storage_bytes'] != 4294967296 or req['home_publish_cap_bytes'] != 4294967296: fail(f'{tag}: Home cap')
    if req['home_min_free_bytes'] != 536870912000 or req['home_publish_headroom_bytes'] != 2147483648: fail(f'{tag}: Home floor/headroom')
    if req['nvme_staging_limit_bytes'] != 25769803776 or req['nvme_free_reserve_bytes'] != 107374182400: fail(f'{tag}: NVMe contract')
    if req['current_attempt_id'] != f"F5/{req['case_id']}/{req['attempt_id']}": fail(f'{tag}: current attempt identity')
    if req['physical_binding_sha256'] != sha_safe(bind_path): fail(f'{tag}: binding hash')
    if bind['schema'] != 'ds02.f5.fresh165.native-ready-typed157-binding.v1': fail(f'{tag}: binding schema')
    if bind['tag'] != tag or bind['case_id'] != req['case_id'] or bind['physical_case_id'] != req['physical_case_id']: fail(f'{tag}: binding identity')
    if bind['physical_condition_sha256'] != req['physical_condition_sha256']: fail(f'{tag}: physical scope')
    if bind['source_bed_marker_mkbound'] != 40 or bind['native_bed_marker_mk'] != 50: fail(f'{tag}: marker mapping')
    c = norm_counts(req['actual_counts'])
    if c != EXPECTED: fail(f'{tag}: actual counts {c}')
    if req['actual_counts'] != req['expected_counts']: fail(f'{tag}: expected/actual counts differ')
    if req['expected_frames'] != 801 or req['expected_particle_axis'] != 194427 or req['expected_dimension'] != 3: fail(f'{tag}: timeline')
    if req['future_output_hashes'] != {'typed_h5_sha256':None,'typed_receipt_sha256':None,'conversion_report_sha256':None,'xmf_manifest_sha256':None,'bed_audit_report_sha256':None,'render_manifest_sha256':None}: fail(f'{tag}: future hashes')
    # Actual JSON/XML upstream hashes are current and independently checked.
    current_hash_inputs = [('gencase_receipt','gencase_receipt_sha256'),('prepared_input_report','prepared_input_report_sha256'),('generated_xml','generated_xml_sha256'),('actual_initial_qa_receipt','actual_initial_qa_receipt_sha256'),('actual_initial_qa_report','actual_initial_qa_report_sha256')]
    for path_key, hash_key in current_hash_inputs:
        p = Path(req[path_key]); h = req[hash_key]
        if p.suffix.lower() not in SAFE or sha_safe(p) != h: fail(f'{tag}: current hash {path_key}')
    native_receipt_path = Path(req['actual_native_dependency']['receipt'])
    if sha_safe(native_receipt_path) != req['actual_native_dependency']['receipt_sha256']:
        fail(f'{tag}: current hash actual native receipt')
    g = load(req['gencase_receipt']); q = load(req['actual_initial_qa_report']); n = load(req['actual_native_dependency']['receipt'])
    if (g.get('status'),g.get('returncode')) != ('completed',0): fail(f'{tag}: GenCase terminal')
    if (n.get('status'),n.get('returncode')) != ('completed',0): fail(f'{tag}: native terminal')
    if not q.get('all_basic_placement_checks_pass') or q.get('stage1_basic_placement_proof') != 'pass_excluding_numerical_precision' or q.get('numerical_precision_result_accepted') is not False: fail(f'{tag}: QA gate')
    if req['actual_native_dependency']['attempt_id'] != n['request']['attempt_id']: fail(f'{tag}: native attempt')
    if req['actual_native_dependency']['frames'] != n['request'].get('expected_frames'): fail(f'{tag}: native frames')
    if req['generated_xml_sha256'] != load(req['prepared_input_report']).get('xml_sha256'): fail(f'{tag}: XML producer attestation')
    validate_input_closure(req)
    cmd = req['command']
    if str(Path(req['command_provenance']['worker_path'] if 'worker_path' in req['command_provenance'] else '')):
        pass
    if req['command_provenance']['worker_sha256'] != WORKER_SHA or not any('nvme_convert_home_capped_v2.py' in x for x in cmd): fail(f'{tag}: command worker')
    for x in ['--home-publish-cap-bytes','4294967296','--home-floor-bytes','536870912000','--home-publish-headroom-bytes','2147483648','--nvme-free-reserve-bytes','107374182400','--current-attempt-id',req['current_attempt_id']]:
        if x not in cmd: fail(f'{tag}: command control {x}')
    return {'tag':tag,'case_id':req['case_id'],'physical_case_id':req['physical_case_id'],'actual_native_attempt':n['request']['attempt_id'],'counts':c,'input_count':len(req['input_files']),'status':'metadata-pass-disabled'}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--package-root',type=Path,required=True); args=ap.parse_args(); pkg=args.package_root
    requests=sorted((pkg/'requests').glob('*.json'))
    if len(requests) != 12: fail(f'expected 12 requests, got {len(requests)}')
    results=[validate_one(pkg,p) for p in requests]
    tags=[x['tag'] for x in results]
    if len(set(tags)) != 12: fail('duplicate tags')
    # Meaningful stale-worker negative: the same guard rejects a synthetic mismatched hash.
    stale_rejected=False
    try: require_worker_hash('stale-worker-sha')
    except AssertionError: stale_rejected=True
    if not stale_rejected: fail('stale worker negative did not reject')
    manifest=load(pkg/'manifest.json')
    for rel,h in manifest['files'].items():
        p=pkg/rel
        if not p.exists() or sha_safe(p) != h: fail(f'manifest mismatch {rel}')
    report={'schema':'ds02.f5.fresh165.validator-report.v1','package_id':PACKAGE_ID,'source_only':True,'arrays_read_or_hashed':False,'science_payloads_read_or_hashed':False,'request_count':12,'results':results,'negative_checks':{'stale_worker_hash_rejected':True},'manifest_checked':True,'future_hashes_null':True,'status':'pass-disabled-metadata-only'}
    out=pkg/'metadata/fresh165-validator-report.json'; out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__': main()
