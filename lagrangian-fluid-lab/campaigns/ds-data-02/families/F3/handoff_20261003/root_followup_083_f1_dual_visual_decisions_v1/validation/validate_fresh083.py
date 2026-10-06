#!/usr/bin/env python3
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256();
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
idx=json.loads((ROOT/"metadata/visual-frontier-index.json").read_text())
assert idx["batch_size"]==2
for rel in idx["decision_paths"]:
 d=json.loads((ROOT/rel).read_text())
 assert d["status"]=="visual-approved-by-delegated-agent"
 assert d["independent_physical_case_count_increment"]==0
 assert d["global_count_update"]=="not written; primary agent owns checkpoint and acceptance counts"
 assert d["review_method"]["contact_sheets_reviewed"]==17
 assert d["review_method"]["fullsize_keyframes_reviewed"]==[0,65,115,400]
 assert d["render_metadata_evidence"]["frames"]==401
 assert d["render_metadata_evidence"]["source_frames"]==401
 assert d["render_metadata_evidence"]["all_frames_rendered"] is True
 assert d["render_metadata_evidence"]["nonfinite_active_states"]==0
 assert d["render_metadata_evidence"]["max_missing_particles_in_frame_diagnostics"]==0
 assert len(d["bindings"]["render"]["contact_sheets"])==17
 assert len(d["bindings"]["render"]["keyframes"])==4
 for item in d["bindings"]["render"]["contact_sheets"]+d["bindings"]["render"]["keyframes"]:
  p=Path(item["path"]); assert p.is_file(),p; assert sha(p)==item["sha256"],p
 assert d["provenance_status"]["all_required_terminal_returncodes_zero"] is True
print("fresh083 visual metadata + rendered-PNG hash validation: PASS")
