#!/usr/bin/env python3
"""Validate fresh153 metadata-only storage audit without opening science payloads."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PKG=Path(__file__).resolve().parents[1]
META=PKG/'metadata/storage-bound-audit.json'
MANIFEST=PKG/'manifest.json'
SCIENCE_SUFFIXES={'.bi4','.obi4','.ibi4','.h5','.csv','.dat','.vtk','.npy','.npz'}
EXPECTED={
 'F2_401x418104':(401,418104),
 'F3_836x179208':(836,179208),
 'F5_801x194427':(801,194427),
}

def sha(path:Path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()

def check(cond,msg):
 if not cond: raise AssertionError(msg)

def walk_science_hashes(obj,where=''):
 if isinstance(obj,dict):
  for k,v in obj.items():
   if where.startswith('science_paths_stat_only') and ('sha' in k.lower()):
    raise AssertionError(f'science stat section contains hash field: {where}.{k}')
   walk_science_hashes(v,f'{where}.{k}' if where else k)
 elif isinstance(obj,list):
  for i,v in enumerate(obj): walk_science_hashes(v,f'{where}[{i}]')

d=json.loads(META.read_text())
check(d['schema']=='ds02.f5.fresh153.typed-storage-bound-audit.v1','schema')
check(d['source_only_package'] is True and d['no_jobs_started'] is True and d['no_requests_receipts_or_shared_state_modified'] is True,'source safety')
check(d['science_payload_policy']=={'opened':False,'hashed':False,'copied':False,'science_paths_representation':'stat-only; producer JSON attestations are not recomputed'},'science policy')
walk_science_hashes(d)
check(set(d['representatives'])==set(EXPECTED),'representative set')
for name,(frames,particles) in EXPECTED.items():
 r=d['representatives'][name]
 check(r['report']['conversion_status']=='completed','conversion status '+name)
 check((r['report']['frames'],r['report']['particles'])==(frames,particles),'shape '+name)
 check(r['science_paths_stat_only']['output_hdf5']['exists'] is True,'H5 stat '+name)
 check(isinstance(r['science_paths_stat_only']['output_hdf5']['bytes'],int),'H5 bytes '+name)
 check(r['logical_h5_uncompressed_bytes']==40*frames*particles+8*frames+13*particles,'logical bound '+name)
 check(r['observed_h5_ratio_is_not_a_reservation_basis'] is True,'compression boundary '+name)
 for item in r['report']['partvtk']['csv_stats']:
  check('stat' in item and 'sha256' not in item['stat'],'CSV stat-only '+name)
  check(isinstance(item['stat'].get('exists'),bool),'CSV stat exists '+name)
for group in d['source_evidence'].values():
 p=Path(group['path']); check(p.exists() and p.suffix.lower() not in SCIENCE_SUFFIXES,'source path')
 check(sha(p)==group['sha256'],'source SHA '+str(p))
 lines=p.read_text().splitlines()
 for ex in group['excerpts']:
  check(lines[ex['start']-1:ex['end']]==ex['lines'],'source excerpt '+str(p))
controller=d['controller_metadata_inputs']['root854_controller_contract']['selected']
check(controller['estimated_Home_output_gib']==32 and controller['extra_space_wait_margin_gib']==16 and controller['Home_floor_gib']==500,'Root854 contract')
typed=d['controller_metadata_inputs']['root854_typed_request_selected_fields']['selected']
check(typed['cpu_task_kind']=='conversion' and typed['estimated_storage_bytes']==32*1024**3 and typed['staging_limit_bytes']==24*1024**3,'typed request')
xmf=d['controller_metadata_inputs']['root877_xmf_request_selected_fields']['selected']
check(xmf['cpu_task_kind']=='audit' and xmf['estimated_storage_bytes']==1024**3,'XMF successor metadata')
cap=d['capacity_model']
check(cap['home_floor_bytes']==500*1024**3 and cap['typed_controller_estimated_output_bytes']==32*1024**3,'capacity floor')
check(cap['nvme_staging_limit_bytes']==24*1024**3 and cap['nvme_staging_free_reserve_bytes']==100*1024**3,'NVMe bound')
check(cap['current_home_free_over_floor_bytes']<cap['typed_controller_estimated_output_bytes'],'typed blocked at captured snapshot')
check(d['successor_plan']['status'].startswith('metadata_only'),'successor safety')
check(d['successor_plan']['preserve_existing_request_and_receipt_bytes'] is True and d['successor_plan']['preserve_global_conversion_concurrency_guard'] is True,'successor preservation')
manifest=json.loads(MANIFEST.read_text())
check(manifest['manifest_excludes']==['metadata/fresh153-validator-report.json','manifest.json'],'manifest excludes')
for rel,expected in manifest['files'].items():
 p=PKG/rel; check(p.exists() and p.suffix.lower() not in SCIENCE_SUFFIXES,'package file '+str(p)); check(sha(p)==expected,'package SHA '+rel)
print(json.dumps({'status':'passed','package':str(PKG),'representatives':list(EXPECTED),'science_payload_opened':False,'science_paths_hashed':False,'metadata_only_successor':True},indent=2))
