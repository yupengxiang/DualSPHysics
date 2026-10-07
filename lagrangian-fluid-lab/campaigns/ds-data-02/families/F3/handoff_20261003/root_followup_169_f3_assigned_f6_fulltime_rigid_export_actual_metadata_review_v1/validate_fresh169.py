#!/usr/bin/env python3
"""Validate fresh169 from JSON metadata only.

This validator deliberately never opens or hashes CSV, IBI4, BI4, H5, DAT,
VTK, VTU, PVTU, or XMF scientific payloads.  Reported output hashes are
producer attestations.  The registered Root workers, rather than this source
package, read/hash the official rigid-input and CSV payloads.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REVIEW = HERE / "metadata/fresh169-review.json"

PILOT_REPORT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025/"
    "root-stage1-f6-last-dzxy-s1375-yawp18-full241-rigid-history-source168-root1303/"
    "floatinginfo/fulltime-rigid-motion-report.json"
)
PILOT_RECEIPT = PILOT_REPORT.parents[1] / "execution-receipt.json"
PILOT_ROOT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F6_last_DZXY_S1375_YAWP18_full241_official_rigid_motion_"
    "Part_hypothesis_pilot_inventory47_closed_Root142928_CPU2_1303"
)
PILOT_CONTROLLER = PILOT_ROOT / "controller-result.json"
PILOT_SPEC = PILOT_ROOT / "enabled-fulltime-floatinginfo-pilot-spec.json"
PILOT_REQUEST = PILOT_ROOT / "enabled-pilot-runner-request.json"
PILOT_CLOSURE = PILOT_ROOT / "actual47-small-IBI4-inventory-independent-metadata-closure.json"

BATCH_ROOT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F6_remaining46_full241_official_rigid_motion_exports_actual_"
    "Part0to240_pilot_native_time_inventory_closed_Root142928_CPU2_1304"
)
BATCH_RESULT = BATCH_ROOT / "batch-result.json"

INVENTORY_REPORT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
    "F6-fulltime-rigid-inventory/root-stage1-F6-47small-IBI4-inventory-"
    "source168-root1302/inventory/inventory-report.json"
)
INVENTORY_RECEIPT = INVENTORY_REPORT.parents[1] / "execution-receipt.json"
INVENTORY_CLOSURE = PILOT_CLOSURE

NATIVE_TIME_BINDING = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F6_remaining47_fulltime_export_own_native_typed_XMF_241_"
    "time_bindings_preparation_1300/47-own-full241-native-time-bindings-for-"
    "official-rigid-export.json"
)
BASELINE_COVERAGE = HERE.parent / "root_followup_167_f3_assigned_f6_rigid_state_delivery_coverage_v1/metadata/f6-final48-rigid-state-coverage.json"
MAIN_DELIVERY = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_F6_actual48_fulltime_official_rigid_motion_47new241rows_one_existing_history_CPU2_and_pendingF5_1131_1180_ownQI_checkpoint_1305/"
    "F6-FINAL48-FULLTIME-RIGID-MOTION-DELIVERY.json"
)

OFFICIAL_BINARY = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/FloatingInfo_linux64"
OFFICIAL_BINARY_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
NATIVE_TOLERANCE_S = 1e-6
EXPECTED_ROWS = 241
EXPECTED_ENTRIES = 47
EXPECTED_PARTFLOAT_BYTES = 8_477_672

REQUIRED_HEADERS = {
    "part",
    "time [s]",
    "fvel.x [m/s]", "fvel.y [m/s]", "fvel.z [m/s]",
    "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]",
    "center.x [m]", "center.y [m]", "center.z [m]",
    "surge [m]", "sway [m]", "heave [m]",
    "roll [deg]", "pitch [deg]", "yaw [deg]",
}
REQUIRED_COMMAND_FLAGS = {
    "-first:0", "-last:240", "-onlymk:60", "-savemotion:1", "-csvsep:0"
}
FORBIDDEN_SUFFIXES = {".csv", ".ibi4", ".bi4", ".h5", ".dat", ".vtk", ".vtu", ".pvtu", ".xmf"}


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"{label} is not JSON: {path}")
    require(path.is_file(), f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostic path
        raise ValidationError(f"invalid JSON {label}: {path}") from exc
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


def validate_official_command(command: Any, label: str) -> None:
    require(isinstance(command, list) and command, f"{label}.official_command missing")
    require(command[0] == OFFICIAL_BINARY, f"{label} uses an unexpected official binary")
    require(REQUIRED_COMMAND_FLAGS.issubset(set(command)), f"{label} official first/last/mk/motion flags incomplete")
    require("-dirdata" in command and "-savedata" in command, f"{label} data/output options missing")


def validate_report(report: dict[str, Any], label: str, expected_case: str | None = None) -> dict[str, Any]:
    require(report.get("schema") == "ds02.f6.fulltime-floatinginfo-worker-result.v1", f"{label} report schema mismatch")
    require(report.get("status") == "completed" and report.get("returncode") == 0, f"{label} is not completed/0")
    require(report.get("future_hashes_null") is False, f"{label} actual report incorrectly remains future-null")
    case = report.get("case")
    require(isinstance(case, dict), f"{label}.case missing")
    physical_case_id = case.get("physical_case_id")
    require(isinstance(physical_case_id, str) and physical_case_id, f"{label} physical identity missing")
    require(case.get("family_id") == "F6" and case.get("assigned_family") == "F3", f"{label} family roles changed")
    require(case.get("case_id") == physical_case_id, f"{label} case/physical identity mismatch")
    require(case.get("new_case_credit") == 0, f"{label} case credit changed")
    if expected_case is not None:
        require(physical_case_id == expected_case, f"{label} does not match batch physical identity")

    native = report.get("native_receipt")
    require(isinstance(native, dict), f"{label}.native_receipt missing")
    require(native.get("status") == "completed" and native.get("returncode") == 0, f"{label} native receipt not completed/0")
    require(is_hex64(native.get("actual_sha256")) and native.get("actual_sha256") == native.get("expected_sha256"), f"{label} native receipt SHA closure missing")
    native_path = Path(native.get("path", ""))
    load_json(native_path, f"{label} native receipt")

    inventory = report.get("partfloatinfo_inventory")
    require(isinstance(inventory, dict), f"{label} inventory binding missing")
    require(inventory.get("request_id") == "fresh168-partfloatinfo-inventory-v1", f"{label} inventory request mismatch")
    require(inventory.get("report_path") == str(INVENTORY_REPORT), f"{label} inventory report path mismatch")
    require(inventory.get("report_sha256") == json_sha(INVENTORY_REPORT, "inventory report"), f"{label} inventory report SHA mismatch")
    entry = inventory.get("entry")
    require(isinstance(entry, dict), f"{label} inventory entry missing")
    require(entry.get("physical_case_id") == physical_case_id and entry.get("case_id") == case.get("case_id"), f"{label} inventory identity mismatch")
    require(entry.get("relative_path") == "PartFloatInfo.ibi4", f"{label} inventory input name changed")
    require(entry.get("bytes_before") == 180_376 and entry.get("bytes_after") == 180_376, f"{label} inventory stat changed")
    require(is_hex64(entry.get("sha256")), f"{label} producer inventory SHA missing")

    validate_official_command(report.get("official_command"), label)
    require(report.get("official_binary_sha256") == OFFICIAL_BINARY_SHA, f"{label} official binary SHA mismatch")

    parse = report.get("parse")
    require(isinstance(parse, dict), f"{label}.parse missing")
    require(parse.get("rows_examined") == EXPECTED_ROWS and parse.get("part_row_count") == EXPECTED_ROWS, f"{label} row count is not 241")
    require(parse.get("row_ordinals") == list(range(EXPECTED_ROWS)), f"{label} row ordinals are not 0..240")
    require(parse.get("strictly_increasing_time") is True, f"{label} time is not strictly increasing")
    require(parse.get("rigid_fields_finite_rows") == EXPECTED_ROWS, f"{label} finite rigid-field rows are not 241")
    require(parse.get("required_rigid_field_count") == 17, f"{label} required rigid-field count changed")
    headers = parse.get("header_columns")
    require(isinstance(headers, list) and REQUIRED_HEADERS.issubset(set(headers)), f"{label} required unit-bearing fields missing")

    observed = parse.get("part_values_observed")
    part_contract = parse.get("part_column_contract")
    require(observed == list(range(EXPECTED_ROWS)), f"{label} observed Part is not 0..240")
    require(isinstance(part_contract, dict), f"{label} Part contract missing")
    require(part_contract.get("pilot_required") is True and part_contract.get("mode") == "frame_index", f"{label} Part pilot mode is not frame_index")
    require(part_contract.get("expected_values") == list(range(EXPECTED_ROWS)), f"{label} Part expected values are not 0..240")
    require(part_contract.get("observed_values") == list(range(EXPECTED_ROWS)), f"{label} Part observed values are not 0..240")
    require(part_contract.get("frame_identity_from_part") is True and part_contract.get("no_part_value_inferred") is False, f"{label} Part identity was inferred or not bound")

    native_times = parse.get("native_time_comparison")
    require(isinstance(native_times, dict), f"{label} native-time comparison missing")
    native_vec = native_times.get("native_times_s")
    official_vec = parse.get("official_times_s")
    delta_vec = native_times.get("official_minus_native_s")
    require(isinstance(native_vec, list) and len(native_vec) == EXPECTED_ROWS, f"{label} native-time vector is not 241")
    require(isinstance(official_vec, list) and len(official_vec) == EXPECTED_ROWS, f"{label} official-time vector is not 241")
    require(isinstance(delta_vec, list) and len(delta_vec) == EXPECTED_ROWS, f"{label} time-delta vector is not 241")
    max_delta = native_times.get("max_abs_delta_s")
    require(isinstance(max_delta, (int, float)) and max_delta >= 0 and max_delta <= NATIVE_TOLERANCE_S, f"{label} native-time delta exceeds 1e-6 s")
    terminal = parse.get("terminal_coverage")
    require(isinstance(terminal, dict) and terminal.get("covered") is True, f"{label} terminal coverage missing")

    output = report.get("output")
    require(isinstance(output, dict), f"{label} output metadata missing")
    require(isinstance(output.get("csv"), str) and output["csv"].lower().endswith(".csv"), f"{label} output CSV reference missing")
    require(isinstance(output.get("bytes"), int) and output["bytes"] > 0, f"{label} output byte metadata missing")
    require(is_hex64(output.get("sha256")), f"{label} producer output SHA missing")

    return {
        "case_id": case["case_id"],
        "physical_case_id": physical_case_id,
        "rows": EXPECTED_ROWS,
        "part_first": observed[0],
        "part_last": observed[-1],
        "finite_rows": parse["rigid_fields_finite_rows"],
        "native_time_max_abs_delta_s": max_delta,
        "inventory_entry_sha256": entry["sha256"],
        "producer_output_sha256": output["sha256"],
    }


def validate() -> dict[str, Any]:
    review = load_json(REVIEW, "fresh169 review")
    controller = load_json(PILOT_CONTROLLER, "pilot controller result")
    require(controller.get("status") == "completed" and controller.get("returncode") == 0 and controller.get("launcher_returncode") == 0, "pilot controller is not completed/0")
    pilot_request = load_json(PILOT_REQUEST, "pilot request")
    pilot_spec = load_json(PILOT_SPEC, "pilot spec")
    require(pilot_request.get("case_id") == pilot_spec.get("case", {}).get("case_id"), "pilot request/spec case mismatch")
    require(pilot_request.get("disabled") is False and pilot_request.get("execution_allowed") is True, "pilot request is not a Root-enabled actual request")
    require(pilot_spec.get("status") == "root_enabled_pilot_output_contract_under_test", "pilot spec status mismatch")

    inventory = load_json(INVENTORY_REPORT, "registered inventory report")
    require(inventory.get("schema") == "ds02.f6.partfloatinfo-inventory-result.v1", "inventory schema mismatch")
    require(inventory.get("status") == "completed" and inventory.get("returncode") == 0, "inventory not completed/0")
    require(inventory.get("entry_count") == EXPECTED_ENTRIES and len(inventory.get("entries", [])) == EXPECTED_ENTRIES, "inventory does not contain 47 entries")
    require(inventory.get("total_observed_bytes", EXPECTED_PARTFLOAT_BYTES) == EXPECTED_PARTFLOAT_BYTES, "inventory total byte metadata changed")
    inventory_by_physical = {e.get("physical_case_id"): e for e in inventory["entries"]}
    require(len(inventory_by_physical) == EXPECTED_ENTRIES, "inventory physical identities are not unique")

    closure = load_json(PILOT_CLOSURE, "inventory closure")
    require(closure.get("actual_entries") == EXPECTED_ENTRIES and closure.get("total_observed_IBI4_bytes") == EXPECTED_PARTFLOAT_BYTES, "inventory closure counts changed")
    require(closure.get("main_scientific_payload_IO") is False and closure.get("worker_only_scientific_payload_hashing") is True, "inventory source boundary changed")
    # PILOT_ROOT is the 1303 directory below handoff_20261003; the 1302
    # inventory request is its sibling under that same handoff directory.
    inventory_request = PILOT_ROOT.parent / "root_stage1_F6_47small_PartFloatInfo_IBI4_metadata_bound_inventory_registered_Root142928_CPU2_1302/enabled-inventory-runner-request.json"
    require(closure.get("registered_inventory_request", {}).get("sha256") == json_sha(inventory_request, "registered inventory request"), "inventory request closure SHA mismatch")

    pilot_receipt = load_json(PILOT_RECEIPT, "pilot execution receipt")
    require(pilot_receipt.get("status") == "completed" and pilot_receipt.get("returncode") == 0, "pilot receipt is not completed/0")
    require(pilot_receipt.get("request_sha256") == json_sha(PILOT_REQUEST, "pilot request"), "pilot request SHA closure mismatch")

    pilot_summary = validate_report(load_json(PILOT_REPORT, "pilot report"), "pilot")
    require(pilot_summary["physical_case_id"] == "F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025", "pilot case mismatch")

    batch = load_json(BATCH_RESULT, "remaining46 batch result")
    require(batch.get("schema") == "ds02.F6.fulltime.remaining46.batch-result.v1", "remaining46 batch schema mismatch")
    require(batch.get("status") == "completed" and batch.get("requests") == 46 and batch.get("processed") == 46 and batch.get("completed_zero") == 46, "remaining46 batch is not terminal completed/0")
    require(batch.get("case_credit") == 0, "remaining46 batch case credit changed")
    rows: list[dict[str, Any]] = []
    seen: set[str] = {pilot_summary["physical_case_id"]}
    for idx, result in enumerate(batch.get("results", [])):
        require(result.get("status") == "completed" and result.get("returncode") == 0 and result.get("launcher_returncode") == 0, f"remaining46 result[{idx}] is not completed/0")
        receipt_path = Path(result.get("actual_receipt", ""))
        receipt = load_json(receipt_path, f"remaining46 receipt[{idx}]")
        require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"remaining46 receipt[{idx}] is not completed/0")
        report_path = receipt_path.parent / "floatinginfo/fulltime-rigid-motion-report.json"
        physical = result.get("physical_case_id")
        require(isinstance(physical, str) and physical not in seen, f"remaining46 duplicate/missing identity at {idx}")
        summary = validate_report(load_json(report_path, f"remaining46 report[{idx}]"), f"remaining46[{idx}]", physical)
        summary.update({
            "report_path": str(report_path),
            "report_json_sha256": json_sha(report_path, f"remaining46 report[{idx}]"),
            "receipt_path": str(receipt_path),
            "receipt_json_sha256": json_sha(receipt_path, f"remaining46 receipt[{idx}]"),
        })
        seen.add(physical)
        rows.append(summary)
    require(len(rows) == 46 and len(seen) == 47, "fresh169 does not close 47 unique fresh full-time cases")

    baseline = load_json(BASELINE_COVERAGE, "fresh167 baseline coverage")
    require(baseline.get("aggregate", {}).get("final48_rows") == 48, "baseline coverage does not describe final48")
    require(baseline.get("aggregate", {}).get("full_time_verified_cases") == ["F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE"], "historical baseline identity changed")

    main_delivery = load_json(MAIN_DELIVERY, "Root1305 final delivery")
    require(main_delivery.get("schema") == "ds02.main.F6.final48.fulltime-rigid-motion-delivery.v1", "Root1305 final schema mismatch")
    require(main_delivery.get("fulltime_complete_cases") == 48 and len(main_delivery.get("rows", [])) == 48, "Root1305 does not close 48 full-time rows")
    require(main_delivery.get("new_registered_complete_exports") == 47 and main_delivery.get("existing_full241_history_reused") == 1, "Root1305 fresh/history split changed")
    require(main_delivery.get("main_scientific_payload_IO") is False and main_delivery.get("solver_reruns") == 0, "Root1305 source boundary or rerun count changed")
    require(main_delivery.get("new_case_credit") == 0 and main_delivery.get("Q_N") == 0 and main_delivery.get("Q_E") == 0, "Root1305 credit changed")
    require(main_delivery.get("numeric_certification_not_granted") is True, "Root1305 incorrectly grants numeric certification")

    require(review.get("schema") == "ds02.f3.assigned-f6.fresh169.rigid-export-metadata-review.v1", "review schema mismatch")
    require(review.get("status") == "completed_metadata_review" and review.get("actual_case_count") == 47, "review snapshot is not complete")
    require(review.get("case_credit") == 0 and review.get("Q_N") == 0 and review.get("Q_E") == 0, "review credit changed")
    require(review.get("scientific_payload_read_or_hashed_by_source") is False, "review source boundary changed")
    require(len(review.get("fresh_worker_reports", [])) == 47, "review snapshot row count mismatch")
    require(len(review.get("remaining46", {}).get("rows", [])) == 46, "review remaining46 row count mismatch")
    baseline_review = review.get("historical_baseline_separate_role", {})
    require(baseline_review.get("baseline_part_validation_independently_verified_by_fresh169") is False, "historical baseline Part validation was overstated")
    require(baseline_review.get("baseline_part_validation_value") == "null/unavailable; no fresh169 Part0..240 pilot was run for the historical baseline", "historical baseline Part null boundary changed")
    product_review = review.get("main1305_final_delivery", {})
    require(product_review.get("product", {}).get("path") == str(MAIN_DELIVERY), "review does not bind Root1305 product path")
    require(product_review.get("product", {}).get("sha256") == json_sha(MAIN_DELIVERY, "Root1305 final delivery"), "review Root1305 product SHA mismatch")

    packaged_forbidden = [p for p in HERE.rglob("*") if p.is_file() and p.suffix.lower() in FORBIDDEN_SUFFIXES]
    require(not packaged_forbidden, f"scientific payload was packaged: {packaged_forbidden}")
    return {"status": "PASS", "fresh_fulltime_cases": 47, "remaining46_completed_zero": 46, "pilot_part": "frame_index 0..240", "native_time_tolerance_s": NATIVE_TOLERANCE_S}


if __name__ == "__main__":
    try:
        result = validate()
    except ValidationError as exc:
        print(f"fresh169 validator: FAIL: {exc}")
        raise SystemExit(1)
    print("fresh169 validator: PASS " + json.dumps(result, sort_keys=True))
