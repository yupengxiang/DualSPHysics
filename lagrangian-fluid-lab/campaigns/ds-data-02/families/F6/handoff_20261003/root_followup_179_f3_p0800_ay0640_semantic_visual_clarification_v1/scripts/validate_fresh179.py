#!/usr/bin/env python3
"""Read-only validator for fresh179's immutable F3 semantic clarification."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

FORBIDDEN = (".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu")
ALLOWED = {".json", ".xml", ".xmf", ".png", ".md", ".py"}
VISUAL_ALLOWED = {".png"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_ref(item: dict, expected_kind: str | None = None, allowed=None) -> Path:
    assert isinstance(item, dict), item
    for key in ("path", "sha256", "bytes", "kind"):
        assert key in item, (key, item)
    path = Path(item["path"])
    assert path.is_file(), path
    low = str(path).lower()
    assert not any(low.endswith(suffix) for suffix in FORBIDDEN), path
    allowed = ALLOWED if allowed is None else allowed
    assert path.suffix.lower() in allowed, path
    assert sha256(path) == item["sha256"], ("SHA drift", path)
    assert path.stat().st_size == item["bytes"], ("size drift", path)
    if expected_kind is not None:
        assert item["kind"] == expected_kind, (path, item["kind"], expected_kind)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, default=Path(__file__).parents[1])
    pkg = ap.parse_args().package
    d = json.loads((pkg / "metadata/semantic-clarification.json").read_text())
    imm = json.loads((pkg / "metadata/source177-immutability.json").read_text())
    direct = json.loads((pkg / "metadata/direct-recheck-png-evidence.json").read_text())

    assert d["schema"] == "ds02.f6.fresh179.f3-rendered-type-semantics-correction.v1"
    assert d["fresh_id"] == "fresh179" and d["assigned_family"] == "F6"
    assert d["actual_physical_family"] == "F3"
    assert d["model"] == "gpt-5.6-luna" and d["reasoning_effort"] == "max"
    assert d["recursive_delegation"] is False
    assert d["reviewer"] == "/root/f6_endpoint_initial_qa"

    case = d["case"]
    assert case["case_id"] == "F3_STAGE1_DP006_P0800_AY0640"
    assert case["physical_case_id"] == "F3_TWOAXIS_P0800_AY0640_STAGE1_FIRST48_PITCH_VARIANT"
    canonical = "b0c6ad866ca0852a24c1adb1351a845264ceff8a571647b43fed5d46bbabefcd"
    source_condition_template_sha = "97da097c31403a9573ebb779afcab38e50dee2a24da3d8e1d523f017606ee7e2"
    assert case["canonical_native_scope_sha256"] == canonical
    assert case["actual_converter_scope_sha256"] == canonical
    assert case["source_condition_template_file_sha256"] == source_condition_template_sha
    assert "template file only" in case["source_condition_template_file_sha256_role"]
    assert case["source_namespace_is_separate_from_converter_and_native_xmf"] is True
    namespace = case["source_namespace"]
    assert namespace["condition_sha256"] == source_condition_template_sha
    assert namespace["condition_sha256_role"].startswith("SHA256 of condition_path/source-condition-template.json")
    assert namespace["source_physical_condition_sha256"] is None
    assert namespace["status"] == "preserved source/template namespace; not used as converter scope"
    assert case["actual_converter_scope_fields"]["computed_scope_sha256"] == canonical
    assert case["actual_converter_scope_fields"]["expected_sha256"] == canonical
    assert case["actual_converter_scope_fields"]["preflight_payload_opened"] is False
    assert case["actual_converter_scope_fields"]["preflight_payload_hashed"] is False
    assert case["native_source_plan_physical_condition_field_present"] is False
    assert case["xmf_source_plan_physical_condition_field_present"] is False
    assert case["native_source_plan_physical_condition_field_value"] is None
    assert case["xmf_source_plan_physical_condition_field_value"] is None

    assert imm["schema"] == "ds02.f6.fresh179.source177-immutability.v1"
    assert imm["source_fresh_id"] == "fresh177"
    assert imm["source177_commit"] == "c025e12e62f3c0b5508be4f533572726e57c015d"
    assert imm["modification_policy"]["source177_modified_by_fresh179"] is False
    assert imm["modification_policy"]["semantic_clarification_only"] is True
    source177_refs = imm["source177_files"]
    assert len(source177_refs) == 5
    for item in source177_refs:
        check_ref(item, "source")

    # Verify the original decision and its original full PNG evidence without mutating it.
    source177_decision_path = next(Path(item["path"]) for item in source177_refs if item["path"].endswith("metadata/personal-visual-decision.json"))
    source177_png_path = next(Path(item["path"]) for item in source177_refs if item["path"].endswith("metadata/png-evidence.json"))
    source177_decision = json.loads(source177_decision_path.read_text())
    assert source177_decision["schema"] == "ds02.f6.fresh177.f3-personal-visual-review.v1"
    assert source177_decision["decision"]["status"] == "visual-approved-by-delegated-agent"
    assert source177_decision["case"]["native_counts_attested"]["moving"] == 0
    assert source177_decision["case"]["native_counts_attested"]["floating"] == 0
    assert "moving/floating bodies" in source177_decision["observations"]["initial_state"]
    assert "evolving body motion" in source177_decision["observations"]["mechanism"]
    assert "body/fluid interaction" in source177_decision["observations"]["mid_event"]
    source177_png = json.loads(source177_png_path.read_text())
    assert source177_png["personally_viewed_with"] == "view_image"
    assert source177_png["contact_sheet_count"] == 35 and source177_png["key_frame_count"] == 9
    assert len(source177_png["items"]) == 44
    for item in source177_png["items"]:
        check_ref(item, "visualization", VISUAL_ALLOWED)

    # Validate the six images that were reopened for the semantic correction.
    assert direct["schema"] == "ds02.f6.fresh179.direct-png-recheck.v1"
    assert direct["tool"] == "view_image" and direct["direct_recheck_completed"] is True
    assert direct["source177_full_review_counts"] == {
        "contact_sheets": 35,
        "key_frames": 9,
        "original_review_record_is_immutable": True,
    }
    assert len(direct["items"]) == 6
    assert sorted(item["index"] for item in direct["items"] if item["kind"] == "visualization" and "frame_" in Path(item["path"]).name) == [0, 417, 835]
    assert sorted(item["index"] for item in direct["items"] if "all_frames_" in Path(item["path"]).name) == [0, 17, 34]
    assert all(item["viewed_with"] == "view_image" and item["viewed_again"] is True for item in direct["items"])
    for item in direct["items"]:
        check_ref(item, "visualization", VISUAL_ALLOWED)
    check_ref(direct["source177_full_review_record"], "metadata")

    report_path = check_ref(d["recheck"]["render_report"], "metadata")
    report = json.loads(report_path.read_text())
    assert report["frames"] == report["source_frames"] == 836
    assert report["actual_times_preserved_exactly"] is True
    assert report["native_identity_axis_preserved"] is True
    assert report["nonfinite_active_states"] == 0
    assert report["type_aliases"] == {"fixed": [0], "floating": [2], "fluid": [3], "moving": [1]}
    assert report["boundary_display"]["actual_fixed_points_shown"] is True
    assert "native fluid blue points" in report["rendering"]
    assert "fixed-boundary cutaway points" in report["rendering"]

    owner_path = check_ref(d["recheck"]["source124_owner"], "metadata")
    owner = json.loads(owner_path.read_text())
    owner_namespace = owner["source_namespace"]
    assert owner_namespace["condition_sha256"] == source_condition_template_sha
    assert owner_namespace["source_physical_condition_sha256"] is None
    assert owner_namespace["status"] == "preserved source/template namespace; not used as converter scope"
    owner_scope = owner["actual_converter_scope"]
    assert owner_scope["computed_scope_sha256"] == canonical
    assert owner_scope["expected_sha256"] == canonical
    template_path = check_ref(d["recheck"]["source_condition_template_file"], "metadata")
    assert hashlib.sha256(template_path.read_bytes()).hexdigest() == source_condition_template_sha
    assert template_path == Path(owner_namespace["condition_path"])

    proof_path = check_ref(d["recheck"]["root1269_proof"], "metadata")
    proof = json.loads(proof_path.read_text())
    assert proof["all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified"] is True
    assert proof["all_native_UIds_active_each_frame"] is True
    assert proof["native_source_plan_physical_condition_field_present"] is False
    assert proof["XMF_source_plan_physical_condition_field_present"] is False
    assert proof["native_request_condition_sha256"] == canonical
    assert proof["actual_converter_condition_sha256"] == canonical
    assert proof["q_n_granted"] is False and proof["q_e_granted"] is False
    assert proof["new_case_credit"] == 0

    prep_path = check_ref(d["recheck"]["prepared_input_report"], "metadata")
    prep = json.loads(prep_path.read_text())
    assert prep["physical_condition_sha256"] == canonical
    assert prep["generated_particle_counts"] == {"fixed": 111708, "moving": 0, "floating": 0, "fluid": 67500}
    assert prep["expected_frames"] == 836
    assert prep["nominal_pitch_multiplier"] == 0.8
    assert prep["transverse_amplitude_m_s2"] == 0.64

    actual = d["actual_type_evidence"]
    assert actual["generated_particle_counts"] == {"total": 179208, "fixed": 111708, "moving": 0, "floating": 0, "fluid": 67500}
    assert actual["render_report_type_aliases"] == {"fixed": [0], "floating": [2], "fluid": [3], "moving": [1]}
    assert actual["fixed_boundary_is_shown"] is True
    assert actual["render_frames"] == actual["render_source_frames"] == 836

    corr = d["semantic_correction"]
    assert corr["classification"] == "template_semantic_misuse_confirmed_by_actual_counts_and_rendered_type_legend"
    assert corr["original_body_language_is_physical_claim"] is False
    assert corr["new_physical_failure_identified"] is False
    corrected = corr["corrected_fields"]
    assert "moving or floating body" in corrected["initial_state"]
    assert "No rigid-body release" in corrected["mechanism"]
    assert "template carry-over" in corrected["mid_event"]
    assert "no moving/floating body" in corrected["late_event"]
    assert d["decision"] == {
        "case_credit": 0,
        "global_acceptance": False,
        "new_scientific_job_started": False,
        "new_visual_credit": 0,
        "precision_status": "not accepted",
        "production_approval": False,
        "q_e_granted": False,
        "q_n_granted": False,
        "source177_visual_decision_unchanged": True,
        "status": "semantic-clarification-only-source177-immutable",
    }
    assert d["source_boundaries"] == {
        "raw_H5_BI4_CSV_DAT_VTK_opened_or_hashed": False,
        "science_jobs_started": False,
        "science_payload_hashed": False,
        "science_payload_read": False,
        "shared_registry_or_ledger_written": False,
    }
    print("fresh179 validation PASS: source177 byte-exact; actual F3 types fixed=111708/fluid=67500/moving=0/floating=0; six PNGs directly rechecked; semantic correction only; no credit")


if __name__ == "__main__":
    main()
