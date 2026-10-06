#!/usr/bin/env python3
"""Metadata and derived-PNG validator for F5 fresh184.

It reads JSON metadata and producer-rendered PNG derivatives only. It does not
open raw H5, BI4, CSV, DAT, VTK, or solver payloads and never launches work.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[0].parent

def load(rel):
    return json.loads((PKG / rel).read_text())

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)

actual = load("metadata/actual1096-render-metadata.json")
png = load("metadata/png-visual-evidence.json")
closure = load("metadata/physical-stage-closure.json")
decision = load("metadata/visual-decision.json")
upstream = load("metadata/upstream-evidence.json")
manifest = load("manifest.json")

receipt_path = Path(actual["execution_receipt"]["path"])
report_path = Path(actual["render_report"]["path"])
publish_path = Path(actual["publish_receipt"]["path"])
for p in (receipt_path, report_path, publish_path):
    check(p.is_file(), "missing producer metadata " + str(p))
receipt = json.loads(receipt_path.read_text())
report = json.loads(report_path.read_text())
publish = json.loads(publish_path.read_text())
check(sha(receipt_path) == actual["execution_receipt"]["sha256"], "receipt metadata hash")
check(sha(report_path) == actual["render_report"]["sha256"], "render report metadata hash")
check(sha(publish_path) == actual["publish_receipt"]["sha256"], "publish receipt metadata hash")
for role, item in upstream["upstream_chain"].items():
    p = Path(item["path"])
    check(p.is_file(), "missing upstream metadata " + role)
    check(sha(p) == item["sha256"], "upstream metadata hash " + role)

check(actual["attempt_id"] == "root-stage1-f5-m090_t085-source177-full801-original116023-frozen-progress-repair1-root1096", "Root1096 attempt identity")
check(receipt["status"] == "completed" and receipt["returncode"] == 0, "terminal receipt")
check(report["frames"] == 801 and report["source_frames"] == 801, "report frame count")
check(report["all_frames_rendered"] is True, "all_frames_rendered")
check(report["native_identity_axis_preserved"] is True, "native identity axis")
check(report["actual_times_preserved_exactly"] is True, "time axis")
check(report["nonfinite_active_states"] == 0, "nonfinite state")
check(report["numerical_precision_status"] == "not accepted", "precision must remain unaccepted")
check(publish["status"] == "published_after_atomic_rename", "publish status")
check(publish["report_sha256_after_rebind"] == actual["render_report"]["sha256"], "report rebind hash")
check(publish["source_h5_opened_or_hashed_by_wrapper"] is False, "wrapper source-H5 guard")

check(len(png["contact_sheets"]) == 34, "contact count")
check(len(png["keyframes"]) == 9, "keyframe count")
check(png["keyframe_indices"] == [0,100,200,300,400,500,600,700,800], "keyframe indices")
check(png["all_actual_contact_sheets_reviewed"] is True, "contact review")
check(png["all_nine_keyframes_reviewed"] is True, "keyframe review")
for item in png["contact_sheets"] + png["keyframes"]:
    p = Path(item["path"])
    check(p.is_file(), "missing rendered PNG " + str(p))
    check(p.stat().st_size == item["bytes"], "PNG size changed " + str(p))
    check(sha(p) == item["sha256"], "PNG hash changed " + str(p))

summary = closure["dynamic_bed_summary"]
check(summary["frames_scanned"] == 801, "bed frame metadata")
check(summary["initial_fluid_uid_count"] == 31658, "bed UID denominator")
check(summary["one_dp_max_count"] == 0 and summary["two_dp_max_count"] == 0, "bed bins")
check(summary["one_two_dp_zero_is_not_sub_dp_depth_proof"] is True, "sub-DP interpretation")
check(summary["sub_dp_depth_inferred"] is False, "sub-DP inference")
check(summary["missing_initial_uid_max"] == 0, "missing UID")
check(summary["unexpected_uid_max"] == 0, "unexpected UID")
check(summary["nonfinite_position_max"] == 0 and summary["nonfinite_mass_max"] == 0, "nonfinite metadata")
check(decision["decision"]["standalone_first_stage_visual_approved"] is True, "visual decision")
check(decision["decision"]["strict_container_guarantee"] is False, "strict-container overclaim")
check(decision["decision"]["numerical_precision_accepted"] is False, "precision overclaim")
check(decision["decision"]["independent_case_count_increment"] == 0, "case credit")
check(decision["scope_and_negative_evidence"]["old_root1083_receipt_not_used_as_terminal_render_evidence"] is True, "Root1083 exclusion")
check(actual["source_agent_science_payload_io"]["raw_h5_bi4_csv_dat_vtk_read"] is False, "raw science read")
check(actual["source_agent_science_payload_io"]["raw_h5_bi4_csv_dat_vtk_hash"] is False, "raw science hash")
check(actual["source_agent_science_payload_io"]["scientific_job_started"] is False, "scientific launch")
check(upstream["scope_roles"]["roles_remain_distinct"] is True, "scope separation")
check(upstream["scope_roles"]["cross_resolution_claim"] is False, "cross-resolution claim")

listed = {x["path"]: x for x in manifest["files"]}
for rel in (
    "README.md",
    "metadata/actual1096-render-metadata.json",
    "metadata/png-visual-evidence.json",
    "metadata/physical-stage-closure.json",
    "metadata/upstream-evidence.json",
    "metadata/visual-decision.json",
    "scripts/validate_fresh184.py",
):
    p = PKG / rel
    check(rel in listed, "manifest entry " + rel)
    check(p.is_file(), "package file " + str(p))
    check(p.stat().st_size == listed[rel]["bytes"], "manifest size " + rel)
    check(sha(p) == listed[rel]["sha256"], "manifest hash " + rel)
check(manifest["manifest_excludes_self"] is True, "manifest self exclusion")
check(manifest["source_only"] is True, "source-only package")
print("PASS fresh184 metadata + 34 contact sheets + 9 keyframes")
print("Root1096 completed/0, 801 frames, visual approval with limitations")
print("strict container, sub-DP inference, precision, Q-N, and case credit remain false")
