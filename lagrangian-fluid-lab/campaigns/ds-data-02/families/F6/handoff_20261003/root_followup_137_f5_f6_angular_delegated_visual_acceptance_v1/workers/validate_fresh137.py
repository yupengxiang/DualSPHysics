#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
PKG=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def fail(msg): raise SystemExit('fresh137 validation FAILED: '+msg)
def req(cond,msg):
 if not cond: fail(msg)
def load(rel):
 p=PKG/rel; req(p.exists(),f'missing {p}'); return json.loads(p.read_text())
sel=load('metadata/selection-frozen.json'); vr=load('metadata/visual-review.json'); ch=load('metadata/chain-closure.json'); ph=load('metadata/png-hashes.json'); ev=load('metadata/evidence-files.json')
req(sel['schema']=='ds02.f6.fresh137.frozen-routing-selection.v1','selection schema')
req(sel['scientific_payload_read_or_hashed_by_reviewer'] is False,'selection payload flag')
req(sel['global_credit_updated_by_agent'] is False and sel['checkpoint_accepted_decisions_count']==205,'checkpoint/credit')
req(len(sel['selected_cases'])==3 and len(vr['cases'])==3,'three cases')
prior={x['package']:set(x['case_ids']) for x in sel.get('excluded_prior_packages', [])}
req('fresh136' in prior and not (prior['fresh136'] & set(x['case_id'] for x in sel['selected_cases'])),'fresh136 exclusion')
req(not any(k.lower().endswith(('.h5','.bi4','.csv','.dat','.vtk')) for k in [x['path'] for x in ev['files']]),'scientific evidence path')
for item in ev['files']:
 p=Path(item['path']); req(p.exists(), 'metadata evidence missing '+str(p)); req(sha(p)==item['sha256'], 'metadata evidence hash '+str(p))
bycase={x['case_id']:x for x in vr['cases']}
req(set(bycase)==set(ch['cases'])==set(ph['cases']),'case key closure')
for c in vr['cases']:
 cid=c['case_id']; r=c['render']; b=c['producer_boundaries']; s=c['scope_separation']
 req(c['status']=='visual-approved-by-delegated-agent' and c['case_credit']==0 and c['global_credit_updated_by_agent'] is False,cid+' status/credit')
 req(c['agent_personally_viewed_all_contact_sheets'] and c['agent_personally_viewed_all_key_frames'],cid+' view flags')
 req(r['frames']==r['source_frames'] and r['all_frames_rendered'] is True and r['actual_times_preserved_exactly'] is True,cid+' frame report')
 req(r['nonfinite_active_states']==0 and r['native_identity_axis_preserved'] is True and r['source_h5_read_only'] is True,cid+' integrity')
 req(r['diagnostic_only'] is False and r['independent_case_increment']==0,cid+' report class')
 req(r['numerical_precision_status'] in ('not accepted','not accepted for stage1 product; historical numerical evidence retained'),cid+' precision boundary')
 req(b['root951_completed_0'] and b['typed_completed_0'] and b['xmf_completed_0'],cid+' chain terminal')
 req(b['final_uid_not_inferred'] is True and b['production_approval']=='none' and b['q_n']=='not granted/not assessed' and b['q_e']=='not granted/not assessed',cid+' claim boundary')
 req(s['scope_equality_claim']=='none' and s['canonical_actual_source_plan_scopes_separate'] is True,cid+' scopes')
 req(len(ph['cases'][cid]['contact_sheets'])==r['contact_sheets'] and len(ph['cases'][cid]['key_frames'])==len(r['key_frames']),cid+' png count')
 for item in ph['cases'][cid]['contact_sheets']+ph['cases'][cid]['key_frames']:
  p=Path(item['path']); req(p.exists(),cid+' PNG missing '+str(p)); req(sha(p)==item['sha256'],cid+' PNG hash '+str(p))
 for stage,mp in c['producer_chain'].items():
  for label,pstr in mp.items():
   if label in {'status','returncode','launcher_returncode'}: continue
   p=Path(pstr); req(p.exists(),f'{cid} {stage} {label} missing')
 req(c['observations']['failure_screen'],cid+' observations')
# Check frozen route copies hash consistency.
rp=PKG/'metadata/routing/actual-progress.frozen.json'; cp=PKG/'metadata/routing/checkpoint-133.frozen.json'
req(sha(rp)==sel['route_snapshot_sha256'] and sha(cp)==sel['checkpoint_snapshot_sha256'],'frozen routing hashes')
print('fresh137 validation PASS: 3 cases, 83 contact/key PNGs, metadata chain closure, no scientific payload evidence, case_credit=0')
