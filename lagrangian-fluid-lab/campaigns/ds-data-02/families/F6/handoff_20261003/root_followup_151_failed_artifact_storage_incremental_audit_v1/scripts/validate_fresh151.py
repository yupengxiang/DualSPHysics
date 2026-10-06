#!/usr/bin/env python3
"""Validate fresh151 bounded metadata audit without touching scientific payloads."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN=(".h5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".pvd")
def digest(p):
 p=Path(p)
 if p.suffix.lower() in FORBIDDEN: raise AssertionError(f"scientific payload hash forbidden: {p}")
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def check_ref(x):
 p=Path(x['path']); assert p.exists(), p; assert x.get('exists') is True, p; assert digest(p)==x.get('sha256'), p
j=json.loads((ROOT/'metadata/audit-evidence.json').read_text())
s=json.loads((ROOT/'metadata/audit-summary.json').read_text())
assert j['schema'].startswith('ds-data-02.fresh151.')
assert s['status']=='pass_no_new_cleanup_candidate' and s['candidate_count']==0
assert j['read_policy']['scientific_payload_contents_opened'] is False
assert j['read_policy']['scientific_payloads_hashed'] is False
assert j['read_policy']['deletion_performed'] is False
for x in j['evidence_refs'].values(): check_ref(x)
assert len(j['historical_partial_files'])==2
for x in j['historical_partial_files']:
 assert x['exists_now'] is False and x['candidate_for_fresh151'] is False
f=j['new_post_fresh147_failure_review'][0]
check_ref(f['controller_result']); check_ref(f['controller_launch_process'])
assert f['launcher_returncode']==1 and f['actual_receipt_exists'] is False and f['attempt_root_exists'] is False
assert f['scientific_worker_started'] is False and f['partial_or_intermediate_candidate'] is False
r=j['root951_live_dependency']; assert r['pid']==4004579 and r['start_ticks']==207142232 and r['target_progress_hits']==0
assert r['fd_count']>=1
blob=json.dumps(j)
# Only metadata paths are stored; scientific suffixes must not be hashed or represented as evidence blobs.
for suffix in ('.h5', '.bi4', '.csv', '.dat', '.vtk', '.vtu', '.pvd'):
 assert suffix not in [str(x.get('path','')).lower() for x in j['evidence_refs'].values()]
out={'schema':'ds-data-02.fresh151.validator-result.v1','status':'pass','package':'fresh151','new_cleanup_candidates':0,'scientific_payload_contents_opened':False,'scientific_payloads_hashed':False}
(ROOT/'metadata/validation-result.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
print(json.dumps(out,sort_keys=True))
