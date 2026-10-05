from __future__ import annotations
import copy, hashlib, importlib.util, json, re, sys
from pathlib import Path
import xml.etree.ElementTree as ET

F7 = Path('/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics')
I = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
L = I / 'lagrangian-fluid-lab'
PKG = F7 / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_077_actual_converter_scope_root142_adapter_v1'
OLD = F7 / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_076_actual_full601_typed_xmf_render_templates_v1'
SOURCE = F7 / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_074_stage1_next24_target_angles_v1'
MOTHER = F7 / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_071_stage1_first24_actual_gencase_qa_native_v1/owners/F7_OBSTACLE_QUINTIC_B08_A039.owner.json'
CONVERTER = L / 'scripts/ds_data02_direct_convert.py'
NVME = L / 'scripts/ds_data02_nvme_convert_v1.py'
RUNTIME = L / 'scripts/ds_data02_runtime_v2.py'
STRICT = L / 'scripts/ds_data02_strict_dispatch_v1.py'
ROOT142 = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142'
RENDER = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py'
XMF = I / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_repair_a_short51_actual_typed_bed_pipeline_105/workers/export_xmf.py'
VENV = L / '.venv/bin/python'
DATA_F7 = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7')
CASES = [f'F7_OBSTACLE_QUINTIC_B08_A{n:03d}P5' for n in (30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,54,59,64)]
HEX64 = re.compile(r'^[0-9a-f]{64}$')
RAW = {'.bi4','.csv','.h5','.hdf5','.dat','.vtk','.npy','.npz','.ibi4'}

for p in [OLD, SOURCE]:
    if not p.is_dir():
        raise SystemExit(f'missing source input directory: {p}')
for p in [MOTHER, CONVERTER, NVME, RUNTIME, STRICT, ROOT142/'launch.py', ROOT142/'root_home_floor_inventory_policy.py', RENDER, XMF, VENV]:
    if not p.is_file():
        raise SystemExit(f'missing source input: {p}')

def load(p):
    v=json.loads(Path(p).read_text(encoding='utf-8'))
    if not isinstance(v,dict): raise ValueError(f'JSON object required: {p}')
    return v

