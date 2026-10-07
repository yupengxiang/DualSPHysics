#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

def fail(x): raise SystemExit('FAIL: '+x)
def walk(x):
 if isinstance(x,dict):
  for k,v in x.items(): yield k,v; yield from walk(v)
 elif isinstance(x,list):
  for v in x: yield from walk(v)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('audit',type=Path);a=ap.parse_args();d=json.loads(a.audit.read_text())
 if d.get('schema')!='ds02.f6.fresh209.f3-f4-f5.normalized-tuples-144.v1':fail('schema')
 if d.get('source_boundaries',{}).get('scientific_payloads_read_or_hashed') is not False:fail('payload boundary')
 rows=d.get('cases',{});
 if {k:len(v) for k,v in rows.items()}!={'F3':48,'F4':48,'F5':48}:fail('144 counts')
 if any(d.get('collision_groups',{}).get(k) for k in ['F3','F4','F5']):fail('normalized tuple collision')
 for fam,rs in rows.items():
  for r in rs:
   if r['actual_native']['status'] not in {'completed','running'}:fail(f"native runtime status {fam}/{r['physical_case_id']}")
   if r['actual_native']['status']=='completed' and r['actual_native']['returncode']!=0:fail(f"native terminal {fam}/{r['physical_case_id']}")
   if r['actual_native']['metadata_input_mismatch_count']!=0 and r['actual_native']['status']!='running':fail(f"launch-after metadata mismatch {fam}/{r['physical_case_id']}")
   if r['request_identity']['identity_status'] not in {'MATCH','REQUEST_PHYSICAL_ID_ABSENT','REQUEST_PHYSICAL_ID_ALIAS_DIFFERENT'}:fail(f"unknown physical identity role {fam}/{r['physical_case_id']}")
   if not r['source_evidence'] or any(x.get('exists') is not True for x in r['source_evidence']):fail(f"source evidence {fam}/{r['physical_case_id']}")
   for key,val in r.get('normalized_tuple',{}).items():
    if isinstance(val,str) and any(t in val.lower() for t in ['resolution','/home/','time_window']):fail(f"forbidden tuple value {fam}/{r['physical_case_id']}")
 # F3 endpoint correction must be actual producer join, not stale request role.
 endpoints={r['physical_case_id']:r for r in rows['F3'] if r['physical_case_id'] in {'F3_TWOAXIS_PITCH1000_AY0250_VISUAL_DOMAIN','F3_TWOAXIS_PITCH1000_AY0750_VISUAL_DOMAIN'}}
 if any(endpoints[p]['status']!='PASS_ACTUAL_FORCING_JOIN' for p in endpoints):fail('F3 endpoint forcing correction')
 if endpoints['F3_TWOAXIS_PITCH1000_AY0250_VISUAL_DOMAIN']['normalized_tuple']['transverse_amplitude_m_s2']!=.25:fail('F3 lower actual forcing')
 if endpoints['F3_TWOAXIS_PITCH1000_AY0750_VISUAL_DOMAIN']['normalized_tuple']['transverse_amplitude_m_s2']!=.75:fail('F3 upper actual forcing')
 print(json.dumps({'schema':d['schema'],'status':'PASS','counts':{k:len(v) for k,v in rows.items()},'collision_groups':d['collision_groups'],'uncertain_rows':d['summary']},sort_keys=True))
if __name__=='__main__':main()
