#!/usr/bin/env python3
"""Validate frozen fresh156 wait evidence without opening scientific payloads."""
from __future__ import annotations
import hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]

def fail(m): raise AssertionError(m)
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p):
    h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest()
def walk(v):
    if isinstance(v,dict):
        for k,x in v.items(): yield from walk(k); yield from walk(x)
    elif isinstance(v,list):
        for x in v: yield from walk(x)
    elif isinstance(v,str): yield v

def main():
    s=load(ROOT/'metadata/f2-render-wait-status.json'); r=load(ROOT/'metadata/root951-last-f6-wait.json')
    if s['schema']!='ds02.f6.fresh156.render-wait-audit.v1': fail('status schema')
    if s['root_checkpoint']['checkpoint']!=174 or s['root_checkpoint']['accepted_per_family']['F2']!=29: fail('checkpoint snapshot')
    rows=s['priority_render_observations']
    if {x['registration_id'] for x in rows[:5]} != {'1063','1064','1065','1097','1098'}: fail('priority registrations')
    for x in rows:
        if x['status']!='registered_live_no_terminal_receipt' or x['controller_result_present'] or x['execution_receipt_present'] or x['visual_review_eligible']: fail('live row marked terminal')
    if s['visual_review']['attempted'] or s['visual_review']['case_credit']!=0: fail('visual/credit claim')
    if s['next_visual_candidate']['registration_id']!='1063': fail('next candidate')
    if r['requested']!=37 or r['result_count']!=36 or r['f6_completed_results']!=22 or r['unresolved_case']['case_id']!='F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025' or r['unresolved_case']['actual_receipt'] is not None: fail('Root951 wait evidence')
    if r['child_processes_observed']!=0 or r['case_credit']!=0: fail('Root951 process/credit policy')
    for v in list(walk(s))+list(walk(r)):
        if v.lower().endswith(('.h5','.bi4','.csv','.dat','.vtk')): fail('science payload path')
    expected={'scientific_payloads_read_or_hashed':False,'jobs_started':False,'shared_state_modified':False,'global_credit_added':False,'case_credit':0}
    if s['policy']!=expected: fail('policy')
    print(json.dumps({'status':'PASS','schema':s['schema'],'priority_live_count':6,'view_image_calls':0,'root951_unresolved_case':r['unresolved_case']['case_id']},indent=2))

if __name__=='__main__':
    try: main()
    except (AssertionError,KeyError,json.JSONDecodeError,OSError) as e:
        print('fresh156 validation FAILED:',e,file=sys.stderr); raise SystemExit(1)
