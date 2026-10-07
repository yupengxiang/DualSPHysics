#!/usr/bin/env python3
"""Read-only validator for fresh186; never opens scientific payloads."""
from pathlib import Path
import hashlib, json, sys

HERE=Path(__file__).resolve().parents[1]
M=json.loads((HERE/'manifest.json').read_text())

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def check(cond,msg):
    if not cond: raise SystemExit('FAIL: '+msg)

check(M['schema']=='ds02.f6.delegated-visual-review.v1','schema')
check(M['package_id']=='fresh186','package')
check(M['assigned_family']=='F6' and M['actual_family']=='F3','family roles')
check(M['decision']=='visual-approved-by-delegated-agent','decision')
check(M['case_credit']==0 and M['q_n_granted'] is False and M['q_e_granted'] is False,'credit/Q flags')
check(M['payload_policy']['scientific_payloads_opened_or_hashed'] is False,'payload policy')
vr=M['visual_review']
contacts=vr['contact_sheets']; keys=vr['key_frames']
check(len(contacts)==35 and [x['index'] for x in contacts]==list(range(35)),'contact count/index')
check(len(keys)==9 and [x['frame'] for x in keys]==[0,100,200,300,400,500,600,700,835],'key frames')
for item in contacts+keys:
    p=Path(item['path'])
    check(p.is_file(),'missing PNG '+str(p))
    check(p.suffix.lower()=='.png','non-PNG visual ref')
    check(item['viewed'] is True,'unviewed PNG '+str(p))
    actual=sha(p)
    check(actual==item['sha256'],'PNG SHA mismatch '+str(p))
    check(item['publish_receipt_sha256']==actual,'publish SHA mismatch '+str(p))
    check(item['publish_receipt_bytes']==item['bytes'],'publish byte mismatch '+str(p))
for name,r in M['producer_chain'].items():
    if not isinstance(r,dict) or 'path' not in r: continue
    p=Path(r['path'])
    check(p.is_file(),'missing evidence '+name+': '+str(p))
    check(p.suffix.lower() in {'.json','.xml','.xmf','.py','.txt','.log'},'forbidden evidence extension '+str(p))
    if r.get('sha256') and len(r['sha256'])==64: check(sha(p)==r['sha256'],'evidence SHA mismatch '+name)
check(M['actual_metadata']['frames']==836,'frame count')
check(M['actual_metadata']['native_particles']==179208,'native count')
check(M['actual_metadata']['fluid_particles']==67500,'fluid count')
check(M['actual_metadata']['fixed_particles']==111708,'fixed count')
check(M['actual_metadata']['moving_particles']==0 and M['actual_metadata']['floating_particles']==0,'type counts')
check(M['actual_metadata']['dimension']==3,'dimension')
sc=M['scope_roles']
check(sc['native_source_plan_condition_sha256']['present'] is False and sc['native_source_plan_physical_condition_sha256']['present'] is False,'native absent plan fields')
check(sc['xmf_source_plan_condition_sha256']['present'] is True and sc['xmf_source_plan_condition_sha256']['value']=='e61cb7352047037b91f4be0cd22379375980b5b51592a8e516608ea2d3b27aa9','XMF source plan')
check(sc['xmf_source_plan_physical_condition_sha256']['present'] is False and sc['xmf_source_plan_physical_condition_sha256']['value'] is None,'XMF physical plan absence')
print('fresh186 validation PASS: 35 contact sheets + 9 key frames viewed and SHA-closed; F3 actual metadata/QI/scope roles closed; no scientific payload references opened or hashed; credit/Q-N/Q-E remain false/zero')
