import hashlib,json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
ENDPOINTS=['F4_DROP_ENDPOINT_GAP0p18000_DP010','F4_DROP_ENDPOINT_GAP0p26000_DP010']
EXPECTED={ENDPOINTS[0]:('F4_DROP_B08_gap0p18000_xoff0p00000_yoff0p00000_uz0p50000','773e18d598ef3452bdf1721ed894a0a90af22d37b3d3dada9fd7bada9e15de56'),ENDPOINTS[1]:('F4_DROP_B08_gap0p26000_xoff0p00000_yoff0p00000_uz0p50000','b625efb4404dfa63055fae940f7a078a6ecf94dfb323d7ce71ccb4812aa75412')}
S24=24*1024**3; F100=100*1024**3
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(p.read_text())
def test_fresh064_contract():
 helper=load(PKG/'helper-binding.json'); sem=load(PKG/'semantic-binding.json'); source=load(PKG/'source-input-binding.json')
 assert helper['wrapper']['path'].endswith('ds_data02_nvme_convert_v1.py') and helper['scientific_reader']['path'].endswith('ds_data02_direct_convert.py')
 assert helper['protocol']['nvme_free_floor_bytes']==F100 and helper['protocol']['staging_peak_limit_bytes']==S24
 assert sem['conversion_contract']['expected_frames']==1201 and sem['conversion_contract']['official_partvtk_frames']==[0,600,1200]
 assert len(sem['endpoints'])==2 and source['family_id']=='F4'
 seen=set()
 for x in sem['endpoints']:
  eid=x['endpoint_id']; assert eid in ENDPOINTS and eid not in seen; seen.add(eid); cid,ch=EXPECTED[eid]
  owner_path=Path(x['canonical_physical_owner']['owner_path']); owner=load(owner_path)
  assert owner['schema']=='ds02.f4.direct-binding.v1' and owner['physical_case_id']==cid and owner['physical_binding_sha256']==ch and owner['physical_binding']['physical_case_id']==cid
  assert owner['mother_full1201_owner']['time_variant']=='genuine_adaptive_halfstep_full1201'
  alias=x['historical_source_plan_alias']; assert alias['request_case_id']==eid and alias['request_physical_case_id']==eid and alias['request_physical_condition_sha256']!=ch
  req=load(PKG/'requests'/(eid+'-nvme-conversion-request.json'))
  assert req['launch'] is False and req['launch_allowed'] is False and req['kind']=='cpu' and req['cpu_task_kind']=='conversion'
  assert req['physical_case_id']==cid and req['physical_binding_sha256']==ch and req['conversion_scope']['native_frame_count']==1201
  assert req['storage_contract']['nvme_free_floor_bytes']==F100 and req['storage_contract']['staging_peak_limit_bytes']==S24
  assert '--staging-limit-bytes' in req['command'] and str(S24) in req['command'] and '--keep-validation-csv' in req['command']
  assert '-mdbc' not in req['command'] and '-tmax:1.2' not in req['command'] and '-tout:0.001' not in req['command']
  receipt=load(Path(req['native_solver_receipt'])); assert receipt['status']=='completed' and receipt['returncode']==0
  assert req['native_solver_receipt_sha256']==sha(Path(req['native_solver_receipt'])) and req['owner_metadata_sha256']==sha(owner_path)
  for raw in req['input_files']:
   p=Path(raw); assert p.is_file(),p; assert req['input_sha256'][raw]==sha(p),p
 assert seen==set(ENDPOINTS)
