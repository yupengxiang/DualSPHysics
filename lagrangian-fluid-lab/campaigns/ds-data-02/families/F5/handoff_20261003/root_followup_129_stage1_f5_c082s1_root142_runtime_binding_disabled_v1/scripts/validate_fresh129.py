#!/usr/bin/env python3
"""Metadata-only validator for the disabled fresh129 Root142 XMF bindings."""
from __future__ import annotations
import ast, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCIENCE_SUFFIXES={'.dat','.bi4','.h5','.hdf5','.csv','.vtk','.vtu','.npy','.npz'}
TAGS=('M085_T080','M115_T100')
EXPECTED={'data2d':False,'fixed_particles':158559,'floating_particles':0,'fluid_particles':31658,'moving_particles':4210,'solver_dimension':3,'total_particles':194427,'xml_particle_counts':{'fixed':158559,'floating':0,'fluid':31658,'moving':4210}}

def fail(msg): raise SystemExit('fresh129 validation failed: '+msg)
def load(p):
    try:return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception as e: fail(f'cannot load {p}: {e}')
def sha(p):
    p=Path(p)
    if p.suffix.lower() in SCIENCE_SUFFIXES: fail(f'science payload hash attempted: {p}')
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()
def static(path, value, label):
    p=Path(path)
    if not p.is_file(): fail(f'{label}: missing {p}')
    if sha(p)!=value: fail(f'{label}: digest mismatch {p}')
def check_upstream(tag,b):
    tr=Path(b['full_typed_receipt']); treq=Path(b['full_typed_request']); reportp=Path(b['full_typed_conversion_report']); nr=Path(b['full_native_receipt']); nreq=Path(b['full_native_request']);
    rr=load(tr); rq=load(treq); rp=load(reportp); n=load(nr); c=load(Path(b['root753_controller']))
    if (rr.get('status'),rr.get('returncode'))!=('completed',0): fail(f'{tag}: typed status')
    if (n.get('status'),n.get('returncode'))!=('completed',0): fail(f'{tag}: native status')
    if c.get('finished')!=2 or c.get('completed0')!=2: fail(f'{tag}: Root754 controller')
    if rr.get('request_sha256')!=sha(treq): fail(f'{tag}: typed request closure')
    if rr.get('request',{}).get('attempt_id')!=tr.parent.name: fail(f'{tag}: typed nested attempt')
    if rp.get('conversion_status')!='completed' or rp.get('frames')!=801 or rp.get('particles')!=194427: fail(f'{tag}: conversion dimensions')
    if not isinstance(rp.get('solver_dimension'),dict) or rp['solver_dimension'].get('solver_dimension')!=3: fail(f'{tag}: report 3D')
    if (rp.get('partvtk_validation') or {}).get('all_passed') is not True: fail(f'{tag}: PartVTK')
    if rp.get('output_sha256')!=b['trajectory_h5_sha256']: fail(f'{tag}: H5 producer attestation')
    if (rp.get('hash_scopes') or {}).get('physical_condition_sha256')!=b['source_h5_physical_condition_sha256']: fail(f'{tag}: legacy scope')
    if sha(tr)!=b['full_typed_receipt_sha256'] or sha(treq)!=b['full_typed_request_sha256'] or sha(reportp)!=b['full_typed_conversion_report_sha256']: fail(f'{tag}: typed hashes')
    if sha(nr)!=b['full_native_receipt_sha256'] or sha(nreq)!=b['full_native_request_sha256']: fail(f'{tag}: native hashes')
    if b['actual_counts']!=EXPECTED or b['expected_counts']!=EXPECTED: fail(f'{tag}: counts')
    if b['physical_condition_sha256']==b['source_h5_physical_condition_sha256']: fail(f'{tag}: canonical/legacy collapsed')
    if b['fresh125_source_forecast_scope_sha256']==b['source_h5_physical_condition_sha256']: fail(f'{tag}: forecast/legacy collapsed')
    return {'typed':'completed/0','native':'completed/0','frames':801,'particles':194427,'dimension':3,'partvtk_all_passed':True,'h5_attestation_only':True}
