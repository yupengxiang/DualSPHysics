from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import pytest

from scripts.core_material_output_contract_v1 import (
    ADMISSION_SCHEMA,
    PATH_COVERAGE_POLICY,
    ROOT_ADMISSION_SCHEMA,
    ROOT_PHYSICAL_CASE_ID,
    SCHEMA,
    UNKNOWN_FRACTION_LIMIT,
    audit_material_output_admission,
    audit_material_output_contract,
    evaluate_material_output,
    validate_material_output,
)


def _event(name: str) -> dict:
    return {
        "definition": f"synthetic {name} event",
        "denominator_policy": "all_initial_mass",
        "cdf": {
            "time_s": [0.0, 1.0, 2.0],
            "lower": [0.0, 0.20, 0.50],
            "upper": [0.0, 0.25, 0.60],
            "denominator_policy": "all_initial_mass",
        },
        "censor": {
            "type": "right",
            "fraction": 0.10,
            "policy": "right_censored_mass_remains_in_denominator",
            "counts_as_acceptance": False,
        },
    }


def _f3_output() -> dict:
    return {
        "schema": SCHEMA,
        "family": "F3",
        "case_id": "synthetic-f3-case",
        "diagnostic_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "mass": {
            "initial_mass_kg": 100.0,
            "closure_tolerance_kg": 1.0e-9,
            "denominator_policy": "all_initial_mass",
            "source": {"mass_kg": 40.0, "fraction": 0.40},
            "destination": {"mass_kg": 59.5, "fraction": 0.595},
            "unknown": {"mass_kg": 0.5, "fraction": 0.005},
        },
        "transfer_matrix": {
            "row_labels": ["source", "destination", "unknown"],
            "column_labels": ["source", "destination", "unknown"],
            "mass_kg": [
                [35.0, 4.5, 0.5],
                [5.0, 54.5, 0.0],
                [0.0, 0.5, 0.0],
            ],
        },
        "events": {
            "first_passage": _event("first-passage"),
            "return": _event("return"),
            "residence": _event("residence"),
        },
        "unknown_bound": {
            "denominator_policy": "all_initial_mass",
            "observed_fraction": 0.005,
            "worst_case_fraction": UNKNOWN_FRACTION_LIMIT,
            "limit": UNKNOWN_FRACTION_LIMIT,
            "includes_right_censored_mass": True,
        },
        "path_error": {
            "denominator_policy": "all_initial_mass",
            "coverage_policy": PATH_COVERAGE_POLICY,
            "maximum_abs_error_m": 0.004,
            "tolerance_m": 0.01,
            "common_reliable_mass_coverage": 0.98,
            "minimum_common_reliable_mass_coverage": 0.95,
        },
        "family_specific": {
            "source_definition": {"axis": 0, "boundary": 0.0},
            "trace_schema": "core.material.f3.synthetic.trace.v1",
            "native_interval_s": 0.01,
            "full_window_s": 2.0,
        },
    }


def _f4_output() -> dict:
    value = _f3_output()
    value["family"] = "F4"
    value["case_id"] = "synthetic-f4-case"
    value["family_specific"] = {
        "scope_id": "F4_synthetic_scope",
        "revision_id": "F4_synthetic_revision",
        "recipe_id": "F4_synthetic_recipe",
        "event_window_s": 2.0,
        "maximum_extension_s": 4.0,
        "residence_definition": {
            "definition": "time inside the destination region after contact",
            "right_censored": True,
        },
    }
    return value


def test_pass_receipt_is_json_only_and_never_qualification() -> None:
    result = validate_material_output(_f3_output())

    assert result["schema"] == SCHEMA
    assert result["status"] == "diagnostic_only"
    assert result["diagnostic_only"] is True
    assert result["passed"] is True
    assert result["qualification_claim"] == "none"
    assert result["qualification_credit"] == 0
    assert isinstance(result["qualification_credit"], int)
    assert result["T2_macro"] is False and result["T2_path"] is False
    assert result["execution_constraints"]["hdf5_opened"] is False
    assert result["execution_constraints"]["solver_started"] is False
    assert result["execution_constraints"]["registry_mutation"] == 0
    assert result["execution_constraints"]["ledger_mutation"] == 0
    assert result["mass"]["closure_pass"] is True
    assert result["transfer_matrix"]["closure_pass"] is True
    assert result["gates"]["event_cdf_and_censor_contract"] is True


