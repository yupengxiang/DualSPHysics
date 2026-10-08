from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_s1_semantic_compare_v2.py"
SPEC = importlib.util.spec_from_file_location("semantic_compare_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _calibration() -> dict:
    rows = []
    native_counts = {"F2": 476, "F4": 51, "F6": 801}
    for family, count in (("F2", 48), ("F4", 22), ("F6", 48)):
        base, remainder = divmod(native_counts[family], count)
        for index in range(count):
            rows.append({
                "case_key": f"{family}/scan-{index:03d}",
                "family_id": family,
                "native_count": base + int(index < remainder),
                "errors": [],
                "labels": {
                    "native_cause": "VALID_NATIVE_CAUSE",
                    "source_mk": "VALID_SOURCE_MK_MAPPING",
                    "physical_fate": "UNKNOWN_PHYSICAL_FATE",
                    "dynamical_impact": "UNKNOWN_DYNAMICAL_IMPACT",
                    "QN": "NOT_ASSESSED",
                    "QE": "NOT_ASSESSED",
                },
            })
    return {
        "schema": MODULE.CALIBRATION_SCHEMA,
        "status": "LABEL_CALIBRATED_SOURCE_MK_CENSORING_NO_MODEL",
        "current": {"sha256": MODULE.CURRENT_SHA256},
        "coverage": {
            "selected_case_count": 118,
            "selected_native_id_count": 1328,
            "selected_case_counts": {"F2": 48, "F4": 22, "F6": 48},
        },
        "cases": rows,
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }


def test_calibration_validation_keeps_family_counts_and_unknowns(tmp_path: Path) -> None:
    payload = _calibration()
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    summary = MODULE._validate_calibration(path, payload)
    assert summary["family_case_counts"] == {"F2": 48, "F4": 22, "F6": 48}
    assert summary["physical_fate"] == "UNKNOWN"
    assert summary["dynamical_impact"] == "UNKNOWN"


def test_calibration_validation_rejects_wrong_coverage(tmp_path: Path) -> None:
    payload = _calibration()
    payload["coverage"]["selected_native_id_count"] = 118
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MODULE.SemanticCompareError, match="native ID count"):
        MODULE._validate_calibration(path, payload)


def test_make_contract_is_forward_only_and_unknown(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.json"
    base = tmp_path / "base-semantics-contract.json"
    calibration.write_text(json.dumps(_calibration()), encoding="utf-8")
    report_bindings = {}
    for name in MODULE.BASE_REPORT_FIELDS:
        report = tmp_path / f"{name}.json"
        report.write_text(json.dumps({"name": name}), encoding="utf-8")
        report_bindings[name] = {"path": str(report)}
    base.write_text(json.dumps({
        "schema": MODULE.BASE_CONTRACT_SCHEMA,
        **report_bindings,
    }), encoding="utf-8")
    output = tmp_path / "compare-contract.json"
    contract = MODULE.make_contract(calibration, base, output)
    assert contract["physical_fate"] == "UNKNOWN"
    assert contract["dynamical_impact"] == "UNKNOWN"
    assert json.loads(output.read_text())["schema"] == MODULE.CONTRACT_SCHEMA


def test_make_request_rebinds_completed_v1_reports_without_h5_inputs(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    scripts = root / "lagrangian-fluid-lab" / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "ds_data02_stage2_f2_s1_semantic_compare_v2.py",
        "ds_data02_stage2_f2_s1_trajectory_semantics_v1.py",
        "ds_data02_stage2_dispatch_v8.py",
        "ds_data02_strict_dispatch_v8.py",
        "ds_data02_runtime_v8.py",
    ):
        (scripts / name).write_text("# fixture\n", encoding="utf-8")
    current = root / "lagrangian-fluid-lab" / "campaigns" / "ds-data-02" / "stage2" / "CURRENT336.json"
    current.parent.mkdir(parents=True)
    current.write_text("{}\n", encoding="utf-8")
    report_paths = {}
    for name in ("trajectory_report", "conversion_report", "expanded_native_report", "expanded_runout"):
        report = tmp_path / f"{name}.json"
        report.write_text(json.dumps({"name": name}), encoding="utf-8")
        report_paths[name] = {"path": str(report.resolve())}
    base = tmp_path / "base-semantics-contract.json"
    base.write_text(json.dumps({
        "schema": "ds02.stage2.f2-s1-trajectory-semantics-contract.v1",
        **report_paths,
    }), encoding="utf-8")
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration()), encoding="utf-8")
    contract_path = tmp_path / "compare-contract.json"
    MODULE.make_contract(calibration, base, contract_path)
    request_path = tmp_path / "request.json"

    request = MODULE.make_request(contract_path, request_path, root)

    assert request["launch_allowed"] is True
    assert request["solver_launch_forbidden"] is True
    assert request["source_cost"]["h5_bytes_read"] == 0
    assert request["source_cost"]["trajectory_bytes_read"] == 0
    assert request["source_cost"]["part_bi4_bytes_read"] == 0
    assert all(".h5" not in path and ".bi4" not in path for path in request["input_files"])
    assert len(request["input_files"]) == len(request["input_sha256"])


def test_make_request_rejects_non_v1_semantics_contract(tmp_path: Path) -> None:
    contract = tmp_path / "compare-contract.json"
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration()), encoding="utf-8")
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    contract.write_text(json.dumps({
        "schema": MODULE.CONTRACT_SCHEMA,
        "calibration_report": {"path": str(calibration)},
        "base_semantics_contract": {"path": str(base)},
    }), encoding="utf-8")
    with pytest.raises(MODULE.SemanticCompareError, match="completed v1"):
        MODULE.make_request(contract, tmp_path / "request.json", tmp_path)
