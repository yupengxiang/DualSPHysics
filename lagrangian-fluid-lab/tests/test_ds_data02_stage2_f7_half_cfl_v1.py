from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ds_data02_stage2_f7_half_cfl_v1.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_stage2_f7_half_cfl_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

ARTIFACT_DIR = (
    Path(__file__).resolve().parents[1]
    / "campaigns/ds-data-02/stage2/native-reconstruction/f7-half-cfl-v1/request-004"
)


def test_independent_definition_preserves_geometry_and_changes_only_registered_numbers() -> None:
    result = MODULE.validate_definition_pair()
    assert result["numeric_edits"] == {
        "cflnumber": {"reference": 0.2, "variant": 0.1},
        "TimeOut_s": {"reference": 0.02, "variant": 0.01},
    }
    assert result["reference"]["sha256"] == "f45a212f48ae0d55485e795b63e38702edd5cd2aac40aa69d4be9c155e7a4d37"
    assert result["variant"]["sha256"] == "b79307bec1e8ad07df0468027d2dc5f9143121c0bb82e496aee60e3352537bf0"
    assert result["geometry_sha256"] == MODULE.validate_definition_pair()["geometry_sha256"]
    assert result["initial_particle_intent"]["fluid_particles"] == 40700
    assert result["initial_particle_intent"]["total_particles"] == 70179


def test_request_is_cpu_gencase_only_and_hash_bound() -> None:
    request = MODULE.build_gencase_request()
    assert request["schema"] == "ds02.stage2.f7-half-cfl-gencase-request.v8"
    assert request["kind"] == "cpu"
    assert request["cpu_task_kind"] == "gencase"
    assert request["solver_launch_allowed"] is False
    assert request["execution_contract"]["hdf5_opened"] is False
    assert request["execution_contract"]["bi4_opened_by_this_request"] is False
    assert request["sha256"] == MODULE.canonical_sha(request)
    assert all(not path.lower().endswith((".h5", ".hdf5", ".bi4")) for path in request["input_files"])
    assert "DualSPHysics5.4_linux64" not in " ".join(request["command"])
    for path, digest in request["input_sha256"].items():
        assert MODULE.sha256_file(path) == digest


def test_plan_keeps_old_false_and_does_not_require_future_solver_receipt() -> None:
    request = MODULE.build_gencase_request()
    gate = MODULE.audit_same_cfl_runparts()
    gate["sha256"] = MODULE.canonical_sha(gate)
    plan = MODULE.build_half_plan(request, gate)
    assert plan["launch_allowed"] is False
    assert plan["solver_launch_allowed"] is False
    assert plan["gencase_request_launch_allowed"] is True
    assert plan["dense_save_interval_s"] == 0.01
    assert plan["readiness_gate"]["half_solver_ready"] is False
    assert plan["readiness_gate"]["solver_receipt_not_required_for_this_gate"] is True
    assert plan["historical_old_plan"]["launch_allowed"] is False
    assert plan["historical_old_plan"]["sha256"] == MODULE.sha256_file(MODULE.OLD_HALF_PLAN)
    assert plan["same_cfl_end_gate"]["frame_count_1202_and_12p000032_are_planning_only"] is True


def test_existing_runparts_end_is_observed_and_not_promoted_to_dense_contract() -> None:
    gate = MODULE.audit_same_cfl_runparts()
    assert gate["observed"]["numeric_rows"] == 601
    assert gate["observed"]["last_time_s"] == pytest.approx(12.00003209155591)
    assert gate["observed"]["mean_positive_save_interval_s"] == pytest.approx(0.0200000534859265)
    assert gate["checks"]["terminal_complete_12s"] is True
    assert gate["checks"]["dense_12s_gate"] is False
    assert gate["planning_contract"]["interpretation"] == "planning-only; observed RunPARTs controls the gate"


def test_readiness_requires_generated_source_and_initial_qa_but_not_solver_receipt(tmp_path: Path) -> None:
    empty = MODULE.half_solver_readiness()
    assert empty["half_solver_ready"] is False
    assert "actual initial typed QA" in empty["missing"]

    generated_xml = tmp_path / "generated.xml"
    generated_bi4 = tmp_path / "generated.bi4"
    receipt = tmp_path / "execution-receipt.json"
    generated_xml.write_text("<case />")
    generated_bi4.write_bytes(b"manufactured initial artifact")
    receipt.write_text(json.dumps({"status": "completed", "returncode": 0}))
    ready = MODULE.half_solver_readiness(
        generated_xml=generated_xml,
        generated_bi4=generated_bi4,
        gencase_receipt=receipt,
        initial_typed_qa={"identity_axis": "(Zone,Idp)", "valid": True},
    )
    assert ready["half_solver_ready"] is True
    assert ready["solver_receipt_not_required_for_this_gate"] is True


def test_committed_artifacts_match_builder() -> None:
    request_path = ARTIFACT_DIR / "f7-s2-half-cfl-gencase-request-v8-001.json"
    plan_path = ARTIFACT_DIR / "f7-s2-half-cfl-plan-v2-001.json"
    gate_path = ARTIFACT_DIR / "f7-s2-same-cfl-runparts-end-gate-v1-001.json"
    request = json.loads(request_path.read_text())
    plan = json.loads(plan_path.read_text())
    gate = json.loads(gate_path.read_text())
    assert request["sha256"] == MODULE.canonical_sha(request)
    assert plan["sha256"] == MODULE.canonical_sha(plan)
    assert gate["sha256"] == MODULE.canonical_sha(gate)
    assert plan["gencase_request_sha256"] == request["sha256"]
    assert plan["same_cfl_end_gate"]["sha256"] == gate["sha256"]
