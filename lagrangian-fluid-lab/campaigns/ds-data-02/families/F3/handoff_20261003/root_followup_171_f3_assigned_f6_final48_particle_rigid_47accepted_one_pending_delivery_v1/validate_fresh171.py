#!/usr/bin/env python3
"""Read-only validator for fresh171.

Only JSON metadata is opened and hashed.  Referenced XMF/XML/PNG/CSV/H5/BI4/
DAT/VTK files are checked with existence/stat only; their content is never read
or hashed by this validator.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "F6-FINAL48-PARTICLE-RIGID-47ACCEPTED-ONE-PENDING.json"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
CP = HANDOFF / (
    "root_stage1_source170_F6_fixedactual24_particle_XMF_fulltime_rigid_join_"
    "same_native_receipts_times_and_baseline_absence_main_delivery_1313/"
    "full336-current295-actual-final48-delivery-progress-index.json"
)
ROOT1313 = HANDOFF / (
    "root_stage1_source170_F6_fixedactual24_particle_XMF_fulltime_rigid_join_"
    "same_native_receipts_times_and_baseline_absence_main_delivery_1313/"
    "F6-ACTUAL_FIRST24-PARTICLE-RIGID-JOINED-DELIVERY.json"
)
ROOT1305 = HANDOFF / (
    "root_stage1_F6_actual48_fulltime_official_rigid_motion_47new241rows_"
    "one_existing_history_CPU2_and_pendingF5_1131_1180_ownQI_checkpoint_1305/"
    "F6-FINAL48-FULLTIME-RIGID-MOTION-DELIVERY.json"
)
ROOT1320 = HANDOFF / (
    "root_stage1_F6_47_actual_native_receipts_34_old_nulls_recovered_full336_331_unique_digest_"
    "five_true_legacy_absences_1320/full336-native-field-role-closure-331-unique-five-real-absences.json"
)
FORBIDDEN_PACKAGED_SUFFIXES = {".h5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu", ".xmf", ".png"}
PENDING = "F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025"
BASELINE = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE"


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load_json(path: Path, label: str) -> Any:
    require(path.suffix.lower() == ".json", f"{label} is not JSON: {path}")
    require(path.is_file(), f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"invalid JSON {label}: {path}: {exc}") from exc


def json_sha(path: Path, label: str) -> str:
    require(path.suffix.lower() == ".json", f"only JSON may be hashed: {label}: {path}")
    require(path.is_file(), f"missing JSON {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_source_ref(ref: dict[str, Any], label: str) -> None:
    path = Path(ref.get("path", ""))
    require(path.suffix.lower() == ".json", f"{label} source is not JSON: {path}")
    expected = ref.get("sha256")
    require(isinstance(expected, str) and len(expected) == 64, f"{label} source SHA missing")
    require(json_sha(path, label) == expected, f"{label} source SHA drifted")


def check_metadata_ref(ref: Any, label: str, require_exists: bool = True) -> None:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise ValidationError(f"{label} is not a path ref")
    path = Path(ref["path"])
    probe = ref.get("metadata_probe") if isinstance(ref.get("metadata_probe"), dict) else {}
    if require_exists:
        require(path.is_file(), f"missing {label}: {path}")
    if path.suffix.lower() == ".json" and path.is_file():
        actual = json_sha(path, label)
        if isinstance(probe.get("json_sha256"), str):
            require(actual == probe["json_sha256"], f"{label} JSON changed since package build")
        if probe.get("declared_sha256_matches_json") is False:
            raise ValidationError(f"{label} producer-declared JSON SHA did not match at package build")
    else:
        # Scientific/visual non-JSON paths are only stat-checked.  This
        # includes XMF/XML, PNG, CSV, H5 and BI4; no bytes are opened here.
        require(probe.get("content_read_or_hashed") is False, f"{label} payload was opened by package validator")
        require(path.is_file(), f"missing non-JSON metadata target {label}: {path}")


def check_png_ref(ref: Any, label: str) -> None:
    require(isinstance(ref, dict) and isinstance(ref.get("path"), str), f"{label} PNG ref malformed")
    path = Path(ref["path"])
    require(path.suffix.lower() == ".png", f"{label} is not PNG")
    require(path.is_file(), f"missing {label}: {path}")
    probe = ref.get("metadata_probe", {})
    require(probe.get("content_read_or_hashed") is False, f"{label} PNG content boundary changed")


def check_primary(row: dict[str, Any], label: str) -> None:
    visual = row["accepted_visual_metadata"]
    manifest = visual.get("actual_xmf_manifest")
    xml = visual.get("actual_xmf_xml")
    report = visual.get("actual_render_report")
    receipt = visual.get("actual_render_receipt")
    for ref, name in ((manifest, "XMF manifest"), (xml, "XMF XML"), (report, "render report"), (receipt, "render receipt")):
        require(isinstance(ref, dict), f"{label} primary {name} missing")
        check_metadata_ref(ref, f"{label} primary {name}")
    require(str(manifest["path"]).lower().endswith(".json"), f"{label} XMF manifest is not JSON")
    require(str(xml["path"]).lower().endswith(".xmf"), f"{label} XMF XML path is not .xmf")
    require(str(report["path"]).lower().endswith(".json"), f"{label} render report is not JSON")
    require(str(receipt["path"]).lower().endswith(".json"), f"{label} render receipt is not JSON")
    require(visual.get("primary_visual_evidence", {}).get("primary_refs_are_selected_from_own_decision_or_own_closure") is True,
            f"{label} visual refs were not selected from own decision/closure")
    contacts = visual.get("contact_png_refs")
    require(isinstance(contacts, list) and contacts, f"{label} contact PNG refs absent")
    for i, ref in enumerate(contacts):
        if isinstance(ref, dict) and isinstance(ref.get("path"), str):
            check_png_ref(ref, f"{label}.contact[{i}]")
    keys = visual.get("key_png_refs")
    require(isinstance(keys, list), f"{label} key PNG field absent")
    for i, ref in enumerate(keys):
        if isinstance(ref, dict) and isinstance(ref.get("path"), str):
            check_png_ref(ref, f"{label}.key[{i}]")
    evidence = visual.get("primary_visual_evidence", {})
    if not keys:
        require(evidence.get("named_key_png_paths_available") is False, f"{label} missing key paths not disclosed")
        require(isinstance(evidence.get("key_png_paths_absent_reason"), str), f"{label} key path absence reason missing")
    # Native/typed/QA/owner refs are metadata JSON or stat-only producer refs.
    for group in ("native_refs", "typed_refs", "gencase_or_definition_refs", "initial_qa_or_audit_refs", "owner_or_source_refs"):
        for i, ref in enumerate(visual.get(group, [])):
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                check_metadata_ref(ref, f"{label}.{group}[{i}]")


def check_rigid(row: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    require(row.get("rigid_motion_join") == expected, f"{label} rigid row is not copied from Root1305")
    rigid = row["rigid_motion_join"]
    require(rigid.get("case_credit") == 0, f"{label} rigid case credit changed")
    if row["physical_case_id"] == BASELINE:
        require(rigid.get("legacy_Part_column_validation_field_present") is False, f"{label} baseline Part field promoted")
        require(rigid.get("legacy_Part_unique_count") is None, f"{label} baseline Part count fabricated")
        return
    require(rigid.get("fulltime_rigid_status") == "completed/0,241rows", f"{label} rigid status mismatch")
    require(rigid.get("frames") == 241, f"{label} rigid frame count mismatch")
    require(rigid.get("required_rigid_fields_finite_all241") is True, f"{label} rigid finite claim missing")
    require(rigid.get("actual_Part_frame_index_first_last") == [0, 240], f"{label} Part endpoints mismatch")
    require(rigid.get("actual_Part_unique_count") == 241, f"{label} Part count mismatch")
    require(rigid.get("native_time_tolerance_s") == 1e-6, f"{label} time tolerance mismatch")
    require(rigid.get("max_abs_actual_native_time_delta_s", 1) <= 1e-6, f"{label} native-time delta exceeds tolerance")
    require(rigid.get("official_times_not_resampled") is True, f"{label} time resampling boundary changed")
    csv = rigid.get("official_rigid_motion_CSV", {})
    require(isinstance(csv, dict) and str(csv.get("path", "")).lower().endswith(".csv"), f"{label} CSV ref missing")
    require(csv.get("main_payload_read_or_hashed") is False, f"{label} CSV payload boundary changed")
    # CSV is a scientific payload: only the path/stat boundary is checked.
    check_metadata_ref({"path": csv["path"], "metadata_probe": {"content_read_or_hashed": False}}, f"{label} official CSV")


def validate() -> dict[str, Any]:
    catalog = load_json(CATALOG, "fresh171 catalog")
    cp = load_json(CP, "cp242 progress index")
    root1313 = load_json(ROOT1313, "Root1313 first24 product")
    root1305 = load_json(ROOT1305, "Root1305 final48 rigid product")
    root1320 = load_json(ROOT1320, "Root1320 native field-role closure")
    require(catalog.get("schema") == "ds02.f3.assigned-f6.fresh171.final48-particle-rigid-47accepted-one-pending.v1", "catalog schema mismatch")
    require(cp.get("schema") == "ds02.stage1.full336.role-aware-progress-index.v6", "cp242 schema mismatch")
    require(root1313.get("schema") == "ds02.main.F6.fixedactual24.particle-rigid-joined-delivery.v1", "Root1313 schema mismatch")
    require(root1305.get("schema") == "ds02.main.F6.final48.fulltime-rigid-motion-delivery.v1", "Root1305 schema mismatch")
    require(root1320.get("schema") == "ds02.main.full336-native-condition-field-role-closure.v1", "Root1320 schema mismatch")
    for key, ref in catalog.get("authoritative_sources", {}).items():
        check_source_ref(ref, key)
    cp_rows = {row["physical_case_id"]: row for row in cp["cases"] if row.get("family_id") == "F6"}
    rigid_rows = {row["physical_case_id"]: row for row in root1305["rows"] if row.get("family_id") == "F6"}
    root1320_rows = {row["physical_case_id"]: row for row in root1320["actual47_F6_native_receipt_checks"]}
    root1313_rows = {row["physical_case_id"]: row for row in root1313.get("rows", [])}
    root1313_sidecars = {row["physical_case_id"]: row for row in root1313.get("main_native_particle_rigid_binding_sidecars", [])}
    rows = catalog.get("rows", [])
    require(len(rows) == 48 and len(cp_rows) == 48 and len(rigid_rows) == 48, "F6 final48 row count mismatch")
    require(len({row["physical_case_id"] for row in rows}) == 48, "catalog physical IDs are not unique")
    accepted = [row for row in rows if row.get("visual_status", "").startswith("accepted")]
    pending = [row for row in rows if row.get("visual_status") == "pending_visual_render_not_accepted"]
    require(len(accepted) == 47 and len(pending) == 1, "catalog must contain 47 accepted and one pending row")
    require(pending[0]["physical_case_id"] == PENDING, "pending row identity changed")
    m = catalog["membership"]
    first8 = set(m["frozen_first8_physical_case_ids"])
    first24 = set(m["actual_first24_physical_case_ids"])
    final48 = set(m["registered_final48_physical_case_ids"])
    require(len(first8) == 8 and len(first24) == 24 and len(final48) == 48, "membership counts mismatch")
    require(first8 <= first24 <= final48, "frozen8/actual24/registered48 relation failed")
    require(m.get("frozen8_subset_actual24_subset_registered48") is True, "subset flag changed")
    require(final48 == set(cp_rows) == set(rigid_rows), "catalog membership differs from authoritative sources")
    require(set(root1320_rows) == final48 - {BASELINE}, "Root1320 native role set differs from final48 minus baseline")
    require(BASELINE in root1320.get("true_actual_field_absence_physical_case_ids", []), "baseline native absence not disclosed by Root1320")
    require(catalog["delivery"]["accepted_visual_delivery_complete"] is False, "pending visual was promoted")
    require(catalog["assignment"]["new_case_credit"] == 0 and catalog["assignment"]["Q_N"] == 0 and catalog["assignment"]["Q_E"] == 0,
            "catalog credit boundary changed")
    require(catalog["assignment"]["scientific_payload_read_or_hashed_by_source"] is False, "source payload boundary changed")

    for row in rows:
        physical = row["physical_case_id"]
        label = f"{row['delivery_order']}/{physical}"
        require(row.get("progress_index_row") == cp_rows[physical], f"{label} cp row changed")
        check_rigid(row, rigid_rows[physical], label)
        credit = row.get("credit_and_precision", {})
        require(credit.get("case_credit") == 0 and credit.get("new_visual_credit") == 0 and credit.get("Q_N") == 0 and credit.get("Q_E") == 0,
                f"{label} credit changed")
        if row["visual_status"].startswith("accepted"):
            check_primary(row, label)
            native_role = row["accepted_visual_metadata"].get("root1320_native_field_role_closure")
            if physical == BASELINE:
                require(isinstance(native_role, dict) and native_role.get("actual_complete_native_receipt") is None,
                        f"{label} baseline native field absence was promoted")
                require(row["accepted_visual_metadata"].get("native_refs") == [], f"{label} baseline native ref fabricated")
            else:
                require(physical in root1320_rows, f"{label} missing Root1320 native role row")
                require(isinstance(native_role, dict), f"{label} Root1320 native role closure missing")
                require(native_role.get("actual_complete_native_receipt") == root1320_rows[physical].get("actual_native_receipt"),
                        f"{label} Root1320 native receipt role changed")
                require(row["accepted_visual_metadata"].get("native_refs"), f"{label} actual native ref missing")
            dref = row["accepted_visual_metadata"]["accepted_decision"]
            check_metadata_ref(dref, f"{label} accepted decision")
            # Decision ref must be the immutable cp242 ref.
            require(dref == cp_rows[physical]["accepted_decision"], f"{label} accepted decision ref changed")
            closure = row["accepted_visual_metadata"].get("independent_metadata_closure")
            if closure:
                check_metadata_ref(closure, f"{label} metadata closure")
            if physical in first24:
                side = row.get("root1313_first24_sidecar_crosscheck")
                require(isinstance(side, dict) and side.get("physical_case_id") == physical, f"{label} first24 sidecar missing")
                require(side.get("accepted_visual_decision") == dref, f"{label} first24 decision sidecar mismatch")
        else:
            boundary = row.get("pending_visual_boundary", {})
            require(boundary.get("accepted_decision") is None, f"{label} pending decision fabricated")
            require(boundary.get("primary_particle_xmf_render_refs") is None and boundary.get("primary_png_refs") is None,
                    f"{label} pending primary visual refs fabricated")
            require(row.get("accepted_visual_metadata") is None, f"{label} pending visual metadata fabricated")
            role = row.get("root1320_native_field_role_closure")
            require(isinstance(role, dict) and role.get("actual_complete_native_receipt"),
                    f"{label} pending native field-role closure missing")
    baseline = catalog["baseline_boundary"]
    require(baseline["physical_case_id"] == BASELINE, "baseline identity changed")
    require(baseline["legacy_Part_column_validation_field_present"] is False and baseline["legacy_Part_unique_count"] is None,
            "baseline Part false/null boundary changed")
    require(baseline["fresh170_or_1313_independent_baseline_Part_validation"] is False, "baseline Part evidence promoted")

    packaged = [path for path in HERE.rglob("*") if path.is_file() and path.suffix.lower() in FORBIDDEN_PACKAGED_SUFFIXES]
    require(not packaged, f"scientific payload was packaged: {packaged}")
    return {"status": "PASS", "rows": 48, "accepted_visual": 47, "pending_visual": 1,
            "frozen8": 8, "actual24": 24, "baseline_part": "false/null",
            "scientific_payload_read_or_hashed": False}


if __name__ == "__main__":
    try:
        result = validate()
    except ValidationError as exc:
        print(f"fresh171 validator: FAIL: {exc}")
        raise SystemExit(1)
    print("fresh171 validator: PASS " + json.dumps(result, sort_keys=True))
