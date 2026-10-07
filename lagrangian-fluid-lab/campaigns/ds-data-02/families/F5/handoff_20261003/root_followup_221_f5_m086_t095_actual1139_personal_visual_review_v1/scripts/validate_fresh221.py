#!/usr/bin/env python3
"""Read-only validator for the F5 fresh221 personal visual handoff.

It reads JSON/XML/XMF metadata and published PNG stat information only. It
never opens or hashes PNG, H5, BI4, CSV, DAT, VTK, or other science payloads.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, re
ROOT = Path(__file__).resolve().parents[1]
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T095_NEXT34"
PHYS = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M086_T095"
ATT = "root-stage1-f5-m086_t095-actual1016-bed0-full801-original116023-frozen-progress-root1139"
QI_SHA = "7c8249da0ae83663be1ddd9960e017840fddac3ce218ed317f3558ac92e5836a"
CAN = "8d2888e5d37945e48917d79c4913124b6142fc310af80798137204978151407c"
LEGACY = "9f244b68219c72e26a04193480cfa0fd7b6fb629fa434824a802ef85f9b16ede"
BED = "12449b514d94bf9509e330d725b9021c1c78b7ad50cb58d164f7680ce03f8b24"
KEY = [0,100,200,300,400,500,600,700,800]
EXPECTED = {"README.md","metadata/actual-render-metadata.json","metadata/physical-stage-closure.json","metadata/png-visual-evidence.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh221.py"}
def load(rel): return json.loads((ROOT/rel).read_text())
def dg(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()
def ok(v,m):
    if not v: raise AssertionError(m)
def verify_metadata_ref(ref, allow_xml=True):
    path=Path(ref['path']); ok(path.is_file(),f'missing metadata ref: {path}')
    ok(path.suffix.lower() in ({'.json','.xml','.xmf'} if allow_xml else {'.json'}),f'non-metadata ref: {path}')
    ok(dg(path)==ref['sha256'],f'metadata SHA mismatch: {path}')
def main():
    manifest=load('manifest.json'); ok(manifest['source_only'] and manifest['manifest_excludes_self'],'manifest flags')
    ok(manifest['assigned_family_id']=='F5','family'); ok(not manifest['science_payloads_copied'] and not manifest['scientific_jobs_started_by_source_agent'] and not manifest['shared_state_written_by_source_agent'],'isolation')
    entries={x['path']:x for x in manifest['files']}; ok(set(entries)==EXPECTED,'manifest file set')
    for rel,item in entries.items():
        path=ROOT/rel; ok(path.is_file(),f'missing package file: {rel}'); ok(path.stat().st_size==item['bytes'],f'package bytes: {rel}'); ok(dg(path)==item['sha256'],f'package SHA: {rel}')
    render=load('metadata/actual-render-metadata.json'); closure=load('metadata/physical-stage-closure.json'); visual=load('metadata/png-visual-evidence.json'); upstream=load('metadata/upstream-evidence.json'); decision=load('metadata/visual-decision.json')
    for item in (render,closure,visual,upstream,decision): ok(item['case_id']==CASE and item['physical_case_id']==PHYS,'identity')
    receipt=render['execution_receipt']; ok(render['attempt_id']==ATT and receipt['status']=='completed' and receipt['returncode']==0,'execution')
    pub=render['publish_receipt']; ok(pub['status']=='published_after_atomic_rename','publish')
    rep=render['render_report']; ok(rep['frames']==801 and rep['source_frames']==801 and rep['all_frames_rendered'] and rep['actual_times_preserved_exactly'],'render frames'); ok(rep['native_identity_axis_preserved'] and rep['nonfinite_active_states']==0 and rep['numerical_precision_status']=='not accepted','render integrity')
    e=render['expected_and_actual']; ok(e['particles']==194427 and e['fluid_initial_UIDs']==31658 and e['contact_sheets']==34 and e['keyframe_indices']==KEY,'counts'); ok(e['fixed']==158559 and e['moving']==4210 and e['floating']==0 and e['solver_dimension']==3 and not e['data2d'],'producer counts')
    s=render['scope_roles']; ok(s['native_request_and_actual_converter_canonical']==CAN and s['typed_legacy_scope']==LEGACY,'native/legacy scope'); ok(not s['native_source_plan_condition_field_present'] and s['native_source_plan_condition_sha256'] is None,'native condition mask'); ok(s['native_source_plan_physical_condition_field_present'] and s['native_source_plan_physical_condition_sha256']==CAN,'native physical mask'); ok(not s['xmf_source_plan_condition_field_present'] and s['xmf_source_plan_condition_sha256'] is None,'XMF condition mask'); ok(s['xmf_source_plan_physical_condition_field_present'] and s['xmf_source_plan_physical_condition_sha256']==CAN,'XMF physical mask'); ok(not s['xmf_source_plan_physical_condition_has_SourceDef_role'] and s['xmf_source_plan_physical_condition_has_native_canonical_role'],'XMF canonical role'); ok(s['binding_SourceDef_input_present'] and s['binding_SourceDef_input_sha256']==BED,'SourceDef input'); ok(s['bed_declared_source_plan_file_sha256']==BED and s['roles_are_distinct'] and not s['scope_equality_claimed'],'bed scope')
    qi=upstream['main_qi']; ok(qi['sha256']==QI_SHA,'QI SHA'); verify_metadata_ref({'path':qi['path'],'sha256':qi['sha256']},allow_xml=False)
    for name in ('render_receipt','render_report','bed_receipt','bed_report','xmf_manifest','xmf_receipt','xmf_xml','initial_qa_receipt','initial_qa_report','gencase_receipt','generated_xml','native_receipt','typed_receipt','typed_report'):
        ref=upstream['actual_completed_metadata_evidence'].get(name)
        if ref: verify_metadata_ref(ref)
    verify_metadata_ref(upstream['actual_SourceDef'])
    def verify_png_group(group,n,key_name):
        ok(len(group)==n,key_name+' count'); idx=[x['index'] if key_name=='contacts' else x['frame_index'] for x in group]; ok(idx==(list(range(34)) if key_name=='contacts' else KEY),key_name+' indexes')
        for x in group:
            ok(x['reviewed'] and x['review_mode']=='view_image',key_name+' review'); ok(re.fullmatch(r'[0-9a-f]{64}',x['sha256']),key_name+' producer hash'); ok(x['sha256_source']=='producer render-publish-receipt.json',key_name+' provenance'); p=Path(x['absolute_path']); ok(p.is_file(),key_name+' missing published PNG'); ok(p.stat().st_size==x['filesystem_size_bytes_observed_by_source_agent']==x['bytes'],key_name+' stat')
    verify_png_group(visual['producer_attested_contact_sheets'],34,'contacts'); verify_png_group(visual['producer_attested_keyframes'],9,'keyframes'); ok(visual['review_coverage']['source_agent_computed_png_hashes'] is False,'PNG hash provenance'); ok(visual['review_coverage']['reviewed_published_pngs_only'] is True,'PNG scope')
    d=decision['decision']; ok(d['standalone_first_stage_visual_approved'] and not d['severe_visual_failure'] and not d['needs_root_image_intervention'],'visual decision'); ok(d['weak_or_localized_response_limit'] and not d['large_runup_or_inundation_established'],'visual limitation'); ok(not d['strict_container_guarantee'] and not d['sub_dp_penetration_claim'],'claim limits'); ok(not d['numerical_precision_accepted'] and not d['q_n_granted'] and not d['q_e_granted'] and d['independent_case_count_increment']==0,'credit/precision')
    reviewed=datetime.fromisoformat(decision['reviewer']['reviewed_at_utc'].replace('Z','+00:00')); finished=datetime.fromisoformat(receipt['finished_at_utc'].replace('Z','+00:00')); ok(reviewed>=finished and reviewed<=datetime.now(timezone.utc),'review time'); ok(decision['reviewer']['model']=='gpt-5.6-luna/max' and decision['reviewer']['recursive_delegation'] is False,'reviewer model')
    print('fresh221 F5 M086/T095 metadata and personal visual handoff validation PASS'); print('package='+str(ROOT)); print('reviewed=34 contact sheets + 9 keyframes; case_credit_increment=0')
if __name__=='__main__': main()
