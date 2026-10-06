#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN=('.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtu','.npy','.npz')
def load(name):return json.loads((ROOT/'metadata'/name).read_text())
def walk(x):
 if isinstance(x,dict):
  for k,v in x.items(): yield from walk(k); yield from walk(v)
 elif isinstance(x,list):
  for v in x: yield from walk(v)
 elif isinstance(x,str): yield x
closure=load('f2-native-actual-json-closure.json')
census=load('f2-render-priority-census.json')
ref=load('frozen-root1205-reference.json')
rows=closure['rows']; summary=closure['summary']
assert len(rows)==13 and len({x['physical_case_id'] for x in rows})==13 and len({x['case_id'] for x in rows})==13
assert summary['native_receipt_count']==10
assert summary['actual_completed_receipt_count']==28
assert summary['conversion_report_count']==10
assert summary['native_rows_without_accepted_chain_receipt']==[
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT090',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT105',
]
assert set(summary['native_condition_mismatch_to_accepted_semantic'])=={
 'F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX046_RY014_FILL080_ROT120',
 'F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX048_RY014_FILL080_ROT065',
 'F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX048_RY014_FILL080_ROT120',
 'F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX052_RY014_FILL080_ROT065',
}
assert set(summary['native_condition_match_to_accepted_semantic'])=={
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX049_RY014_FILL080_ROT090',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX049_RY014_FILL080_ROT105',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT075',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT105',
 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT105',
}
assert summary['native_rows_with_true_condition_absence']==1
assert summary['native_physical_binding_present_count']==0
assert summary['conversion_solver_receipt_count']==10
for row in rows:
 a=row['accepted_decision']; assert a['declared_sha256']==a['actual_json_sha256']
 for kind in ('native_receipt_declarations','actual_completed_receipt_declarations'):
  for rec in row[kind]:
   assert rec['exists'] is True
   assert rec['declared_sha256']==rec['actual_json_sha256']
   assert rec['status']=='completed' and rec['returncode']==0
   ident=rec['request_identity']; assert ident['case_id']['present'] is True
   if kind=='native_receipt_declarations':
    assert ident['physical_case_id']['present'] is True
    assert ident['physical_binding']['present'] is False
 for conv in row['conversion_report_declarations']:
  assert conv['exists'] is True
  assert conv['declared_sha256']==conv['actual_json_sha256']
  assert conv['conversion_metadata']['conversion_status']=='completed'
  sp=conv['source_provenance_solver_receipt']; assert sp.get('path') and sp['exists'] is True
  assert sp['declared_sha256']==sp['actual_json_sha256']
assert ref['root1205_index_counts']['f2_cases']==48 and ref['f2_counts']=={'accepted':32,'native_scope_unresolved':13}
assert census['reports_scanned']==35 and census['new_unreviewed_completed_published_count']==0
assert census['only_existing_unaccepted_published_case']['review_repeated_in_fresh167'] is False
assert census['last_original951_f6']['terminal_receipt'] is None
for s in walk({'closure':closure,'census':census,'ref':ref}):
 assert not any(ext in s.lower() for ext in FORBIDDEN), s
print('fresh167 validator PASS: 13 accepted F2 chains followed; 10 native receipts and 10 conversion source_provenance.solver_receipts verified; actual hashes/aliases/true absences preserved; no new visual candidate or scientific payload reference')
