#!/usr/bin/env python3
"""Read-only validator for the fresh192 personal visual evidence package.

The validator reads JSON metadata and filesystem statistics for the already
published PNGs.  It deliberately never opens or hashes PNG, H5, BI4, IBI4,
CSV, DAT, VTK, or other scientific payloads.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
DECISION_PATH = PACKAGE / "metadata" / "actual1189-personal-visual-decision.json"
EVIDENCE_PATH = PACKAGE / "metadata" / "png-evidence" / "actual1189.json"
FRESH191_PATH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/"
    "root_followup_191_f3_assigned_f5_m110_t100_original1189_metadata_preflight_v1/"
    "metadata/m110-t100-original1189-preflight.json"
)
FRESH191_SHA = "f589fa0602851cdbbba4efe6fc15f6dd846bcaab088c1591a3f2e727ea3b4729"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_SUFFIXES = {
    ".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp"
}


def fail(message: str) -> None:
    raise AssertionError(message)


def load_json(path: Path) -> dict:
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        fail(f"forbidden payload read: {path}")
    if not path.is_file():
        fail(f"missing JSON metadata: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"JSON object required: {path}")
    return value


def sha256_json(path: Path) -> str:
    # JSON metadata is within the permitted audit boundary; no scientific
    # payload is opened by this function.
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_png_entries(entries: list[dict], expected_role: str, expected_count: int) -> None:
    if len(entries) != expected_count:
        fail(f"{expected_role} count {len(entries)} != {expected_count}")
    seen: set[str] = set()
    for entry in entries:
        if entry.get("role") != expected_role:
            fail(f"wrong PNG role: {entry.get('role')!r}")
        path = Path(entry["path"])
        if path in seen:
            fail(f"duplicate PNG path: {path}")
        seen.add(str(path))
        if path.suffix.lower() != ".png" or not path.is_file():
            fail(f"published PNG missing: {path}")
        if path.stat().st_size != entry.get("bytes_stat"):
            fail(f"PNG stat changed: {path}")
        producer_sha = entry.get("producer_declared_sha256")
        if not isinstance(producer_sha, str) or not HEX64.fullmatch(producer_sha):
            fail(f"invalid producer-declared PNG SHA: {path}")
        if entry.get("personally_viewed_with_view_image") is not True:
            fail(f"PNG was not personally viewed: {path}")
        if entry.get("content_read_or_hashed_by_reviewer") is not False:
            fail(f"PNG read/hash boundary violated: {path}")
        if not isinstance(entry.get("relative_path"), str):
            fail(f"missing relative PNG path: {path}")


def main() -> int:
    decision = load_json(DECISION_PATH)
    evidence = load_json(EVIDENCE_PATH)
    fresh191 = load_json(FRESH191_PATH)

    assert decision["schema"] == "ds02.f3.assigned-f5.personal-visual-decision.v2"
    assert evidence["schema"] == "ds02.f3.assigned-f5.personal-visual-png-evidence.v1"
    assert decision["fresh_id"] == evidence["fresh_id"] == "fresh192"
    assert decision["assigned_worktree_family"] == evidence.get("assigned_worktree_family", "F3") == "F3"
    assert decision["actual_case_family"] == "F5"
    assert decision["configured_model"] == evidence.get("configured_model", "gpt-5.6-luna/max") == "gpt-5.6-luna/max"
    assert decision["model_substitution"] is False
    assert decision["case_credit"] == decision["q_n"] == decision["q_e"] == 0
    assert decision["visual_status"] == "visual-approved-by-delegated-agent"

    assert decision["case_id"] == evidence["case_id"] == fresh191["case_identity"]["case_id"]
    assert decision["physical_case_id"] == evidence["physical_case_id"] == fresh191["case_identity"]["physical_case_id"]
    assert decision["personal_review"]["method"] == evidence["review_boundary"]["view_method"] == "view_image"
    completed_at = decision["personal_review"]["review_completed_at_utc"]
    assert evidence["review_completed_at_utc"] == completed_at
    # Python's datetime parser accepts six fractional digits; retain the
    # recorded nanosecond precision in JSON while parsing a bounded prefix.
    timestamp_for_parse = completed_at.replace("Z", "+00:00")
    timestamp_for_parse = re.sub(r"(\.\d{6})\d+(?=\+00:00$)", r"\1", timestamp_for_parse)
    datetime.fromisoformat(timestamp_for_parse)

    review = decision["personal_review"]
    assert review["contact_sheets_viewed"] == 34
    assert review["key_frames_viewed"] == 9
    assert review["key_frame_indices"] == [0, 100, 200, 300, 400, 500, 600, 700, 800]
    assert review["all_required_published_pngs_viewed"] is True
    assert review["png_bytes_hashed_by_reviewer"] is False
    assert review["render_started_review_only_after_terminal_publish"] is True
    assert evidence["review_boundary"]["published_pngs_opened"] is True
    assert evidence["review_boundary"]["png_bytes_hashed_by_reviewer"] is False
    assert evidence["review_boundary"]["scientific_payload_read_or_hashed"] is False

    check_png_entries(evidence["contact_sheets"], "contact_sheet", 34)
    check_png_entries(evidence["key_frames"], "key_frame", 9)

    runtime = decision["runtime_identity"]
    assert runtime["frames"] == 801
    assert runtime["particles"] == 194427
    assert runtime["fixed"] == 158559
    assert runtime["moving"] == 4210
    assert runtime["fluid"] == 31658
    assert runtime["floating"] == 0
    assert runtime["dimension"] == 3
    assert runtime["vector_shape"] == "N x 3"
    assert runtime["key_frame_indices"] == [0, 100, 200, 300, 400, 500, 600, 700, 800]
    assert runtime["actual_time_window_s"] == [0.0, 16.00008511666941]
    assert runtime["all801_geometry_velocity_N3_times_UID_finite_verified"] is True
    assert runtime["all_native_UIDs_active_each_frame"] is True

    provenance = decision["actual_provenance"]
    assert provenance["fresh191_preflight_commit"] == "4492bb90c5f8d278b53db3d862f3f2881a6e6605"
    assert provenance["fresh191_preflight_sha256"] == FRESH191_SHA
    assert sha256_json(FRESH191_PATH) == FRESH191_SHA
    assert provenance["terminal_status"] == "completed/0"
    assert provenance["atomic_publish_status"] == "published_after_atomic_rename"

    receipt = load_json(Path(provenance["render_receipt"]["path"]))
    report = load_json(Path(provenance["render_report"]["path"]))
    publish = load_json(Path(provenance["publish_receipt"]["path"]))
    assert receipt.get("status") == "completed"
    assert receipt.get("returncode") == 0
    assert report.get("schema") == "ds02.stage1.paraview-full-animation-integrity.v1"
    assert report.get("source_frames") == report.get("frames") == 801
    assert report.get("actual_times_preserved_exactly") is True
    assert report.get("all_frames_rendered") is True
    assert report.get("diagnostic_only") is False
    assert report.get("nonfinite_active_states") == 0
    assert report.get("source_h5_read_only") is True
    assert report.get("manifest_sha256") == "da60c416f57dc3e12ccc32cf9763ff7b1e5b1fa4b7980e84f577729a13946e51"
    diagnostics = report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != 801:
        fail("render report does not contain all 801 frame diagnostics")
    for index, frame in enumerate(diagnostics):
        if frame.get("frame") != index or frame.get("missing") != 0:
            fail(f"frame diagnostic mismatch at {index}")
        if frame.get("finite_positions_active") is not True:
            fail(f"non-finite positions at frame {index}")
        fields = frame.get("finite_fields", {})
        for field in ("density", "mass", "pressure", "velocity"):
            if fields.get(field, {}).get("finite_active") is not True or fields.get(field, {}).get("nonfinite_active") != 0:
                fail(f"non-finite {field} at frame {index}")
    assert publish.get("status") == "published_after_atomic_rename"
    assert publish.get("renderer_delegated_to_root023") is True
    assert publish.get("source_h5_opened_or_hashed_by_wrapper") is False
    assert publish.get("pvsm_private_stage_paths_rebound") is True
    assert publish.get("report_output_paths_rewritten_to_final_home") is True
    published_files = publish.get("files_excluding_receipt")
    if not isinstance(published_files, list) or len(published_files) != 838:
        fail("publish receipt does not enumerate all 838 published files")
    published_by_path = {item.get("relative_path"): item for item in published_files}
    for entry in evidence["contact_sheets"] + evidence["key_frames"]:
        item = published_by_path.get(entry["relative_path"])
        if item is None:
            fail(f"PNG absent from publish receipt: {entry['relative_path']}")
        if item.get("bytes") != entry["bytes_stat"] or item.get("sha256") != entry["producer_declared_sha256"]:
            fail(f"publish receipt disagrees with producer PNG metadata: {entry['relative_path']}")
    assert provenance.get("published_files_excluding_receipt") == 838
    assert publish.get("published_bytes_excluding_receipt") == 79057966

    roles = decision["scope_roles"]
    assert roles["roles_are_distinct"] is True
    assert roles["native_canonical_physical_condition_sha256"] == "83d6ff1798c49ce500aaf07d2319fac66f48d496d73fa1c044582fd9ec2b9024"
    assert roles["typed_legacy_owner_scope_sha256"] == "7b383a4e371948c22f8702cd9704844d1b16d8835fa12f203b688892fbc9f2a2"
    assert roles["xmf_physical_condition_sha256"] == roles["native_canonical_physical_condition_sha256"]
    assert roles["bed_source_definition_sha256"] == "da761772174d2a4ba20736647649b2e1117e48c55924426a3e24194057d366a7"
    assert roles["source_plan_file_sha256"] == "366adc5200604490871116a0a5b8503c9bef4bfb1e72195df94995605fa7d324"
    assert roles["native_source_plan_condition_present"] is False
    assert roles["native_source_plan_physical_condition_present"] is True
    assert roles["xmf_source_plan_condition_present"] is False
    assert roles["xmf_source_plan_physical_condition_present"] is True
    assert roles["prospective_canonical_preserved_separately"] == "9b51cce0a2f5940a8e6fdf2d284e407dd57f918fad42172eccfd498cbac1eaee"

    boundary = decision["read_boundary"]
    assert boundary["metadata_json_xml_xmf_code_read"] is True
    assert boundary["published_pngs_viewed"] is True
    assert boundary["scientific_payload_read_or_hashed"] is False
    assert boundary["new_job_started"] is False
    assert boundary["shared_state_written"] is False
    assert boundary["fresh191_modified"] is False

    for path in PACKAGE.rglob("*"):
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            fail(f"forbidden payload in fresh192 package: {path}")

    print("fresh192 personal visual package PASS")
    print("viewed=34 contacts + 9 keys")
    print(f"review_completed_at_utc={completed_at}")
    print("terminal=completed/0; atomic_publish=published_after_atomic_rename")
    print("science_payload_read_or_hashed=false; png_bytes_hashed_by_reviewer=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
