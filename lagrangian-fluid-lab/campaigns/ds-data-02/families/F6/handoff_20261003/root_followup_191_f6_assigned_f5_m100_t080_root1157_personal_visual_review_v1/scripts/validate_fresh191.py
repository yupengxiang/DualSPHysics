#!/usr/bin/env python3
"""Read-only validator for F6 fresh191 F5 M100/T080 visual evidence.

The validator reads JSON/XML/XMF metadata and published PNG visualizations.
It never opens H5/BI4/CSV/DAT/VTK scientific payloads and never launches work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ALLOWED_METADATA = {".json", ".xml", ".xmf"}
ALLOWED_VISUAL = {".png"}
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp", ".pvd", ".raw"}
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M100_T080_NEXT34"
PHYS = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M100_T080"
CANON = "984f9d8cbf42e1845e1f86d86faf2a9a2d7bcf9cf9f7e6c0556c41b58edd6b68"
LEGACY = "385f4332b4fdbe7127caac5f2a891a3cbd554b57c2695eb2cb158902a456e332"
SOURCEDEF = "cb23c5396ffc7d9eb5a48f119e65915b22bd158eb1af2367a1645bca46f0a25c"
COUNTS = {"fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658, "total": 194427}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_ref(item: dict, kind: str | None = None) -> Path:
    assert isinstance(item, dict) and {"path", "sha256", "bytes", "kind"} <= set(item), item
    p = Path(item["path"])
    assert p.is_file(), p
    assert p.suffix.lower() in (ALLOWED_METADATA | ALLOWED_VISUAL), p
    assert not any(str(p).lower().endswith(s) for s in FORBIDDEN), p
    assert sha(p) == item["sha256"], (p, "sha drift")
    assert p.stat().st_size == item["bytes"], (p, "size drift")
    if kind is not None:
        assert item["kind"] == kind, (p, item["kind"], kind)
    return p


def read_json_ref(ev: dict, key: str) -> tuple[Path, dict]:
    p = check_ref(ev[key], "metadata")
    return p, json.loads(p.read_text())


def completed_receipt(ev: dict, key: str) -> dict:
    p, d = read_json_ref(ev, key)
    assert d.get("schema") == "ds02.execution-receipt.v1", (p, d.get("schema"))
    assert d.get("status") == "completed", (p, d.get("status"))
    assert d.get("returncode") == 0, (p, d.get("returncode"))
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    pkg = args.package.resolve()
    decision = json.loads((pkg / "metadata/personal-visual-decision.json").read_text())
    assert decision["schema"] == "ds02.f6.fresh191.f5-personal-visual-review.v1"
    assert decision["fresh_id"] == "fresh191"
    assert decision["family_id"] == decision["assigned_family"] == "F6"
    assert decision["actual_family"] == "F5"
    assert decision["model"] == "gpt-5.6-luna" and decision["reasoning_effort"] == "max"
    assert decision["recursive_delegation"] is False
    predecessor = check_ref(decision["predecessor"], "metadata")
    assert predecessor.name == "final48-delivery.json" and "root_followup_190_f6_final48" in str(predecessor)

    case = decision["case"]
    assert case["case_id"] == CASE and case["physical_case_id"] == PHYS
    assert case["canonical_native_physical_condition_sha256"] == CANON
    assert case["actual_converter_legacy_scope_sha256"] == LEGACY
    assert case["bed_xmf_source_definition_scope_sha256"] == SOURCEDEF
    assert case["declared_counts"] == COUNTS and case["terminal_counts"] == COUNTS
    assert case["dimension"] == 3 and case["expected_frames"] == 801
    assert case["scope_roles"]["native_source_plan_condition_sha256"] is None
    assert case["scope_roles"]["xmf_source_plan_condition_sha256"] is None
    assert case["scope_roles"]["native_source_plan_physical_condition_sha256"] == CANON
    assert case["scope_roles"]["xmf_source_plan_physical_condition_sha256"] == CANON
    assert case["scope_roles"]["bed_source_plan_physical_condition_sha256"] == SOURCEDEF
    assert case["scope_roles"]["typed_actual_converter_legacy"] == LEGACY
    assert case["scope_roles"]["native_plan_equals_xmf_plan"] is True
    assert case["scope_roles"]["native_or_xmf_plan_equals_SourceDef"] is False
    assert case["scope_roles"]["equality_claimed"] is False
    assert case["source_plan_field_presence"]["native"]["source_plan_condition_sha256"] == {"present": False, "value": None}
    assert case["source_plan_field_presence"]["native"]["source_plan_physical_condition_sha256"] == {"present": True, "value": CANON}
    assert case["source_plan_field_presence"]["xmf"]["source_plan_condition_sha256"] == {"present": False, "value": None}
    assert case["source_plan_field_presence"]["xmf"]["source_plan_physical_condition_sha256"]["value"] == CANON
    assert case["source_plan_field_presence"]["bed_source_definition"]["source_plan_physical_condition_sha256"]["value"] == SOURCEDEF

    dec = decision["decision"]
    assert dec["status"] == "visual-approved-by-delegated-agent"
    assert dec["case_credit"] == 0 and dec["global_acceptance"] is False
    assert dec["precision_status"] == "not accepted"
    assert dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["production_approval"] is False
    assert "Root1350" in dec["main_process_qi"]
    for field in ("initial_state", "mechanism", "mid_event", "late_event", "failure_screen", "limits"):
        assert isinstance(dec["observations"][field], str) and dec["observations"][field]

    ev = decision["evidence"]
    for key, item in ev.items():
        check_ref(item, "metadata")
    for key in ("gencase_receipt", "initial_qa_receipt", "native_receipt", "typed_receipt", "xmf_receipt", "bed_receipt", "render_receipt"):
        completed_receipt(ev, key)

    qi_path, qi = read_json_ref(ev, "main_qi_proof")
    assert qi_path.name.endswith("proof.json")
    assert qi["case_id"] == CASE and qi["physical_case_id"] == PHYS and qi["full_frames"] == 801 and qi["particles"] == 194427
    assert qi["actual_native_source_plan_condition_field_present"] is False
    assert qi["actual_native_source_plan_condition_sha256"] is None
    assert qi["actual_native_source_plan_physical_condition_field_present"] is True
    assert qi["actual_native_source_plan_physical_condition_sha256"] == CANON
    assert qi["XMF_source_plan_physical_condition_field_sha256"] == CANON
    assert qi["XMF_source_plan_physical_condition_field_has_SourceDef_role"] is False
    assert qi["bed_declared_source_plan_field_sha256"] == SOURCEDEF
    assert qi["bed_declared_source_plan_field_has_SourceDef_role"] is True
    assert qi["actual_converter_legacy_scope_sha256"] == LEGACY
    assert qi["q_n_granted"] is False and qi["q_e_granted"] is False and qi["main_scientific_payload_IO"] is False

    prep_path, prep = read_json_ref(ev, "prepared_input_report")
    assert prep.get("case_id") == CASE, (prep_path, prep.get("case_id"))
    qa_path, qa = read_json_ref(ev, "initial_qa_report")
    assert qa["status"] == "completed_stage1_placement_mk50_diagnostic"
    assert qa["all_basic_placement_checks_pass"] is True and qa["arrays_opened_by_source_agent"] is False

    manifest_path, manifest = read_json_ref(ev, "xmf_manifest")
    assert manifest["schema"] == "ds02.stage1.paraview-temporal-product.v1"
    assert manifest["case_id"] == CASE and manifest["physical_case_id"] == PHYS
    assert manifest["frames"] == manifest["expected_frames"] == 801
    assert manifest["particles"] == manifest["expected_particles"] == 194427
    assert manifest["expected_dimension"] == 3
    assert manifest["actual_counts"] == {
        "data2d": False,
        "fixed_particles": 158559,
        "floating_particles": 0,
        "fluid_particles": 31658,
        "moving_particles": 4210,
        "solver_dimension": 3,
        "total_particles": 194427,
        "xml_particle_counts": {"fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210},
    }
    assert manifest["physical_condition_sha256"] == CANON
    assert manifest["source_plan_physical_condition_sha256"] == CANON
    assert manifest["canonical_physical_scope"]["physical_condition_sha256"] == CANON
    assert manifest["canonical_physical_scope"]["source_definition_sha256"] == SOURCEDEF
    assert manifest["physical_condition_hash_semantics"]["source_h5_sha256"] == LEGACY
    assert manifest["physical_condition_hash_semantics"]["roles_remain_distinct"] is True

    report_path, report = read_json_ref(ev, "render_report")
    assert report["schema"] == "ds02.stage1.paraview-full-animation-integrity.v1"
    assert report["frames"] == report["source_frames"] == 801
    assert report["all_frames_rendered"] is True
    assert report["actual_times_preserved_exactly"] is True
    assert report["native_identity_axis_preserved"] is True
    assert report["nonfinite_active_states"] == 0
    fs = report["frame_diagnostics"]
    assert len(fs) == 801 and fs[0]["frame"] == 0 and fs[-1]["frame"] == 800
    expected_types = {"fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658, "unknown": 0}
    for frame in fs:
        assert frame["active"] == 194427 and frame["missing"] == 0
        assert frame["finite_positions_active"] is True and frame["identity_axis_preserved"] is True
        assert frame["type_counts_active"] == expected_types
        assert frame["floating_points"] == 0 and frame["moving_points"] == 4210 and frame["fluid_points"] == 31658
        assert all(v["finite_active"] is True and v["nonfinite_active"] == 0 for v in frame["finite_fields"].values())

    publish_path, publish = read_json_ref(ev, "publish_receipt")
    assert publish["status"] == "published_after_atomic_rename"
    assert publish["source_h5_opened_or_hashed_by_wrapper"] is False
    published = {item["relative_path"]: item for item in publish["files_excluding_receipt"]}
    vr = decision["visual_review"]
    assert vr["personally_viewed_with"] == "view_image"
    assert vr["contact_sheet_count"] == 34 and len(vr["contact_sheets"]) == 34
    assert vr["key_frame_count"] == 9 and len(vr["key_frames"]) == 9
    assert vr["report_frames"] == vr["report_source_frames"] == 801
    for i, item in enumerate(vr["contact_sheets"]):
        p = check_ref(item, "visualization")
        assert item["viewed"] is True and item["sheet_index"] == i
        assert item["frame_start"] == i * 24 and item["frame_end"] == min(i * 24 + 23, 800)
        rel = f"all_frames_{i:03d}.png"
        assert published[rel]["sha256"] == item["sha256"] and published[rel]["bytes"] == item["bytes"]
        assert p.name == rel
    frames = [item["frame"] for item in vr["key_frames"]]
    assert frames == [0, 100, 200, 300, 400, 500, 600, 700, 800]
    for item in vr["key_frames"]:
        p = check_ref(item, "visualization")
        assert item["viewed"] is True and p.name == f"frame_{item['frame']:04d}.png"
        rel = f"frames/frame_{item['frame']:04d}.png"
        assert published[rel]["sha256"] == item["sha256"] and published[rel]["bytes"] == item["bytes"]

    boundaries = decision["source_boundaries"]
    for field in ("science_payload_read", "science_payload_hashed", "science_jobs_started", "shared_registry_or_ledger_written", "historical_source_changed", "model_substitution"):
        assert boundaries[field] is False
    assert decision["future_work"]["no_new_render_or_solver_request"] is True

    package_manifest = json.loads((pkg / "metadata/package-manifest.json").read_text())
    assert package_manifest["schema"] == "ds02.f6.fresh191.package-manifest.v1"
    assert package_manifest["fresh_id"] == "fresh191" and package_manifest["source_only"] is True
    for entry in package_manifest["files"]:
        p = pkg / entry["path"]
        assert p.is_file(), p
        assert p.stat().st_size == entry["bytes"], p
        assert sha(p) == entry["sha256"], p
    print("fresh191 validation PASS: F5 M100/T080 Root1157 completed/0; 801 frames; 34 contacts + 9 keys personally viewed; canonical/legacy/SourceDef scopes separate; condition-plan fields absent; no scientific payload IO; case credit 0")


if __name__ == "__main__":
    main()
