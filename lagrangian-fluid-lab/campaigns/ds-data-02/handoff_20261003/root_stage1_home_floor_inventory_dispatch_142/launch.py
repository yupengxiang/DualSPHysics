import sys,json
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parent),'/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts']
import ds_data02_runtime_v2 as runtime
import ds_data02_strict_dispatch_v1 as strict
import root_home_floor_inventory_policy as policy

q=json.loads(Path(sys.argv[1]).read_text())
with policy.install(runtime,q) as evidence:r=strict.run_request(Path(sys.argv[1]))
print(json.dumps({'status':r.get('status'),'returncode':r.get('returncode'),'error':r.get('error'),'output_root':r.get('output_root'),'actual_inventory_policy':evidence}))
raise SystemExit(0 if r.get('status')=='completed' else 1)
