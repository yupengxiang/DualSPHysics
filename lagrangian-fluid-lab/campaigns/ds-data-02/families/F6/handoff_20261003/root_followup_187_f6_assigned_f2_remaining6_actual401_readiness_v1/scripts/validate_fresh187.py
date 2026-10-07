#!/usr/bin/env python3
"""Readonly validator for fresh187; metadata JSON/XML/XMF only."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
DATA=HERE/'metadata'/'f2-six-readiness.json'
MANIFEST=HERE/'manifest.json'
ALLOWED={'.json','.xml','.xmf'}
FORBIDDEN={'.h5','.bi4','.csv','.dat','.vtk','.vtu','.raw'}
EXPECTED=[
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX049_RY014_FILL080_ROT075',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT090',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX061_RY014_FILL080_ROT090',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT090',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT105',
]

def digest(p:Path):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def check_ref(r, missing=False):
 p=r.get('path')
 assert p, r
 pp=Path(p)
 assert pp.suffix.lower() in ALLOWED, p
 assert pp.suffix.lower() not in FORBIDDEN, p
 if r.get('exists',False):
  assert pp.exists(), p
  assert r.get('sha256')==digest(pp), p
 else:
  assert missing, ('unexpected missing ref',p)

def walk_forbidden(v):
 if isinstance(v,dict):
  for x in v.values(): walk_forbidden(x)
 elif isinstance(v,list):
  for x in v: walk_forbidden(x)
 elif isinstance(v,str):
  low=v.lower()
  # scientific payload paths are not allowed in this package; hashes are not paths.
  if any(s in low for s in ('trajectory.h5','/bi4','/csv/','_motion.dat','/vtk/','.vtu')):
   raise AssertionError('scientific payload path leaked: '+v)

data=json.loads(DATA.read_text()); package=json.loads(MANIFEST.read_text())
assert data['schema']=='ds02.f6.fresh187.f2-six-actual401-readiness.v1'
assert data['case_count']==6 and data['selected_pending_row_count']==6 and data['authoritative_index_pending_count'] >= 6
assert data['package_contract']['science_payload_IO'] is False
assert data['package_contract']['new_job'] is False
assert data['package_contract']['restart'] is False
assert data['package_contract']['case_credit']==0
assert [c['physical_case_id'] for c in data['cases']]==EXPECTED
check_ref(data['authoritative_index'])
for c in data['cases']:
 assert c['family_id']=='F2' and c['assigned_family']=='F6'
 assert c['status']=='original-render-registered-still-pending' and c['case_credit']==0
 e=c['expected']; assert e=={'frames':401,'particles':418104,'dimension':3,'contact_sheets':17,'physical_window_s':[0,4],'save_interval_s':0.01}
 n=c['native']; assert n['receipt_status']=='completed' and n['returncode']==0
 assert n['precision_status']=='not_accepted' and n['q_e'] is False
 check_ref(n['receipt'])
 g=c['gencase_initial_qa']; assert g['gencase_status']=='completed' and g['gencase_returncode']==0 and g['gencase_total_particles']==418104 and g['gencase_fluid_particles']==21114 and g['gencase_dimension']==3
 assert g['initial_qa_status']=='pass' and g['source_only_worker'] is False
 for k in ('gencase_receipt','generated_xml','initial_qa_receipt','initial_qa_report'): check_ref(g[k])
 t=c['typed']; assert t['conversion_status']=='completed' and t['frames']==401 and t['particles']==418104 and t['dimension']==3
 assert t['numeric_precision_status']=='not_accepted'
 for k in ('report','receipt'): check_ref(t[k])
 assert t['receipt_status']=='completed' and t['receipt_returncode']==0
 x=c['xmf_and_scopes']; assert x['producer_scope_schema']=='legacy-owner-scope.v0'; assert x['frames']==401 and x['full_saved_states'] is True
 assert x['source_plan_physical_condition_sha256']['present'] is False and x['source_plan_physical_condition_sha256']['value'] is None
 assert x['scope_equality_not_claimed'] is True and x['review_case_credit']==0 and x['review_omission_states_and_causes_unknown'] is True
 for k in ('manifest','xml','receipt','review_metadata'): check_ref(x[k])
 assert x['receipt_status']=='completed' and x['receipt_returncode']==0
 r=c['registered_render_readiness']; assert r['published'] is False and r['terminal_receipt'] is None and r['worker_phase']=='original-controller-live-awaiting-admission'
 for k in ('outer_request','loaded_wrapper','controller_launch'): check_ref(r[k])
 check_ref(r['pending_worker_receipt'],missing=True)
 assert r['live_probe']['expected_pid'] and r['live_probe']['expected_start_ticks']
 assert c['no_visual_or_scientific_claim']['visual_status']=='pending' and c['no_visual_or_scientific_claim']['case_credit']==0
 walk_forbidden(c)
print('fresh187 validation PASS: 6 F2 pending actual-401 rows; native/typed/XMF metadata closed; render receipt/publish remain null; no payload paths/jobs/credit')
