import json,sys
from pathlib import Path
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
sys.path.insert(0,str(R/'lagrangian-fluid-lab/scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ds_data02_stage1_dispatch_f1 as d
r=d.run_request(Path(sys.argv[1]))
print(json.dumps({k:r.get(k) for k in ('status','returncode','error')}),flush=True)
raise SystemExit(0 if r['status']=='completed' else 1)
