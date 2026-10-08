from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_v4_current_bound.py"
PARENT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_parent_v7_current_bound.py"
FROZEN = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-replay-request-v15-001.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = _load(EVALUATOR, "typed_only_evaluator_v4_current_bound_test")
P = _load(PARENT, "typed_only_parent_v7_current_bound_test")


def _shadow_and_result() -> tuple[dict, dict, str, str]:
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    actual = frozen["current_binding"]["sha256"]
    historical = "a" * 64
    shadow = copy.deepcopy(frozen)
    shadow["current_binding"]["sha256"] = historical
    for item in shadow["source_files"]:
        if item["role"] == "current_catalog":
            item["sha256"] = historical
    profile = shadow["observer_profile"]
    profile["current_binding_sha256"] = historical
    profile["source_file_sha256"] = dict(profile["source_file_sha256"], current_catalog=historical)
    profile["sha256"] = E.canonical_sha(profile)
    source_files = {item["role"]: item["sha256"] for item in shadow["source_files"]}
    result = {
        "schema": E.V2.V1.V3.RESULT_SCHEMA,
        "model_invoked": False,
        "case_identity": copy.deepcopy(shadow["case_identity"]),
        "source_binding": {
            "binding_status": "EXACT_CURRENT_SOURCE_BOUND_RELOCATED",
            "current_catalog_sha256": historical,
            "trajectory_h5_producer_sha256": shadow["trajectory_h5"]["producer_declared_sha256"],
            "source_files": source_files,
        },
        "observer_profile": copy.deepcopy(profile),
        "cohort": {
            "identity_key": "(Zone,Idp)", "selected_count": 21114,
            "initial_fluid_candidates": 21114,
            "selected_identity_sha256": shadow["cohort"]["source_identity_set_sha256"],
        },
        "initial_mass_denominator": {
            "denominator_kg": profile["mass_denominator_kg"],
            "selected_initial_mass_kg": profile["mass_denominator_kg"],
            "initial_fluid_mass_kg": profile["mass_denominator_kg"],
            "initial_missing_mass_kg": 0.0, "initially_absent_count": 0,
            "later_missing_unique_count": 3, "later_missing_mass_kg": 0.003,
        },
    }
    result["labels"] = [
        {"zone": 0, "idp": index,
         "initial_mass_kg": profile["mass_denominator_kg"] / 21114.0,
         "status": "observed", "event_time_s": 0.0}
        for index in range(21114)
    ]
    front = {str(q): 0.0 for q in profile["mass_quantiles"]}
    result["frame_observations"] = []
    for frame, time_s in enumerate(shadow["window"]["expected_times_s"]):
        result["frame_observations"].append({
            "frame": frame, "time_s": float(time_s),
            "mass_weighted_com_m": [0.0, 0.0, 0.0],
            "mass_weighted_mean_velocity_m_s": [0.0, 0.0, 0.0],
            "mass_weighted_kinetic_energy_J": 0.0,
            "position_frame": "body", "velocity_frame": "world_inertial",
            "mass_quantile_front_m": front,
            "mass_distribution_kg": [profile["mass_denominator_kg"], 0.0, 0.0, 0.0],
            "initial_mass_denominator_kg": profile["mass_denominator_kg"],
            "initial_missing_mass_bucket_kg": 0.0,
            "denominator_unobserved_mass_kg": 0.0,
            "mass_accounting": {"initial_missing_mass_kg": 0.0},
        })
    return result, shadow, actual, historical


def test_v7_shadow_rebinds_profile_and_runs_real_operator() -> None:
    result, frozen, actual, historical = _shadow_and_result()
    score, reconciliation = E._dual_source_score(
        result, frozen,
        {"current_catalog_sha256": actual,
         "historical_result_current_catalog_sha256": historical},
    )
    assert score["cases"]["pass"]["status"] == "PASS"
    assert score["cases"]["wrong_velocity"]["status"] == "FAIL"
    assert reconciliation["shadow_current_binding_sha256"] == historical
    assert reconciliation["shadow_source_file_current_catalog_sha256"] == historical
    assert reconciliation["shadow_observer_profile_current_binding_sha256"] == historical
    assert reconciliation["shadow_observer_profile_source_file_current_catalog_sha256"] == historical
    assert reconciliation["shadow_observer_profile_sha256"] == frozen["observer_profile"]["sha256"]


def test_v7_shadow_rejects_unrelated_profile_catalog() -> None:
    result, frozen, actual, historical = _shadow_and_result()
    frozen["observer_profile"]["current_binding_sha256"] = "c" * 64
    with pytest.raises(E.TypedEvaluatorV4CurrentError, match="neither actual nor historical"):
        E._dual_source_score(
            result, frozen,
            {"current_catalog_sha256": actual,
             "historical_result_current_catalog_sha256": historical},
        )


def test_v7_parent_is_additive_and_uses_v4_child_source() -> None:
    assert P.V6_SCRIPT.name.endswith("parent_v6_current_bound.py")
    assert P.EVALUATOR_SCRIPT.name.endswith("evaluator_v4_current_bound.py")
    assert P.FORWARD_SCHEMA.endswith("v7-current-forward.v1")
