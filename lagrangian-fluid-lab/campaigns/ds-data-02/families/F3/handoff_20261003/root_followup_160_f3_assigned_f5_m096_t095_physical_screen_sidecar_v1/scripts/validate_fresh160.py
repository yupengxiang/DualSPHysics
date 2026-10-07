#!/usr/bin/env python3
"""Validate fresh160 sidecar bindings without scientific-payload IO."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN=(".h5",".hdf5",".bi4",".csv",".dat",".vtk",".vtu",".pvtu")
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def walk(v):
 if isinstance(v,dict):
  for x in v.values(): yield from walk(x)
 elif isinstance(v,list):
  for x in v: yield from walk(x)
 elif isinstance(v,str): yield v
def main():
 d=json.loads((ROOT/'metadata/f5-m096-t095-physical-screen-sidecar.json').read_text())
 if d['source_fresh159']['commit']!='ad50960f6aa1043e3b8de35be744a7366cf9b876': raise AssertionError('fresh159 commit')
 for k in ('decision_path','png_evidence_path','chain_path'):
  p=Path(d['source_fresh159'][k])
  if not p.exists() or sha(p)!=d['source_fresh159'][k.replace('_path','_sha256')]: raise AssertionError(k)
 if d['source_fresh159']['original_package_modified']: raise AssertionError('old package modified')
 if d['main_qi_binding']['sha256']!='a970931f677c9cfcf967483dfa3f5ab8fc9e756fba997621dbfed307f351d05f': raise AssertionError('QI binding')
 e=d['png_evidence_binding']['entries']
 if len(e)!=43 or sum(x['role']=='contact_sheet' for x in e)!=34 or sum(x['role']=='event_keyframe' for x in e)!=9: raise AssertionError('PNG count')
 for x in e:
  p=Path(x['path'])
  if p.suffix.lower()!='.png' or not p.exists() or p.stat().st_size!=x['bytes'] or sha(p)!=x['sha256'] or not x['viewed'] or x['view_method']!='view_image': raise AssertionError(f'PNG {p}')
 if d['role_corrections_from_fresh159']['actual_qi_proof_sha256']['fresh159_value']=='a970931f677c9cfcf967483dfa3f5ab8fc9e756fba997621dbfed307f351d05f': raise AssertionError('placeholder correction lost')
 roles=d['role_corrections_from_fresh159']['source_def_vs_generated_xml']
 gen=Path(roles['generated_xml_path']); src=Path(roles['true_source_def_path'])
 if not gen.exists() or gen.suffix.lower()!='.xml' or sha(gen)!=roles['generated_xml_sha256']: raise AssertionError('generated XML role path/hash')
 if not src.exists() or src.suffix.lower()!='.xml' or sha(src)!=roles['true_source_def_sha256']: raise AssertionError('true SourceDef role path/hash')
 for s in walk(d):
  if any(s.lower().endswith(x) for x in FORBIDDEN): raise AssertionError(f'payload path {s}')
 if any(d['non_claims'].values()):
  # all non_claims are intentionally false; any true value is a violation.
  raise AssertionError('non-claim boundary')
 print('fresh160 validation PASS: 43 PNG bindings, Root1257 SHA correction, role-aware physical screen')
if __name__=='__main__': main()
