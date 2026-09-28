from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
import sys

import pytest

from scripts import f8_r008_admission_verification_bridge_v1 as bridge


LAB = Path(__file__).parents[1]


def _load_report() -> dict:
    return json.loads(
        (LAB / "reports/F8-R008-ADMISSION-VERIFICATION-BRIDGE-V1-2026-09-28.json").read_text(
            encoding="utf-8"
        )
    )


def test_default_bridge_binds_static_chain_but_stays_blocked() -> None:
    report = bridge.build_report()

    assert report["schema"] == bridge.REPORT_SCHEMA
    assert report["status"] == bridge.STATUS
    assert report["scope_id"] == bridge.SCOPE_ID
    assert report["admission"] == {
        "static_dependency_chain_bound": True,
        "source_contracts_bound": True,
        "target_kernel_static_pin_complete": False,
        "target_kernel_source_integrity_verified": False,
        "source_callgraph_conformance": False,
        "trusted_runtime_identity_verified": False,
        "native_integrity_verified": False,
        "terminal_matrix_complete": False,
        "t1_execution_chain_ready": False,
        "next_step": "collect separately authorized target/runtime/native/terminal evidence, then re-run this bridge before any T1 adjudication",
    }
    assert report["authorization"] == bridge.AUTHORIZATION
    assert report["verification"]["static_consistency_passed"] is True
    assert report["verification"]["runtime_verification_passed"] is False
    assert len(report["dependencies"]) == len(bridge.DEPENDENCY_SPECS)
    assert [item["code"] for item in report["blockers"]] == list(bridge.BLOCKER_CODES)


def test_native_registry_and_t1_plan_preserve_denominators() -> None:
    report = bridge.build_report()

    assert report["native_integrity"]["case_count"] == 15
    assert report["native_integrity"]["gate_count"] == 8
    assert report["native_integrity"]["denominator_cells"] == 120
    assert report["native_integrity"]["native_integrity_evaluated"] is False
    plan = report["t1_execution_chain"]
    assert plan["case_count"] == 15
    assert len(plan["rows"]) == 15
    assert tuple(plan["case_ids"]) == bridge.native_registry.EXPECTED_QUALIFICATION_CASE_IDS
    assert all(row["B"] == "not_verified" for row in plan["rows"])
    assert all(row["C"] == "not_verified" for row in plan["rows"])
    assert all(row["D"] == "not_verified" for row in plan["rows"])
    assert all(row["terminal"] == "missing" for row in plan["rows"])


def test_checked_in_machine_report_equals_current_bounded_projection() -> None:
    expected = bridge.build_report()
    checked_in = _load_report()
    assert checked_in == expected
    assert bridge.verify_report() == expected
    assert bridge.validate_report(checked_in) == checked_in


def test_dependency_digest_drift_fails_closed(tmp_path: Path) -> None:
    source = LAB / bridge.DEPENDENCY_SPECS["terminal_matrix"]["path"]
    tampered = json.loads(source.read_text(encoding="utf-8"))
    tampered["summary"]["missing_rows"] = 14
    path = tmp_path / "terminal-matrix.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(bridge.AdmissionVerificationBridgeError, match="missing_rows|terminal matrix"):
        bridge.build_report(dependency_paths={"terminal_matrix": path})


def test_authorization_promotion_is_rejected() -> None:
    promoted = copy.deepcopy(bridge.build_report())
    promoted["authorization"]["T1_numerical"] = True

    with pytest.raises(bridge.AdmissionVerificationBridgeError, match="authorization"):
        bridge.validate_report(promoted)


def test_case_denominator_mutation_is_rejected() -> None:
    mutated = copy.deepcopy(bridge.build_report())
    mutated["t1_execution_chain"]["rows"].pop()

    with pytest.raises(bridge.AdmissionVerificationBridgeError, match="T1 verification rows"):
        bridge.validate_report(mutated)


def test_reviewed_source_digest_drift_is_rejected(tmp_path: Path) -> None:
    source = LAB / bridge.DEPENDENCY_SPECS["safe_bi4_review"]["path"]
    tampered = json.loads(source.read_text(encoding="utf-8"))
    for evidence in tampered["evidence"]:
        if evidence.get("path") == "scripts/f8_r008_safe_bi4_decoder_v1.py":
            evidence["sha256"] = "f" * 64
            break
    path = tmp_path / "safe-review.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(bridge.AdmissionVerificationBridgeError, match="source digest drift"):
        bridge.build_report(dependency_paths={"safe_bi4_review": path})


def test_module_has_no_runtime_execution_surface() -> None:
    source = inspect.getsource(bridge)
    for forbidden in (
        "import subprocess", "subprocess.", "nvidia-smi", "CUDA_VISIBLE_DEVICES",
        "import torch", "import h5py", "fanotify_init", "os.system",
    ):
        assert forbidden not in source
    assert "production_bi4_hdf5_or_solver_frame_read" in source
    assert str(sys.executable)
