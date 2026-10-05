from pathlib import Path
import subprocess,json
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003'
p=sorted((H/'root_stage1_f4_fresh092_percase_binding_root237_diagnostic_470').glob('*-initial-qa-request.json'))[0]
r=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(p)],text=True,capture_output=True)
result={'requested':1,'held_other_requests':23,'request':str(p),'launcher_returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
(Path(__file__).parent/'controller-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));raise SystemExit(r.returncode)
