import hashlib,json
from pathlib import Path
ROOT=Path(__file__).parents[1]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((ROOT/'floatinginfo/state0-binding.json').read_text())
r=json.loads((ROOT/'floatinginfo/state0-request.json').read_text())
m=json.loads((ROOT/'manifest.json').read_text())
assert b['schema']=='ds02.f6.stage1-omega-internal-floatinginfo-state0-binding.v3'
assert r['launch_allowed'] is False and r['execution_allowed'] is False
assert len(b['cases'])==5 and len(r['input_sha256'])>=len(r['input_files'])
for c in b['cases']:
 assert c['solver_status']=='completed' and c['solver_returncode']==0 and c['solver_tool_closed'] is True
 assert c['solver_receipt_sha256']==sha(Path(c['solver_receipt']))
 assert c['root146_request_sha256']==sha(Path(c['root146_request']))
 assert c['state0_audit_sha256'] is None
 assert c['typed_future']['typed_receipt_sha256'] is None
assert m['actual_native_case_count']==5 and m['future_hashes_null'] is True
assert r['future_outputs']['execution_receipt_sha256'] is None
assert r['future_outputs']['summary_sha256'] is None
print('fresh075 contract: PASS')