def test_mass_closure_failure_is_negative_evidence_and_strict_validation_rejects() -> None:
    value = _f3_output()
    value["mass"]["destination"]["mass_kg"] = 59.0
    value["mass"]["destination"]["fraction"] = 0.59

    diagnostic = evaluate_material_output(value)
    assert diagnostic["passed"] is False
    assert diagnostic["gates"]["mass_closure"] is False
    assert diagnostic["gates"]["transfer_matrix_closure"] is False
    with pytest.raises(ValueError, match="mass_closure"):
        validate_material_output(value)


def test_transfer_matrix_requires_unknown_bucket_and_closes_terminal_mass() -> None:
    value = _f3_output()
    value["transfer_matrix"]["column_labels"] = ["source", "destination", "other"]
    with pytest.raises(ValueError, match="unknown"):
        evaluate_material_output(value)

    value = _f3_output()
    value["transfer_matrix"]["mass_kg"][0][2] = 0.0
    diagnostic = evaluate_material_output(value)
    assert diagnostic["passed"] is False
    assert diagnostic["transfer_matrix"]["column_closure_pass"]["unknown"] is False


def test_unknown_worst_case_is_checked_against_fixed_one_percent_limit() -> None:
    value = _f3_output()
    value["unknown_bound"]["worst_case_fraction"] = 0.011

    diagnostic = evaluate_material_output(value)
    assert diagnostic["passed"] is False
    assert diagnostic["gates"]["unknown_worst_case_bound"] is False
    with pytest.raises(ValueError, match="unknown_worst_case_bound"):
        validate_material_output(value)

    value = _f3_output()
    value["unknown_bound"]["limit"] = 0.02
    with pytest.raises(ValueError, match="fixed 1%"):
        evaluate_material_output(value)


def test_all_three_events_require_cdf_bounds_and_explicit_censor_semantics() -> None:
    value = _f3_output()
    del value["events"]["return"]["cdf"]["upper"]
    with pytest.raises(ValueError, match="upper"):
        evaluate_material_output(value)

    value = _f3_output()
    value["events"]["residence"]["censor"]["counts_as_acceptance"] = True
    with pytest.raises(ValueError, match="counts_as_acceptance"):
        evaluate_material_output(value)

    value = _f3_output()
    value["events"]["first_passage"]["cdf"]["lower"] = [0.0, 0.2, 0.2]
    value["events"]["first_passage"]["cdf"]["upper"] = [0.0, 0.25, 0.2]
    with pytest.raises(ValueError, match="upper.*non-decreasing"):
        evaluate_material_output(value)


def test_path_error_and_common_reliable_mass_coverage_are_separate_gates() -> None:
    value = _f3_output()
    value["path_error"]["common_reliable_mass_coverage"] = 0.90
    diagnostic = evaluate_material_output(value)
    assert diagnostic["passed"] is False
    assert diagnostic["gates"]["path_error"] is True
    assert diagnostic["gates"]["common_reliable_mass_coverage"] is False

    value = _f3_output()
    value["path_error"]["maximum_abs_error_m"] = 0.02
    diagnostic = evaluate_material_output(value)
    assert diagnostic["gates"]["path_error"] is False
    assert diagnostic["gates"]["common_reliable_mass_coverage"] is True


def test_f3_and_f4_family_specific_contracts_are_supported_without_credit() -> None:
    f3 = validate_material_output(_f3_output())
    f4 = validate_material_output(_f4_output())
    assert f3["family"] == "F3"
    assert f4["family"] == "F4"
    assert f3["qualification_credit"] == 0
    assert f4["qualification_credit"] == 0

    missing = _f4_output()
    del missing["family_specific"]["residence_definition"]
    with pytest.raises(ValueError, match="residence_definition"):
        evaluate_material_output(missing)


@pytest.mark.parametrize(
    ("location", "bad_value"),
    [
        (("mass", "source", "mass_kg"), math.nan),
        (("mass", "destination", "fraction"), math.inf),
        (("transfer_matrix", "mass_kg", 0, 0), True),
        (("events", "first_passage", "cdf", "lower", 1), math.nan),
        (("unknown_bound", "worst_case_fraction"), math.inf),
        (("path_error", "common_reliable_mass_coverage"), math.nan),
    ],
)
def test_non_finite_or_boolean_numeric_values_are_rejected(location, bad_value) -> None:
    value = _f3_output()
    target = value
    for part in location[:-1]:
        target = target[part]
    target[location[-1]] = bad_value
    with pytest.raises(ValueError):
        evaluate_material_output(value)


