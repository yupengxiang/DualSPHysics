#!/usr/bin/env python3
"""Read-only validator for fresh225; never hashes PNG or science payload."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
CASE="F2_STAGE1_FIRST48_EXPANSION_RX053_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"; PHYS="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT090"; CAN="03e792f100771b0c5bb1e686dfccad3f29e8d4b5b7dcc2847a6cebaa6f30563e"; LEG="2a5f6038420f2c22cb53d5bcf4718ff9af01a52422d40ed47c00e9acf835ec00"; QI_SHA="d57f12d02a35ec5bf0a67f81d2319057ea4d3957392f408fa3949a4836eefc00"; FORBIDDEN={'.h5','.bi4','.ibi4','.csv','.dat','.vtk'}; ALLOWED={'.json','.xml','.xmf','.py'}; EXPECTED={'README.md','metadata/upstream-evidence.json','metadata/visual-evidence.json','metadata/visual-decision.json','metadata/physical-closure.json','scripts/validate_fresh225.py'}
def dg(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def ok(v,m):
 if not v: raise AssertionError(m)
def load(r): return json.loads((ROOT/r).read_text())
def main():
 m=load('manifest.json'); ok(m['schema']=='ds02.f5.fresh225.source-package-manifest.v1' and m['source_only'] and m['assigned_family_id']=='F5' and m['actual_physical_family_id']=='F2' and m['manifest_excludes_self'],'manifest')
 ok(not m['science_payloads_copied'] and not m['scientific_jobs_started_by_source_agent'] and not m['shared_state_written_by_source_agent'],'isolation')
 files={x['path']:x for x in m['files']}; ok(set(files)==EXPECTED,'file set')
 for r,x in files.items(): p=ROOT/r; ok(p.is_file() and p.stat().st_size==x['bytes'] and dg(p)==x['sha256'],'package '+r); ok(p.suffix.lower() not in FORBIDDEN,'package payload')
 u=load('metadata/upstream-evidence.json'); v=load('metadata/visual-evidence.json'); d=load('metadata/visual-decision.json'); c=load('metadata/physical-closure.json')
 for x in (u,v,d,c): ok(x['case_id']==CASE and x['physical_case_id']==PHYS,'identity')
 ok(u['model']=='gpt-5.6-luna/max' and u['recursive_delegation'] is False,'profile')
 sh=u['actual_shape']; ok(sh['dimension']==3 and sh['frames']==401 and sh['particles']==418104 and sh['contact_sheets']==17 and sh['keyframes']==[0,50,100,150,200,250,300,350,400],'shape')
 t=u['terminal_evidence']; ok(t['execution_status']=='completed' and t['execution_returncode']==0 and t['publish_status']=='published_after_atomic_rename' and t['report_frames']==401 and t['report_source_frames']==401 and t['all_frames_rendered'] and t['actual_times_preserved_exactly'] and t['native_identity_axis_preserved'] and t['nonfinite_active_states']==0 and t['source_h5_opened_or_hashed_by_wrapper'] is False,'terminal')
 q=u['main_own_qi']; ok(q['provided_sha256']==QI_SHA and q['is_independent_proof_not_runner_receipt'] and q['case_credit']==0 and q['q_n_granted'] is False and q['q_e_granted'] is False,'QI')
 s=u['scope_roles']; ok(s['canonical_native_source_physical_scope_sha256']==CAN and s['typed_xmf_actual_legacy_producer_scope_sha256']==LEG and s['scope_equality_claimed'] is False,'scopes'); n=s['native_plan_masks']; ok(n['source_plan_condition_sha256']['present'] is False and n['source_plan_physical_condition_sha256']['present'] is True and n['source_plan_physical_condition_sha256']['value']==CAN,'native masks'); x=s['xmf_plan_masks']; ok(x['source_plan_condition_sha256']['present'] is False and x['source_plan_physical_condition_sha256']['present'] is False,'xmf masks')
 o=u['lifecycle_omissions']; ok(o['final_missing_particles']==2 and o['first_missing_frame']==158 and o['cumulative_particle_frame_omissions']==387 and o['producer_attested_final_Idp_sample']==[403829,410867] and o['missing_location_state_cause_unknown'],'omission')
 ok(v['contacts_viewed']==17 and v['keyframes_viewed']==9 and len(v['published_pngs'])==26,'visual count'); co=[x for x in v['published_pngs'] if x['role']=='contact_sheet']; ke=[x for x in v['published_pngs'] if x['role']=='keyframe']; ok([x['index'] for x in co]==list(range(17)) and [x['index'] for x in ke]==[0,50,100,150,200,250,300,350,400],'visual indices')
 for x in v['published_pngs']:
  p=Path(x['absolute_path']); ok(p.is_file() and p.stat().st_size==x['producer_bytes']==x['observed_stat_bytes'],'PNG stat'); ok(re.fullmatch(r'[0-9a-f]{64}',x['producer_sha256'] or '') and x['sha256_source']=='render-publish-receipt.json' and x['sha256_computed_by_source_agent'] is False and x['viewed_by_source_agent'],'PNG provenance')
 ok(d['personal_visual_review_completed'] and d['reviewer_model']=='gpt-5.6-luna/max' and d['recursive_delegation'] is False and d['coverage']=={'contact_sheets':17,'keyframes':9,'keyframe_indices':[0,50,100,150,200,250,300,350,400]},'decision')
 ok(d['case_credit_increment']==0 and d['q_n_granted'] is False and d['q_e_granted'] is False and d['numerical_precision_accepted'] is False and d['strict_container_guarantee'] is False and d['sub_dp_penetration_claimed'] is False and d['root_image_intervention_required'] is False,'claim limits')
 ok(c['personal_visual_review_completed'] and c['case_credit_increment']==0 and c['producer_payload_not_read_or_hashed_by_source_agent'],'closure')
 rt=datetime.fromisoformat(d['review_completed_at_utc']); fin=datetime.fromisoformat(t['execution_finished_at_utc']); ok(rt >= fin,'review after render completion'); ok(rt <= datetime.now(timezone.utc),'review timestamp')
 for r in u['external_metadata_refs']:
  p=Path(r['path']); ok(p.is_file() and p.suffix.lower() in ALLOWED and dg(p)==r['sha256'],'external metadata '+str(p)); ok(not any(str(p).lower().endswith(s) for s in FORBIDDEN),'external payload')
 print('fresh225 F5-assigned F2 RX053/ROT090 personal visual review PASS'); print('package='+str(ROOT)); print('contacts=17 keyframes=9 case_credit_increment=0')
if __name__=='__main__': main()
