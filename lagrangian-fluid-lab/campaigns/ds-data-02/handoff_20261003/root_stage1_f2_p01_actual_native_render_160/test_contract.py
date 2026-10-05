import hashlib,json
from pathlib import Path
root=Path(__file__).parent
req=json.loads(next((root/'request').glob('*.json')).read_text())
assert req['schema']=='ds02.root160.f2.p01.actual-render-only.v1'
assert req['launch_allowed'] is False and req['execution_allowed'] is False
assert req['actual_normal_xmf_prerequisite']['status']=='completed'
assert req['actual_normal_xmf_prerequisite']['returncode']==0
assert req['actual_normal_xmf_prerequisite']['frames']==401
assert req['actual_normal_xmf_prerequisite']['particles']==418104
assert req['native_bounds_contract']['fixed_camera_bounds_forbidden'] is True
assert req['native_bounds_contract']['all_saved_frames']==401
assert req['renderer_contract']['contact_pages']==17
for key in ('execution_receipt','manifest','xdmf'):
 p=Path(req['actual_normal_xmf_prerequisite'][key]); assert p.is_file(), p
 h=hashlib.sha256(p.read_bytes()).hexdigest()
 assert h==req['actual_normal_xmf_prerequisite'][key+'_sha256'], (p,h)
for k,v in req['future_outputs'].items():
 if k.endswith('_sha256'): assert v is None, (k,v)
print('root160 contract: PASS')
