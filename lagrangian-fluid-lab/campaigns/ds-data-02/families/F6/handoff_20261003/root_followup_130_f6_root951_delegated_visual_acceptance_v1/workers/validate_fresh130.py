#!/usr/bin/env python3
"""Validate fresh130 metadata and visual evidence without scientific payload reads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
INDEX = HERE / "metadata" / "review-index.json"
EVIDENCE = HERE / "metadata" / "evidence-files.json"
SUMMARY = HERE / "metadata" / "visual-summary.json"
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".csv", ".dat", ".vtk", ".vtm", ".vtu"}


def load(path: Path):
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


index = load(INDEX)
evidence = load(EVIDENCE)
summary = load(SUMMARY)

assert index["schema"] == "ds02.f6.fresh130.delegated-visual-review.v1"
assert evidence["schema"] == "ds02.f6.fresh130.evidence-files.v1"
assert summary["schema"] == "ds02.f6.fresh130.visual-summary.v1"
assert index["fresh_id"] == summary["fresh_id"] == "fresh130"
assert index["case_id"] == summary["case_id"] == "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025"
assert index["decision"] == "visual-approved-by-delegated-agent"
assert index["reviewer_role"] == "delegated_visual_agent"
assert index["global_credit_updated_by_agent"] is False
assert index["case_credit_granted_by_agent"] is False
assert index["precision_status"] == "not accepted"
assert index["qn_or_production_claim"] is False
assert index["scientific_payload_read_or_hashed_by_agent"] is False

visual = index["visual_review"]
assert visual["contact_sheet_count_viewed"] == 11
assert visual["keyframe_count_viewed"] == 9
assert visual["all_contact_sheets_viewed"] is True
assert visual["all_requested_keyframes_viewed"] is True
assert visual["requested_keyframe_indices"] == [0, 30, 60, 90, 120, 150, 180, 210, 240]
assert all(item["viewed_with"] == "view_image" for item in visual["contact_sheets"])
assert all(item["viewed_with"] == "view_image" for item in visual["keyframes"])

receipt = index["render_receipt"]
assert receipt["status"] == "completed"
assert receipt["returncode"] == 0
report = index["render_report"]
assert report["frames"] == report["source_frames"] == 241
assert report["all_frames_rendered"] is True
assert report["actual_times_preserved_exactly"] is True
assert report["native_identity_axis_preserved"] is True
assert report["nonfinite_active_states"] == 0
life = index["renderer_report_lifecycle"]
assert life["frame_diagnostics_count"] == 241
assert life["missing_event_sum"] == 933
assert life["nonzero_missing_frame_count"] == 234
assert life["maximum_missing_particles_single_frame"] == 4
assert life["final_uid_inference_by_agent"] is False

scope = index["scope"]
assert scope["scope_must_not_be_equated"] is True
assert scope["source_canonical_physical_condition_sha256"] != scope["actual_converter_scope_sha256"]
assert scope["source_plan_condition_sha256"] != scope["actual_converter_scope_sha256"]

entries = evidence["entries"]
assert len(entries) == index["evidence_file_count"]
assert len({entry["path"] for entry in entries}) == len(entries)
for entry in entries:
    path = Path(entry["path"])
    assert path.suffix.lower() not in FORBIDDEN_SUFFIXES, path
    assert path.exists(), path
    assert sha256(path) == entry["sha256"], path

# The evidence list is intentionally restricted to JSON/XML/source metadata and PNGs.
assert "trajectory.h5" not in "\n".join(entry["path"] for entry in entries)
assert evidence["scientific_payload_read_or_hashed_by_agent"] is False

assert summary["receipt_status"] == "completed/0"
assert summary["frames"] == "241/241"
assert summary["viewed_contacts"] == 11
assert summary["viewed_keyframes"] == 9
assert summary["case_credit_granted_by_agent"] is False
assert summary["source_h5_hash_by_agent"] is False

print("fresh130 validation PASS: Root951 completed/0; 11 contact sheets and 9 keyframes viewed; delegated visual approval recorded")

