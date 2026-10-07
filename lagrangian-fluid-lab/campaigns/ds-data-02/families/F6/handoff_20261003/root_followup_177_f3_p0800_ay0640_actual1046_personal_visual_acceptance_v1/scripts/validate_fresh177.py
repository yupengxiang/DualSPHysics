#!/usr/bin/env python3
"""Read-only validator for F6 fresh177's F3 full836 visual evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

FORBIDDEN = (".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu")
ALLOWED = {".json", ".xml", ".xmf", ".png"}
RECEIPT_KEYS = (
    "gencase_preparation_receipt",
    "initial_parent_qa_receipt",
    "native_receipt",
    "typed_receipt",
    "xmf_receipt",
    "render_receipt",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_ref(item: dict, expected_kind: str | None = None) -> Path:
    assert isinstance(item, dict), item
    for key in ("path", "sha256", "bytes", "kind"):
        assert key in item, (key, item)
    path = Path(item["path"])
    assert path.is_file(), path
    lower = str(path).lower()
    assert not any(lower.endswith(suffix) for suffix in FORBIDDEN), path
    assert path.suffix.lower() in ALLOWED, path
    assert sha256(path) == item["sha256"], ("SHA drift", path)
    assert path.stat().st_size == item["bytes"], ("size drift", path)
    if expected_kind is not None:
        assert item["kind"] == expected_kind, (path, item["kind"], expected_kind)
    return path


def load_completed_receipt(item: dict) -> dict:
    path = check_ref(item, "metadata")
    data = json.loads(path.read_text())
    assert data.get("status") == "completed", (path, data.get("status"))
    assert data.get("returncode") == 0, (path, data.get("returncode"))
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=Path(__file__).parents[1])
    package = parser.parse_args().package

    decision = json.loads((package / "metadata/personal-visual-decision.json").read_text())
    closure = json.loads((package / "metadata/chain-closure.json").read_text())
    png_index = json.loads((package / "metadata/png-evidence.json").read_text())

    assert decision["schema"] == "ds02.f6.fresh177.f3-personal-visual-review.v1"
    assert decision["fresh_id"] == "fresh177"
    assert decision["family_id"] == "F6"
    assert decision["actual_case_family"] == "F3"
    assert decision["model"] == "gpt-5.6-luna"
    assert decision["reasoning_effort"] == "max"
    assert decision["recursive_delegation"] is False
    assert decision["reviewer"] == "/root/f6_endpoint_initial_qa"

    case = decision["case"]
    assert case["case_id"] == "F3_STAGE1_DP006_P0800_AY0640"
    assert case["physical_case_id"] == "F3_TWOAXIS_P0800_AY0640_STAGE1_FIRST48_PITCH_VARIANT"
    assert case["assigned_family"] == "F6"
    assert case["actual_physical_family"] == "F3"
    canonical = "b0c6ad866ca0852a24c1adb1351a845264ceff8a571647b43fed5d46bbabefcd"
    source_plan = "97da097c31403a9573ebb779afcab38e50dee2a24da3d8e1d523f017606ee7e2"
    assert case["canonical_native_physical_condition_sha256"] == canonical
    assert case["actual_converter_scope_sha256"] == canonical
    assert case["source_plan_scope_sha256"] == source_plan
    assert case["scope_roles"]["equality_claimed_to_source_plan"] is False
    assert case["parameters"] == {
        "dimension": 3,
        "dp_m": 0.006,
        "nominal_pitch_multiplier": 0.8,
        "save_interval_s": 0.01,
        "time_window_s": [0.0, 8.35],
        "transverse_amplitude_m_s2": 0.64,
    }
    assert case["native_counts_attested"] == {
        "total": 179208, "fixed": 111708, "moving": 0, "floating": 0, "fluid": 67500
    }

    decision_block = decision["decision"]
    assert decision_block["status"] == "visual-approved-by-delegated-agent"
    assert decision_block["case_credit"] == 0
    assert decision_block["global_acceptance"] is False
    assert decision_block["precision_status"] == "not accepted"
    assert decision_block["q_n_granted"] is False
    assert decision_block["q_e_granted"] is False
    assert decision_block["production_approval"] is False
    assert decision_block["new_scientific_job_started"] is False
    assert decision["source_boundaries"] == {
        "raw_H5_BI4_CSV_DAT_VTK_opened_or_hashed": False,
        "science_jobs_started": False,
        "science_payload_hashed": False,
        "science_payload_read": False,
        "shared_registry_or_ledger_written": False,
    }

    assert closure["schema"] == "ds02.f6.fresh177.f3-actual-chain-closure.v1"
    assert closure["fresh_id"] == "fresh177"
    assert closure["assigned_family"] == "F6"
    assert closure["actual_physical_family"] == "F3"
    assert closure["scope_roles"]["canonical_native_physical_condition_sha256"] == canonical
    assert closure["scope_roles"]["actual_converter_scope_sha256"] == canonical
    assert closure["scope_roles"]["source_plan_scope_sha256"] == source_plan
    assert closure["scope_roles"]["source_plan_is_not_converter_physical_scope"] is True
    assert closure["scope_roles"]["scope_equality_to_source_plan_claimed"] is False
    envelope = closure["registered_request_envelope"]
    assert envelope == {
        "actual_authority": "enabled-render-wrapper.json plus terminal paraview-full-animation-report.json and published PNG inventory",
        "actual_expected_contact_sheets": 35,
        "actual_expected_frames": 836,
        "actual_expected_particles": 179208,
        "historical_expected_contact_sheets": 34,
        "historical_expected_frames": 801,
        "historical_expected_particles": 194427,
        "stale_fields_reused_as_actual": False,
    }

    evidence = closure["evidence"]
    refs = []
    for key, item in evidence.items():
        if key in RECEIPT_KEYS:
            load_completed_receipt(item)
        else:
            check_ref(item, "metadata")
        refs.append(item)
    assert len(refs) == len(evidence)

    review = json.loads(Path(evidence["actual_producer_review"]["path"]).read_text())
    assert review["case_id"] == case["case_id"] if "case_id" in review else True
    assert review["physical_case_id"] == case["physical_case_id"]
    assert review["physical_condition_sha256"] == canonical
    assert review["all836_geometry_and_velocity_N3_and_exact_actual_times"] is True
    assert review["all836_native_UIDs_present"] is True
    assert review["case_credit"] == 0
    assert review["primary_scientific_payload_IO"] is False

    wrapper = json.loads(Path(evidence["render_wrapper"]["path"]).read_text())
    assert wrapper["expected_frames"] == 836
    assert wrapper["expected_particles"] == 179208
    assert wrapper["expected_contact_sheets"] == 35
    assert wrapper["keyframe_indices"] == [0, 104, 208, 312, 417, 521, 626, 730, 835]
    assert wrapper["physical_case_id"] == case["physical_case_id"]
    assert wrapper["actual_converter_scope_sha256"] == canonical

    registered = json.loads(Path(evidence["render_request"]["path"]).read_text())
    assert registered["expected_frames"] == 801
    assert registered["expected_particles"] == 194427
    assert registered["expected_contact_sheets"] == 34
    assert registered["case_id"] == case["case_id"]
    assert registered["physical_case_id"] == case["physical_case_id"]
    assert registered["physical_condition_sha256"] == canonical

    report_path = check_ref(evidence["render_report"], "metadata")
    report = json.loads(report_path.read_text())
    assert report["frames"] == 836
    assert report["source_frames"] == 836
    assert report["all_frames_rendered"] is True
    assert report["actual_times_preserved_exactly"] is True
    assert report["native_identity_axis_preserved"] is True
    assert report["nonfinite_active_states"] == 0
    assert report["diagnostic_only"] is False
    assert report["independent_case_increment"] == 0
    assert report["numerical_precision_status"] == "not accepted"
    assert len(report["outputs"]["contact_sheets"]) == 35

    publish = json.loads(Path(evidence["publish_receipt"]["path"]).read_text())
    assert publish["status"] == "published_after_atomic_rename"
    assert publish["source_h5_opened_or_hashed_by_wrapper"] is False
    assert publish["renderer_delegated_to_root023"] is True

    qi = json.loads(Path(evidence["root1269_qi_proof"]["path"]).read_text())
    assert qi["case_id"] == case["case_id"]
    assert qi["physical_case_id"] == case["physical_case_id"]
    assert qi["all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified"] is True
    assert qi["all_native_UIds_active_each_frame"] is True
    assert qi["new_case_credit"] == 0
    assert qi["q_n_granted"] is False and qi["q_e_granted"] is False
    assert qi["main_scientific_payload_IO"] is False

    assert png_index["schema"] == "ds02.f6.fresh177.published-png-evidence.v1"
    assert png_index["personally_viewed_with"] == "view_image"
    assert png_index["personal_view_completed"] is True
    assert png_index["contact_sheet_count"] == 35
    assert png_index["key_frame_count"] == 9
    assert png_index["key_frame_indices"] == [0, 104, 208, 312, 417, 521, 626, 730, 835]
    items = png_index["items"]
    contacts = [item for item in items if "sheet_index" in item]
    keys = [item for item in items if "frame" in item]
    assert len(contacts) == 35 and len(keys) == 9
    assert [item["sheet_index"] for item in contacts] == list(range(35))
    assert [item["frame"] for item in keys] == [0, 104, 208, 312, 417, 521, 626, 730, 835]
    assert all(item["viewed"] is True and item["viewed_with"] == "view_image" for item in items)
    assert all(item["kind"] == "visualization" for item in items)
    assert png_index["science_payload_read_or_hashed_by_this_package"] is False
    for item in items:
        check_ref(item, "visualization")

    life = decision["lifecycle_and_render_metadata"]
    assert life["frames"] == life["source_frames"] == 836
    assert life["expected_particles"] == 179208
    assert life["expected_contact_sheets"] == 35
    assert life["keyframe_indices"] == [0, 104, 208, 312, 417, 521, 626, 730, 835]
    assert life["actual_times_preserved_exactly"] is True
    assert life["native_identity_axis_preserved"] is True
    assert life["nonfinite_active_states"] == 0
    assert life["publish_status"] == "published_after_atomic_rename"

    print("fresh177 validation PASS: F3 P0800/AY0640; Root1046 completed/0 and published full836 verified; 35 contact sheets + 9 key frames personally viewed; scope roles and stale request envelope separated; case credit 0")


if __name__ == "__main__":
    main()
