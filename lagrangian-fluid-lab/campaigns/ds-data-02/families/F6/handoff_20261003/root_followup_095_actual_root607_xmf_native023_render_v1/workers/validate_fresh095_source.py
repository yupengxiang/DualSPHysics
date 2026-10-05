#!/usr/bin/env python3
from pathlib import Path
import ast, hashlib, json
PKG=Path(__file__).resolve().parents[1]
SCIENCE={'.h5','.bi4','.ibi4','.csv','.dat','.vtu','.vtk','.xmf'}
def science(p):
    s=str(p).lower(); return Path(s).suffix in SCIENCE or s.endswith('/run.out') or '/solver_output/' in s
def sha(p):
    p=Path(p); assert not science(p), p; return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):
    p=Path(p); assert not science(p), p; return json.loads(p.read_text())
def check_io(d,label):
    assert d['fresh_id']=='fresh095', label
    assert d['disabled'] is True and d['launch'] is False and d['execution_allowed'] is False, label
    assert d['future_hashes_null'] is True, label
    assert set(d['input_files'])==set(d['input_sha256']), label
    for p,v in d['input_sha256'].items():
        assert not science(p), (label,p); assert Path(p).is_file() and sha(p)==v, (label,p)
    for p,v in d.get('future_input_sha256',{}).items(): assert v is None, (label,p)
    for k,v in d.get('future_outputs',{}).items():
        if k.endswith('_sha256'): assert v is None, (label,k)
    assert d.get('worker_contract'), label
    worker=Path(d['worker']); assert worker.is_file() and sha(worker)==d['worker_sha256'], label
    ast.parse(worker.read_text())
    assert 'subprocess' not in worker.read_text() and 'os.system' not in worker.read_text(), label
    assert d['physical_condition_sha256'] is None or len(d['physical_condition_sha256'])==64, label
    assert len(d['source_canonical_physical_condition_sha256'])==64 and len(d['source_plan_condition_sha256'])==64, label
    assert d['state0_dependency']['status'] in ('actual_root582_state0_pass','actual_root595_state0_pass'), label
    s=d['state0_dependency']
    for k in ('audit_report','execution_receipt','summary'):
        assert Path(s[k]).is_file() and s[k+'_sha256']==sha(s[k]), (label,k)
    assert 'root582' not in json.dumps(s).lower() if s['status']=='actual_root595_state0_pass' else True
    t=d['typed_dependency']; assert t['producer_physical_condition_sha256'] is None or len(t['producer_physical_condition_sha256'])==64, label
    assert t['trajectory_h5_sha256'] is None, label
    assert d['worker_cli']==d['command'], label
xmf_req=sorted((PKG/'requests'/'xmf').glob('*.json')); render_req=sorted((PKG/'requests'/'render').glob('*.json'))
xmf_bind=sorted((PKG/'bindings'/'xmf').glob('*.json')); render_bind=sorted((PKG/'bindings'/'render').glob('*.json'))
assert len(xmf_req)==len(render_req)==len(xmf_bind)==len(render_bind)==24
cases=set(); actual=0; future=0
for f in xmf_req:
 d=load(f); check_io(d,str(f)); assert d['schema']=='ds02.runner-request.v2'; assert d['worker_contract']['binding_schema']=='ds02.f6.fresh095.xmf-binding.v1'; assert d['command'][-1]=='{attempt_root}/xdmf'; assert d['xmf_binding_sha256']==sha(d['xmf_binding']); assert d['input_sha256'][d['xmf_binding']]==d['xmf_binding_sha256']; cases.add(d['case_id']); actual += d['physical_condition_sha256'] is not None; future += d['physical_condition_sha256'] is None
for f in render_req:
 d=load(f); check_io(d,str(f)); assert d['schema']=='ds02.runner-request.v2'; assert d['worker_contract']['binding_schema']=='ds02.f6.fresh095.render-binding.v1'; assert d['command'][-1]=='{attempt_root}/render'; assert d['render_binding_sha256']==sha(d['render_binding']); assert d['input_sha256'][d['render_binding']]==d['render_binding_sha256']; assert d['camera_policy']['fixed_camera_override'] is False; assert d['camera_policy']['camera_bounds_in_manifest'] is False
for f in xmf_bind:
 d=load(f); assert d['schema']=='ds02.f6.fresh095.xmf-binding.v1' and d['disabled'] and not d['launch']; assert set(d['input_files'])==set(d['input_sha256']);
 for p,v in d['input_sha256'].items(): assert not science(p) and Path(p).is_file() and sha(p)==v,(str(f),p)
 assert d['worker_sha256']==sha(d['worker']); assert d['producer_scope_sha256']==d['physical_condition_sha256']; assert d['trajectory_h5_sha256'] is None
for f in render_bind:
 d=load(f); assert d['schema']=='ds02.f6.fresh095.render-binding.v1' and d['disabled'] and not d['launch']; assert set(d['input_files'])==set(d['input_sha256']);
 for p,v in d['input_sha256'].items(): assert not science(p) and Path(p).is_file() and sha(p)==v,(str(f),p)
 assert d['renderer_source']['sha256']==sha(d['renderer_source']['path']); assert d['trajectory_h5_sha256'] is None; assert d['camera_policy']['fixed_camera_override'] is False and d['camera_policy']['camera_bounds_in_manifest'] is False
assert len(cases)==24
print(json.dumps({'status':'pass','fresh_id':'fresh095','cases':24,'typed_scope_actual':actual,'typed_scope_future':future},indent=2))
