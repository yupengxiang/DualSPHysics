#!/usr/bin/env python3
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256();
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def load(x): return json.loads((ROOT/x).read_text())
idx=load("metadata/visual-frontier-index.json"); d=load("decisions/F3_STAGE1_DP006_P1200_AY0750.json"); e=load("metadata/root796_render_evidence.json")
assert idx["batch_size"]==1 and idx["status"]=="visual-approved-by-delegated-agent" and idx["independent_case_increment"]==0
assert d["status"]=="visual-approved-by-delegated-agent" and d["family_id"]=="F3"
for k in ("production_approval_grant","q_n_grant","numerical_precision_grant","pitch_domain_grant"): assert d["claim_limits"][k] is False
assert d["source_payload_policy"]["science_payload_read_or_hashed_by_source_package"] is False
report_path=Path(e["render"]["report"]["path"]); manifest_path=Path(e["xmf"]["manifest"]["path"])
assert report_path.is_file() and sha(report_path)==e["render"]["report"]["sha256"]
assert manifest_path.is_file() and sha(manifest_path)==e["xmf"]["manifest"]["sha256"]
report=json.loads(report_path.read_text()); manifest=json.loads(manifest_path.read_text())
assert report["frames"]==836 and report["source_frames"]==836 and report["all_frames_rendered"] is True
assert report["actual_times_preserved_exactly"] is True and report["native_identity_axis_preserved"] is True and report["nonfinite_active_states"]==0
assert len(report["outputs"]["contact_sheets"])==35 and len(report["frame_diagnostics"])==836
assert manifest["frames"]==836 and manifest["particles"]==179208 and manifest["dimension"]==3 and manifest["independent_case_count_increment"]==0
assert manifest["physical_condition_sha256"]==d["physical_condition_sha256"] and manifest["source_and_actual_scopes_are_distinct"] is True
for frame in report["frame_diagnostics"]:
 assert frame["active"]==manifest["particles"] and frame["missing"]==0 and frame["finite_positions_active"] is True
 assert all(v["finite_active"] is True and v["nonfinite_active"]==0 for v in frame["finite_fields"].values())
for kind in ("native","typed","xmf","render"):
 r=e[kind]["receipt"]; p=Path(r["path"]); assert p.is_file() and sha(p)==r["sha256"]; q=json.loads(p.read_text()); assert q["status"]=="completed" and q["returncode"]==0
for item in e["render"]["contact_sheets"]+e["render"]["keyframe_images"]:
 p=Path(item["path"]); assert p.is_file() and sha(p)==item["sha256"]; assert not any(s in str(p).lower() for s in (".h5",".bi4",".csv",".dat",".vtk"))
assert e["render"]["keyframes_reviewed"]==[0, 1, 65, 115, 200, 300, 400, 500, 600, 700, 800, 835] and e["render"]["contact_sheet_count"]==35
for p in ROOT.rglob("*"):
 if p.is_file(): assert p.suffix.lower() not in {".h5",".bi4",".csv",".dat",".vtk"}, p
print("fresh102 F3 Root796 visual metadata + PNG validation: PASS")
