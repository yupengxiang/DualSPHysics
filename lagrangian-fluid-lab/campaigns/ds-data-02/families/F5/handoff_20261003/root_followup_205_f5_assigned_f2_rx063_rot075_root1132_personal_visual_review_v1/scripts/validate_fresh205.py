#!/usr/bin/env python3
"""Metadata-only validator for the F5-assigned F2 Root1132 visual handoff."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CASE = "F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT075_DP010_SPATIAL_REFERENCE_SAVE010"
PHYSICAL = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT075"
ATTEMPT = "root-stage1-f2-rx063-rot075-actual1116-full401-116-023-nvme-hard2gib-root1132"
NATIVE = "ba9d9df7d7059d92ee318b4b0d98bc77a118c7a68bca385b1b95bb75898bac94"
LEGACY = "4da599dadeae04d45d430f415509ba8cbd9af670a849358ec2cbaa24ffcc8adf"

def read(rel: str):
    return json.loads((PACKAGE / rel).read_text())

def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)

def main() -> None:
    required = [
        "README.md",
        "manifest.json",
        "metadata/actual-render-metadata.json",
        "metadata/physical-stage-closure.json",
        "metadata/png-visual-evidence.json",
        "metadata/upstream-evidence.json",
        "metadata/visual-decision.json",
    ]
    for rel in required:
        check((PACKAGE / rel).is_file(), f"missing package file: {rel}")
    manifest = read("manifest.json")
    actual = read("metadata/actual-render-metadata.json")
    physical = read("metadata/physical-stage-closure.json")
    visual = read("metadata/png-visual-evidence.json")
    upstream = read("metadata/upstream-evidence.json")
    decision = read("metadata/visual-decision.json")
    check(actual["case_id"] == CASE and actual["physical_case_id"] == PHYSICAL, "actual identity mismatch")
    check(actual["attempt_id"] == ATTEMPT, "attempt mismatch")
    check(actual["receipt"]["status"] == "completed" and actual["receipt"]["returncode"] == 0, "producer receipt is not completed/0")
    check(actual["counts"] == {"total": 418104, "fixed": 372840, "moving": 24150, "floating": 0, "fluid_initial": 21114, "fluid_terminal": 21079, "solver_dimension": 3, "data2d": False}, "actual counts mismatch")
    check(actual["animation_report"]["frames"] == 401 and actual["animation_report"]["source_frames"] == 401, "frame count mismatch")
    check(actual["publish"]["status"] == "published_after_atomic_rename", "publish not atomic/completed")
    finished = datetime.fromisoformat(actual["receipt"]["finished_at_utc"])
    reviewed_at = datetime.fromisoformat(visual["reviewed_at_utc"])
    check(reviewed_at >= finished, "visual review timestamp precedes producer completion")
    check(reviewed_at <= datetime.now(timezone.utc), "visual review timestamp is in the future")
    check(visual["reviewer_model"] == "gpt-5.6-luna/max" and visual["recursive_delegation"] is False, "reviewer provenance mismatch")
    check(actual["actual_scope_roles"]["native_canonical"] == NATIVE, "native canonical scope mismatch")
    check(actual["actual_scope_roles"]["typed_converter_legacy"] == LEGACY, "typed legacy scope mismatch")
    check(actual["missing_fluid_metadata"] == {"first_missing_frame": 137, "frames_with_any_missing_particle": 264, "final_missing_particles": 35, "max_missing_per_frame": 35, "cumulative_particle_frame_omissions": 8392, "final_missing_fraction_initial_fluid": 0.0016576678980771053, "locations_states_causes": "unknown", "producer_attested_missing_id_sha256": "77346a6b93920a09238dc62bedfa2e7b411baf9ecff05a83d71daaaa3f882766", "no_state_reconstruction": True}, "omission evidence mismatch")
    entries = visual["published_pngs_reviewed"]["entries"]
    contacts = [e for e in entries if e["kind"] == "contact_sheet"]
    keys = [e for e in entries if e["kind"] == "keyframe"]
    check(len(contacts) == 17 and len(keys) == 9 and visual["published_pngs_reviewed"]["total"] == 26, "review entry count mismatch")
    check({e["index"] for e in contacts} == set(range(17)), "contact sheet indices incomplete")
    check([e["frame"] for e in keys] == [0, 50, 100, 150, 200, 250, 300, 350, 400], "keyframe indices mismatch")
    for e in entries:
        check(e["reviewed"] is True and e["review_mode"] == "view_image", "unreviewed visual entry")
        check(HEX64.fullmatch(e["producer_sha256"] or ""), f"bad producer PNG digest: {e['relative_path']}")
    check(visual["visual_decision"]["personal_first_stage_visual_approval"] is True, "personal visual decision missing")
    check(visual["visual_decision"]["case_credit_increment"] == 0, "case credit changed")
    check(decision["case_credit_increment"] == 0 and decision["qn"] is False and decision["qe"] is False, "decision credit/Q flags changed")
    check(physical["numeric_scope"]["numerical_precision_accepted"] is False, "precision was accepted")
    check(physical["open_rim_visual_scope"]["strict_container_accepted"] is False, "strict container unexpectedly accepted")
    check(upstream["scientific_payload_policy"] == {"read_by_source_agent": False, "hashed_by_source_agent": False, "copied_by_source_agent": False, "future_jobs_started": False, "shared_ledger_modified": False}, "payload policy changed")
    check(manifest["source_payloads_included"] is False and manifest["future_science_execution"] is False, "package includes execution/payload")
    listed = {x["path"]: x for x in manifest["files"]}
    check("manifest.json" not in listed, "manifest self-reference present")
    for rel, item in listed.items():
        p = PACKAGE / rel
        check(p.is_file(), f"manifest file missing: {rel}")
        check(item["bytes"] == p.stat().st_size, f"manifest byte mismatch: {rel}")
        check(item["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest(), f"manifest SHA mismatch: {rel}")
    print("fresh205 assigned-F5 F2 RX063/ROT075 visual handoff validation PASS")
    print(f"package={PACKAGE}")
    print("reviewed=17 contact sheets + 9 keyframes; completed/0; case_credit_increment=0")

if __name__ == "__main__":
    main()
