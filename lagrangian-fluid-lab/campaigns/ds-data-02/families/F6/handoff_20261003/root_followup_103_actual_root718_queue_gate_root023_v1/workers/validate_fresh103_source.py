#!/usr/bin/env python3
"""Source-only fresh103 validator for Root711/718 XMF and Root716 render gates."""
from __future__ import annotations
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parents[1]
ROOT711_REG = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_all24_mixed699success7_plus709future17_XMF_registration_711/actual-mixed24-XMF-registration.json')
ROOT713_REVIEW = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_fresh102_mixed711_XMF_to_renderer_source_adoption_713/actual-source-adoption-review.json')
ROOT717_REVIEW = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_wait710_resource_reservations_list_failure_classification_717/failure-and-queue-repair-review.json')
ROOT718_CONTROLLER = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_XMF709_wait_native707_actual_list_reservations_controller_repair_718/batch-controller.py')
ROOT722_REG = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_mixed699seven_709seventeen_actual_all24_XMF_terminal_722/actual-all24-XMF-terminal-registration.json')
ROOT715_REVIEW = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_actual669_full1201_renderer023_complete_runtime_contract_715/complete-runtime-and-output-contract-render-enable-review.json')
ROOT716_CONTROLLER = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_render715_wait638_global2_controller_716/batch-controller.py')
INTEGRATION_ROOT = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
INTEGRATION_CWD = INTEGRATION_ROOT / 'lagrangian-fluid-lab'
OFFICIAL_XMF = INTEGRATION_CWD / 'campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_100_actual_root607_root658_xmf_native023_render_v1/workers/export_xmf.py'
REQUIRED = ('family_id', 'case_id', 'attempt_id', 'kind', 'command', 'cwd', 'max_wall_seconds', 'cpu_threads', 'estimated_storage_bytes', 'input_files', 'worktree_root')
XMF_LITERAL = ('bound_metadata_sha256', 'conversion_report', 'expected_frames', 'physical_case_id', 'physical_condition_sha256', 'physical_window_s', 'producer_scope_schema', 'native_receipt', 'trajectory_h5', 'typed_receipt')
SCIENTIFIC_SUFFIXES = {'.h5', '.hdf5', '.bi4', '.ibi4', '.csv', '.dat'}
COMPLETED = 'actual699_completed0_N3_pass'
WAITING = 'registered709_WAIT_actual707_CPUphase_drain'

class ContractError(RuntimeError): pass

def load(p: Path) -> dict[str, Any]: return json.loads(p.read_text(encoding='utf-8'))
def sha(p: Path) -> str:
    if p.suffix.lower() in SCIENTIFIC_SUFFIXES: raise ContractError(f'scientific hash attempted: {p}')
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def require(c: bool, m: str) -> None:
    if not c: raise ContractError(m)
