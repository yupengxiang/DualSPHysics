import json,sys
from pathlib import Path
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
sys.path.insert(0,str(R/'lagrangian-fluid-lab/scripts'))
import ds_data02_strict_dispatch_v1 as strict
r=strict.run_request(Path(sys.argv[1]))
print(json.dumps({k:r.get(k) for k in ('status','returncode','error','attempt_id')}))
raise SystemExit(0 if r['status']=='completed' else 1)
