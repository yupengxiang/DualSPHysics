#!/usr/bin/env python3
"""Metadata-only validator for the fresh168 disabled F6 FloatingInfo package.

The validator may stat the existing ``PartFloatInfo.ibi4`` files and hash
code/document/JSON metadata.  It never opens or hashes BI4/H5/CSV/DAT/VTK
scientific payloads and it never enables or launches a request.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
INDEX_PATH = HERE / "requests/f6-final48-fulltime-floatinginfo-disabled-request-index.json"
TEMPLATE_PATH = HERE / "requests/fulltime-floatinginfo-request.template.json"
CONTRACT_PATH = HERE / "metadata/official-floatinginfo-contract.json"
WORKER_PATH = HERE / "workers/run_fulltime_floatinginfo_fresh168.py"
WORKER_SHA = "8433709919f4bbc45eb1d302246a58062bdcd7dbdd02c2ab5f2acb7d861438f8"
INVENTORY_WORKER_PATH = HERE / "workers/run_partfloatinfo_inventory_fresh168.py"
INVENTORY_WORKER_SHA = "3b053331308c080a35a96994c367ec49329d875ad3d6948accce1140f41f13d2"
RUNNER_SHA = "708c4c83d22257f7b59bad93cd19915fb66a199a2a5b1291d6ada71bb467ea76"
OFFICIAL_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
HELP_SHA = "872778057e82400ccbb33fd1c79b99574c71c7d588bfcbc78add7d7e99217bba"
EXPECTED_PARTFLOAT_BYTES = 8_477_672
EXPECTED_CASES = 47


class ValidationError(RuntimeError):
    pass


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostics only
        raise ValidationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON object required: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def absolute(value: Any, label: str) -> Path:
    require(isinstance(value, str) and value, f"{label} must be a path string")
    path = Path(value)
    require(path.is_absolute(), f"{label} must be absolute: {value!r}")
    return path


def validate_template(template: dict[str, Any]) -> None:
    require(template.get("schema") == "ds02.f6.fulltime-floatinginfo-request.v1", "template schema mismatch")
    require(template.get("disabled") is True, "template must remain disabled")
    require(template.get("source_only") is True, "template must remain source-only")
    require(template.get("execution_allowed") is False, "template must not be executable")
    require(template.get("future_hashes_null") is True, "template future hashes must be null")
    require(template.get("requires_root_enabled_copy") is True, "template must require a Root enabled copy")
    require(template.get("output", {}).get("report_sha256") is None, "template report hash must be null")
    require(template.get("output", {}).get("output_sha256") is None, "template output hash must be null")
    require(template.get("native", {}).get("rigid_state_input", {}).get("source_stat_bytes") is None, "template stat must be a placeholder")
    template_time = template.get("time_contract", {})
    require(template_time.get("native_times_s") is None and template_time.get("native_time_tolerance_s") == 1e-6 and template_time.get("native_times_required_before_export") is True, "template native-time gate changed")
    template_part = template.get("official_export", {}).get("part_contract", {})
    require(template_part.get("pilot_required") is True and template_part.get("mode") is None and template_part.get("expected_values") is None, "template part pilot gate changed")
    inventory = template.get("native", {}).get("rigid_state_input", {}).get("inventory_binding", {})
    require(inventory.get("required_before_official_export") is True, "template inventory gate missing")
    require(inventory.get("inventory_request_id") == "fresh168-partfloatinfo-inventory-v1", "template inventory request id changed")
    require(inventory.get("report_path") == "<INVENTORY_REPORT_JSON>", "template inventory report placeholder missing")
    require(inventory.get("report_sha256") is None and inventory.get("entry_source_sha256") is None, "template inventory hashes must be null")
    worker = template.get("worker", {})
    require(worker.get("inventory_worker_path") == str(INVENTORY_WORKER_PATH), "template inventory worker path missing")
    require(worker.get("inventory_worker_sha256") == INVENTORY_WORKER_SHA, "template inventory worker SHA missing")
    required_placeholders = {
        "CASE_ID", "PHYSICAL_CASE_ID", "NATIVE_CONDITION_SHA256", "NATIVE_DATA_ROOT",
        "NATIVE_RECEIPT_JSON", "NATIVE_RECEIPT_SHA256", "STATE0_AUDIT_JSON",
        "ROOT_PRIVATE_OUTPUT_DIR", "INVENTORY_REPORT_JSON", "ROLE_SHA256_OR_NULL",
    }
    require(set(template.get("template_placeholders", [])) == required_placeholders, "template placeholder set changed")


def validate() -> dict[str, Any]:
    require(INDEX_PATH.is_file(), f"missing index: {INDEX_PATH}")
    require(TEMPLATE_PATH.is_file(), f"missing template: {TEMPLATE_PATH}")
    require(CONTRACT_PATH.is_file(), f"missing contract: {CONTRACT_PATH}")
    require(WORKER_PATH.is_file(), f"missing worker: {WORKER_PATH}")
    index = load(INDEX_PATH)
    template = load(TEMPLATE_PATH)
    contract = load(CONTRACT_PATH)
    validate_template(template)

    require(index.get("schema") == "ds02.f3.assigned-f6.fresh168.fulltime-floatinginfo-request-index.v1", "index schema mismatch")
    require(index.get("assigned_family") == "F3" and index.get("actual_family") == "F6", "family assignment mismatch")
    require(index.get("disabled") is True, "index must be disabled")
    require(index.get("future_receipt_report_output_hashes") is None, "index future hashes must be null")
    require(index.get("source_scientific_payload_read_or_hashed") is False, "source payload policy changed")
    rows = index.get("requests")
    require(isinstance(rows, list) and len(rows) == EXPECTED_CASES, f"expected {EXPECTED_CASES} disabled requests")
    require(index.get("case_count") == EXPECTED_CASES, "index case_count mismatch")
    require(sha256(WORKER_PATH) == WORKER_SHA, "worker SHA differs from the indexed source byte")
    require(INVENTORY_WORKER_PATH.is_file(), f"missing inventory worker: {INVENTORY_WORKER_PATH}")
    require(sha256(INVENTORY_WORKER_PATH) == INVENTORY_WORKER_SHA, "inventory worker SHA differs from the indexed source byte")

    inventory_request_path = absolute(index.get("inventory_request_path"), "inventory_request_path")
    require(inventory_request_path.is_file(), f"inventory request missing: {inventory_request_path}")
    require(sha256(inventory_request_path) == index.get("inventory_request_sha256"), "inventory request SHA mismatch")
    inventory_request = load(inventory_request_path)
    require(inventory_request.get("schema") == "ds02.f6.partfloatinfo-inventory-request.v1", "inventory request schema mismatch")
    require(inventory_request.get("request_id") == "fresh168-partfloatinfo-inventory-v1", "inventory request identity mismatch")
    require(inventory_request.get("disabled") is True and inventory_request.get("source_only") is True and inventory_request.get("execution_allowed") is False, "inventory request is not disabled source-only")
    require(inventory_request.get("launch_owner") == "root" and inventory_request.get("cpu_task_kind") == "audit" and inventory_request.get("cpu_threads") == 2, "inventory worker dispatch contract changed")
    require(inventory_request.get("max_wall_seconds") == 600 and inventory_request.get("estimated_storage_bytes") == 67_108_864, "inventory resource bound changed")
    require(inventory_request.get("future_hashes_null") is True and inventory_request.get("scientific_payload_read_by_source") is False, "inventory source policy changed")
    require(inventory_request.get("worker", {}).get("path") == str(INVENTORY_WORKER_PATH), "inventory worker path mismatch")
    require(inventory_request.get("worker", {}).get("sha256") == INVENTORY_WORKER_SHA, "inventory worker request SHA mismatch")
    require(inventory_request.get("worker", {}).get("runner_sha256") == RUNNER_SHA, "inventory Root142 runner SHA mismatch")
    inventory_output = inventory_request.get("output", {})
    require(inventory_output.get("report_sha256") is None and inventory_output.get("entries_sha256") is None, "inventory future hashes must be null")

    coverage_path = absolute(index.get("source_coverage_path"), "source_coverage_path")
    require(coverage_path.is_file(), f"source coverage metadata missing: {coverage_path}")
    require(sha256(coverage_path) == index.get("source_coverage_sha256"), "source coverage metadata SHA mismatch")

    physical_ids: set[str] = set()
    case_ids: set[str] = set()
    stat_total = 0
    stat_sizes: list[int] = []
    official_paths: set[tuple[str, str]] = set()
    inventory_entries = inventory_request.get("entries")
    require(isinstance(inventory_entries, list) and len(inventory_entries) == EXPECTED_CASES, "inventory entry count mismatch")
    inventory_by_physical = {entry.get("physical_case_id"): entry for entry in inventory_entries if isinstance(entry, dict)}
    require(len(inventory_by_physical) == EXPECTED_CASES, "inventory physical identities are not unique")
    for row_number, request in enumerate(rows):
        prefix = f"request[{row_number}]"
        require(request.get("schema") == "ds02.f6.fulltime-floatinginfo-request.v1", f"{prefix} schema mismatch")
        require(request.get("package") == "fresh168", f"{prefix} package mismatch")
        require(request.get("disabled") is True and request.get("source_only") is True, f"{prefix} is not disabled source-only")
        require(request.get("execution_allowed") is False, f"{prefix} is executable")
        require(request.get("status") == "source_only_disabled_waiting_root142", f"{prefix} status mismatch")
        require(request.get("launch_owner") == "root", f"{prefix} launch owner mismatch")
        require(request.get("cpu_task_kind") == "audit", f"{prefix} task kind mismatch")
        require(request.get("cpu_threads") == 2, f"{prefix} CPU thread mismatch")
        require(request.get("max_wall_seconds") == 600, f"{prefix} wall bound mismatch")
        require(request.get("estimated_storage_bytes") == 536_870_912, f"{prefix} storage estimate mismatch")
        require(request.get("future_hashes_null") is True, f"{prefix} future hash policy mismatch")
        require(request.get("new_case_credit") is None, f"{prefix} unexpected top-level case credit")
        require(request.get("no_shared_registry_or_ledger_write_by_source") is True, f"{prefix} shared-state policy changed")
        require(request.get("scientific_payload_read_by_source") is False, f"{prefix} source payload policy changed")
        require(request.get("requires_root_enabled_copy") is True, f"{prefix} missing Root handoff requirement")

        case = request.get("case")
        require(isinstance(case, dict), f"{prefix}.case missing")
        require(case.get("family_id") == "F6" and case.get("assigned_family") == "F3", f"{prefix} family role mismatch")
        case_id = case.get("case_id")
        physical_id = case.get("physical_case_id")
        require(isinstance(case_id, str) and case_id, f"{prefix} case ID missing")
        require(isinstance(physical_id, str) and physical_id, f"{prefix} physical ID missing")
        require(case_id not in case_ids and physical_id not in physical_ids, f"{prefix} duplicate physical identity")
        case_ids.add(case_id)
        physical_ids.add(physical_id)
        require(case.get("physical_condition_sha256") == request.get("native", {}).get("condition_sha256"), f"{prefix} native condition role drift")
        require(case.get("new_case_credit") == 0, f"{prefix} case credit is not zero")
        inventory_entry = inventory_by_physical.get(physical_id)
        require(isinstance(inventory_entry, dict), f"{prefix} is absent from inventory request")

        native = request.get("native")
        require(isinstance(native, dict), f"{prefix}.native missing")
        native_root = absolute(native.get("data_root"), f"{prefix}.native.data_root")
        rigid = native.get("rigid_state_input")
        require(isinstance(rigid, dict), f"{prefix} rigid input missing")
        require(rigid.get("relative_path") == "PartFloatInfo.ibi4", f"{prefix} official rigid input mismatch")
        require(rigid.get("source_stat_only") is True, f"{prefix} rigid input is not stat-only")
        require(rigid.get("state0_is_not_full_time") is True, f"{prefix} state0 was promoted")
        inventory_binding = rigid.get("inventory_binding")
        require(isinstance(inventory_binding, dict), f"{prefix} inventory binding missing")
        require(inventory_binding.get("required_before_official_export") is True, f"{prefix} inventory gate missing")
        require(inventory_binding.get("inventory_request_id") == "fresh168-partfloatinfo-inventory-v1", f"{prefix} inventory request id changed")
        require(inventory_binding.get("report_path") is None and inventory_binding.get("report_sha256") is None and inventory_binding.get("entry_source_sha256") is None, f"{prefix} disabled inventory hashes are not null")
        require(rigid.get("state0_rows_examined") == 2, f"{prefix} state0 row contract mismatch")
        stat_bytes = rigid.get("source_stat_bytes")
        require(isinstance(stat_bytes, int) and stat_bytes > 0, f"{prefix} stat-only byte count missing")
        rigid_path = native_root / "PartFloatInfo.ibi4"
        require(rigid_path.is_file(), f"{prefix} PartFloatInfo.ibi4 missing: {rigid_path}")
        require(inventory_entry.get("case_id") == case_id and inventory_entry.get("data_root") == str(native_root), f"{prefix} inventory identity/root mismatch")
        require(inventory_entry.get("relative_path") == "PartFloatInfo.ibi4" and inventory_entry.get("expected_stat_bytes") == stat_bytes, f"{prefix} inventory stat binding mismatch")
        # Stat-only: never open this scientific input or compute its digest.
        require(rigid_path.stat().st_size == stat_bytes, f"{prefix} PartFloatInfo.ibi4 stat changed")
        stat_total += stat_bytes
        stat_sizes.append(stat_bytes)
        require(native.get("receipt_status") == "completed" and native.get("receipt_returncode") == 0, f"{prefix} native receipt is not completed/0 metadata")
        receipt_path = absolute(native.get("receipt_path"), f"{prefix}.native.receipt_path")
        require(receipt_path.is_file(), f"{prefix} native receipt missing")
        require(isinstance(native.get("receipt_sha256"), str) and len(native["receipt_sha256"]) == 64, f"{prefix} native receipt SHA missing")

        locator = request.get("native_embedded_rigid_state_locator")
        require(isinstance(locator, dict), f"{prefix} rigid locator missing")
        require(locator.get("relative_path") == "PartFloatInfo.ibi4", f"{prefix} locator path mismatch")
        require(locator.get("source_stat_bytes") == stat_bytes, f"{prefix} locator stat mismatch")
        require(locator.get("state0_is_not_full_time") is True, f"{prefix} locator promotes state0")
        require(locator.get("full241_native_exists_by_metadata") is True, f"{prefix} full-native metadata missing")

        state0 = request.get("state0_evidence")
        require(isinstance(state0, dict) and state0.get("status") == "pass", f"{prefix} state0 evidence missing")
        require(state0.get("rows_examined") == 2, f"{prefix} state0 evidence row count changed")
        limits = state0.get("frame_limits")
        require(isinstance(limits, dict) and limits.get("first") == 0 and limits.get("last") == 1, f"{prefix} state0 limits changed")
        audit_path = absolute(state0.get("audit_json", {}).get("path"), f"{prefix}.state0.audit_json.path")
        require(audit_path.is_file(), f"{prefix} state0 audit metadata missing")

        official = request.get("official_export")
        require(isinstance(official, dict), f"{prefix}.official_export missing")
        binary = absolute(official.get("binary_path"), f"{prefix}.official_export.binary_path")
        help_path = absolute(official.get("help_path"), f"{prefix}.official_export.help_path")
        require(binary.is_file() and os.access(binary, os.X_OK), f"{prefix} official binary unavailable")
        require(help_path.is_file(), f"{prefix} official help unavailable")
        require(official.get("binary_sha256") == OFFICIAL_SHA and official.get("help_sha256") == HELP_SHA, f"{prefix} official SHA contract changed")
        require(official.get("first") == 0 and official.get("last") == 240 and official.get("only_mk") == 60, f"{prefix} official frame/marker contract changed")
        require(official.get("save_motion") == 1 and official.get("csvsep") == 0, f"{prefix} official motion/CSV flags changed")
        require(official.get("delimiter") == ";" and official.get("output_filename") == "FloatingInfo_mk60.csv", f"{prefix} official CSV contract changed")
        official_paths.add((str(binary), str(help_path)))

        frame = request.get("frame_contract")
        require(isinstance(frame, dict) and frame.get("first") == 0 and frame.get("last") == 240 and frame.get("expected_count") == 241, f"{prefix} frame contract changed")
        require(frame.get("must_parse_all_rows") is True and frame.get("bounded_prefix_rejected") is True, f"{prefix} bounded-prefix policy changed")
        time_contract = request.get("time_contract")
        require(isinstance(time_contract, dict), f"{prefix} time contract missing")
        require(time_contract.get("expected_start_s") == 0.0 and time_contract.get("expected_end_s") == 12.0 and time_contract.get("nominal_tout_s") == 0.05, f"{prefix} time window changed")
        require(time_contract.get("native_times_s") is None and time_contract.get("native_time_tolerance_s") == 1e-6 and time_contract.get("native_times_required_before_export") is True and time_contract.get("no_resampling") is True, f"{prefix} native-time policy changed")
        part_contract = official.get("part_contract")
        require(isinstance(part_contract, dict), f"{prefix} part-column contract missing")
        require(part_contract.get("pilot_required") is True and part_contract.get("mode") is None and part_contract.get("expected_values") is None, f"{prefix} part-column pilot gate changed")

        worker = request.get("worker")
        require(isinstance(worker, dict), f"{prefix} worker binding missing")
        require(worker.get("path") == str(WORKER_PATH) and worker.get("sha256") == WORKER_SHA, f"{prefix} worker binding drift")
        require(worker.get("runner_sha256") == RUNNER_SHA, f"{prefix} Root142 runner binding drift")
        require(worker.get("inventory_worker_path") == str(INVENTORY_WORKER_PATH), f"{prefix} inventory worker path drift")
        require(worker.get("inventory_worker_sha256") == INVENTORY_WORKER_SHA, f"{prefix} inventory worker SHA drift")
        require(worker.get("inventory_request_path") == str(inventory_request_path), f"{prefix} inventory request path drift")
        output = request.get("output")
        require(isinstance(output, dict), f"{prefix} output binding missing")
        require(output.get("directory") == "<ROOT_PRIVATE_OUTPUT_DIR>/<CASE_ID>", f"{prefix} output directory is not private placeholder")
        require(output.get("report_sha256") is None and output.get("output_sha256") is None and output.get("receipt") is None, f"{prefix} future output hash is populated")

    require(stat_total == EXPECTED_PARTFLOAT_BYTES, f"PartFloatInfo stat total changed: {stat_total} != {EXPECTED_PARTFLOAT_BYTES}")
    require(set(stat_sizes) == {180_376}, f"unexpected PartFloatInfo stat sizes: {sorted(set(stat_sizes))}")
    require(len(official_paths) == 1, "official binary/help paths are not uniform")

    require(contract.get("documented_dirdata_input") == "PartFloatInfo.ibi4", "official dirdata contract must name PartFloatInfo.ibi4")
    require(contract.get("documented_fields_units", {}).get("fomega") == "rad/s", "angular-velocity units missing")
    require(contract.get("documented_fields_units", {}).get("roll") == "deg", "Euler-angle units missing")
    require(contract.get("part_column", {}).get("header") == "part" and contract.get("part_column", {}).get("source_policy") == "pilot_required_before_full_export", "part-column pilot contract missing")
    require(contract.get("native_time_policy", {}).get("required_values") == 241 and contract.get("native_time_policy", {}).get("tolerance_s") == 1e-6, "native-time policy missing")
    require("pitch-sign" in contract.get("version_note", ""), "v5.4 pitch-sign note missing")

    forbidden_suffixes = {".h5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu", ".xmf"}
    packaged_forbidden = [path for path in HERE.rglob("*") if path.is_file() and path.suffix.lower() in forbidden_suffixes]
    require(not packaged_forbidden, f"scientific payload packaged in source bundle: {packaged_forbidden}")
    return {"status": "PASS", "requests": len(rows), "partfloat_stat_bytes": stat_total, "worker_sha256": sha256(WORKER_PATH)}


if __name__ == "__main__":
    try:
        result = validate()
    except ValidationError as exc:
        print(f"fresh168 validator: FAIL: {exc}")
        raise SystemExit(1)
    print(f"fresh168 validator: PASS ({result['requests']} requests; PartFloatInfo stat bytes={result['partfloat_stat_bytes']}; disabled source-only)")
