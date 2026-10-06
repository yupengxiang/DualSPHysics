from pathlib import Path
import json,runpy
O=Path(__file__).parent;cfg=json.loads((O/'controller-config.json').read_text());p=runpy.run_path(cfg['fair_dispatch'])['dispatch'](cfg['request']);result={'launcher_returncode':p.returncode,'stdout_tail':p.stdout[-40000:],'stderr_tail':p.stderr[-16384:],'case_credit':0};(O/'controller-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);raise SystemExit(p.returncode)
