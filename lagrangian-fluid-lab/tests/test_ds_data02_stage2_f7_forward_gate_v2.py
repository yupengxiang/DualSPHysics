from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = _load(
    "f7_actual_runparts_gate_v2_test",
    ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f7_actual_runparts_gate_v2.py",
)
QA = _load(
    "f7_half_initial_qa_v2_test",
    ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f7_half_cfl_initial_qa_v2.py",
)


def test_actual_v5_runparts_gate_binds_observed_1201_rows_and_endpoint():
    value = GATE.build_gate()
    assert value["status"] == "OBSERVED_NATIVE_SAME_CFL_RUNPARTS"
    assert value["runparts"]["numeric_rows"] == 1201
    assert value["runparts"]["first_part"] == 0
    assert value["runparts"]["last_part"] == 1200
    assert value["runparts"]["last_time_s"] == 12.00003209155591
    assert value["observed_control"]["time_out_s"] == 0.01
    assert value["checks"]["planned_1202_rows_claimed"] is False
    assert value["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_half_initial_qa_keeps_motion_warning_and_pending_bi4_hash(tmp_path: Path):
    value = QA.build(tmp_path)
    qa = value["qa"]
    request = value["request"]
    assert qa["status"] == "PENDING_INITIAL_TYPED_QA"
    assert qa["xml_comparison"]["same_initial_particle_intent"] is True
    assert qa["xml_comparison"]["half_cfl_is_0p1"] is True
    assert qa["xml_comparison"]["baseline_cfl_is_0p2"] is True
    assert qa["xml_comparison"]["typed_arrays_compared"] is False
    assert qa["gencase"]["observed_omp_threads"] == 16
    assert qa["gencase"]["thread_contract_status"] == "MISMATCH_OBSERVED"
    assert any("not found to copy" in item for item in qa["gencase"]["warnings"])
    assert qa["generated"]["half_bi4"]["sha256"] is None
    assert request["status"] == "PENDING_PARENT_IO_SLOT"
    assert request["launch_allowed"] is False
    assert request["compare_contract"]["half_bi4_content_hash"] == "PARENT_GUARD_REQUIRED"
