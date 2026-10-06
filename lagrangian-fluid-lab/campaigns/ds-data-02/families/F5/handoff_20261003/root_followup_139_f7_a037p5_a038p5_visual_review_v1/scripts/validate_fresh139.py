#!/usr/bin/env python3
"""Metadata/PNG-only verifier for fresh139; never opens BI4/H5/CSV/DAT/VTK science payloads."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]; META=PKG/'metadata/fresh139-visual-review.json'; CASES=('F7_OBSTACLE_QUINTIC_B08_A037P5','F7_OBSTACLE_QUINTIC_B08_A038P5'); EXPECTED={'dimension':3,'total':70179,'fixed':27495,'moving':1984,'floating':0,'fluid':40700}; KEYS=(0,14,125,200,300,400,450,500,550,600); SAFE_META_SUFFIXES={'.json','.xml','.md','.py'}
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def check(c,m):
 if not c: raise AssertionError(m)
d=json.loads(META.read_text()); check(d['schema']=='ds02.f5.fresh139.f7.visual-review-handoff.v1','schema'); check(d['source_only_package'] and d['no_jobs_started'] and d['no_science_payload_read_or_hashed'],'source safety'); check(d['controller']['requested']==24 and d['controller']['finished']==24 and d['controller']['completed0']==24 and d['controller']['pending_held']==0,'controller'); check(len(d['cases'])==2,'case count'); seen=set()
for c in d['cases']:
 check(c['case_id'] in CASES,'case id'); check(c['case_id'] not in seen,'duplicate case'); seen.add(c['case_id']); v=c['visual_scope']; check(len(v['all_601_saved_frame_pngs'])==601,'frame inventory'); check(len(v['all_26_contact_sheets'])==26,'contact inventory'); check(v['reviewed_all_contact_sheets'] is True,'contact review'); check(v['reviewed_event_keyframes']==list(KEYS),'keyframes'); check(v['actual_times_preserved_exactly'] is True and v['native_identity_axis_preserved'] is True,'render preservation'); check(c['actual_counts_and_solver']['dimension']==3 and c['actual_counts_and_solver']['total']==70179,'dimension/count'); check(c['actual_counts_and_solver']['fixed']==27495 and c['actual_counts_and_solver']['moving']==1984 and c['actual_counts_and_solver']['floating']==0 and c['actual_counts_and_solver']['fluid']==40700,'counts'); check(c['actual_render_metadata']['frames']==601 and c['actual_render_metadata']['source_frames']==601,'render frame count'); check(c['actual_render_metadata']['all_frame_metadata_checks']=={'missing_zero':True,'finite_positions':True,'finite_mass_velocity_density_pressure':True,'identity_axis_preserved':True,'expected_counts_match':True},'frame checks'); check(c['scope_separation']['canonical_equals_source_plan_claim'] is False and c['scope_separation']['scopes_are_kept_distinct'] is True,'scope'); check(c['qualification_status']['precision_status']=='not_accepted' and c['qualification_status']['q_n']=='not_granted' and c['qualification_status']['production_approval']=='none','qualification'); check(c['qualification_status']['case_credit_granted'] is False and c['qualification_status']['independent_case_count_increment']==0,'credit'); check(len(c['six_segment_motion_metadata']['segments_for_this_amplitude'])==6,'six segments'); check(c['six_segment_motion_metadata']['native_sampled_regular']=='not C2','native C2');
 for item in v['all_601_saved_frame_pngs']+v['all_26_contact_sheets']+v['ten_event_keyframes']:
  p=Path(item['path']); check(p.exists(),f'missing PNG {p}'); check(p.suffix.lower()=='.png',f'not PNG {p}'); check(sha(p)==item['sha256'],f'PNG SHA {p}')
for item in d['external_metadata_inputs']:
 p=Path(item['path']); check(p.exists(),f'metadata input {p}'); check(p.suffix.lower() in SAFE_META_SUFFIXES,f'unsafe metadata suffix {p}'); check(sha(p)==item['sha256'],f'metadata SHA {p}')
print(json.dumps({'status':'passed','package':str(PKG),'cases':list(CASES),'frames_per_case':601,'contacts_per_case':26,'keyframes_per_case':10,'science_payload_opened':False},indent=2))
