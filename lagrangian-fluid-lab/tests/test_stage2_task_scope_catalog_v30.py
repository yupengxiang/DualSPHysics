from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_task_scope_catalog_v30.py"
SPEC = importlib.util.spec_from_file_location("stage2_task_scope_catalog_v30", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _case(*, native: bool = True, quality: bool = False, lifecycle: bool = True) -> dict:
    native_data = None
    if native:
        native_data = {
            "native_motive": "position",
            "native_count": 3,
            "source_visible_mass": {
                "initial_fluid_mass_denominator_kg": 2.0,
                "missing_source_visible_mass_lower_bound_kg": 0.003,
                "missing_source_visible_fraction_lower_bound": 0.0015,
                "screen_gate_fraction": 0.003,
                "source_mk_partition": {"status": "UNKNOWN"},
            },
            "saved_censoring": {"particle_observation_count": 3, "saved_record_impact_count": 1},
        }
    ledger = {
        "active_nonfinite": 0 if lifecycle else 1,
        "active_nonpositive_mass": 0,
        "active_nonpositive_density": 0,
    }
    return {
        "case_key": "F2/CASE_00",
        "current": {"current_index": 78, "family_id": "F2", "physical_case_id": "CASE_00", "runtime_case_alias": "ALIAS", "frames": 10, "particles": 20, "actual_time_window_s": [0.0, 1.0], "source_role": "native_initial_mk"},
        "scientific_audit": {"field_failures": [], "fluid_ledger": ledger},
        "native_omission": native_data,
        "quality_scope": {"quality_checks_closed": True, "source_role": "native_initial_mk", "task_eligibility": {"QN": "UNKNOWN"}} if quality else {"status": "NOT_EVALUATED_NON_ANCHOR"},
        "qualification_dimensions": {
            "finite_fields": {"field_failures": []},
            "mass": native_data["source_visible_mass"] if native else {"initial_fluid_mass_kg": 2.0},
            "identity": {"native_identity": "NATIVE_ID_MOTIVE_SOURCE_CLOSED", "current_identity": "EXACT_CURRENT336_CASE", "identity_key": "(Zone,Idp)", "native_count": 3},
            "time": {"current_saved_window_s": [0.0, 1.0], "frames": 10, "first_missing_window_s": [0.1, 0.2]},
            "censoring": {"status": "SOURCE_BOUND_NATIVE_SAVED_RECORD_CENSORING" if native else "NO_NATIVE_118_CENSOR_RECORD_FOR_THIS_CASE"},
            "failed_scope": {"producer_parent_failure_or_recovery": "UNKNOWN_FOR_NON_ANCHOR"},
        },
    }


def test_task_case_keeps_native_mass_and_censor_as_limited_scope():
    result = MODULE._task_case(_case())
    assert result["native_mk_scope"]["status"] == "ELIGIBLE_NATIVE_MOTIVE_ID_AND_COUNT"
    assert result["mass_scope"]["missing_fraction_lower_bound"] == 0.0015
    assert result["mass_scope"]["error_bound"] == "UNKNOWN"
    assert result["time_scope"]["status"] == "ELIGIBLE_SAVED_RECORD_BRACKET_DIAGNOSTIC"
    assert result["error_qualification"]["QN"] == "UNKNOWN"


def test_task_case_non_native_does_not_inherit_native_credit():
    result = MODULE._task_case(_case(native=False, quality=False))
    assert result["native_mk_scope"]["status"] == "NOT_IN_118_NATIVE_LEDGER"
    assert result["censor_scope"]["status"] == "NO_NATIVE_118_CENSOR_RECORD_FOR_THIS_CASE"
    assert result["quality_scope"]["status"] == "NOT_EVALUATED_NON_ANCHOR"


def test_finite_scope_distinguishes_exposed_zero_metrics_from_unexposed_rows():
    closed = MODULE._finite_scope(_case(native=False, lifecycle=True))
    open_scope = MODULE._finite_scope(_case(native=False, lifecycle=False))
    assert closed["lifecycle"] == "CLOSED_ZERO_NONFINITE_AND_NONPOSITIVE_MASS_DENSITY"
    assert open_scope["lifecycle"] == "LIFECYCLE_FAILURE_OR_NONZERO_REPORTED"
    assert closed["field_audit"] == "ELIGIBLE_FIELD_FAILURE_LIST_EMPTY"


def test_v28_request_rejects_scientific_payload_read(tmp_path: Path):
    source = tmp_path / "worker.py"
    source.write_text("# worker\n", encoding="utf-8")
    request = {
        "schema": "ds02.runner-request.v1", "request_schema": MODULE.V28_REQUEST_SCHEMA,
        "status": "prepared_guard_pending_actual_CPU", "launch_allowed": True,
        "cpu_threads": 1, "max_wall_seconds": 900,
        "source_cost": {"original_trajectory_h5_bytes_read": 1, "materialized_label_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "raw_solver_output_bytes_read": 0},
        "read_policy": {"trajectory_h5_opened": False, "materialized_label_h5_opened": False, "part_bi4_opened": False, "solver_started": False, "model_invoked": False},
        "input_files": [str(source)], "input_sha256": {str(source): MODULE.sha256_file(source)},
    }
    with pytest.raises(MODULE.ScopeError, match="scientific payload reads"):
        MODULE._validate_v28_request(tmp_path / "request.json", request)


def test_committed_v28_handoff_binds_the_real_request():
    handoff_path = Path(__file__).parents[1] / "campaigns/ds-data-02/stage2/requests/product-delivery-metadata-v28-forward-001/v28-handoff.json"
    root_copy_path = handoff_path.parent / "product-delivery-metadata-v28-request.json"
    if not handoff_path.is_file() or not root_copy_path.is_file():
        pytest.skip("v28 handoff is not present in this checkout")
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    request_ref = handoff["request"]
    producer_path = Path(request_ref["path"])
    if not producer_path.is_file():
        pytest.skip("immutable v28 producer request is not mounted in this checkout")
    producer_request = json.loads(producer_path.read_text(encoding="utf-8"))
    producer_sha = MODULE.sha256_file(producer_path)
    assert request_ref["sha256"] == producer_sha
    # The checked-out/root copy is allowed to have a different absolute path,
    # but it must be the exact immutable producer bytes.
    assert MODULE.sha256_file(root_copy_path) == producer_sha
    summary = MODULE._validate_v28_handoff(handoff_path, handoff, producer_path, producer_request)
    assert summary["request"]["path"] == str(producer_path)
    assert summary["request"]["sha256"] == producer_sha
    assert [item["commit"] for item in summary["dependencies"]] == ["e30fea6ee", "87741b84c", "455d6b730", "86db22652"]
