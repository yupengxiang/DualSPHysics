#!/usr/bin/env python3
"""Build the fresh192 personal visual decision from fresh191 metadata.

This source-only builder reads JSON metadata and stats published PNG paths. It
does not open or hash PNGs and does not access H5/BI4/IBI4/CSV/DAT/VTK data.
The timestamp is the recorded completion time of the personal view session.
"""

from __future__ import annotations

import json
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
FRESH191 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/"
    "root_followup_191_f3_assigned_f5_m110_t100_original1189_metadata_preflight_v1/"
    "metadata/m110-t100-original1189-preflight.json"
)
FRESH191_SHA = "f589fa0602851cdbbba4efe6fc15f6dd846bcaab088c1591a3f2e727ea3b4729"
REVIEW_COMPLETED_UTC = "2026-10-07T11:20:04.284231555+00:00"


def read_json(path: Path) -> dict:
    if path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}:
        raise RuntimeError(f"forbidden payload read: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def viewed_png(entry: dict, role: str) -> dict:
    path = Path(entry["path"])
    if path.suffix.lower() != ".png" or not path.exists():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "relative_path": entry["relative_path"],
        "role": role,
        "bytes_stat": path.stat().st_size,
        "producer_declared_sha256": entry["producer_declared_sha256"],
        "personally_viewed_with_view_image": True,
        "content_read_or_hashed_by_reviewer": False,
    }