def dump(p,v):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(v,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8')

def sha(p):
    p=Path(p); h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def canonical(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def ensure_hex(v,label):
    if not isinstance(v,str) or not HEX64.fullmatch(v): raise ValueError(f'{label} not sha256: {v!r}')
    return v

def load_converter():
    spec=importlib.util.spec_from_file_location('ds02_converter_fresh077',CONVERTER)
    m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); return m

conv=load_converter()
mother=load(MOTHER)
mother_scope=conv._physical_condition_scope(mother)
mother_scope_sha=conv.canonical_hash(mother_scope)
if mother_scope.get('schema')!='ds-data-02.physical-binding.v1': raise ValueError('mother scope schema')
MOTHER_DENSITY=mother_scope['density_kg_m3']; MOTHER_MECHANISM=mother_scope['mechanism_id']; MOTHER_GRAVITY=mother_scope['gravity_m_s2']

(PKG/'owners').mkdir(parents=True,exist_ok=True)
(PKG/'requests/typed').mkdir(parents=True,exist_ok=True)
(PKG/'metadata').mkdir(parents=True,exist_ok=True)
(PKG/'scripts').mkdir(parents=True,exist_ok=True)
(PKG/'builders').mkdir(parents=True,exist_ok=True)
rows=[]
for case in CASES:
    old_path=SOURCE/'owners'/f'{case}.owner.json'
    if not old_path.is_file(): raise ValueError(f'missing owner {old_path}')
    old=load(old_path); old_sha=sha(old_path); old_pb=copy.deepcopy(old['physical_binding'])
    old_declared=ensure_hex(old['canonical_physical_binding_sha256'],f'{case} old canonical')
    source_plan=ensure_hex(old['condition_hash_semantics']['declared_source_hash'],f'{case} source plan')
    xml_path=Path(old['source']['source_definition'])
    if not xml_path.is_file(): raise ValueError(f'missing source definition {xml_path}')
    xml_root=ET.parse(xml_path).getroot()
    const=xml_root.find('.//constantsdef')
    grav=const.find('gravity') if const is not None else None
    rhop=const.find('rhop0') if const is not None else None
    xml_gravity=[float(grav.attrib[a]) for a in ('x','y','z')] if grav is not None else None
    xml_density=float(rhop.attrib['value']) if rhop is not None else None
    if xml_gravity != MOTHER_GRAVITY or xml_density != MOTHER_DENSITY: raise ValueError(f'{case} XML constants differ')
    pb=copy.deepcopy(old_pb); controls=pb.get('controls',{})
    moved=[]
    if 'gravity_m_s2' in controls:
        if 'gravity_m_s2' in pb and pb['gravity_m_s2'] != controls['gravity_m_s2']: raise ValueError(f'{case} conflicting gravity')
        pb['gravity_m_s2']=controls.pop('gravity_m_s2'); moved.append('controls.gravity_m_s2 -> gravity_m_s2')
    if 'density_kg_m3' not in pb:
        pb['density_kg_m3']=MOTHER_DENSITY; moved.append('mother physical_binding.density_kg_m3')
    if 'mechanism_id' not in pb:
        pb['mechanism_id']=MOTHER_MECHANISM; moved.append('mother physical_binding.mechanism_id')
    if pb.get('gravity_m_s2') != xml_gravity or pb.get('density_kg_m3') != xml_density: raise ValueError(f'{case} XML/repair mismatch')
    repaired=copy.deepcopy(old)
    repaired['physical_binding']=pb
    repaired['schema']='ds02.f7.fresh077.converter-owner.v1'
    repaired['scope_id']='root_followup_077_actual_converter_scope_root142_adapter_v1'
    repaired['status']='source_only_disabled_pending_root142_typed_chain'
    repaired['launch_allowed']=False
    scope=conv._physical_condition_scope(repaired)
    scope_sha=conv.canonical_hash(scope)
    if scope_sha in {old_declared,source_plan}: raise ValueError(f'{case} repaired scope collapsed')
    repaired['canonical_physical_binding_sha256']=scope_sha
    repaired['physical_condition_sha256']=scope_sha
    sem=copy.deepcopy(repaired.get('condition_hash_semantics',{}))
    sem.update({
        'converter_hash_scope':'actual ds_data02_direct_convert._physical_condition_scope(owner) canonical JSON of corrected physical_binding.v1',
        'declared_source_hash':source_plan,
        'declared_source_hash_scope':'fresh074 source plan physical_condition_payload retained separately',
        'source_and_converter_hashes_are_distinct':True,
        'original_declared_canonical_binding_sha256':old_declared,
        'corrected_converter_scope_sha256':scope_sha,
        'scope_repair_required':True,
        'scope_repair_reason':'fresh074 placed gravity_m_s2 under controls and omitted density_kg_m3/mechanism_id; current converter allowlist requires explicit top-level fields',
    })
    repaired['condition_hash_semantics']=sem
    repaired['scope_repair']={
        'schema':'ds02.f7.fresh077.converter-scope-repair.v1',
        'original_owner_path':str(old_path.resolve()), 'original_owner_sha256':old_sha,
        'original_declared_canonical_binding_sha256':old_declared,
        'source_plan_condition_sha256':source_plan,
        'corrected_scope_sha256':scope_sha,
        'corrections':moved,
        'source_definition_path':str(xml_path.resolve()), 'source_definition_sha256':sha(xml_path),
        'source_xml_constants':{'gravity_m_s2':xml_gravity,'density_kg_m3':xml_density},
        'mother_owner_path':str(MOTHER.resolve()), 'mother_owner_sha256':sha(MOTHER),
        'mother_scope_sha256':mother_scope_sha,
        'converter_source':str(CONVERTER.resolve()), 'converter_source_sha256':sha(CONVERTER),
        'converter_callable':'ds_data02_direct_convert._physical_condition_scope(owner)',
        'arrays_read':False, 'payloads_read_or_hashed':False, 'jobs_started':False,
    }
    new_path=PKG/'owners'/f'{case}.converter-owner.json'; dump(new_path,repaired); new_sha=sha(new_path)
    rows.append({
        'case_id':case,'original_owner_path':str(old_path.resolve()),'original_owner_sha256':old_sha,
        'original_declared_canonical_binding_sha256':old_declared,'source_plan_condition_sha256':source_plan,
        'corrected_owner_path':str(new_path.resolve()),'corrected_owner_sha256':new_sha,
        'converter_scope_schema':scope.get('schema'),'converter_scope_sha256':scope_sha,
        'source_definition_path':str(xml_path.resolve()),'source_definition_sha256':sha(xml_path),
        'source_xml_constants':{'gravity_m_s2':xml_gravity,'density_kg_m3':xml_density},
        'corrections':moved,'canonical_distinct':scope_sha not in {old_declared,source_plan},
        'status':'passed',
    })

scope_meta={
 'schema':'ds02.f7.fresh077.actual-converter-scope-preflight.v1','scope_id':'root_followup_077_actual_converter_scope_root142_adapter_v1','family_id':'F7','case_count':len(rows),
 'converter':{'path':str(CONVERTER.resolve()),'sha256':sha(CONVERTER),'callable':'ds_data02_direct_convert._physical_condition_scope(owner)','import_python':str(VENV.resolve()),'import_python_sha256':sha(VENV)},
 'mother_reference':{'path':str(MOTHER.resolve()),'sha256':sha(MOTHER),'scope_sha256':mother_scope_sha,'density_kg_m3':MOTHER_DENSITY,'mechanism_id':MOTHER_MECHANISM,'gravity_m_s2':MOTHER_GRAVITY},
 'cases':rows,'all_passed':all(r['status']=='passed' for r in rows),'arrays_read':False,'payloads_read_or_hashed':False,'jobs_started':False,'shared_state_written':False,
 'claim_boundary':'Corrected owner scope is converter-compatible metadata only; no typed conversion, XMF/render product, visual acceptance, Q-N, precision, or production claim.',
}
scope_path=PKG/'metadata/converter-scope-preflight.json'; dump(scope_path,scope_meta); scope_sha_file=sha(scope_path)

# Root142 source/strict audit against immutable fresh076 requests, metadata/source only.
sys.path.insert(0,str(L/'scripts'))
import ds_data02_runtime_v2 as runtime
import ds_data02_strict_dispatch_v1 as strict
runtime_counts={}; failures=[]; total=0
for p in sorted((OLD/'requests').rglob('*.json')):
    d=load(p); total+=1
    try:
        actual=runtime.validate_request(d)
        strict.check_registered_hashes(d,actual)
        runtime_counts[d.get('cpu_task_kind','?')]=runtime_counts.get(d.get('cpu_task_kind','?'),0)+1
    except Exception as e: failures.append({'path':str(p),'error':f'{type(e).__name__}: {e}'})
root_sources=[ROOT142/'launch.py',ROOT142/'root_home_floor_inventory_policy.py',RUNTIME,STRICT,CONVERTER,NVME,XMF,RENDER,VENV]
root_audit={
 'schema':'ds02.f7.fresh077.root142-contract-audit.v1','scope_id':'root_followup_077_actual_converter_scope_root142_adapter_v1',
 'runtime_required_fields':['family_id','case_id','attempt_id','kind','command','cwd','max_wall_seconds','cpu_threads','estimated_storage_bytes','input_files','worktree_root'],
 'strict_guard_required':'strict_dispatch_v1.check_registered_hashes requires strict guard path in both input_files and input_sha256; each input digest must match actual metadata/source bytes',
 'source_hashes':{str(p.resolve()):sha(p) for p in root_sources},
 'root142':{'launch':str((ROOT142/'launch.py').resolve()),'policy':str((ROOT142/'root_home_floor_inventory_policy.py').resolve()),'policy_sha256':sha(ROOT142/'root_home_floor_inventory_policy.py'),'policy_core_sha256':'5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60','profile':'root_home_floor_no_legacy_dataset_walk_v1','launch_owner':'root','kind':'cpu'},
 'fresh076_static_request_audit':{'total':total,'runtime_validate_passed':total-len(failures),'strict_digest_closure_passed':total-len(failures),'counts_by_cpu_task_kind':runtime_counts,'failures':failures,'arrays_read':False,'payloads_read_or_hashed':False,'jobs_started':False},
 'required_runtime_contract':{'input_files_sha_exact_set':True,'producer_scope_schema':'ds-data-02.physical-binding.v1','typed_frames':601,'typed_particles':70179,'dimension':3,'xmf_vector_shape':'N 3','xmf_scalar_shape':'N','isolated_output_dirs':['{attempt_root}/xdmf','{attempt_root}/render']},
 'finding':'fresh076 request/runtime/strict fields pass metadata-only validation, but its conversion owner is rejected by the current converter scope validator; fresh077 replaces only the owner metadata and typed request input closure.',
 'arrays_read':False,'payloads_read_or_hashed':False,'jobs_started':False,'shared_state_written':False,
}
root_audit_path=PKG/'metadata/root142-contract-audit.json'; dump(root_audit_path,root_audit); root_audit_sha=sha(root_audit_path)

# Corrected Root142 typed requests. fresh076 stays immutable.
for case in CASES:
    old_req_path=OLD/f'requests/typed/{case}.full601-typed-nvme-076.disabled-request.json'; d=load(old_req_path)
    owner_row=next(r for r in rows if r['case_id']==case); owner_path=Path(owner_row['corrected_owner_path']); owner_sha=owner_row['corrected_owner_sha256']; old_owner=Path(owner_row['original_owner_path'])
    d['scope_id']='root_followup_077_actual_converter_scope_root142_adapter_v1'; d['attempt_id']=f'root-stage1-f7-{case.rsplit("_",1)[1].lower()}-full601-typed-nvme-077'
    cmd=list(d['command']); oi=cmd.index('--owner-metadata'); cmd[oi+1]=str(owner_path); d['command']=cmd
    d['canonical_physical_binding_sha256']=owner_row['converter_scope_sha256']; d['physical_condition_sha256']=owner_row['converter_scope_sha256']; d['source_plan_condition_sha256']=owner_row['source_plan_condition_sha256']
    d['canonical_owner']=copy.deepcopy(d.get('canonical_owner',{})); d['canonical_owner'].update({'owner_path':str(owner_path),'owner_sha256':owner_sha,'canonical_physical_binding_sha256':owner_row['converter_scope_sha256'],'source_plan_condition_sha256':owner_row['source_plan_condition_sha256']})
    d['producer_scope']=copy.deepcopy(d.get('producer_scope',{})); d['producer_scope']['canonical_physical_binding_sha256']=owner_row['converter_scope_sha256']; d['producer_scope']['source_plan_condition_sha256']=owner_row['source_plan_condition_sha256']; d['producer_scope']['actual_hashes']=None
    d['owner_metadata']={'path':str(owner_path),'sha256':owner_sha,'scope_schema':'ds-data-02.physical-binding.v1','scope_sha256':owner_row['converter_scope_sha256'],'source_plan_condition_sha256':owner_row['source_plan_condition_sha256']}
    d['conversion_owner_contract']={'converter':str(CONVERTER.resolve()),'converter_sha256':sha(CONVERTER),'callable':'ds_data02_direct_convert._physical_condition_scope(owner)','corrected_owner':str(owner_path),'corrected_owner_sha256':owner_sha,'scope_schema':'ds-data-02.physical-binding.v1','scope_sha256':owner_row['converter_scope_sha256'],'original_declared_canonical_binding_sha256':owner_row['original_declared_canonical_binding_sha256'],'source_plan_condition_sha256':owner_row['source_plan_condition_sha256']}
    d['actual_input_closure']=copy.deepcopy(d.get('actual_input_closure',{})); d['actual_input_closure'].update({'original_owner':str(old_owner),'original_owner_sha256':owner_row['original_owner_sha256'],'corrected_converter_owner':str(owner_path),'corrected_converter_owner_sha256':owner_sha,'corrected_converter_scope_sha256':owner_row['converter_scope_sha256'],'scope_preflight':str(scope_path.resolve()),'scope_preflight_sha256':scope_sha_file,'root142_contract_audit':str(root_audit_path.resolve()),'root142_contract_audit_sha256':root_audit_sha,'raw_payload_hashes_remain_null':True})
    d['future_outputs']={k:(v.replace('-076','-077') if isinstance(v,str) else v) for k,v in d.get('future_outputs',{}).items()}
    d['future_input_files']=[v.replace('-076','-077') if isinstance(v,str) else v for v in d.get('future_input_files',[])]
    d['future_input_sha256']={((k.replace('-076','-077') if isinstance(k,str) else k)):v for k,v in d.get('future_input_sha256',{}).items()}
    # Replace old owner path in the registered metadata closure and add corrected owner/audits.
    files=[]; prov=copy.deepcopy(d.get('input_hash_provenance',{})); hashes=copy.deepcopy(d.get('input_sha256',{}))
    for raw in d['input_files']:
        if str(Path(raw).resolve())==str(old_owner.resolve()):
            continue
        files.append(raw)
    for raw in list(hashes):
        if str(Path(raw).resolve())==str(old_owner.resolve()): del hashes[raw]; prov.pop(raw,None)
    additions=[str(owner_path),str(scope_path.resolve()),str(root_audit_path.resolve())]
    for raw in additions:
        if raw not in files: files.append(raw)
        hashes[raw]=sha(Path(raw)); prov[raw]='fresh077 metadata-only corrected converter owner/scope/root142 audit; no scientific payload'
    d['input_files']=files; d['input_sha256']=hashes; d['input_hash_provenance']=prov
    d['status']='corrected_converter_scope_disabled_pending_root142_typed'
    d['disabled_reason']='Disabled source request. Use corrected converter owner; Root142 strict qualification must review and enable this new 077 attempt.'
    d['source_only']=True; d['launch']=False; d['launch_allowed']=False; d['execution_allowed']=False; d['disabled']=True; d['future_hashes_null']=True; d['independent_case_count_increment']=0
    # exact closure is intentionally metadata-only; reject any payload in current inputs.
    if {str(Path(x).resolve()) for x in files}!={str(Path(x).resolve()) for x in hashes}: raise ValueError(f'{case} closure mismatch')
    for raw in files:
        if Path(raw).suffix.lower() in RAW: raise ValueError(f'payload in typed input closure: {raw}')
    out=PKG/f'requests/typed/{case}.full601-typed-nvme-077.disabled-request.json'; dump(out,d)

# Package builder/provenance marker is written by caller after this script; manifest now.
all_files=[p for p in PKG.rglob('*') if p.is_file()]
manifest={
 'schema':'ds02.f7.fresh077.manifest.v1','scope_id':'root_followup_077_actual_converter_scope_root142_adapter_v1','family_id':'F7','case_count':len(CASES),'case_ids':CASES,
 'input_template_package':str(OLD.resolve()),'input_template_manifest_sha256':sha(OLD/'manifest.json'),'consumed_fresh076_immutable':True,
 'corrected_owner_count':len(rows),'typed_request_count':len(list((PKG/'requests/typed').glob('*.json'))),
 'converter_scope_schema':'ds-data-02.physical-binding.v1','converter_scope_preflight_sha256':scope_sha_file,'root142_contract_audit_sha256':root_audit_sha,
 'all_requests_disabled':True,'future_hashes_null':True,'arrays_read':False,'bi4_read':False,'h5_read':False,'csv_read':False,'motion_read':False,'jobs_started':False,'shared_state_written':False,
 'claim_boundary':'This package repairs only converter-owner metadata and supplies Root142 preflight/typed-to-XMF-render adapter. It grants no typed product, visual acceptance, Q-N, precision, or production status.',
 'source_only':True,
}
dump(PKG/'manifest.json',manifest)
print(json.dumps({'package':str(PKG),'cases':len(CASES),'scope_preflight':scope_sha_file,'root142_audit':root_audit_sha,'mother_scope':mother_scope_sha,'owner_scope_hashes':[r['converter_scope_sha256'] for r in rows],'fresh076_runtime_audit':root_audit['fresh076_static_request_audit']},indent=2))
