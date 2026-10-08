#!/usr/bin/env python3
"""Compare the guarded F2 trajectory labels with the all-118 calibration.

The trajectory/expanded comparison is delegated to the consumed, source-bound
``ds_data02_stage2_f2_s1_trajectory_semantics_v1`` contract.  This forward
consumer adds the completed all-118 calibration as an independent small JSON
input.  It checks source-MK and censoring semantics before reporting any
cross-product comparison.  It never opens H5, BI4, OBI4, or solver output
containers and never grants physical-fate, dynamics, QN, or QE credit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CALIBRATION_SCHEMA = "ds02.stage2.label-calibration.v1"
SCHEMA = "ds02.stage2.f2-s1-semantic-compare.v2"
CONTRACT_SCHEMA = "ds02.stage2.f2-s1-semantic-compare-contract.v2"
EXPECTED_CASES = {"F2": 48, "F4": 22, "F6": 48}
EXPECTED_IDS = 1328
BASE_CONTRACT_SCHEMA = "ds02.stage2.f2-s1-trajectory-semantics-contract.v1"
BASE_REPORT_FIELDS = (
    "trajectory_report",
    "conversion_report",
    "expanded_native_report",
    "expanded_runout",
)


class SemanticCompareError(RuntimeError):
    """Raised when the all-118/trajectory semantic join is not exact."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise SemanticCompareError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SemanticCompareError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise SemanticCompareError(f"{label} is not a JSON object: {path}")
    return path, payload


