"""Source-only API checks for the F1 exact-mother batch-8 handoff."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


SCOPE = Path(__file__).resolve().parents[1]
SCRIPT = SCOPE / "scripts" / "build_exact_mother_batch8.py"
PLAN_PATH = SCOPE / "batch8_plan.json"
CONTRACT_PATH = SCOPE / "source_contract.json"


def _load_builder():
    spec = importlib.util.spec_from_file_location("f1_exact_mother_builder", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_plan_has_the_requested_eight_commensurate_recipes():
    plan = _load(PLAN_PATH)
    assert plan["schema"] == "ds02.f1.exact-mother-batch8-plan.v1"
    assert plan["source_only"] is True
    assert plan["execution_performed"] is False
    assert plan["launch_allowed"] is False
    rows = plan["rows"]
    assert len(rows) == 8
    assert [row["initial_fluid_height_m"] for row in rows[:4]] == [0.11, 0.13, 0.15, 0.19]
    assert [row["initial_fluid_height_m"] for row in rows[4:]] == [0.22, 0.26, 0.30, 0.34]
    assert {row["resolution"]["dp_m"] for row in rows[:4]} == {0.01}
    assert {row["resolution"]["dp_m"] for row in rows[4:]} == {0.02}
    assert all(row["resolution"]["label"] == "coarse" for row in rows)
    assert all(row["resolution"]["single_resolution"] is True for row in rows)


def test_predictions_are_integer_grid_predictions_only():
    plan = _load(PLAN_PATH)
    expected = {
        "F1_MOTHER_ECC_H011_DP010": ([40, 67, 11], 29480, 0.02948, 29.48),
        "F1_MOTHER_ECC_H013_DP010": ([40, 67, 13], 34840, 0.03484, 34.84),
        "F1_MOTHER_ECC_H015_DP010": ([40, 67, 15], 40200, 0.0402, 40.2),
        "F1_MOTHER_ECC_H019_DP010": ([40, 67, 19], 50920, 0.05092, 50.92),
        "F1_MOTHER_DUAL_H022_DP020": ([50, 50, 11], 27500, 0.22, 220.0),
        "F1_MOTHER_DUAL_H026_DP020": ([50, 50, 13], 32500, 0.26, 260.0),
        "F1_MOTHER_DUAL_H030_DP020": ([50, 50, 15], 37500, 0.30, 300.0),
        "F1_MOTHER_DUAL_H034_DP020": ([50, 50, 17], 42500, 0.34, 340.0),
    }
    for row in plan["rows"]:
        values = row["predicted_initial_state"]
        assert row["case_id"] in expected
        assert (
            values["grid_cells_xyz"],
            values["predicted_fluid_particles"],
            values["theoretical_fluid_volume_m3"],
            values["theoretical_fluid_mass_kg"],
        ) == expected[row["case_id"]]
        assert values["status"] == "prediction_only_until_new_gencase_and_initial_qa"


def test_only_fluid_height_mutation_is_planned():
    plan = _load(PLAN_PATH)
    contracts = _load(CONTRACT_PATH)["contracts"]
    for row in plan["rows"]:
        contract = contracts[row["source_contract_id"]]
        mutation = row["planned_source_mutation"]
        assert mutation["kind"] == "single_parameter_source_mutation"
        assert mutation["target"] == "fluid_drawbox.size.z"
        assert mutation["materialization_status"] == "not_materialized"
        assert mutation["materialized_definition_sha256"] is None
        assert mutation["all_other_source_bytes"].startswith("must remain byte-identical")
        assert abs(mutation["target_value_m"] - (row["initial_fluid_height_m"] - row["resolution"]["dp_m"])) < 1e-12
        assert mutation["selector"] == contract["fluid_drawbox_source_contract"]["mutation_selector"]
        assert contract["source_literals"]["setshapemode"] == "dp | actual | bound"
        assert contract["source_literals"]["boundary_support_layer_count_claim"] is None


def test_source_hashes_and_native_contracts_are_bound():
    builder = _load_builder()
    contracts_doc = _load(CONTRACT_PATH)
    contracts = contracts_doc["contracts"]
    assert contracts_doc["tool_use_policy"] == {
        "this_scope_invoked_conversion": False,
        "this_scope_invoked_gencase": False,
        "this_scope_invoked_solver": False,
        "this_scope_read_source_arrays": False,
        "this_scope_rendered_paraview": False,
    }
    for contract_id, contract in contracts.items():
        definition = Path(contract["source_definition"]["path"])
        assert definition.exists(), definition
        assert _sha256(definition) == contract["source_definition"]["sha256"]
        typed_request = Path(contract["canonical_binding_034"]["typed_request_path"])
        assert typed_request.exists(), typed_request
        assert _sha256(typed_request) == contract["canonical_binding_034"]["typed_request_sha256"]
        assert contract["eos_constants"] == builder.COMMON_EOS
        assert contract["native_execution_step_flags"]["Boundary"] == "1"
        assert contract["native_execution_step_flags"]["StepAlgorithm"] == "1"
        assert contract["native_execution_step_flags"]["Kernel"] == "1"
        assert contract["native_execution_step_flags"]["TimeOut"] == "0.01"
        assert contract["native_mass_policy"] == "native_massfluid_no_rescaling"


def test_all_requests_are_fail_closed_and_require_fresh_qa():
    plan = _load(PLAN_PATH)
    for row in plan["rows"]:
        assert row["execution_contract"]["launch_allowed"] is False
        assert row["execution_contract"]["independent_case_count_increment"] == 0
        assert row["execution_contract"]["user_visual_approval_recorded"] is False
        assert row["execution_contract"]["bi4_equality_claim"] is False
        assert row["actual_artifacts"] is None
        for kind, relpath in row["request_files"].items():
            request = _load(SCOPE / relpath)
            assert request["launch_allowed"] is False
            assert request["production_approval"] == "none"
            assert request["independent_case_count_increment"] == 0
            assert request.get("actual_outputs") is None
            if kind == "gencase":
                assert request["claim_boundary"]["new_generation_completed"] is False
                assert request["post_gencase_initial_qa_request"].endswith("_initial_qa_request.json")
            else:
                assert request["claim_boundary"] if "claim_boundary" in request else True
                assert request["input_contract"]["new_artifact_hashes_are_pending"] is True


def test_historical_negatives_and_unaccepted_gates_remain_visible():
    plan = _load(PLAN_PATH)
    failures = {(item["mechanism_id"], item["head_m"]) for item in plan["historical_negatives"]}
    assert failures == {("eccentric_obstacle", 0.30), ("asymmetric_dual_channel", 0.55)}
    assert all(item["revalidated_by_this_scope"] is False for item in plan["historical_negatives"])
    assert plan["quality_gates"]["q_n"].startswith("not accepted")
    assert plan["quality_gates"]["visual_review"].startswith("pending Root")
    assert plan["claim_boundary"] == {
        "bi4_equality_claim": False,
        "geometry_or_solver_numeric_change_claim": False,
        "new_height_generation_claim": False,
        "setshapemode_rewrite_or_invalidity_claim": False,
        "two_dp_to_four_layer_translation_claim": False,
        "zero_loss_or_eliminated_overtopping_proven": False,
    }


def test_scope_contains_no_generated_or_array_artifacts():
    forbidden_suffixes = {".bi4", ".h5", ".vtk", ".xmf", ".csv"}
    generated = [path for path in SCOPE.rglob("*") if path.is_file() and path.suffix in forbidden_suffixes]
    assert generated == []
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import h5py" not in source
    assert "import numpy" not in source
    assert "subprocess" not in source
