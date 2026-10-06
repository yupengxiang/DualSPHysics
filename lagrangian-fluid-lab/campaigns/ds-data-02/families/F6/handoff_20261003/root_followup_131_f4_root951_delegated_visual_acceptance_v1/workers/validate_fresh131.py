#!/usr/bin/env python3
"""Metadata-only validator for F6 fresh131 Root951 visual handoff."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

PKG=Path(__file__).resolve().parents[1]
FORBIDDEN={".h5",".bi4",".csv",".dat",".vtk",".vtm",".vtu",".pvtu"}
def load(rel):
    return json.loads((PKG/rel).read_text())
def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def require(cond,msg):
    if not cond: raise SystemExit("FAIL: "+msg)

review=load("metadata/visual-review.json")
closure=load("metadata/chain-closure.json")
png=load("metadata/png-hashes.json")
evidence=load("metadata/evidence-files.json")
require(review["status"]=="visual-approved-by-delegated-agent","unexpected visual status")
require(closure["status"]==review["status"],"status mismatch")
require(review["case_credit"]==0 and closure["case_credit"]==0,"case credit must remain zero")
require(review["global_credit_updated_by_agent"] is False,"global credit mutation claim")
require(review["scientific_payload_read_or_hashed_by_reviewer"] is False,"scientific payload read/hash claim")
require(review["agent_personally_viewed_all_contact_sheets"] is True and review["agent_personally_viewed_all_key_frames"] is True,"view evidence incomplete")
contacts=png["contact_sheets"]; keys=png["key_frames"]
require(len(contacts)==51 and [x["index"] for x in contacts]==list(range(51)),"contact sheet inventory")
require(len(keys)==9 and [x["frame"] for x in keys]==[0,150,300,450,600,750,900,1050,1200],"keyframe inventory")
for entry in contacts+keys:
    p=Path(entry["path"]); require(p.exists(),f"missing PNG {p}")
    require(p.suffix.lower()==".png","non-PNG in visual hash manifest")
    require(p.stat().st_size==entry["bytes"],f"PNG size mismatch {p}")
    require(digest(p)==entry["sha256"],f"PNG digest mismatch {p}")
for f in evidence["files"]:
    p=Path(f["path"]); require(p.exists(),f"missing metadata evidence {p}")
    require(p.suffix.lower() not in FORBIDDEN,f"forbidden scientific suffix in evidence {p}")
    require(digest(p)==f["sha256"],f"metadata evidence digest mismatch {p}")
require(evidence["scientific_payload_read_or_hashed_by_reviewer"] is False,"evidence payload claim")
render=closure["producer_chain"]["render"]
require(render["status"]=="completed/0","render receipt not completed/0")
report=load(Path(render["report"]["path"]).relative_to(Path("/"))) if False else json.loads(Path(render["report"]["path"]).read_text())
require(report["frames"]==1201 and report["source_frames"]==1201,"render frame count")
require(report["all_frames_rendered"] is True and report["actual_times_preserved_exactly"] is True,"render integrity flags")
require(report["nonfinite_active_states"]==0,"nonfinite active states")
require(closure["lifecycle_disclosure"]["transient_missing_frame_count"]==0,"unexpected missing lifecycle")
require(closure["lifecycle_disclosure"]["final_uid_status"].startswith("not independently inferred"),"UID inference boundary")
require(closure["scope_separation"]["equality_claim"]=="none","scope equality claim")
print("PASS: fresh131 metadata, 51 contact PNGs, 9 keyframe PNGs, Root951 receipt/report, and metadata chain validated")
