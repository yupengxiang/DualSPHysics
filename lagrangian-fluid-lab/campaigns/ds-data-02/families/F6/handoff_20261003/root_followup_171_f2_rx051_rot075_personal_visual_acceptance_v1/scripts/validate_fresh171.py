#!/usr/bin/env python3
"""Read-only validator for F6 fresh171 RX051 ROT075 visual evidence."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
FORBIDDEN=(".h5",".hdf5",".bi4",".csv",".dat",".vtk")
ALLOWED=(".json",".xml",".xmf",".png")
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def check_ref(x,kind=None):
 assert isinstance(x,dict) and 'path' in x and 'sha256' in x,x
 p=Path(x['path']);assert p.is_file(),p
 low=str(p).lower();assert not any(low.endswith(s) for s in FORBIDDEN),p
 assert p.suffix.lower() in ALLOWED,p
 assert sha(p)==x['sha256'],(p,'sha drift')
 assert p.stat().st_size==x['bytes'],(p,'size drift')
 if kind is not None:assert x.get('kind')==kind,(p,x.get('kind'),kind)
 return p
def receipt(x):
 p=check_ref(x,'metadata');d=json.loads(p.read_text())
 assert d.get('schema')=='ds02.execution-receipt.v1',(p,d.get('schema'))
 assert d.get('status')=='completed',(p,d.get('status'))
 assert d.get('returncode')==0,(p,d.get('returncode'))
 return d
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--package',type=Path,default=Path(__file__).parents[1]);pkg=ap.parse_args().package
 d=json.loads((pkg/'metadata/personal-visual-decision.json').read_text())
 assert d['schema']=='ds02.f6.fresh171.f2-personal-visual-review.v1'
 assert d['fresh_id']=='fresh171' and d['family_id']=='F6' and d['model']=='gpt-5.6-luna' and d['reasoning_effort']=='max'
 assert d['recursive_delegation'] is False
 pred=d['predecessor'];pp=Path(pred['path']);check_ref({'path':str(pp),'sha256':pred['sha256'],'bytes':pp.stat().st_size,'kind':'metadata'},'metadata')
 assert json.loads(pp.read_text()).get('fresh_id')=='fresh170' and pred['must_remain_unchanged'] is True
 c=d['case'];assert c['case_id'].endswith('ROT075_DP010_SPATIAL_REFERENCE_SAVE010');assert c['physical_case_id'].endswith('ROT075')
 assert c['canonical_source_physical_condition_sha256']=='d5717c7d2ca477473e0a4104e4358626e3b383b419eef5442541396d0a5a49a5'
 assert c['typed_legacy_and_actual_converter_scope_sha256']=='03875ff8541c6e0ebfb459e6061107e83663423d8aea9ad8cd446d4362040bd0'
 assert c['scope_roles']['equality_claimed'] is False and c['not_copied_from_fresh170'] is True
 dec=d['decision'];assert dec['status']=='visual-approved-by-delegated-agent' and dec['case_credit']==0 and dec['global_acceptance'] is False
 assert dec['main_process_qi']=='separate; not claimed by this package' and dec['precision_status']=='not accepted'
 assert dec['quantitative_review_required'] is True and dec['visual_zero_fluid_loss_claim'] is False
 assert dec['strict_container_guarantee'] is False and dec['root_qi_gate'].startswith('hold for Root1240 quantitative first-stage review')
 ev=d['evidence']
 for x in ev.values():check_ref(x,'metadata')
 for k in ('gencase_receipt','initial_qa_receipt','native_receipt','typed_receipt','xmf_receipt','render_receipt'):receipt(ev[k])
 qa=json.loads(Path(ev['initial_qa_report']['path']).read_text());assert qa.get('status')=='pass'
 manifest=json.loads(Path(ev['xmf_manifest']['path']).read_text());assert manifest['frames']==manifest['expected_frames']==401
 assert manifest['physical_condition_sha256']==c['typed_legacy_and_actual_converter_scope_sha256'];assert manifest['canonical_source_physical_condition_sha256']==c['canonical_source_physical_condition_sha256'];assert manifest['scope_equality_not_claimed'] is True;assert manifest['producer_scope_schema']=='legacy-owner-scope.v0'
 report=json.loads(Path(ev['render_report']['path']).read_text());assert report['frames']==report['source_frames']==401 and report['all_frames_rendered'] is True and report['actual_times_preserved_exactly'] is True and report['nonfinite_active_states']==0 and report['numerical_precision_status']=='not accepted'
 pub=json.loads(Path(ev['publish_receipt']['path']).read_text());assert pub['status']=='published_after_atomic_rename' and pub['source_h5_opened_or_hashed_by_wrapper'] is False
 life=d['lifecycle_and_render_metadata'];assert life['frames']==life['source_frames']==401 and life['final_missing_particles']==48 and life['maximum_missing_particles']==48 and life['transient_missing_frame_count']==264
 assert life['first_missing_frame']==137 and life['particle_frame_omission_events']==10182
 assert life['final_missing_id_sample_count']==8 and life['final_missing_ids_sample_not_complete'] is True
 assert life['fluid_missing_fraction_of_initial_fluid']=={'numerator':48,'denominator':21114,'percent':0.227337}
 assert life['final_missing_type_counts']=={'0':0,'1':0,'2':0,'3':48};assert life['final_missing_mk_counts']=={'1':17,'2':17,'3':14}
 vr=d['visual_review'];assert vr['personally_viewed_with']=='view_image' and vr['contact_sheet_count']==17 and len(vr['contact_sheets'])==17 and vr['key_frame_count']==9 and len(vr['key_frames'])==9
 assert d['visual_review']['observations']['quantitative_omission'].startswith('The producer metadata records nonzero fluid omission')
 assert d['visual_review']['observations']['container_claim_boundary'].startswith('The review does not claim zero fluid loss')
 for i,x in enumerate(vr['contact_sheets']):check_ref(x,'visualization');assert x['sheet_index']==i
 for x in vr['key_frames']:check_ref(x,'visualization');assert x['path'].endswith(f"frame_{x['frame']:04d}.png")
 sb=d['source_boundaries'];assert sb['science_payload_read'] is False and sb['science_payload_hashed'] is False and sb['science_jobs_started'] is False and sb['shared_registry_or_ledger_written'] is False
 assert d['future_work']['no_new_render_or_solver_request'] is True
 print('fresh171 validation PASS: F2 RX051 ROT075; 17 contacts + 9 keys viewed; completed/0 chain and published full401 verified; own missing stats retained; case credit 0')
if __name__=='__main__':main()
