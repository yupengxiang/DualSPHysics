import sys,json,hashlib
from pathlib import Path
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
sys.path[:0]=[str(R/'lagrangian-fluid-lab/scripts'),str(H/'root_stage1_f3_first24_eight_solver_resource_policy_134'),str(Path(__file__).parent)]
import ds_data02_runtime_v2 as runtime
import ds_data02_strict_dispatch_v1 as strict
import ds02_root_all_idle_gpu_policy_v2 as gpu_policy
import root_native_home_floor_inventory_policy as home_policy
q=json.loads(Path(sys.argv[1]).read_text());assert q['launch_owner']=='root' and q['kind'] in {'qualification','production'}
assert hashlib.sha256(Path(home_policy.__file__).read_bytes()).hexdigest()==q['root_inventory_policy_source_sha256']
with gpu_policy.install(runtime,q) as ge, home_policy.install(runtime,q) as he:r=strict.run_request(Path(sys.argv[1]))
print(json.dumps({**{k:r.get(k) for k in ('status','returncode','error','output_root')},'actual_inventory_policy':he,'actual_gpu_policy':ge}))
raise SystemExit(0 if r.get('status')=='completed' else 1)
