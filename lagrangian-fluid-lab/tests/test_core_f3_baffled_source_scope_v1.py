"""Contract tests for the independent F3 internal-baffle source scope."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCOPE = LAB / "campaigns/core-v1/cfd/f3-baffle-exchange-source-scope-v1"
CARD_PATH = SCOPE / "candidate-card-v1.json"
MATRIX_PATH = SCOPE / "qualification-matrix-v1.json"
DENOMINATOR_PATH = SCOPE / "failure-denominator-v1.json"
PREPARED_PATH = SCOPE / "anchor-q0p5-dp0p0075-v3/prepared.json"
SCRIPT_PATH = LAB / "scripts/core_f3_baffled_source_scope_preflight_v1.py"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_versioned_artifacts_and_sha_bindings_are_closed() -> None:
    card = _read(CARD_PATH)
    matrix = _read(MATRIX_PATH)
    denominator = _read(DENOMINATOR_PATH)
    prepared = _read(PREPARED_PATH)

    assert card["status"] == "candidate_handoff_root_review_only"
    assert card["qualified"] is False
    assert card["qualification_claim"].startswith("none;")
    assert card["qualification_design"]["matrix"]["sha256"] == _sha256(MATRIX_PATH)
    assert card["qualification_design"]["failure_denominator"]["sha256"] == _sha256(DENOMINATOR_PATH)
    assert card["preflight"]["prepared"]["sha256"] == _sha256(PREPARED_PATH)
    assert card["preflight"]["runner"]["sha256"] == _sha256(SCRIPT_PATH)
    assert prepared["source_provenance"]["core_preflight_runner_sha256"] == _sha256(SCRIPT_PATH)
    assert denominator["matrix_path"].endswith("qualification-matrix-v1.json")
    assert matrix["candidate_card_path"].endswith("candidate-card-v1.json")


def test_fixed_matrix_has_fifteen_unique_rows_and_zero_credit() -> None:
    matrix = _read(MATRIX_PATH)
    rows = matrix["rows"]

    assert matrix["status"] == "fixed_design_preflight_anchor_only"
    assert matrix["design_only"] is True
    assert len(rows) == 15
    assert len({row["row_id"] for row in rows}) == 15
    assert all(row["status"] == "not_started" for row in rows)
    assert Counter(row["row_kind"] for row in rows) == Counter(
        {"spatial_anchor": 9, "held_out_impulse": 4, "temporal_output_cadence": 2}
    )
    assert matrix["qualification_rule"]["denominator"] == 15
    assert matrix["qualification_rule"]["required_pass_count"] == 15
    assert matrix["qualification_rule"]["preflight_rows_credit"] == 0
    assert matrix["anchor"]["preflight_credit"] == 0
    assert matrix["anchor"]["case_id"] not in {row["row_id"] for row in rows}
    assert matrix["execution_controls"] == {
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "matrix_launch": False,
    }

    for row in rows:
        assert abs(row["u0_x_m_s"] - (0.45 + 0.60 * row["q"])) < 1e-12
        assert row["time_max_s"] == 8.35
        assert row["dp_m"] in {0.005, 0.0075, 0.01}
        assert row["output_interval_s"] in {0.002, 0.005, 0.01}


def test_failure_denominator_retains_every_failure_class() -> None:
    denominator = _read(DENOMINATOR_PATH)
    rules = denominator["fixed_rules"]
    accounting = denominator["denominator"]

    assert accounting == {
        "planned_rows": 15,
        "executed_rows": 0,
        "passed_rows": 0,
        "failed_rows": 0,
        "unattempted_rows": 15,
        "preflight_rows_credited": 0,
        "qualification_numerator": 0,
    }
    assert all(rules[key] is True for key in (
        "all_planned_rows_stay_in_denominator",
        "unattempted_rows_stay_in_denominator",
        "infrastructure_failures_stay_in_denominator",
        "scientific_failures_stay_in_denominator",
        "event_censor_is_failure",
    ))
    assert all(rules[key] is False for key in (
        "same_input_retry",
        "threshold_relaxation",
        "horizon_extension",
        "survivor_renormalization",
        "single_point_diagnostic_is_qualification",
        "preflight_anchor_is_qualification",
    ))
    assert denominator["row_statuses"]["not_started"] == 15
    assert denominator["execution_controls"]["registry_mutation"] == 0
    assert len(denominator["historical_noncredit_evidence"]) == 5


def test_preflight_native_artifact_passes_without_solver_product() -> None:
    card = _read(CARD_PATH)
    prepared = _read(PREPARED_PATH)

    assert prepared["schema"] == "core.f3.baffled_source_scope.preflight.v1"
    assert prepared["scope_id"] == card["scope_id"]
    assert prepared["revision_id"] == card["revision_id"]
    assert prepared["status"] == "prepared_only"
    assert prepared["preflight_pass"] is True
    assert prepared["launch_allowed"] is False
    assert prepared["solver_product_present"] is False
    assert prepared["sampling"]["fluid_particles"] == 33120
    assert prepared["sampling"]["boundary_particles"] == 44174
    assert prepared["sampling"]["total_particles"] == 77294
    assert prepared["sampling"]["mass_gate_pass"] is True
    assert abs(prepared["sampling"]["relative_mass_error"]) <= 0.03
    assert prepared["native_initial"]["initial_state_pass"] is True
    assert prepared["geometry"]["mkbound_roles"] == {
        "0": "finite_outer_tank_open_top",
        "1": "internal_baffle",
    }
    assert prepared["geometry"]["physical_geometry_changed_relative_to_plain_source"] is True
    assert prepared["novelty_contract"]["relative_to_legacy_baffle_probe"]["same_input"] is False
    assert prepared["novelty_contract"]["relative_to_legacy_baffle_probe"]["legacy_bi4_reused"] is False
    assert prepared["novelty_contract"]["relative_to_legacy_baffle_probe"]["legacy_trajectory_reused"] is False
    controls = prepared["execution_controls"]
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["qualification_numerator_credit"] == 0


def test_current_and_legacy_inputs_are_explicitly_noncredit() -> None:
    card = _read(CARD_PATH)
    handoff = _read(LAB / "campaigns/core-v1/cfd/f3-native-mls-sources/handoff-v2.json")
    legacy_def = LAB / "cases/F3/F3_baffled_slosh/F3_baffled_slosh_Def.xml"
    legacy_h5 = LAB / "data/F3_baffled_slosh.h5"

    novelty = card["novelty_audit"]
    assert handoff["status"] == "prepared_only"
    assert handoff["safety"]["qualification_granted"] is False
    assert novelty["current_f3_mls_handoff"]["reused"] is False
    assert novelty["legacy_baffle_probe_definition"]["new_inputs_reused"] is False
    assert novelty["legacy_baffle_probe_definition"]["legacy_generated_source_reused"] is False
    assert novelty["legacy_baffle_probe_definition"]["legacy_trajectory_reused"] is False
    assert legacy_def.is_file()
    assert legacy_h5.is_file()
    assert novelty["legacy_baffle_probe_definition"]["sha256"] == _sha256(legacy_def)
    assert card["admission_gates"]["threshold_relaxation"] is False
    assert card["admission_gates"]["point_diagnostic_as_qualification"] is False
    assert card["admission_gates"]["t1_qualification_admissible_now"] is False
