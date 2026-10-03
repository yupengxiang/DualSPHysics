import importlib.util,argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--binding",required=True);p.add_argument("--output",required=True);a=p.parse_args()
s=importlib.util.spec_from_file_location("unchanged_native_audit",'/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_f5_f6_native_telemetry_036/audit.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
b=json.loads(Path(a.binding).read_text());r=[m.audit(c) for c in b["cases"]];Path(a.output).write_text(json.dumps({"schema":"ds02.f1.actual-thick-dbc-halfstep-native-telemetry.v1","cases":r,"q_n":"not_granted","production_approval":"none"},indent=2)+"\n")
