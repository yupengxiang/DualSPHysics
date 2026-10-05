#!/usr/bin/env python3
"""Root-only, exact two orphan CPU settlements; no solver, signal or converter."""
from pathlib import Path
import importlib.util,json,hashlib,os
ROOT=Path(__file__).resolve().parent
DATA=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
RUNTIME=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def mod(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
assert os.geteuid()==1001 and os.getegid()==1001,'actual qualified host owner jade 1001:1001 required'
review=json.loads((ROOT/'root-source-review.json').read_text());assert sha(ROOT/'reconcile_typed_conversion.py')==review['library_sha256']
assert sha(RUNTIME)=='5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60'
m=mod('root184_reconcile',ROOT/'reconcile_typed_conversion.py');rt=mod('root184_runtime',RUNTIME)
bs=json.loads((ROOT/'root-exact-bindings.json').read_text())
assert set(bs)=={'P03','AY0270'}
side=DATA/'runtime/root-orphan-conversion-reconciliation-184';side.mkdir(parents=True,exist_ok=True)
original_capture=m.capture_two_samples
current_role=None
def capture_and_preserve(*args,**kwargs):
 evidence=original_capture(*args,**kwargs)
 rt.atomic_json(side/(current_role.lower()+'-fresh-in-lock-double-proc-proof.json'),evidence)
 return evidence
m.capture_two_samples=capture_and_preserve
for role in ['P03','AY0270']:
 current_role=role;b=bs[role];b['runtime_v2_sha256']=sha(RUNTIME)
 # Exact unchanged historical receipt and reservation hashes are checked in library under lock.
 result=m.apply_reconciliation(runtime_module=rt,data_root=DATA,binding=b,evidence=None,sidecar_dir=side,tool_status=143,enable=True,authorization_token=m.AUTHORIZATION_TOKEN,probe_interval_seconds=1.0)
 result.update(role=role,source_sha256=sha(ROOT/'reconcile_typed_conversion.py'),root_review_sha256=sha(ROOT/'root-source-review.json'))
 rt.atomic_json(side/(role.lower()+'-settlement.json'),result)
 print(json.dumps({'role':role,'status':result['status'],'charged_cpu_core_seconds':result['charge']['cpu_core_seconds'],'child_returncode':result['charge']['child_returncode'],'os_exit_zero':result['charge']['os_exit_zero'],'transaction_id':result['transaction_id']}),flush=True)
