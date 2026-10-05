#!/usr/bin/env python3
"""Fresh093 metadata-only contract preflight; never opens BI4/H5/CSV arrays."""
from __future__ import annotations
import ast, json
from pathlib import Path
PACKAGE=Path(__file__).resolve().parents[1]
CASE="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
COUNTS={"total_particles":194427,"fixed_particles":158559,"moving_particles":4210,"floating_particles":0,"fluid_particles":31658}
def load(path):
 value=json.loads(path.read_text(encoding="utf-8")); assert isinstance(value,dict),path; return value
def main():
 m=load(PACKAGE/"manifest.json"); assert m["actual_counts"]==COUNTS and m["full801_authorized"] is False
 p=load(PACKAGE/"metadata/root319-placement-mk50.json"); assert p["all_basic_placement_checks_pass"] is True and p["numerical_precision"]["accepted"] is False and p["mk50_center_support_counts"]==[208,27,22,15,20,20]
 s=load(PACKAGE/"metadata/actual-short-native-316.json"); assert s["status"]=="completed" and s["returncode"]==0 and s["all_51_saved_states"] is True and s["saved_state_count"]==51 and s["saved_state_filenames"]==[f"Part_{i:04d}.bi4" for i in range(51)]
 r=load(Path(s["receipt_path"])); assert r["status"]=="completed" and r["returncode"]==0 and r["request"]["case_id"]==CASE
 for name in ("typed-conversion-request.json","xmf-request.json","dynamic-bed-audit-request.json","render-root023-request.json"):
  q=load(PACKAGE/"requests"/name); assert q["execution_allowed"] is False and q["launch_allowed"] is False and q["solver_allowed"] is False and q["full801_authorized"] is False and q["case_id"]==CASE and q["expected_frames"]==51
 t=load(PACKAGE/"requests/typed-conversion-request.json"); assert t["expected_particles"]==194427 and t["expected_fluid_particles"]==31658 and t["conversion_contract"]["all_51_saved_states_required"] is True
 d=load(PACKAGE/"requests/dynamic-bed-audit-request.json"); assert d["cpu_task_kind"]=="audit" and d["output_contract"]["scan_all_51_frames"] is True
 rr=load(PACKAGE/"requests/render-root023-request.json"); assert rr["renderer_sha256"]=="5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66" and rr["camera_bounds"] is None and rr["domain_bounds"] is None
 b=load(PACKAGE/"bindings/short-event-bed-audit-binding.json"); assert b["expected_particle_axis"]==194427 and b["expected_fluid_particles"]==31658 and b["native_bed_marker_mk"]==50 and b["source_bed_marker_mkbound"]==40 and b["source_h5_physical_condition_sha256"].startswith("<root-bind:")
 ast.parse((PACKAGE/"workers/bed_audit.py").read_text(encoding="utf-8"))
 print("fresh093 metadata-only preflight passed; all downstream execution remains disabled")
if __name__=="__main__": main()
