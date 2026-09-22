from __future__ import annotations

import json

from scripts.f9_definition_contract_v1 import OUTPUT, build_contract


def test_f9_definition_contract_is_static_only() -> None:
    contract = build_contract()
    assert contract["status"] == "static_definition_contract_only_no_runtime_authorization"
    assert contract["admission_granted"] is False
    assert contract["geometry_contract"]["top_boundary_particles"] is False
    assert contract["execution_parameters_contract"]["XYPeriodic_parameter"] == "forbidden"
    assert contract["anchor_geometry"]["geometric_forward_translation_m"][2] < 0.0
    assert contract["anchor_geometry"]["runtime_periodic_x_vector_m"][0] < 0.0
    assert contract["anchor_geometry"]["runtime_periodic_x_vector_m"][2] > 0.0


def test_f9_definition_contract_freezes_nusselt_boundary_semantics() -> None:
    contract = build_contract()
    assert contract["execution_parameters_contract"]["Boundary"] == 2
    assert contract["execution_parameters_contract"]["SlipMode"] == 2
    assert contract["execution_parameters_contract"]["ViscoTreatment"] == 3
    assert contract["execution_parameters_contract"]["NoPenetration"] == 1
    assert contract["constantsdef_contract"]["gravity_is_only_driving_input"] is True
    assert contract["execution_parameters_contract"]["DtFixed_s"] == 0.00001
    assert contract["execution_parameters_contract"]["expected_output_rows"] == 501
    assert contract["runtime_authorization"]["definition_write"] is False
    assert contract["runtime_authorization"]["solver"] is False


def test_committed_f9_definition_contract_is_hash_bound() -> None:
    assert OUTPUT.is_file()
    contract = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert contract["status"] == "static_definition_contract_only_no_runtime_authorization"
    assert len(contract["evidence"]) == 3
    assert all(item["sha256"] for item in contract["evidence"])
