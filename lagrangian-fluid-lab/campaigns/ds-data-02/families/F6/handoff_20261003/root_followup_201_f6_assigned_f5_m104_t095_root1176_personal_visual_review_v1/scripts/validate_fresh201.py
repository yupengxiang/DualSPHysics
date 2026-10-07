#!/usr/bin/env python3
"""Read-only fresh201 visual-review validator; never opens scientific payloads or hashes PNGs."""
from __future__ import annotations
import hashlib, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
META = ROOT / "metadata" / "visual-review.json"
BAD = {".h5", ".bi4", ".csv", ".dat", ".vtk", ".vtu"}

def fail(msg: str) -> None:
    raise SystemExit("FAIL: " + msg)

def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def require(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)

d = json.loads(META.read_text())
require(d["schema"] == "ds02.f6.fresh201.f5.personal-visual-review.v1", "schema")
require(d["package_id"] == "fresh201", "package id")
require(d["assigned_family"] == "F6" and d["physical_family"] == "F5", "family roles")
require(d["case_id"] == "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M104_T095_NEXT34", "case")
require(d["physical_case_id"] == "F5_COMPACT_RUNUP_RECOVERY_C082S1_M104_T095", "physical case")
for ref in d["metadata_refs"]:
    p = pathlib.Path(ref["path"])
    require(p.suffix.lower() not in BAD, "scientific payload ref: " + str(p))
    require(p.is_file(), "missing metadata ref: " + str(p))
    require(p.stat().st_size == ref["bytes"], "metadata size drift: " + str(p))
    require(sha(p) == ref["sha256"], "metadata SHA drift: " + str(p))
proof = next(x for x in d["metadata_refs"] if x["role"] == "main_full801_qi_proof")
require(proof["sha256"] == "2ebb39a807f2da63f3c8e8c0e0c7330b3bacfedf781aae9d970f15e2d884349c", "QI proof SHA")
term = d["actual_terminal_evidence"]
exec_ref = pathlib.Path(term["execution_receipt"]["path"])
pub_ref = pathlib.Path(term["publish_receipt"]["path"])
report_ref = pathlib.Path(term["render_report"]["path"])
for p in (exec_ref, pub_ref, report_ref):
    require(p.is_file(), "terminal metadata missing: " + str(p))
exec_d = json.loads(exec_ref.read_text())
pub_d = json.loads(pub_ref.read_text())
report_d = json.loads(report_ref.read_text())
require(exec_d.get("status") == "completed" and exec_d.get("returncode") == 0, "render not completed/0")
require(pub_d.get("status") == "published_after_atomic_rename", "not atomically published")
require(report_d.get("frames") == 801 and report_d.get("source_frames") == 801 and report_d.get("all_frames_rendered") is True, "full report")
require(report_d.get("actual_times_preserved_exactly") is True, "actual times not preserved")
require(report_d.get("native_identity_axis_preserved") is True and report_d.get("nonfinite_active_states") == 0, "identity/finite report")
contract = d["actual_render_contract"]
require(contract["frames"] == 801 and contract["particles"] == 194427, "render counts")
require(contract["actual_time_window_s"] == [0.0, 16.00012550006781], "actual time window")
require(contract["nominal_window_s"] == 16.0, "nominal window")
require(contract["counts"] == {"fixed_particles":158559,"moving_particles":4210,"floating_particles":0,"fluid_particles":31658,"total_particles":194427,"solver_dimension":3}, "counts")
roles = d["scope_roles"]
require(roles["roles_are_separate"] is True, "scope roles collapsed")
require(roles["native"]["source_plan_condition_sha256"]["present"] is False and roles["native"]["source_plan_condition_sha256"]["value"] is None, "native condition role")
require(roles["native"]["source_plan_physical_condition_sha256"]["present"] is True, "native physical role")
require(roles["XMF"]["source_plan_condition_sha256"]["present"] is False and roles["XMF"]["source_plan_condition_sha256"]["value"] is None, "XMF condition role")
require(roles["XMF"]["source_plan_physical_condition_sha256"]["present"] is True, "XMF physical role")
visual = d["visual_review"]
require(visual["status"] == "visual-approved-by-delegated-agent", "visual status")
require(visual["personally_viewed_with_view_image"] is True, "personal view flag")
contacts = visual["contact_sheets"]
keys = visual["key_frames"]
require(len(contacts) == 34 and len(keys) == 9, "PNG closure")
require([x["index"] for x in contacts] == list(range(34)), "contact indices")
require([x["frame_index"] for x in keys] == [0,100,200,300,400,500,600,700,800], "key indices")
for x in contacts + keys:
    p = pathlib.Path(x["path"])
    require(p.suffix.lower() == ".png" and p.is_file(), "missing published PNG: " + str(p))
    require(p.stat().st_size == x["bytes"] == x["producer_bytes"], "PNG stat mismatch: " + str(p))
    require(len(x["producer_sha256"]) == 64 and x["personally_viewed_with_view_image"] is True, "PNG producer/view metadata")
require(d["limitations"]["numerical_precision_accepted"] is False, "precision claim")
require(d["limitations"]["strict_containment_certified"] is False and d["limitations"]["subDP_precision_certified"] is False, "containment/subDP claim")
require(d["visual_review"]["case_credit"] == 0 and d["visual_review"]["q_n"] is False and d["visual_review"]["q_e"] is False, "credit/Q gates")
policy = d["scientific_payload_policy"]
require(policy["payloads_read"] is False and policy["payloads_hashed"] is False and policy["payloads_copied"] is False, "payload policy")
print("PASS fresh201: terminal/publish/QI metadata, scopes, 34 contacts, 9 key frames, and delegated visual review closure")
