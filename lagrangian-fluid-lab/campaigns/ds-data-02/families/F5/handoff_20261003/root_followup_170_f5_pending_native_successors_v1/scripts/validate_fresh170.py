#!/usr/bin/env python3
"""Fresh170 metadata-only validator; never opens science payloads."""
from pathlib import Path
import hashlib,json,sys
PKG=Path(__file__).resolve().parents[1]
FORBIDDEN={".h5",".bi4",".csv",".dat",".vtk"}
def load(p): return json.loads(Path(p).read_text())
def digest(p):
 p=Path(p)
 if p.suffix.lower() in FORBIDDEN: raise AssertionError(f"forbidden science read/hash: {p}")
 return hashlib.sha256(p.read_bytes()).hexdigest()
def req(c,m):
 if not c: raise AssertionError(m)
def main():
 plan=load(PKG/"metadata/fresh170-source-plan.json"); status=load(PKG/"metadata/root850-root871-native-status.json")
 req(len(plan["pending_tags"])==11,"pending count"); req(len(status["pending_rows"])==34,"status rows")
 req(status["root850"]["actual_full801_native_pass_count"]==12,"Root850 count"); req(status["root850"]["native_scientific_failures"]==0,"Root850 failures")
 req(status["root871"]["new_successor_completed_count"]==11,"Root871 new count"); req(status["root871"]["pending_request_count"]==7,"Root871 pending count"); req(status["pending_classification"]["failed_partial_native_attempts"]==[],"partial native")
 for tag in plan["pending_tags"]:
  b=load(PKG/"bindings"/f"{tag}-native-successor-binding.json"); q=load(PKG/"requests"/f"{tag}-native-successor-request.json")
  req(b["disabled"] and b["source_only"] and not b["execution_allowed"],"binding enabled")
  req(q["disabled"] and q["source_only"] and not q["launch"] and not q["execution_allowed"] and not q["solver_allowed"],"request enabled")
  req(q["expected_frames"]==801 and q["expected_dimension"]==3 and q["physical_window_s"]==[0,16] and q["tout_s"]==0.02,"recipe")
  req(q["actual_counts"]["total_particles"]==194427 and q["actual_counts"]["fluid_particles"]==31658,"counts")
  req(q["native_bed_marker_mk"]==50 and q["source_bed_marker_mkbound"]==40,"markers")
  req(q["binding_sha256"]==digest(q["binding"]),"binding hash")
  for f,h in q["input_sha256"].items():
   p=Path(f); req(p.is_file(),f"missing input {p}"); req(p.suffix.lower() not in FORBIDDEN,f"science input {p}"); req(digest(p)==h,f"hash mismatch {p}")
  for a in q["producer_payload_attestations"]: req(a["source_did_not_read_or_hash"] is True and Path(a["path"]).suffix.lower() in FORBIDDEN,"payload policy")
 obs=load(PKG/"metadata/root993-root998-xmf-bed-observation.json"); req(obs["actual_xmf_completed_count"]==3,"XMF count"); req({x["tag"] for x in obs["entries"]}=={"M086_T095","M088_T085","M088_T095"},"XMF tags")
 for x in obs["entries"]: req(x["status"]=="completed" and x["returncode"]==0 and x["future_bed_report_sha256"] is None,"XMF/bed")
 out={"schema":"ds02.f5.fresh170.validator-report.v1","status":"pass","pending_count":11,"root850_completed":12,"root871_new_completed":11,"root871_never_launched":7,"not_submitted":4,"xmf_completed":3,"science_payload_read_or_hashed_by_validator":False}
 (PKG/"metadata/fresh170-validator-report.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n"); print(json.dumps(out,indent=2))
if __name__=="__main__":
 try: main()
 except Exception as e: print(f"fresh170 validation failed: {e}",file=sys.stderr); raise