def test_qualification_fields_are_fail_closed_and_numeric_zero_is_required() -> None:
    value = _f3_output()
    value["qualification_credit"] = "none"
    with pytest.raises(ValueError, match="numeric zero"):
        evaluate_material_output(value)

    value = _f3_output()
    value["T2_path"] = True
    with pytest.raises(ValueError, match="T2_path"):
        evaluate_material_output(value)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_binding(path: Path, artifact_id: str, role: str, physical_case_id: str) -> dict:
    raw = path.read_bytes()
    return {
        "artifact_id": artifact_id,
        "role": role,
        "physical_case_id": physical_case_id,
        "path": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _complete_collection(tmp_path: Path, physical_case_ids: tuple[str, ...] = ("physical-a",)) -> tuple[list[dict], dict]:
    outputs: list[dict] = []
    for index, physical_case_id in enumerate(physical_case_ids):
        value = _f3_output()
        value["case_id"] = f"material-case-{index}"
        value["physical_case_id"] = physical_case_id
        for event in value["events"].values():
            event["censor"] = {
                "type": "none",
                "fraction": 0.0,
                "policy": "no_censoring",
                "counts_as_acceptance": False,
            }
        value["source_coverage"] = {
            "schema": "core.material.source_summary.v1",
            "family": value["family"],
            "case_id": value["case_id"],
            "denominator_policy": "all_initial_mass",
            "required_source_ids": ["source-a", "source-b"],
            "source_count": 2,
            "initial_mass_kg": 100.0,
            "source_mass_sum_kg": 100.0,
            "rows": [
                {
                    "source_id": "source-a",
                    "initial_mass_kg": 50.0,
                    "unknown_fraction_max": 0.005,
                    "denominator_policy": "all_initial_mass",
                },
                {
                    "source_id": "source-b",
                    "initial_mass_kg": 50.0,
                    "unknown_fraction_max": 0.005,
                    "denominator_policy": "all_initial_mass",
                },
            ],
        }
        source_path = tmp_path / f"{physical_case_id}-source.bin"
        material_path = tmp_path / f"{physical_case_id}-material.json"
        source_path.write_bytes(f"source-{physical_case_id}".encode("utf-8"))
        material_path.write_text(
            json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8"
        )
        source = _file_binding(source_path, f"{physical_case_id}-source", "source_window", physical_case_id)
        material = _file_binding(material_path, f"{physical_case_id}-material", "material_output", physical_case_id)
        value["artifact_bindings"] = [source, material]
        value["full_window"] = {
            "required": True,
            "complete": True,
            "start_s": 0.0,
            "end_s": 2.0,
            "observed_start_s": 0.0,
            "observed_end_s": 2.0,
            "frame_start": 0,
            "frame_end": 2,
            "frame_count": 3,
            "native_rows_exact": True,
            "no_stride_or_synthetic_cadence": True,
            "source_artifact_id": source["artifact_id"],
            "source_artifact_sha256": source["sha256"],
            "material_artifact_id": material["artifact_id"],
            "material_artifact_sha256": material["sha256"],
        }
        outputs.append(value)

    bindings = []
    for value in outputs:
        source = next(item for item in value["artifact_bindings"] if item["role"] == "source_window")
        material = next(item for item in value["artifact_bindings"] if item["role"] == "material_output")
        bindings.append(
            {
                "physical_case_id": value["physical_case_id"],
                "case_id": value["case_id"],
                "family": value["family"],
                "source_artifact_sha256": source["sha256"],
                "material_artifact_sha256": material["sha256"],
                "full_window": {
                    "required": value["full_window"]["required"],
                    "complete": value["full_window"]["complete"],
                    "start_s": value["full_window"]["start_s"],
                    "end_s": value["full_window"]["end_s"],
                    "observed_start_s": value["full_window"]["observed_start_s"],
                    "observed_end_s": value["full_window"]["observed_end_s"],
                    "frame_start": value["full_window"]["frame_start"],
                    "frame_end": value["full_window"]["frame_end"],
                    "frame_count": value["full_window"]["frame_count"],
                    "source_artifact_id": value["full_window"]["source_artifact_id"],
                    "material_artifact_id": value["full_window"]["material_artifact_id"],
                    "native_rows_exact": value["full_window"]["native_rows_exact"],
                    "no_stride_or_synthetic_cadence": value["full_window"]["no_stride_or_synthetic_cadence"],
                },
            }
        )
    root_path = tmp_path / "root-admission.json"
    root_path.write_text("root admission", encoding="utf-8")
    root_artifact = _file_binding(root_path, "root-admission", "root_admission", ROOT_PHYSICAL_CASE_ID)
    root_admission = {
        "schema": ROOT_ADMISSION_SCHEMA,
        "granted": True,
        "status": "approved",
        "physical_case_ids": sorted(physical_case_ids),
        "required_source_ids": ["source-a", "source-b"],
        "full_window_s": 2.0,
        "output_binding_sha256": _canonical_digest(sorted(bindings, key=lambda item: item["physical_case_id"])),
        "artifact": root_artifact,
    }
    return outputs, root_admission


def _audit(outputs: list[dict], root_admission: dict, tmp_path: Path) -> dict:
    return audit_material_output_contract(
        outputs,
        registered_physical_case_ids=sorted(item["physical_case_id"] for item in outputs),
        required_source_ids=["source-a", "source-b"],
        artifact_root=tmp_path,
        expected_full_window_s=2.0,
        root_admission=root_admission,
    )


def test_complete_external_collection_is_admission_ready_but_t2_stays_false(tmp_path: Path) -> None:
    outputs, root_admission = _complete_collection(tmp_path)
    result = _audit(outputs, root_admission, tmp_path)

    assert result["schema"] == ADMISSION_SCHEMA
    assert result["admission_pass"] is True
    assert result["status"] == "admission_ready_but_non_qualifying"
    assert result["T2_macro"] is False
    assert result["T2_path"] is False
    assert result["qualification_credit"] == 0
    assert result["macro_t2_upgrade_blocked"] is True
    assert all(result["gates"].values())
    assert result["execution_constraints"]["registry_mutation"] == 0


def test_missing_source_denominator_and_single_sidecar_fail_closed(tmp_path: Path) -> None:
    outputs, root_admission = _complete_collection(tmp_path)
    del outputs[0]["source_coverage"]
    result = _audit(outputs, root_admission, tmp_path)

    assert result["admission_pass"] is False
    assert result["gates"]["source_coverage"] is False
    assert result["gates"]["root_admission"] is False
    assert result["T2_macro"] is False
    with pytest.raises(ValueError, match="outputs must be a list"):
        audit_material_output_admission(
            outputs[0],
            registered_physical_case_ids=["physical-a"],
            required_source_ids=["source-a", "source-b"],
            artifact_root=tmp_path,
            expected_full_window_s=2.0,
            root_admission=root_admission,
        )


def test_duplicate_physical_case_and_incomplete_registered_denominator_are_blocked(tmp_path: Path) -> None:
    outputs, root_admission = _complete_collection(tmp_path, ("physical-a", "physical-b"))
    outputs[1]["physical_case_id"] = outputs[0]["physical_case_id"]
    result = audit_material_output_contract(
        outputs,
        registered_physical_case_ids=["physical-a", "physical-b"],
        required_source_ids=["source-a", "source-b"],
        artifact_root=tmp_path,
        expected_full_window_s=2.0,
        root_admission=root_admission,
    )

    assert result["admission_pass"] is False
    assert result["gates"]["physical_case_uniqueness"] is False
    assert result["gates"]["registered_physical_case_coverage"] is False
    assert result["T2_macro"] is False


def test_artifact_hash_bytes_root_and_full_window_bindings_fail_closed(tmp_path: Path) -> None:
    outputs, root_admission = _complete_collection(tmp_path)
    source = tmp_path / "physical-a-source.bin"
    source.write_bytes(b"tampered!")
    result = _audit(outputs, root_admission, tmp_path)
    assert result["admission_pass"] is False
    assert result["gates"]["artifact_hash_bytes"] is False
    assert result["gates"]["root_admission"] is False

    window_root = tmp_path / "window"
    window_root.mkdir()
    outputs, root_admission = _complete_collection(window_root)
    outputs[0]["full_window"]["material_artifact_sha256"] = "0" * 64
    result = _audit(outputs, root_admission, window_root)
    assert result["admission_pass"] is False
    assert result["gates"]["full_window_binding"] is False
    assert result["gates"]["root_admission"] is False


def test_root_denial_and_short_window_cannot_be_relabelled(tmp_path: Path) -> None:
    outputs, root_admission = _complete_collection(tmp_path)
    root_admission["granted"] = False
    result = _audit(outputs, root_admission, tmp_path)
    assert result["gates"]["root_admission"] is False
    assert result["T2_macro"] is False

    outputs, root_admission = _complete_collection(tmp_path)
    outputs[0]["full_window"]["complete"] = False
    result = _audit(outputs, root_admission, tmp_path)
    assert result["gates"]["full_window_binding"] is False
    assert result["gates"]["root_admission"] is False
    assert result["T2_macro"] is False
