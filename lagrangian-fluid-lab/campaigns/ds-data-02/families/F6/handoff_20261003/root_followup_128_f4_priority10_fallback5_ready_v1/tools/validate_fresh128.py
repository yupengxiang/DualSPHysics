#!/usr/bin/env python3
"""Metadata-only fresh128 validator; never opens scientific payloads."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
S=json.loads((ROOT/"metadata/selection.json").read_text()); C=json.loads((ROOT/"metadata/case-catalog.json").read_text())
def sh(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()
assert S["fresh_id"]=="fresh128" and C["fresh_id"]=="fresh128"
assert len(S["priority_cases"])==10 and len(S["fallback_cases"])==5 and not set(S["priority_cases"])&set(S["fallback_cases"])
assert S["excluded_completed_case"]["case_id"]=="F4_DROP_gap0p25000_xoff0p08000_yoff0p04000_uz0p40000"
for group in ("priority10","fallback5"):
 for x in C["records"][group]:
  assert x["queue_role"]==("priority" if group=="priority10" else "fallback")
  assert x["counts"]["generated_total"]==83233 and x["counts"]["typed_frames"]==1201 and x["counts"]["typed_particles"]==83233
  assert x["counts"]["dimension"]==3 and x["counts"]["xmf_frames"]==1201 and x["counts"]["xmf_particles"]==83233
  assert x["counts"]["native_frame0_pass"] is True and x["counts"]["partvtk_all_passed"] is True
  for k in ("gen_receipt","basic_receipt","native_receipt","frame0_receipt","typed_receipt","xmf_receipt"):
   assert x["actual_status"][k]["status"]=="completed" and x["actual_status"][k]["returncode"]==0
  t=x["render_template"]; assert t["disabled"] is True and t["execution_allowed"] is False and t["launch_allowed"] is False
  assert t["renderer_worker_path"] is None and t["registered_entry_path"] is None
  assert all(v is None for v in t["future_outputs"].values())
  for r in x["metadata_inputs"].values():
   p=Path(r["path"]); assert p.exists() and sh(p)==r["sha256"],p
print("fresh128 metadata validation: PASS")
print("priority10 fallback5 actual native/typed/XMF ready; render worker/output hashes null")