def main() -> int:
    source = read_json(FRESH191)
    ident = source["case_identity"]
    runtime = source["runtime_contract"]
    render = source["upstream_evidence"]["render"]
    png_evidence = {
        "schema": "ds02.f3.assigned-f5.personal-visual-png-evidence.v1",
        "fresh_id": "fresh192",
        "case_id": ident["case_id"],
        "physical_case_id": ident["physical_case_id"],
        "review_completed_at_utc": REVIEW_COMPLETED_UTC,
        "render_report": render["report"],
        "publish_receipt": render["publish_receipt"],
        "contact_sheets": [viewed_png(x, "contact_sheet") for x in render["contact_sheets"]],
        "key_frames": [viewed_png(x, "key_frame") for x in render["key_frames"]],
        "review_boundary": {
            "view_method": "view_image",
            "published_pngs_opened": True,
            "png_bytes_hashed_by_reviewer": False,
            "scientific_payload_read_or_hashed": False,
        },
    }
    png_path = PACKAGE / "metadata" / "png-evidence" / "actual1189.json"
    png_path.write_text(json.dumps(png_evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    decision = {
        "schema": "ds02.f3.assigned-f5.personal-visual-decision.v2",
        "fresh_id": "fresh192",
        "assigned_worktree_family": "F3",
        "actual_case_family": "F5",
        "configured_model": "gpt-5.6-luna/max",
        "model_substitution": False,
        "case_id": ident["case_id"],
        "physical_case_id": ident["physical_case_id"],
        "visual_status": "visual-approved-by-delegated-agent",
        "case_credit": 0,
        "q_n": 0,
        "q_e": 0,
        "personal_review": {
            "reviewer": "production_recovery",
            "method": "view_image",
            "review_completed_at_utc": REVIEW_COMPLETED_UTC,
            "contact_sheets_viewed": len(png_evidence["contact_sheets"]),
            "key_frames_viewed": len(png_evidence["key_frames"]),
            "key_frame_indices": runtime["keyframe_indices"],
            "png_evidence": "metadata/png-evidence/actual1189.json",
            "all_required_published_pngs_viewed": True,
            "png_bytes_hashed_by_reviewer": False,
            "render_started_review_only_after_terminal_publish": True,
            "observations": [
                "Across all 34 contact sheets, the blue fluid body remains visually continuous and follows the channel and sloping-bed geometry from the initial gate state through the late frames.",
                "The nine requested navigation frames show a coherent gradual response with stable wall and bed geometry; no abrupt animation truncation is visible.",
                "At the rendered resolution, no obvious overall explosion, severe visible wall or bed penetration, abnormal initial state, or unexplained large-scale particle disappearance was seen.",
                "A small leading-edge detail is visible in some mid and late views; it is recorded as a display-level observation and is not interpreted as strict containment, sub-DP behavior, or numerical accuracy.",
            ],
            "screen_conclusion": "Passes the delegated first-stage visual screen; numerical precision, strict containment, sub-DP depth, run-up magnitude, and production acceptance remain outside this decision.",
        },
        "actual_provenance": {
            "fresh191_preflight_commit": "4492bb90c5f8d278b53db3d862f3f2881a6e6605",
            "fresh191_preflight": str(FRESH191),
            "fresh191_preflight_sha256": FRESH191_SHA,
            "qi_proof": source["qi_evidence"],
            "render_receipt": render["receipt"],
            "render_report": render["report"],
            "publish_receipt": render["publish_receipt"],
            "terminal_status": "completed/0",
            "atomic_publish_status": render["atomic_publish_status"],
            "actual_time_window_s": runtime["actual_time_window_s"],
            "published_files_excluding_receipt": render["published_files_excluding_receipt"],
            "published_bytes_excluding_receipt": render["published_bytes_excluding_receipt"],
        },
        "runtime_identity": {
            **runtime["counts"],
            "dimension": 3,
            "expected_contact_sheets": runtime["expected_contact_sheets"],
            "key_frame_indices": runtime["keyframe_indices"],
            "actual_time_window_s": runtime["actual_time_window_s"],
            "vector_shape": "N x 3",
            "all801_geometry_velocity_N3_times_UID_finite_verified": source["qi_evidence"]["all801_geometry_velocity_N3_times_UID_finite_verified"],
            "all_native_UIDs_active_each_frame": source["qi_evidence"]["all_native_UIDs_active_each_frame"],
        },
        "scope_roles": {
            "native_canonical_physical_condition_sha256": source["actual_scope"]["native_canonical"]["physical_condition_sha256"],
            "typed_legacy_owner_scope_sha256": source["actual_scope"]["typed_converter_legacy"]["physical_condition_sha256"],
            "xmf_physical_condition_sha256": source["actual_scope"]["xmf"]["physical_condition_sha256"],
            "xmf_source_plan_physical_condition_sha256": source["actual_scope"]["xmf"]["source_plan_physical_condition_sha256"],
            "native_source_plan_condition_present": source["actual_scope"]["native_canonical"]["source_plan_condition_presence"],
            "native_source_plan_physical_condition_present": source["actual_scope"]["native_canonical"]["source_plan_physical_condition_presence"],
            "xmf_source_plan_condition_present": source["actual_scope"]["xmf"]["source_plan_condition_presence"],
            "xmf_source_plan_physical_condition_present": source["actual_scope"]["xmf"]["source_plan_physical_condition_presence"],
            "bed_source_definition_sha256": source["actual_scope"]["source_definition_file"]["sha256"],
            "source_plan_file_sha256": source["actual_scope"]["source_plan_json"]["sha256"],
            "prospective_canonical_preserved_separately": source["actual_scope"]["prospective_canonical_preserved_separately"],
            "roles_are_distinct": True,
        },
        "retained_limits": {
            "initial_qa_precision_status": "negative_and_retained",
            "bed_diagnostic_bins": "not a numerical acceptance threshold",
            "sub_dp_depth": "not quantified",
            "strict_containment": "not asserted",
            "production_acceptance": "not asserted",
        },
        "read_boundary": {
            "metadata_json_xml_xmf_code_read": True,
            "published_pngs_viewed": True,
            "scientific_payload_read_or_hashed": False,
            "new_job_started": False,
            "shared_state_written": False,
            "fresh191_modified": False,
        },
    }
    decision_path = PACKAGE / "metadata" / "actual1189-personal-visual-decision.json"
    decision_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(decision_path)
    print(png_path)
    print(f"viewed={len(png_evidence['contact_sheets'])} contacts + {len(png_evidence['key_frames'])} keys at {REVIEW_COMPLETED_UTC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
