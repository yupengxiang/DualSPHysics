#!/usr/bin/env python3
"""Fresh133 metadata and PNG-only delegated visual-review validator."""
import hashlib,json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
FORBIDDEN={".h5",".bi4",".csv",".dat",".vtk",".vtm",".vtu",".pvtu"}
def load(rel): return json.loads((PKG/rel).read_text())
def load_abs(p): return json.loads(Path(p).read_text())
def digest(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def req(c,m):
 if not c: raise SystemExit("FAIL: "+m)
review=load("metadata/visual-review.json"); closure=load("metadata/chain-closure.json"); png=load("metadata/png-hashes.json"); evidence=load("metadata/evidence-files.json")
req(review["status"]=="visual-approved-by-delegated-agent","status")
req(closure["status"]==review["status"],"status mismatch")
req(review["case_id"]==closure["case_id"] and review["physical_case_id"]!=review["case_id"],"alias/physical separation")
req(review["case_credit"]==0 and closure["case_credit"]==0,"case credit")
req(review["global_credit_updated_by_agent"] is False,"global credit")
req(review["scientific_payload_read_or_hashed_by_reviewer"] is False and closure["scientific_payload_read_or_hashed_by_reviewer"] is False,"payload claim")
req(review["agent_personally_viewed_all_contact_sheets"] is True and review["agent_personally_viewed_all_key_frames"] is True,"view evidence")
req(len(png["contact_sheets"])==17 and [x["index"] for x in png["contact_sheets"]]==list(range(17)),"contact inventory")
req(len(png["key_frames"])==9 and [x["frame"] for x in png["key_frames"]]==[0,50,100,150,200,250,300,350,400],"key inventory")
for e in png["contact_sheets"]+png["key_frames"]:
 p=Path(e["path"]); req(p.exists(),f"missing PNG {p}"); req(p.suffix.lower()==".png","non-PNG"); req(p.stat().st_size==e["bytes"],f"PNG bytes {p}"); req(digest(p)==e["sha256"],f"PNG digest {p}")
for e in evidence["files"]:
 p=Path(e["path"]); req(p.exists(),f"missing evidence {p}"); req(p.suffix.lower() not in FORBIDDEN,f"forbidden evidence {p}"); req(p.stat().st_size==e["bytes"],f"evidence bytes {p}"); req(digest(p)==e["sha256"],f"evidence digest {p}")
req(evidence["scientific_payload_read_or_hashed_by_reviewer"] is False,"evidence payload")
render=closure["producer_chain"]["render"]; rec=load_abs(render["receipt"]); rep=load_abs(render["report"])
req(rec.get("status")=="completed" and rec.get("returncode")==0,"render receipt")
req(rep["frames"]==401 and rep["source_frames"]==401,"401 frames")
req(rep["all_frames_rendered"] is True and rep["actual_times_preserved_exactly"] is True,"render flags")
req(rep["native_identity_axis_preserved"] is True and rep["nonfinite_active_states"]==0,"identity/nonfinite")
req(closure["scope_separation"]["equality_claim"]=="none","scope equality")
req(closure["lifecycle_disclosure"]["final_uid_status"]=="not inferred by visual reviewer","UID boundary")
print("PASS: fresh133 metadata, 17 contact PNGs, 9 keyframes, Root951 receipt/report, and F2 producer chain validated")
