#!/usr/bin/env python3
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parents[1]; META=HERE/'metadata/personal-visual-decision.json'
FORBIDDEN={'.h5','.bi4','.csv','.dat','.vtk','.vtu','.vtp','.pvd','.raw'}

def load(p): return json.loads(Path(p).read_text())
def check_ref(x,label):
    assert isinstance(x,dict), label+' not object'
    p=Path(x['path']); assert p.suffix.lower() not in FORBIDDEN, label+' forbidden payload'; assert p.exists(), label+' missing'
    b=p.read_bytes(); assert len(b)==x['bytes'], label+' size drift'; assert hashlib.sha256(b).hexdigest()==x['sha256'], label+' sha drift'
    return p

def check_receipt(x,label):
    p=check_ref(x,label); d=load(p); assert d.get('schema')=='ds02.execution-receipt.v1',label+' schema'; assert d.get('status')=='completed' and d.get('returncode')==0,label+' not completed/0'; return d

def main():
    d=load(META); assert d['schema']=='ds02.f6.fresh183.f5-personal-visual-review.v1'; assert d['fresh_id']=='fresh183'; assert d['family_id']=='F6' and d['assigned_family']=='F6' and d['actual_family']=='F5'; assert d['model']=='gpt-5.6-luna' and d['reasoning_effort']=='max' and d['recursive_delegation'] is False
    c=d['case']; assert c['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1'; assert c['physical_case_id']=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T100'; assert c['producer_counts']=={'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'total':194427}; assert c['dimension']==3 and c['expected_frames']==801
    assert c['canonical_native_physical_condition_sha256']=='81b91a91bcce2365496f0892d0e5d2a5362da917be1ed49b6dd2c1536e8c0ebf'; assert c['actual_converter_legacy_scope_sha256']=='11b64a1f82d362bd28452eddd2d4ca62e608d8f83d093c8080b726e7c86edcd7'; assert c['xmf_source_def_scope_sha256']=='912423162f08b22524fc67ddf8dde30cf897e98fca126e261c283eabc520e558'; assert c['actual_native_source_plan_field_present'] is False and c['actual_native_source_plan_physical_condition_sha256'] is None; assert c['native_plan_equals_xmf_source_definition'] is False and c['scope_substitution_or_equality_claimed'] is False
    assert d['decision']['status']=='visual-approved-by-delegated-agent' and d['decision']['case_credit']==0 and d['decision']['global_acceptance'] is False and d['decision']['precision_status']=='not accepted' and d['decision']['q_n'] is False and d['decision']['q_e'] is False
    assert d['source_boundaries']['scientific_h5_read'] is False and d['source_boundaries']['scientific_h5_hash'] is False and d['source_boundaries']['scientific_bi4_read'] is False and d['source_boundaries']['scientific_bi4_hash'] is False and d['source_boundaries']['shared_state_modified'] is False
    p=d['predecessor']; pp=Path(p['metadata']); assert p['fresh_id']=='fresh182' and p['schema']=='ds02.f6.fresh182.f2-personal-visual-review.v1' and pp.exists() and hashlib.sha256(pp.read_bytes()).hexdigest()==p['metadata_sha256']
    ev=d['evidence'];
    for k,x in ev.items(): check_ref(x,'evidence.'+k)
    for k in ['gencase_receipt','initial_qa_receipt','native_receipt','typed_receipt','xmf_receipt','bed_receipt','render_receipt']: check_receipt(ev[k],'evidence.'+k)
    qi=load(ev['root_qi_proof']['path']); assert qi['actual_native_source_plan_condition_field_present'] is False and qi['actual_native_source_plan_condition_sha256'] is None; assert qi['canonical_actual_native_request_condition_sha256']==c['canonical_native_physical_condition_sha256']; assert qi['actual_converter_legacy_scope_sha256']==c['actual_converter_legacy_scope_sha256']; assert qi['XMF_source_plan_condition_field_sha256']==c['xmf_source_def_scope_sha256']
    qa=load(ev['initial_qa_report']['path']); assert qa['all_basic_placement_checks_pass'] is True and qa['diagnostic_only'] is True and qa['numerical_precision_result_accepted'] is False
    tr=load(ev['typed_report']['path']); assert tr['conversion_status']=='completed' and tr['frames']==801 and tr['particles']==194427; sd=tr['solver_dimension']; assert sd==3 or (isinstance(sd,dict) and sd.get('solver_dimension')==3); assert tr['lifecycle']['contract']=='closed fixed identity axis' and tr['lifecycle']['transient_missing_frame_count']==0
    xm=load(ev['xmf_manifest']['path']); assert xm['schema']=='ds02.stage1.paraview-temporal-product.v1' and xm['expected_frames']==801 and xm['expected_particles']==194427; assert xm['canonical_physical_scope']['physical_condition_sha256']==c['canonical_native_physical_condition_sha256']; assert xm['source_plan_physical_condition_sha256']==c['xmf_source_def_scope_sha256']
    rr=load(ev['render_report']['path']); assert rr['schema']=='ds02.stage1.paraview-full-animation-integrity.v1' and rr['frames']==801 and rr['source_frames']==801 and rr['all_frames_rendered'] is True and rr['actual_times_preserved_exactly'] is True and rr['native_identity_axis_preserved'] is True and rr['nonfinite_active_states']==0 and rr['numerical_precision_status']=='not accepted'; assert len(rr['frame_diagnostics'])==801; assert rr['frame_diagnostics'][0]['actual_time_s']==0.0 and rr['frame_diagnostics'][-1]['actual_time_s']==16.00008577197294; assert rr['frame_diagnostics'][0]['active']==194427 and rr['frame_diagnostics'][-1]['active']==194427; assert rr['frame_diagnostics'][0]['missing']==0 and rr['frame_diagnostics'][-1]['missing']==0
    pub=load(ev['publish_receipt']['path']); assert pub['status']=='published_after_atomic_rename' and pub['source_h5_opened_or_hashed_by_wrapper'] is False
    cr=load(ev['controller_result']['path']); assert cr['status']=='completed' and cr['returncode']==0 and cr['launcher_returncode']==0 and cr['case_credit']==0
    vr=d['visual_review']; assert vr['method']=='view_image' and vr['viewed_all_contact_sheets'] is True and vr['viewed_contact_sheet_count']==34 and len(vr['contact_sheets'])==34 and vr['viewed_all_key_frames'] is True and vr['viewed_key_frame_count']==9 and [x['frame'] for x in vr['key_frames']]==[0,100,200,300,400,500,600,700,800]
    for i,x in enumerate(vr['contact_sheets']): assert x['sheet_index']==i; check_ref(x,'contact_sheet')
    for i,x in enumerate(vr['key_frames']): assert x['frame']==[0,100,200,300,400,500,600,700,800][i]; check_ref(x,'key_frame')
    assert d['render_product']['source_h5_opened_or_hashed_by_this_agent'] is False and d['future_work']['new_solver_or_render_request'] is False
    print('fresh183 metadata-only validator: PASS')
if __name__=='__main__': main()
