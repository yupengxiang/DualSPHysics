#!/usr/bin/env python3
"""Metadata/PNG-only verifier for fresh137; never opens BI4/H5/CSV/DAT/VTK science payloads."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
META=PKG/'metadata/fresh137-visual-review.json'
CASES=('F7_OBSTACLE_QUINTIC_B08_A035P5','F7_OBSTACLE_QUINTIC_B08_A036P5')
EXPECTED={'dimension':3,'total':70179,'fixed':27495,'moving':1984,'floating':0,'fluid':40700}
KEYS=(0,14,125,200,300,400,450,500,550,600)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
 return h.hexdigest()
def check(cond,msg):
 if not cond: raise AssertionError(msg)
d=json.loads(META.read_text())
check(d['schema']=='ds02.f5.fresh137.f7.visual-review-handoff.v1','schema')
check(d['source_only_package'] and d['no_jobs_started'] and d['no_science_payload_read_or_hashed'],'source safety')
check(d['controller']['requested']==24 and d['controller']['finished']==24 and d['controller']['completed0']==24 and d['controller']['pending_held']==0,'controller')
check(len(d['cases'])==2,'case count')
for c in d['cases']:
 check(c['case_id'] in CASES,'case id')
 check(len(c['visual_scope']['all_601_saved_frame_pngs'])==601,'frame inventory')
 check(len(c['visual_scope']['all_26_contact_sheets'])==26,'contact inventory')
 check(c['visual_scope']['reviewed_all_contact_sheets'] is True,'contact review')
 check(c['visual_scope']['reviewed_event_keyframes']==list(KEYS),'keyframes')
 check(c['actual_counts_and_solver']['dimension']==3 and c['actual_counts_and_solver']['total']==70179,'dimension/count')
 check(c['actual_counts_and_solver']['fixed']==27495 and c['actual_counts_and_solver']['moving']==1984 and c['actual_counts_and_solver']['floating']==0 and c['actual_counts_and_solver']['fluid']==40700,'counts')
 check(c['actual_render_metadata']['all_frame_metadata_checks']=={'missing_zero':True,'finite_positions':True,'finite_mass_velocity_density_pressure':True,'identity_axis_preserved':True,'expected_counts_match':True},'frame checks')
 check(c['scope_separation']['canonical_equals_source_plan_claim'] is False and c['scope_separation']['scopes_are_kept_distinct'] is True,'scope')
 check(c['qualification_status']['precision_status']=='not_accepted' and c['qualification_status']['q_n']=='not_granted' and c['qualification_status']['production_approval']=='none','qualification')
 for item in c['visual_scope']['all_601_saved_frame_pngs']+c['visual_scope']['all_26_contact_sheets']+c['visual_scope']['ten_event_keyframes']:
  p=Path(item['path']); check(p.exists(),f'missing PNG {p}'); check(sha(p)==item['sha256'],f'PNG SHA {p}')
 check(len(c['six_segment_motion_metadata']['segments_for_this_amplitude'])==6,'six segments')
 check(c['six_segment_motion_metadata']['native_sampled_regular']=='not C2','native C2')
 check(c['qualification_status']['case_credit_granted'] is False,'credit')
# Only metadata files are external inputs here; no science payload is opened by this verifier.
for x in d['external_metadata_inputs']:
 p=Path(x['path']); check(p.exists(),f'metadata input {p}'); check(p.suffix.lower() in {'.json','.xml','.md','.py'},f'unsafe metadata suffix {p}')
 check(sha(p)==x['sha256'],f'metadata SHA {p}')
print(json.dumps({'status':'passed','package':str(PKG),'cases':list(CASES),'frames_per_case':601,'contacts_per_case':26,'keyframes_per_case':10,'science_payload_opened':False},indent=2))
