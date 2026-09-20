import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
PREFLIGHT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/preflight-v2/preflight.json"


def load():
    return json.loads(PREFLIGHT.read_text())


def test_f5_v2_cpu_native_preflight_passes_static_gates_only():
    value = load()
    assert value["schema"] == "core.f5.third_t1.preflight.v1"
    assert value["status"] == "cpu_native_preflight_passed_static_only"
    assert value["preflight_pass"] is True
    assert value["qualified"] is False
    assert value["matrix_credit"] == 0
    controls = value["execution_controls"]
    assert controls["gencase_invoked"] is True
    assert controls["native_decode_invoked"] is True
    assert controls["solver_invoked"] is False
    assert controls["gpu_started"] is False
    assert controls["queue_mutation"] == controls["ledger_mutation"] == controls["registry_mutation"] == 0


def test_f5_v2_native_identity_finite_mass_and_geometry_pass():
    value = load()
    native = value["native"]
    generated = value["generated"]
    assert native["total_particles"] == 1374477
    assert native["fluid_particles"] == generated["fluid_particles"] == 1279855
    assert native["unique_ids"] is True
    assert native["finite_arrays"] is True
    assert native["mass_metadata_match"] is True
    assert value["geometry"]["pass"] is True
    assert value["geometry"]["anomalies"] == []
    assert value["hard_gates"]["full_window_reached"] == "not_applicable_until_solver"
    assert value["hard_gates"]["event_completion"] == "not_applicable_until_solver"


def test_f5_v2_preflight_has_no_scientific_credit():
    value = load()
    assert value["qualification_claim"] == "none"
    assert value["execution_controls"]["qualification_credit"] == 0
    assert value["hard_gates"]["trajectory_endpoint_gate"] == "not_applicable_until_solver"
