import sys,json
from pathlib import Path
sys.path[:0]=['/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts','/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134']
import ds_data02_runtime_v2 as runtime
import ds_data02_strict_dispatch_v1 as strict
import ds02_root_all_idle_gpu_policy_v2 as policy
q=json.loads(Path(sys.argv[1]).read_text())
assert q['kind']=='qualification' and q['launch_owner']=='root'
with policy.install(runtime,q) as evidence:r=strict.run_request(Path(sys.argv[1]))
print(json.dumps({k:r.get(k) for k in ('status','returncode','error','output_root')}))
raise SystemExit(0 if r.get('status')=='completed' else 1)
