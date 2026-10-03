import argparse,csv,importlib.util,json
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument("--binding",required=True);p.add_argument("--output",required=True);a=p.parse_args();b=json.loads(Path(a.binding).read_text())
r=json.loads(Path(b["geometry_receipt"]).read_text());assert r["status"]=="completed" and r["returncode"]==0 and r["input_hashes_at_launch"]==r["input_hashes_after_run"]
s=importlib.util.spec_from_file_location("owner_geometry",b["helper"]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
j=json.loads(Path(b["geometry_report"]).read_text());trajectories={};alignment={}
for c in b["cases"]:
 with Path(c["floating_info"]).open() as f:rows=list(csv.DictReader(f,delimiter=";"))
 assert len(rows)==241 and [int(x["part"]) for x in rows]==list(range(241))
 time=np.array([float(x["time [s]"]) for x in rows]);rec=j["cases"][c["role"]]["frames"];assert len(rec)==241
 qt=np.array([x["time_s"] for x in rec]);offset=np.abs(qt-time)
 assert np.isfinite(time).all() and np.all(np.diff(time)>0) and time[0]==0 and time[-1]>=12 and offset.max()<1e-4
 trajectories[c["role"]]={"times":time,"quaternions":np.array([x["quaternion_wxyz"] for x in rec]),"centroids":np.array([x["center_m"] for x in rec])}
 alignment[c["role"]]={"association":"same actual native Part index after complete241 cohort/geometry and timestamp rounding check", "PartVTK_csv_time_precision":"six significant digits; rounded exported timestamps retained in parent", "exact_time_source":"official FloatingInfo fullprecision time[s] from same native PartFloatInfo", "maximum_rounding_difference_s":float(offset.max()),"fullprecision_native_window_s":[float(time[0]),float(time[-1])]}
grid=np.arange(241)*.05;assert all(t["times"][0]<=grid[0] and t["times"][-1]>=grid[-1] for t in trajectories.values())
pairs={x+"_vs_"+y:m.compare_trajectories_physical_time(trajectories[x],trajectories[y],grid) for x,y in [("fine","medium"),("fine","coarse"),("medium","coarse")]}
out={"schema":"ds02.f6.fullprecision-native-time-geometry-comparison.v1","parent_geometry_report_sha256":m.sha256_file(b["geometry_report"]),"parent_geometry_receipt_sha256":m.sha256_file(b["geometry_receipt"]),"alignment":alignment,"physical_grid_s":grid.tolist(),"pairs":pairs,"claim_boundary":{"q_n":"not_granted","production_approval":"none","orientation_budget":None,"correction":"additive exact native timestamp comparison; all parent geometry pose and exported timestamps remain immutable; no extrapolation","translation_budget":"original L=.8 reference andgeneric5% reporting, not wholefamilyqualification"}}
Path(a.output).write_text(json.dumps(out,indent=2,allow_nan=False)+"\n")