def binding(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value.get("path"):
        raise SemanticCompareError(f"{label} lacks an exact path binding")
    path = require_file(value["path"], label)
    actual = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
    if value.get("bytes") is not None and int(value["bytes"]) != actual["bytes"]:
        raise SemanticCompareError(f"{label} byte count differs")
    if value.get("sha256") and str(value["sha256"]) != actual["sha256"]:
        raise SemanticCompareError(f"{label} SHA256 differs")
    return actual


def _load_v1():
    path = SCRIPT.with_name("ds_data02_stage2_f2_s1_trajectory_semantics_v1.py")
    spec = importlib.util.spec_from_file_location("ds02_f2_s1_semantics_v1", path)
    if spec is None or spec.loader is None:
        raise SemanticCompareError(f"cannot load v1 semantic consumer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_calibration(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != CALIBRATION_SCHEMA:
        raise SemanticCompareError("all-118 calibration schema differs")
    if payload.get("status") != "LABEL_CALIBRATED_SOURCE_MK_CENSORING_NO_MODEL":
        raise SemanticCompareError("all-118 calibration is not the completed source-MK calibration")
    current = payload.get("current")
    if not isinstance(current, dict) or current.get("sha256") != CURRENT_SHA256:
        raise SemanticCompareError("all-118 calibration does not bind CURRENT336")
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("selected_case_count") != 118:
        raise SemanticCompareError("all-118 selected case count differs")
    if coverage.get("selected_native_id_count") != EXPECTED_IDS:
        raise SemanticCompareError("all-118 native ID count differs")
    counts = coverage.get("selected_case_counts")
    if counts != EXPECTED_CASES:
        raise SemanticCompareError(f"all-118 family counts differ: {counts!r}")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise SemanticCompareError("all-118 case rows are incomplete")
    family_counts: dict[str, int] = {family: 0 for family in EXPECTED_CASES}
    id_count = 0
    invalid = []
    for row in cases:
        if not isinstance(row, dict) or row.get("family_id") not in EXPECTED_CASES:
            invalid.append("family")
            continue
        family = row["family_id"]
        family_counts[family] += 1
        id_count += int(row.get("native_count", -1))
        labels = row.get("labels")
        if not isinstance(labels, dict):
            invalid.append(f"{row.get('case_key')}:labels")
            continue
        if labels.get("native_cause") != "VALID_NATIVE_CAUSE":
            invalid.append(f"{row.get('case_key')}:native_cause")
        if labels.get("source_mk") != "VALID_SOURCE_MK_MAPPING":
            invalid.append(f"{row.get('case_key')}:source_mk")
        if labels.get("physical_fate") != "UNKNOWN_PHYSICAL_FATE":
            invalid.append(f"{row.get('case_key')}:physical_fate")
        if labels.get("dynamical_impact") != "UNKNOWN_DYNAMICAL_IMPACT":
            invalid.append(f"{row.get('case_key')}:dynamics")
        if labels.get("QN") != "NOT_ASSESSED" or labels.get("QE") != "NOT_ASSESSED":
            invalid.append(f"{row.get('case_key')}:qualification")
        if row.get("errors"):
            invalid.append(f"{row.get('case_key')}:errors")
    if family_counts != EXPECTED_CASES or id_count != EXPECTED_IDS:
        raise SemanticCompareError(f"all-118 row totals differ: {family_counts}, {id_count}")
    if invalid:
        raise SemanticCompareError("all-118 calibration grants or lacks source credit: " + ", ".join(invalid[:4]))
    boundary = payload.get("claim_boundary")
    if not isinstance(boundary, dict) or boundary.get("physical_fate") != "UNKNOWN" or boundary.get("dynamical_impact") != "UNKNOWN":
        raise SemanticCompareError("all-118 claim boundary is not conservative")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "selected_case_count": len(cases),
        "selected_native_id_count": id_count,
        "family_case_counts": family_counts,
        "native_cause": "VALID_NATIVE_CAUSE for all 118 calibration rows",
        "source_mk": "VALID_SOURCE_MK_MAPPING for all 118 calibration rows",
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "per_mk_initial_denominator": "UNKNOWN_PER_MK_INITIAL_ARRAY_NOT_READ where reported by calibration",
    }


def _validate_base_contract(path: Path, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate the exact v1 contract and all four small producer reports."""
    if payload.get("schema") != BASE_CONTRACT_SCHEMA:
        raise SemanticCompareError("F2 trajectory semantic base is not the completed v1 contract")
    return {
        name: binding(payload.get(name), f"F2 trajectory {name}")
        for name in BASE_REPORT_FIELDS
    }


def analyze(contract_path: Path | str) -> dict[str, Any]:
    contract_path, contract = read_json(contract_path, "semantic comparison contract")
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise SemanticCompareError("semantic comparison contract schema differs")
    calibration_path = require_file(contract.get("calibration_report", {}).get("path"), "all-118 calibration report")
    calibration_binding = binding(contract["calibration_report"], "all-118 calibration report")
    calibration_payload = read_json(calibration_path, "all-118 calibration report")[1]
    calibration = _validate_calibration(calibration_path, calibration_payload)
    base_binding = binding(contract.get("base_semantics_contract"), "F2 trajectory semantics contract")
    base_payload = read_json(base_binding["path"], "F2 trajectory semantics contract")[1]
    _validate_base_contract(Path(base_binding["path"]), base_payload)
    v1 = _load_v1()
    try:
        base = v1.analyze(base_binding["path"])
    except Exception as error:
        raise SemanticCompareError(f"F2 trajectory/expanded semantic comparison failed: {error}") from error
    return {
        "schema": SCHEMA,
        "status": "SEMANTICS_VALIDATED_CALIBRATION_AND_TRAJECTORY_SOURCE_BOUND",
        "source_bindings": {
            "contract": {"path": str(contract_path), "bytes": contract_path.stat().st_size, "sha256": sha256(contract_path)},
            "calibration_report": calibration_binding,
            "base_semantics_contract": base_binding,
            "base_semantics": base["source_bindings"],
        },
        "all118_calibration": calibration,
        "f2_trajectory_comparison": base,
        "comparison_limits": {
            "calibration_and_f2_are_not_identity_joined": True,
            "all118_is_source_mk_censoring_calibration": True,
            "f2_saved_frame_events_are_brackets": True,
            "expanded_xyz_is_not_a_domain_only_causal_control": True,
            "native_exclusion_is_not_physical_spill": True,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "not_assessed",
            "QE": "not_assessed",
        },
        "read_policy": {
            "h5_opened": False,
            "trajectory_content_opened": False,
            "part_bi4_opened": False,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
    }


def make_contract(calibration_report: Path | str, base_semantics_contract: Path | str, output: Path | str) -> dict[str, Any]:
    calibration = binding({"path": str(calibration_report)}, "all-118 calibration report")
    base = binding({"path": str(base_semantics_contract)}, "F2 trajectory semantics contract")
    calibration_path, calibration_payload = read_json(calibration["path"], "all-118 calibration report")
    _validate_calibration(calibration_path, calibration_payload)
    base_path, base_payload = read_json(base["path"], "F2 trajectory semantics contract")
    _validate_base_contract(base_path, base_payload)
    contract = {
        "schema": CONTRACT_SCHEMA,
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "calibration_report": calibration,
        "base_semantics_contract": base,
        "source_policy": "calibration and F2 trajectory are conservative semantic products; no Idp/time-only cross-case join",
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "part_bi4_opened": False},
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise SemanticCompareError(f"refusing to overwrite contract: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return contract


def make_request(contract_path: Path | str, output: Path | str, worktree_root: Path | str) -> dict[str, Any]:
    """Build a guarded one-CPU request after the F2 trajectory report exists.

    Only the contract and small JSON/log inputs are registered.  The base v1
    semantic consumer has already recorded the deferred H5 read in its own
    producer request; this comparison worker itself performs no H5 read.
    """
    contract_path = require_file(contract_path, "semantic comparison contract")
    contract = read_json(contract_path, "semantic comparison contract")[1]
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise SemanticCompareError("cannot build request for another contract schema")
    root = Path(worktree_root).expanduser().resolve()
    worker = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_s1_semantic_compare_v2.py"
    v1_worker = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_s1_trajectory_semantics_v1.py"
    current = root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"
    dispatch = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
    strict = root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
    runtime = root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
    base_path = require_file(contract["base_semantics_contract"]["path"], "F2 trajectory semantics contract")
    base = read_json(base_path, "F2 trajectory semantics contract")[1]
    if base.get("schema") != BASE_CONTRACT_SCHEMA:
        raise SemanticCompareError("request requires the completed v1 trajectory semantics contract")
    # Revalidate every producer-side small report binding before placing it in
    # a new request.  A path-only join could otherwise silently consume a
    # report from another F2 attempt with the same case label.
    calibration_binding = binding(contract["calibration_report"], "all-118 calibration report")
    base_bindings = _validate_base_contract(base_path, base)
    calibration_path, calibration_payload = read_json(calibration_binding["path"], "all-118 calibration report")
    _validate_calibration(calibration_path, calibration_payload)
    report_items = [
        ("calibration_report", calibration_binding["path"]),
        ("trajectory_semantics_contract", str(base_path)),
        *[(name, item["path"]) for name, item in base_bindings.items()],
    ]
    inputs = [contract_path, worker, v1_worker, current, dispatch, strict, runtime]
    inputs.extend(Path(path).expanduser().resolve() for _, path in report_items)
    for path in inputs:
        require_file(path, "request input")
    input_hashes = {str(path): sha256(path) for path in inputs}
    request = {
        "schema": "ds02.runner-request.v1",
        "attempt_id": "f2-s1-semantic-compare-v2",
        "case_id": "F2_S1_SEMANTIC_COMPARE_ALL118_AND_TRAJECTORY_V2",
        "family_id": "F2",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 33554432,
        "cwd": str(root / "lagrangian-fluid-lab/scripts"),
        "worktree_root": str(root),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(worker), "run", "--contract", str(contract_path),
            "--output", "{attempt_root}/f2-s1-semantic-compare-v2.json",
        ],
        "input_files": [str(path) for path in inputs],
        "input_sha256": input_hashes,
        "launch_allowed": True,
        "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU",
        "source_cost": {
            "h5_bytes_read": 0,
            "trajectory_bytes_read": 0,
            "part_bi4_bytes_read": 0,
            "small_json_log_bytes_hashed": sum(path.stat().st_size for path in inputs),
        },
        "qualification": {
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
        "solver_launch_forbidden": True,
        "cfd_or_model_run": False,
        "request_note": "Compare completed all-118 source-MK/censoring calibration with the exact F2 saved-frame trajectory/expanded native semantic product; no identity-only cross-case join, no H5 read by this worker, and no physical-fate or dynamics credit.",
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise SemanticCompareError(f"refusing to overwrite request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise SemanticCompareError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("make-contract")
    make.add_argument("--calibration-report", type=Path, required=True)
    make.add_argument("--base-semantics-contract", type=Path, required=True)
    make.add_argument("--output", type=Path, required=True)
    make_request_parser = sub.add_parser("make-request")
    make_request_parser.add_argument("--contract", type=Path, required=True)
    make_request_parser.add_argument("--output", type=Path, required=True)
    make_request_parser.add_argument("--worktree-root", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--contract", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "make-contract":
        result = make_contract(args.calibration_report, args.base_semantics_contract, args.output)
        print(json.dumps({"status": "CONTRACT_CREATED", "path": str(args.output.resolve()), "schema": result["schema"]}, sort_keys=True))
        return 0
    if args.command == "make-request":
        result = make_request(args.contract, args.output, args.worktree_root)
        print(json.dumps({"status": result["status"], "path": str(args.output.resolve()), "inputs": len(result["input_files"])}, sort_keys=True))
        return 0
    result = analyze(args.contract)
    _atomic_json(args.output, result)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
