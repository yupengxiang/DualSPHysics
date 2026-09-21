"""Focused checks for the one-shot F6 v10 observation-axis preflight."""

from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SOURCE = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-root-review-20260921"
OUTPUT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-cpu-native-preflight-20260921"
RECEIPT = OUTPUT / "preflight.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v10_receipt_is_fresh_hash_bound_and_nonqualifying() -> None:
    value = load(RECEIPT)
    assert value["status"] == "cpu_native_preflight_pass_exact_one"
    assert value["preflight_pass"] is True
    assert value["fresh_identity"]["checks"]
    assert all(value["fresh_identity"]["checks"].values())
    assert value["fresh_identity"]["body_id"] == "F6_physical_anchor_body_lambda_v10_20260921"
    assert value["scope_id"] == "F6_fluid_rigid_body_physical_anchor_v2"
    assert value["authorization"]["path"].endswith("/authorization.json")
    assert value["input_hashes"]["definition"]["sha256"]
    assert value["input_hashes"]["generated_xml"]["sha256"]
    assert value["input_hashes"]["generated_bi4"]["sha256"]
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["T1"] is False


def test_v10_executes_cpu_gen_case_and_native_decode_once_without_solver() -> None:
    value = load(RECEIPT)
    controls = value["execution_controls"]
    assert controls["cpu_gencase_invoked"] is True
    assert controls["cpu_native_decode_invoked"] is True
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False
    assert value["authorization"]["sha256"]
    assert value["one_shot_lock"]["sha256"]
    assert value["gencase"]["returncode"] == 0
    assert value["gencase"]["cpu_gencase_invoked"] is True
    assert controls["cpu_native_decode_invoked"] is True


def test_v10_native_mass_body_metadata_and_geometry_contracts_pass() -> None:
    value = load(RECEIPT)
    checks = value["checks"]
    for name in (
        "native_fluid_count",
        "native_body_count",
        "mass_relative_gate",
        "generated_body_mass_matches_contract",
        "generated_body_center_matches_contract",
        "generated_body_inertia_matches_contract",
        "fluid_inside_declared_box",
        "body_inside_declared_box",
        "all_particles_inside_tank",
        "boundnor_finite_if_present",
        "boundnor_count_if_present",
    ):
        assert checks[name] is True
    assert value["geometry_opening_entity_boundary"]["passed"] is True
    assert value["event_window"]["complete"] is False
    assert value["event_window"]["requires_equilibrium_claim"] is False
    assert value["event_window"]["equilibrium_status"] == "not_claimed"


def test_v10_source_is_a_new_definition_and_not_a_v9_input() -> None:
    definition = next(SOURCE.glob("*_Def.xml"))
    text = definition.read_text(encoding="utf-8")
    assert "v9" not in definition.name
    assert "F6_floating_box" not in text
    assert ".bi4" not in text
    assert ".h5" not in text
    contract = load(SOURCE / "definition-contract.json")
    assert contract["fresh_input"]["old_bi4_reused"] is False
    assert contract["fresh_input"]["old_hdf5_reused"] is False
    assert contract["provenance_policy"]["prior_v9_context_not_read_as_input"] is True
