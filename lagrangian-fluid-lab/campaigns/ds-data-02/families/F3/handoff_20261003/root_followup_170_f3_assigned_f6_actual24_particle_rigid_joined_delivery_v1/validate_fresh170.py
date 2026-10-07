#!/usr/bin/env python3
"""Validate fresh170 using JSON metadata only.

This validator opens only JSON source products and the package's own JSON.
It never opens or hashes referenced XMF, PNG, CSV, H5, BI4, DAT, VTK, or other
scientific payloads. Referenced non-JSON hashes are producer attestations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
JOINED = HERE / "metadata/f6-first24-particle-rigid-joined-delivery.json"
ROOT1276 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_sources178164_actual_F2_F3_F6_first24_delivery72_correct_"
    "own_primary_XMF_PNG_8_subset24_subset48_1276"
)
MAIN1276 = ROOT1276 / "MAIN_ACTUAL_F2_F3_F6_FIRST24_DELIVERY72.json"
F6DEL = ROOT1276 / "F6-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json"
ROOT1305 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F6_actual48_fulltime_official_rigid_motion_47new241rows_"
    "one_existing_history_CPU2_and_pendingF5_1131_1180_ownQI_checkpoint_1305/"
    "F6-FINAL48-FULLTIME-RIGID-MOTION-DELIVERY.json"
)
FORBIDDEN_SUFFIXES = {
    ".csv", ".ibi4", ".bi4", ".h5", ".dat", ".vtk", ".vtu", ".pvtu", ".xmf", ".png"
}
REQUIRED_RIGID_FIELDS = {
    "part", "time [s]", "fvel.x [m/s]", "fvel.y [m/s]", "fvel.z [m/s]",
    "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]",
    "center.x [m]", "center.y [m]", "center.z [m]", "surge [m]",
    "sway [m]", "heave [m]", "roll [deg]", "pitch [deg]", "yaw [deg]",
}


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"{label} is not JSON: {path}")
    require(path.is_file(), f"missing {label}: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{label} must be a JSON object: {path}")
    return value


def json_sha(path: Path, label: str) -> str:
    require(path.suffix.lower() == ".json", f"only JSON may be hashed: {label}")
    require(path.is_file(), f"missing JSON to hash {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_hex64(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def ref_equal(actual: Any, expected: Any, label: str) -> None:
    require(actual == expected, f"{label} was not copied verbatim from the authoritative source row")


def selected_particle(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "accepted_decision", "actual_render_report", "actual_xmf_manifest", "actual_xmf_xml",
        "contact_png_refs", "key_png_refs", "render_receipt_refs", "native_refs", "typed_refs",
        "gencase_or_definition_refs", "initial_qa_or_audit_refs", "owner_or_source_refs",
        "primary_visual_evidence", "source_declared_roles", "native_request_role_snapshot",
        "evidence_scope", "all_allowed_refs",
    )
    return {key: row.get(key) for key in keys}


def selected_rigid(row: dict[str, Any]) -> dict[str, Any]:
    if row["physical_case_id"] == "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE":
        keys = (
            "historical_actual_scientific_case_alias", "stage1_visual_acceptance_snapshot",
            "fulltime_rigid_status", "actual_export_receipt", "actual_export_report",
            "actual_rigid_audit_receipt", "official_rigid_motion_CSV", "frames",
            "full_saved_rigid_history_finite_and_monotone_through12", "actual_time_window_s",
            "legacy_Part_column_validation_field_present", "legacy_Part_unique_count",
            "legacy_scope_and_Part_absences_not_fabricated",
            "actual_rigid_motion_from_official_FloatingInfo_not_particle_velocity", "case_credit",
        )
        out = {key: row.get(key) for key in keys}
        out["baseline_part_validation_role"] = (
            "historical baseline; independent fresh170 Part0..240 validation remains false/null"
        )
        return out
    keys = (
        "fulltime_rigid_status", "actual_native_condition_sha256",
        "source_scope_roles_snapshot_preserved", "actual_runner_request",
        "actual_export_receipt", "actual_export_report", "actual_complete_native_receipt",
        "official_rigid_motion_CSV", "frames", "required_rigid_fields_finite_all241",
        "required_fields_with_units", "official_all_CSV_fields_headers_preserved",
        "actual_Part_frame_index_first_last", "actual_Part_unique_count", "actual_time_window_s",
        "native_time_source", "native_time_tolerance_s", "max_abs_actual_native_time_delta_s",
        "official_times_not_resampled", "science_input_inventory_report",
        "scientific_input_IBI4_SHA_producer_attested",
        "scientific_input_hashes_match_at_launch_and_after_run",
        "rigid_states_not_inferred_from_particle_velocity",
        "existing_solver_mass_and_particle_omission_limits_not_overridden", "case_credit",
    )
    return {key: row.get(key) for key in keys}


def validate_reference_tree(value: Any, label: str) -> None:
    """Validate metadata refs without opening the referenced payload."""
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            path = value.get("path")
            require(isinstance(path, str) and path, f"{label} ref path missing")
            require(is_hex64(value.get("sha256")), f"{label} ref SHA is not 64 hex")
        for key, child in value.items():
            validate_reference_tree(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_reference_tree(child, f"{label}[{index}]")


def validate_particle_refs(particle: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    ref_equal(particle, expected, f"{label}.particle_dynamic_xmf_and_visual_refs")
    manifest = particle.get("actual_xmf_manifest")
    xml = particle.get("actual_xmf_xml")
    report = particle.get("actual_render_report")
    require(isinstance(manifest, dict) and isinstance(xml, dict) and isinstance(report, dict), f"{label} primary XMF/render refs missing")
    require(str(manifest.get("path", "")).lower().endswith(".json"), f"{label} XMF manifest is not JSON metadata")
    require(str(xml.get("path", "")).lower().endswith(".xmf"), f"{label} XMF XML reference is not preserved")
    require(str(report.get("ref", {}).get("path", "")).lower().endswith(".json"), f"{label} render report is not JSON metadata")
    require(manifest.get("sha256") == manifest.get("declared_sha256"), f"{label} manifest SHA declaration mismatch")
    require(xml.get("sha256") == xml.get("declared_sha256"), f"{label} XMF XML SHA declaration mismatch")
    metadata = report.get("metadata", {})
    primary = particle.get("primary_visual_evidence", {})
    require(metadata.get("frames") == 241 and metadata.get("source_frames") == 241, f"{label} particle frame metadata is not 241")
    require(metadata.get("all_frames_rendered") is True and metadata.get("diagnostic_only") is False, f"{label} particle report is not a full render")
    require(primary.get("manifest_sha256_matches_render_report") is True, f"{label} render/XMF manifest binding is not closed")
    require(primary.get("primary_refs_case_local") is True, f"{label} primary refs are not case-local")
    require(isinstance(particle.get("contact_png_refs"), list) and particle.get("contact_png_refs"), f"{label} contacts missing")
    require(isinstance(particle.get("key_png_refs"), list) and particle.get("key_png_refs"), f"{label} key PNG refs missing")
    validate_reference_tree(particle, label)


def validate_rigid_join(rigid: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    ref_equal(rigid, expected, f"{label}.rigid_motion_join")
    if label.endswith("baseline"):
        require(rigid.get("legacy_Part_column_validation_field_present") is False, f"{label} baseline Part field was promoted")
        require(rigid.get("legacy_Part_unique_count") is None, f"{label} baseline Part count was fabricated")
        require(rigid.get("baseline_part_validation_role", "").endswith("false/null"), f"{label} baseline boundary missing")
        return
    require(rigid.get("fulltime_rigid_status") == "completed/0,241rows", f"{label} rigid export status mismatch")
    require(rigid.get("frames") == 241 and rigid.get("required_rigid_fields_finite_all241") is True, f"{label} rigid frame/finite contract mismatch")
    require(set(rigid.get("required_fields_with_units", [])) == REQUIRED_RIGID_FIELDS, f"{label} required unit-bearing fields mismatch")
    require(rigid.get("actual_Part_frame_index_first_last") == [0, 240] and rigid.get("actual_Part_unique_count") == 241, f"{label} Part coverage mismatch")
    require(rigid.get("native_time_tolerance_s") == 1e-6 and rigid.get("max_abs_actual_native_time_delta_s", 1) <= 1e-6, f"{label} native time tolerance mismatch")
    require(rigid.get("official_times_not_resampled") is True, f"{label} time resampling boundary changed")
    csv = rigid.get("official_rigid_motion_CSV", {})
    require(str(csv.get("path", "")).lower().endswith(".csv") and is_hex64(csv.get("sha256_producer_attested")), f"{label} producer CSV attestation missing")
    require(csv.get("main_payload_read_or_hashed") is False, f"{label} payload boundary changed")
    require(rigid.get("case_credit") == 0, f"{label} rigid case credit changed")
    validate_reference_tree(rigid, label)


def validate() -> dict[str, Any]:
    joined = load_json(JOINED, "fresh170 joined delivery")
    main = load_json(MAIN1276, "Root1276 main delivery72")
    f6 = load_json(F6DEL, "Root1276 F6 actual24")
    final = load_json(ROOT1305, "Root1305 F6 final48 rigid product")
    require(main.get("schema") == "ds02.main.actual-first24-dynamic-product-delivery.v1", "Root1276 schema mismatch")
    require(f6.get("family_id") == "F6" and f6.get("actual_first24_count") == 24, "Root1276 F6 count mismatch")
    require(final.get("schema") == "ds02.main.F6.final48.fulltime-rigid-motion-delivery.v1", "Root1305 schema mismatch")
    require(final.get("fulltime_complete_cases") == 48 and len(final.get("rows", [])) == 48, "Root1305 final48 mismatch")
    require(json_sha(MAIN1276, "Root1276 main") == joined["source_products"]["root1276_main_delivery72"]["sha256"], "Root1276 main SHA mismatch")
    require(json_sha(F6DEL, "Root1276 F6") == joined["source_products"]["root1276_f6_actual_first24"]["sha256"], "Root1276 F6 SHA mismatch")
    require(json_sha(ROOT1305, "Root1305 final") == joined["source_products"]["root1305_f6_final48_rigid_motion"]["sha256"], "Root1305 SHA mismatch")

    first8 = f6.get("frozen_first8_physical_case_ids", [])
    first24 = f6.get("actual_first24_physical_case_ids", [])
    registered48 = f6.get("registered_final48_physical_case_ids", [])
    require(len(first8) == 8 and len(first24) == 24 and len(registered48) == 48, "membership counts mismatch")
    require(len(set(first8)) == 8 and len(set(first24)) == 24 and len(set(registered48)) == 48, "membership IDs are not unique")
    require(set(first8) <= set(first24) <= set(registered48), "frozen8/actual24/registered48 subset relation failed")
    require(f6.get("first8_subset_actual24_subset_registered48") is True, "Root1276 subset flag changed")
    require(joined.get("membership", {}).get("frozen_first8_physical_case_ids") == first8, "joined first8 order changed")
    require(joined.get("membership", {}).get("actual_first24_physical_case_ids") == first24, "joined first24 order changed")
    require(joined.get("membership", {}).get("registered_final48_physical_case_ids") == registered48, "joined final48 order changed")

    src_rows = {row["physical_case_id"]: row for row in f6["actual_own_primary_rows"]}
    rigid_rows = {row["physical_case_id"]: row for row in final["rows"]}
    rows = joined.get("rows", [])
    require(len(rows) == 24, "joined rows are not 24")
    require([row.get("physical_case_id") for row in rows] == first24, "joined row order/identity mismatch")
    for index, row in enumerate(rows, start=1):
        physical = row.get("physical_case_id")
        label = f"row[{index}]/{physical}"
        require(physical in src_rows and physical in rigid_rows, f"{label} not present in both authoritative products")
        source = src_rows[physical]; expected_rigid = selected_rigid(rigid_rows[physical])
        require(row.get("case_id") == source.get("case_id") and row.get("family_id") == "F6", f"{label} identity mismatch")
        membership = row.get("membership", {})
        require(membership.get("first8_member") is (physical in first8), f"{label} first8 flag mismatch")
        require(membership.get("actual_first24_member") is True and membership.get("registered_final48_member") is True, f"{label} subset flags mismatch")
        validate_particle_refs(row.get("particle_dynamic_xmf_and_visual_refs", {}), selected_particle(source), label)
        validate_rigid_join(row.get("rigid_motion_join", {}), expected_rigid, label + ("/baseline" if physical == "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE" else "/new"))
        credit = row.get("credit_and_precision", {})
        require(credit.get("case_credit") == 0 and credit.get("new_visual_credit") == 0 and credit.get("Q_N") == 0 and credit.get("Q_E") == 0, f"{label} credit changed")

    baseline = joined.get("baseline_boundary", {})
    require(baseline.get("physical_case_id") == "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE", "baseline boundary identity changed")
    require(baseline.get("legacy_Part_column_validation_field_present") is False and baseline.get("legacy_Part_unique_count") is None, "baseline Part absence changed")
    require(baseline.get("part_validation_independently_verified_by_fresh170") is False, "baseline Part verification overstated")
    require(baseline.get("part_validation_value") == "false/null; historical baseline alias is not a 47-new-export Part certificate", "baseline Part value boundary changed")
    limits = joined.get("product_limits", {})
    require(limits.get("new_case_credit") == 0 and limits.get("new_visual_credit") == 0 and limits.get("Q_N") == 0 and limits.get("Q_E") == 0, "product credit changed")
    require(limits.get("numeric_precision_accepted") is False and limits.get("scientific_payload_read_or_hashed_by_source") is False, "product boundary changed")
    require(joined.get("join_contract", {}).get("join_key") == "physical_case_id", "join key changed")
    require(joined.get("join_contract", {}).get("no_directory_or_alias_join") is True, "alias join boundary changed")
    packaged_forbidden = [p for p in HERE.rglob("*") if p.is_file() and p.suffix.lower() in FORBIDDEN_SUFFIXES]
    require(not packaged_forbidden, f"scientific payload packaged: {packaged_forbidden}")
    return {"status":"PASS","joined_actual_first24":24,"frozen_first8":8,"registered_final48":48,"baseline_part":"false/null","source_payload_IO":False}


if __name__ == "__main__":
    try:
        result = validate()
    except ValidationError as exc:
        print(f"fresh170 validator: FAIL: {exc}")
        raise SystemExit(1)
    print("fresh170 validator: PASS " + json.dumps(result, sort_keys=True))
