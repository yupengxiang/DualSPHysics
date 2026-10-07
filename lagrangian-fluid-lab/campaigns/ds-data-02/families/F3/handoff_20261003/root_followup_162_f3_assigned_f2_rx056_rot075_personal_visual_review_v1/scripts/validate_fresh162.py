#!/usr/bin/env python3
"""Bounded metadata/PNG validator for F3-assigned F2 fresh162."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
FORBIDDEN=('.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtu','.pvtu')
CASE='F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT075_DP010_SPATIAL_REFERENCE_SAVE010'
PHYSICAL='F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT075'
def fail(m): raise SystemExit('fresh162 validation failed: '+m)
def load(rel):
 p=HERE/rel
 if not p.is_file(): fail('missing '+rel)
 try:return json.loads(p.read_text())
 except Exception as e:fail(f'invalid JSON {rel}: {e}')
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def walk(v):
 if isinstance(v,dict):
  for k,x in v.items():yield from walk(k);yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
 elif isinstance(v,str):yield v

def no_payload_paths(*objs):
 for obj in objs:
  for s in walk(obj):
   low=s.lower()
   if any(low.endswith(x) or x+'/' in low or x+'\\' in low for x in FORBIDDEN): fail('forbidden payload path in package metadata: '+s)
chain=load('metadata/chain-audit/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT075.json')
prov=load('metadata/source-review-provenance.json')
decision=load('metadata/visual-review/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT075-delegated-visual-decision.json')
png=load('metadata/png-hashes/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT075.json')
integrity=load('metadata/package-integrity.json')
no_payload_paths(chain,prov,decision,png)
for obj,label in [(chain,'chain'),(prov,'provenance'),(decision,'decision'),(png,'png')]:
 if obj.get('case_id')!=CASE:fail(label+' case identity')
 if obj.get('physical_case_id')!=PHYSICAL:fail(label+' physical identity')
if chain.get('assigned_family_id')!='F3' or prov.get('assigned_family_id')!='F3' or decision.get('assigned_family_id')!='F3':fail('assigned family')
if chain.get('actual_family_id')!='F2' or prov.get('actual_family_id')!='F2' or decision.get('actual_family_id')!='F2':fail('actual family')
if decision.get('status')!='visual-approved-by-delegated-agent':fail('visual status')
if decision.get('visual_reviewer')!='/root/production_recovery':fail('reviewer')
if decision.get('contact_sheets',{}).get('count')!=17 or decision.get('keyframes',{}).get('count')!=9:fail('review counts')
if chain.get('review',{}).get('contact_sheets')!=17 or chain.get('review',{}).get('keyframes')!=9:fail('chain counts')
if chain.get('review',{}).get('keyframe_indices')!=[0,50,100,150,200,250,300,350,400]:fail('keyframe indices')
ce=decision.get('chain_evidence',{})
if ce.get('render_frames')!=401 or ce.get('particles')!=418104:fail('actual dimensions')
if decision.get('limits',{}).get('case_credit')!=0 or decision.get('limits',{}).get('q_n_granted') or decision.get('limits',{}).get('q_e_granted'):fail('credit/qualification limits')
if chain.get('review_boundaries',{}).get('scientific_payload_opened_or_hashed_by_reviewer') is not False:fail('chain payload boundary')
if prov.get('read_boundary',{}).get('scientific_payload_opened_or_hashed') is not False:fail('provenance payload boundary')
if chain.get('lifecycle_omission_evidence',{}).get('final_missing_particles')!=40:fail('omission evidence')
if chain.get('lifecycle_omission_evidence',{}).get('unknown_missing_locations_states_and_causes') is not True:fail('omission unknown scope')
if chain.get('outer_request_envelope_discrepancy',{}).get('historical_outer_expected_frames')!=801 or chain.get('outer_request_envelope_discrepancy',{}).get('actual_chain_frames')!=401:fail('outer envelope')
for name,e in chain.get('actual_paths',{}).items():
 if not isinstance(e,dict):fail('bad ref '+name)
 p=Path(e['path'])
 if not p.is_file():fail('missing ref '+name+': '+str(p))
 if digest(p)!=e.get('sha256'):fail('metadata digest drift '+name)
entries=png.get('entries',[])
if len(entries)!=26:fail('PNG count')
contacts=sorted([e for e in entries if e.get('role')=='contact_sheet'],key=lambda e:e.get('contact_index',-1))
keys=sorted([e for e in entries if e.get('role')=='event_keyframe'],key=lambda e:e.get('frame_index',-1))
if [e.get('contact_index') for e in contacts]!=list(range(17)):fail('contact indices')
if [e.get('frame_index') for e in keys]!=[0,50,100,150,200,250,300,350,400]:fail('key indices')
for e in entries:
 if e.get('viewed') is not True or e.get('view_method')!='view_image':fail('PNG review flag')
 p=Path(e['path'])
 if p.suffix.lower()!='.png' or not p.is_file():fail('missing PNG '+str(p))
 if p.stat().st_size!=e.get('bytes') or digest(p)!=e.get('sha256'):fail('PNG digest drift '+str(p))
if integrity.get('package')!='fresh162':fail('package integrity identity')
listed={e['path']:e for e in integrity.get('files',[])}
actual={str(p.relative_to(HERE)):p for p in HERE.rglob('*') if p.is_file() and p.name!='package-integrity.json'}
if set(listed)!=set(actual):fail('package file set mismatch')
if integrity.get('file_count')!=len(actual):fail('package file count')
for rel,p in actual.items():
 e=listed[rel]
 if digest(p)!=e.get('sha256') or p.stat().st_size!=e.get('bytes'):fail('package digest drift '+rel)
print('fresh162 validation PASS: F3-assigned/F2 RX056 ROT075, 401-frame chain, 17 contacts, 9 keyframes, 26 PNG hashes, scope and omission boundaries closed')