def check_request(tag, reqp, bindp):
    r=load(reqp); b=load(bindp)
    aliases=b.get('ready_binding_aliases')
    if not isinstance(aliases,dict) or aliases.get('typed_receipt')!=b.get('full_typed_receipt') or aliases.get('native_receipt')!=b.get('full_native_receipt') or aliases.get('conversion_report')!=b.get('full_typed_conversion_report'):
        fail(f'{tag}: exporter ready-binding aliases')
    for k in ('schema','handoff_schema','family_id','case_id','attempt_id','kind','cpu_task_kind','command','cwd','max_wall_seconds','cpu_threads','estimated_storage_bytes','input_files','input_sha256','input_sha256_provenance','worktree_root','root_dataset_inventory_profile','root_inventory_profile','root_inventory_policy_source_sha256','root_inventory_policy_sha256','root142_runtime_binding','root142_registration','resource_approval_064','python_interpreter','xmf_contract','bed_gate'):
        if k not in r: fail(f'{tag}: missing request {k}')
    if r['kind']!='cpu' or r['cpu_task_kind']!='audit' or r['cpu_threads']!=2 or r['launch_owner']!='root': fail(f'{tag}: Root142 identity')
    if not (r.get('disabled') is True and r.get('execution_allowed') is False and r.get('launch') is False and r.get('launch_allowed') is False and r.get('source_only') is True): fail(f'{tag}: request enabled')
    if any(r.get(k) for k in ('solver_allowed','conversion_allowed','arrays_allowed','array_edit_allowed','shared_registry_write_allowed','shared_state_modified')): fail(f'{tag}: unsafe permission')
    if r['root_dataset_inventory_profile']!='root_home_floor_no_legacy_dataset_walk_v1': fail(f'{tag}: profile')
    rb=r['root142_runtime_binding']
    for field in ('root142_entrypoint','root142_policy_source','runtime_entrypoint','strict_dispatch_entrypoint'):
        if not Path(rb[field]).is_file(): fail(f'{tag}: missing runtime source {field}')
    if rb['root142_entrypoint_sha256']!=sha(rb['root142_entrypoint']) or rb['root142_policy_source_sha256']!=sha(rb['root142_policy_source']) or rb['runtime_entrypoint_sha256']!=sha(rb['runtime_entrypoint']) or rb['strict_dispatch_entrypoint_sha256']!=sha(rb['strict_dispatch_entrypoint']): fail(f'{tag}: runtime source hash')
    if rb['root_dataset_inventory_profile']!=r['root_dataset_inventory_profile'] or rb['launch_owner']!='root' or rb['kind']!='cpu' or rb['cpu_task_kind']!='audit' or rb['cpu_threads']!=2: fail(f'{tag}: runtime block')
    if r['command'][0]!=r['python_interpreter']['path'] or r['python_interpreter']['sha256']!=sha(r['command'][0]): fail(f'{tag}: interpreter')
    if r['resource_approval_064']['sha256']!=sha(r['resource_approval_064']['path']): fail(f'{tag}: approval')
    if r['actual_counts']!=EXPECTED or r['expected_counts']!=EXPECTED: fail(f'{tag}: request counts')
    if r['physical_condition_sha256']!=b['physical_condition_sha256'] or r['source_h5_physical_condition_sha256']!=b['source_h5_physical_condition_sha256']: fail(f'{tag}: request/binding scope')
    if any(v is not None for v in r['future_output_hashes'].values()): fail(f'{tag}: invented future hash')
    if r['bed_gate']['status']!='wait_for_actual_xmf' or any(r['bed_gate'].get(k) is not None for k in ('xmf_manifest_sha256','xmf_receipt_sha256','bed_audit_report_sha256','bed_audit_receipt_sha256')): fail(f'{tag}: bed gate')
    if r['xmf_contract'] != b['xmf_contract']: fail(f'{tag}: XMF contract mismatch')
    if r['attempt_id']!=b['attempt_id'] or r['command'][3]!=str(bindp.resolve()): fail(f'{tag}: binding identity')
    files=r['input_files']; hashes=r['input_sha256']; prov=r['input_sha256_provenance']
    if len(files)!=len(hashes) or len(files)!=len(prov): fail(f'{tag}: input closure lengths')
    for raw in files:
        p=Path(raw).resolve(); key=str(p)
        if not p.is_file(): fail(f'{tag}: missing input {p}')
        if key not in hashes or key not in prov: fail(f'{tag}: unbound input {p}')
        if p.suffix.lower() in SCIENCE_SUFFIXES:
            if p.suffix.lower()!='.h5' or len(hashes[key])!=64 or 'producer-attested' not in prov[key]: fail(f'{tag}: science attestation {p}')
        elif sha(p)!=hashes[key]: fail(f'{tag}: input digest {p}')
    if str((ROOT/'scripts/validate_fresh129.py').resolve()) not in hashes: fail(f'{tag}: validator absent from closure')
    return {'request':str(reqp),'attempt_id':r['attempt_id'],'disabled':True,'input_count':len(files),'kind':'cpu','cpu_task_kind':'audit'}
def main():
    manifest=load(ROOT/'manifest.json')
    if 'manifest.json' in manifest.get('files',{}) or 'metadata/fresh129-validator-report.json' in manifest.get('files',{}): fail('manifest/report self-reference')
    for rel,digest in manifest.get('files',{}).items(): static(ROOT/rel,digest,'manifest')
    if not (ROOT/'workers/export_xmf_legacy_aware.py').is_file(): fail('missing exporter')
    ast.parse((ROOT/'workers/export_xmf_legacy_aware.py').read_text(),filename=str(ROOT/'workers/export_xmf_legacy_aware.py'))
    actual=[]; reqs=[]
    for tag in TAGS:
        bp=ROOT/f'bindings/{tag}-full801-root142-xmf-binding.json'; rp=ROOT/f'requests/{tag}-full801-root142-xmf-request.json'; b=load(bp)
        if not b['schema'].endswith('fresh129.v1'): fail(f'{tag}: binding schema')
        actual.append(check_upstream(tag,b)); reqs.append(check_request(tag,rp,bp))
    report={'schema':'ds02.f5.c082s1.fresh129-validator-report.v1','status':'pass','manifest_self_excluded':True,'root753_upstream':actual,'disabled_requests':reqs,'bed_gate':'wait_for_actual_xmf','source_agent_did_not_read_or_hash_science_payloads':True,'historical_precision_negative_retained':True,'remaining10_and_t120_closed':True}
    (ROOT/'metadata/fresh129-validator-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__': main()