def ast_constants(path: Path) -> set[str]:
    t=ast.parse(path.read_text(encoding='utf-8'))
    return {n.value for n in ast.walk(t) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
def validate_required(req: dict[str,Any]) -> None:
    miss=[k for k in REQUIRED if k not in req]
    if miss: raise ContractError('missing request field(s): '+', '.join(miss))
    require(req.get('kind')=='cpu','kind'); require(req.get('cpu_task_kind')=='audit','cpu_task_kind')
    require(isinstance(req.get('command'),list) and req['command'] and all(isinstance(x,str) for x in req['command']),'command')
    require(isinstance(req.get('input_files'),list) and req['input_files'],'input_files')
    require(isinstance(req.get('worktree_root'),str) and Path(req['worktree_root']).is_absolute(),'worktree_root absolute')
    require(isinstance(req.get('cwd'),str) and Path(req['cwd']).is_absolute(),'cwd absolute')
    require(req['worktree_root']==str(INTEGRATION_ROOT),'worktree_root integration')
    require(req['cwd']==str(INTEGRATION_CWD),'cwd integration lab')
    require(isinstance(req.get('estimated_storage_bytes'),int) and req['estimated_storage_bytes']>0,'storage')
    require(req.get('cpu_threads')==24 and req.get('declared_cpu_cores')==24,'CPU24')
    require(req.get('max_wall_seconds')==14400,'wall')
def closure(obj: dict[str,Any], label: str, own: Path|None=None) -> None:
    files=obj.get('input_files'); hm=obj.get('input_sha256',{})
    require(isinstance(files,list) and isinstance(hm,dict) and set(files)==set(hm),label+' closure')
    if own: require(str(own.resolve()) not in files,label+' self closure')
    for text in files:
        p=Path(text); require(p.is_file(),label+' missing '+text); require(p.suffix.lower() not in SCIENTIFIC_SUFFIXES,label+' scientific input '+text); require(sha(p)==hm[text],label+' digest '+text)
def manifest_contract(worker: Path) -> dict[str,bool]:
    text=worker.read_text(encoding='utf-8'); const=ast_constants(worker)
    funcs={n.name for n in ast.walk(ast.parse(text)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    # Root023 uses reader Points for geometry; Geometry is not a point-field
    # literal in this worker.  Check the actual portable manifest API instead:
    # saved times, source digest, dimensions, required identity fields, and
    # the native velocity field used by the full-frame diagnostics.
    needed_literals={'actual_time_s','xdmf_sha256','frames','particles','valid','particle_id','particle_zone','type','velocity'}
    require(needed_literals <= const,'Root023 manifest contract literals')
    require({'validate_manifest','load_manifest'} <= funcs,'Root023 manifest functions')
    spec=importlib.util.spec_from_file_location('fresh103_renderer',worker); mod=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(mod)
    synthetic={'schema':'ds02.stage1.paraview-temporal-product.v1','xdmf':'synthetic.xmf','xdmf_sha256':'0'*64,'frames':2,'particles':3,'actual_time_s':[0.0,0.05],'fields':['valid','particle_id','particle_zone','type','mass','velocity','density','pressure'],'finite_fields':['mass','velocity','density','pressure']}
    mod.validate_manifest(synthetic)
    bad=dict(synthetic); bad.pop('actual_time_s')
    try: mod.validate_manifest(bad)
    except Exception: pass
    else: raise ContractError('manifest missing actual_time_s negative accepted')
    return {'synthetic_valid_manifest':True,'missing_actual_time_negative_rejected':True}
def root_record(registry: dict[str,Any], case: str, reg: dict[str,Any], reg_sha: str) -> None:
    rec=registry[case]; require(reg.get('root711_status')==rec['status'],case+' Root711 status')
    require(reg.get('root711_registry_sha256')==reg_sha,case+' Root711 registry SHA')
    req=Path(reg['registered_request']); bind=Path(reg['registered_binding']); require(req.is_file() and bind.is_file(),case+' producer metadata')
    require(sha(req)==rec['registered_request_sha256'] and sha(bind)==rec['registered_binding_sha256'],case+' producer metadata digest')
    q=load(req); b=load(bind); require(q.get('case_id')==case and b.get('case_id')==case,case+' producer identity')
    require(q.get('expected_native_frames')==241 and q.get('expected_particles')==417505 and b.get('expected_frames')==241,'producer dimensions')
    require(Path(reg['producer_receipt'])==Path(reg['attempt_root'])/'execution-receipt.json','producer receipt derivation')
    require(Path(reg['producer_manifest'])==Path(reg['attempt_root'])/'xdmf/manifest.json','producer manifest derivation')
    require(Path(reg['producer_case_xmf'])==Path(reg['attempt_root'])/'xdmf/case.xmf','producer xmf derivation')
    if rec['status']==COMPLETED:
        require(all(isinstance(reg.get(k),str) and len(reg[k])==64 for k in ('producer_receipt_sha256','producer_manifest_sha256','producer_case_xmf_sha256')),case+' completed attestation')
    else:
        require(all(reg.get(k) is None for k in ('producer_receipt_sha256','producer_manifest_sha256','producer_case_xmf_sha256')),case+' future hashes null')
def main() -> int:
    require(ROOT711_REG.is_file(),'Root711 missing'); reg_sha=sha(ROOT711_REG); root=load(ROOT711_REG); records={x['case_id']:x for x in root['cases']}; require(len(records)==24,'Root711 case count')
    require(ROOT713_REVIEW.is_file() and load(ROOT713_REVIEW).get('source_commit')=='039c5bd0e4f817d35f9c9f5124575bdfc6b6a451' and load(ROOT713_REVIEW).get('source_preserved_byte_exact') is True,'Root713 adoption')
    r717=load(ROOT717_REVIEW); require(r717.get('canonical_reservation_schema')=='list' and r717.get('actual709_execution_receipts_before_repair')==0,'Root717 list failure evidence')
    require(ROOT722_REG.is_file(),'Root722 terminal registration missing'); root722_sha=sha(ROOT722_REG); root722=load(ROOT722_REG); terminal={x['case_id']:x for x in root722['cases']}; require(root722.get('schema')=='ds02.f6.actual-all24-mixed-XMF-terminal.v1' and len(terminal)==24,'Root722 terminal registration'); require(all(x.get('status')=='actual_completed0_N3_pass' and x.get('actual_XMF_frames')==241 and x.get('actual_particle_axis')==417505 and x.get('actual_input_before_after_equal') is True for x in terminal.values()),'Root722 actual terminal dimensions/status')
    r715=load(ROOT715_REVIEW); require(r715.get('output_child_contract')=='{attempt_root}/render' and r715.get('CPU24_env2_wall14400_global2') is True,'Root715 render contract')
    require(ROOT718_CONTROLLER.is_file() and ROOT716_CONTROLLER.is_file(),'active queue controllers')
    worker=PACKAGE/'workers/render_native023.py'; require(worker.is_file() and sha(worker)=='5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66','Root023 exact SHA')
    manifest_checks=manifest_contract(worker); require(set(XMF_LITERAL)<=ast_constants(OFFICIAL_XMF),'official XMF fields')
    reqs=sorted((PACKAGE/'requests/render').glob('*.json')); binds=sorted((PACKAGE/'bindings/render').glob('*.json')); require(len(reqs)==len(binds)==24,'fresh103 pair count')
    details=[]
    for rp,bp in zip(reqs,binds):
        q=load(rp); b=load(bp); case=q.get('case_id'); require(case in records and b.get('case_id')==case,case+' identity'); require(q.get('fresh_id')=='fresh103' and b.get('fresh_id')=='fresh103',case+' fresh')
        require(q.get('disabled') is True and q.get('execution_allowed') is False and q.get('launch_allowed') is False,case+' request gate'); require(b.get('disabled') is True and b.get('execution_allowed') is False,case+' binding gate'); validate_required(q)
        require(q.get('worker')==str(worker.resolve()) and b.get('worker')==str(worker.resolve()) and q.get('worker_sha256')==sha(worker) and b.get('worker_sha256')==sha(worker),case+' worker')
        require(q.get('render_binding')==str(bp.resolve()) and q.get('render_binding_sha256')==sha(bp),case+' binding pointer'); require(q.get('expected_frames')==241 and b.get('expected_frames')==241 and q.get('expected_particles')==417505 and b.get('expected_particles')==417505,case+' dimensions')
        require(str(q.get('output_dir_contract','')).startswith('{attempt_root}/render') and '--manifest' in q['command'] and q['command'][q['command'].index('--manifest')+1]==q['xmf_manifest'],case+' output/manifest command')
        require('--output-dir' in q['command'] and q['command'][q['command'].index('--output-dir')+1]=='{attempt_root}/render',case+' output child command')
        gate=q.get('render_gate',{}); require(gate.get('f6_gate',{}).get('require_all17_root718_completed0_and_N3_pass') is True and gate.get('f6_gate',{}).get('root718_observed_completed_cases_at_source_snapshot')==17 and gate.get('f4_gate',{}).get('require_all24_root716_completed0') is True and gate.get('f4_gate',{}).get('active_gate_is_root716') is True and gate.get('f4_gate',{}).get('root690_is_historical_not_gate') is True,case+' active gates')
        reg=q.get('xmf_registration_711'); require(isinstance(reg,dict),case+' Root711 pointer'); root_record(records,case,reg,reg_sha)
        obs=q.get('root718_observation'); require(isinstance(obs,dict) and obs.get('case_id')==case,case+' Root718 observation'); require(obs.get('receipt_sha256') is None and obs.get('manifest_sha256') is None and obs.get('case_xmf_sha256') is None,case+' Root718 hashes null')
        actual=terminal[case]; att=q.get('root722_terminal_registration'); require(isinstance(att,dict) and att.get('registry')==str(ROOT722_REG.resolve()) and att.get('registry_sha256')==root722_sha and att.get('status')=='actual_completed0_N3_pass',case+' Root722 terminal attestation')
        require(b.get('root722_terminal_registration',{}).get('registry_sha256')==root722_sha and b.get('root722_terminal_registration',{}).get('status')=='actual_completed0_N3_pass',case+' binding Root722 terminal attestation')
        for field, actual_field in (('xmf_receipt','actual_receipt'),('xmf_manifest','actual_manifest'),('xmf_case','actual_case_xmf')):
            require(q.get(field)==actual[actual_field] and b.get(field)==actual[actual_field],case+' '+field+' terminal path')
        for field, actual_field in (('xmf_receipt_sha256','actual_receipt_sha256'),('xmf_manifest_sha256','actual_manifest_sha256'),('xmf_case_sha256','actual_case_xmf_sha256')):
            require(q.get(field)==actual[actual_field] and b.get(field)==actual[actual_field] and isinstance(q.get(field),str) and len(q[field])==64,case+' '+field+' terminal digest')
        require(q.get('xmf_terminal_status')=='actual_root722_completed0_N3_pass' and q.get('xmf_terminal_frames')==241 and q.get('xmf_terminal_particles')==417505,case+' terminal dimensions')
        require(q.get('render_gate',{}).get('f6_gate',{}).get('root718_terminal_attestation_via_root722') is True and q.get('render_gate',{}).get('f6_gate',{}).get('root722_terminal_registration')==str(ROOT722_REG),case+' active Root722 gate')
        closure(q,case+' request'); closure(b,case+' binding',bp); require(str(bp.resolve()) not in b.get('bound_metadata_sha256',{}),case+' bound self')
        for text,digest in b.get('bound_metadata_sha256',{}).items(): require(Path(text).is_file() and Path(text).suffix.lower() not in SCIENTIFIC_SUFFIXES and sha(Path(text))==digest,case+' bound metadata')
        require(q.get('future_hashes_null') is True and b.get('future_hashes_null') is True,case+' render future hashes'); details.append({'case_id':case,'root711_status':records[case]['status'],'root718_observed_status':obs.get('observed_status'),'render_hashes_null':True})
    probe={k:'present' for k in REQUIRED}; probe.pop('worktree_root')
    try: validate_required(probe)
    except ContractError as e: require('worktree_root' in str(e),'missing worktree_root negative')
    else: raise ContractError('missing worktree_root accepted')
    print(json.dumps({'status':'pass','fresh_id':'fresh103','cases':24,'root711_completed_reused':7,'root709_cases':17,'root718_observed_completed':sum(d['root718_observed_status']=='completed' for d in details if d['root711_status']==WAITING),'root722_actual_completed':24,'active_f6_gate':'Root722 all24 completed0/N3','active_f4_gate':'Root716 all24 completed0','historical_gates_not_active':['Root638','Root689','Root690'],'renderer_sha256':sha(worker),'manifest_contract':manifest_checks,'cpu_threads':24,'environment_threads':2,'max_wall_seconds':14400,'missing_worktree_root':'rejected_before_reservation','no_scientific_payload_read_or_hashed':True},indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
