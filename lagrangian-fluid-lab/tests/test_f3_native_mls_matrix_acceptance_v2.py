from copy import deepcopy
import json

import pytest

from scripts import f3_native_mls_acceptance_adapter_v1 as v1
from scripts.f3_native_mls_matrix_acceptance_v2 import (
    MATRIX_EVIDENCE_SCHEMA,
    SCHEMA,
    main,
    build_matrix_receipt,
)


def _comparison():
    def cdf():
        return {"time_s": [0.0, 1.0, 8.35],
                "lower_mass_fraction": [0.0, 0.2, 0.6],
                "upper_mass_fraction": [0.0, 0.25, 0.7]}

    source = {
        "final_unknown_fraction": 0.005,
        "first_passage_cdf_bounds": cdf(),
        "return_cdf_bounds": cdf(),
        "residence_cdf_bounds": {**cdf(), "value_s": [0.0, 1.0, 2.0]},
    }
    return {
        "schema": v1.COMPARISON_SCHEMA,
        "status": "diagnostic_only",
        "qualification_claim": "none",
        "common_binding": {"source_definition": {"id": "halfspace"},
                           "event_definition": {"id": "x0"}},
        "source_comparison": {
            str(i): {"left": deepcopy(source), "right": deepcopy(source),
                     "difference": {
                         "first_passage_cdf_sup_abs_difference_bound": 0.01,
                         "return_cdf_sup_abs_difference_bound": 0.01,
                         "residence_cdf_sup_abs_difference_bound": 0.01,
                     }}
            for i in (0, 1)
        },
    }


def _row(index):
    stage = "resolution_substep" if index < 24 else "cadence" if index < 28 else "seed_density"
    checkpoint = {
        "schema": "core.material.f3.native_volume_mls.checkpoint.v1",
        "state_sha256": f"{index + 1:064x}",
        "file_sha256": f"{index + 100:064x}",
        "binding_sha256": f"{index + 200:064x}",
        "seed_hash": f"{index + 300:064x}",
        "committed_frame": 4176,
        "fields": ["position", "reliable", "permanent_unknown"],
        "checkpoint_npz": f"row-{index:02d}.checkpoint.npz",
    }
    return {
        "matrix_index": index,
        "matrix_stage": stage,
        "configuration_sha256": f"{index + 400:064x}",
        "physical_case_id": f"F3-physical-{index:02d}",
        "case_id": f"F3-material-{index:02d}",
        "trace_schema": "core.material.f3.native_volume_mls.trace.v2",
        "evidence": {
            "comparison": _comparison(),
            "source_window": {
                "schema": v1.SOURCE_WINDOW_SCHEMA,
                "start_s": 0.0, "end_s": 8.35,
                "observed_start_s": 0.0, "observed_end_s": 8.35,
                "native_interval_s": 0.002, "frame_count": 4176,
                "complete": True, "right_censored": False,
                "cadence_pass": True, "native_rows_exact": True,
                "no_stride_or_synthetic_cadence": True,
            },
            "checkpoint": checkpoint,
            "artifact_bindings": [
                {"artifact_id": f"rows/{index:02d}/comparison.json", "role": "comparison", "sha256": f"{index + 500:064x}"},
                {"artifact_id": f"rows/{index:02d}/source-window.json", "role": "source_window", "sha256": f"{index + 600:064x}"},
                {"artifact_id": f"rows/{index:02d}/checkpoint.json", "role": "checkpoint", "sha256": f"{index + 700:064x}"},
                {"artifact_id": f"rows/{index:02d}/trace.h5", "role": "trace", "sha256": f"{index + 800:064x}"},
            ],
        },
    }


def _evidence(rows=None):
    return {"schema": MATRIX_EVIDENCE_SCHEMA,
            "rows": list(rows if rows is not None else (_row(i) for i in range(33)))}


def test_matrix_receipt_evaluates_every_row_and_never_grants_t2():
    receipt = build_matrix_receipt(matrix_evidence=_evidence(), scope_id="f3-native-mls-v1")
    assert receipt["schema"] == SCHEMA
    assert receipt["status"] == "matrix_evidence_complete_but_non_qualifying"
    assert receipt["matrix"]["evaluated_row_count"] == 33
    assert receipt["matrix"]["passed_row_count"] == 33
    assert receipt["matrix"]["rows"][0]["matrix_stage"] == "resolution_substep"
    assert receipt["matrix"]["rows"][24]["matrix_stage"] == "cadence"
    assert receipt["matrix"]["rows"][28]["matrix_stage"] == "seed_density"
    assert receipt["T2_macro"] is False
    assert receipt["qualification_credit"] == 0
    assert receipt["execution_constraints"]["hdf5_opened"] is False
    assert receipt["execution_constraints"]["npz_opened"] is False


def test_failed_row_scientific_gate_fails_the_full_matrix():
    rows = _evidence()["rows"]
    rows[7]["evidence"]["comparison"]["source_comparison"]["1"]["right"]["final_unknown_fraction"] = 0.011
    receipt = build_matrix_receipt(matrix_evidence=_evidence(rows), scope_id="f3-native-mls-v1")
    assert receipt["status"] == "blocked_for_macro_t2"
    assert receipt["matrix"]["passed_row_count"] == 32
    assert receipt["matrix"]["rows"][7]["gates"]["per_source_unknown_mass"] is False
    assert receipt["T2_macro"] is False


def test_missing_duplicate_or_wrong_stage_row_fails_closed():
    with pytest.raises(ValueError, match="exactly 33"):
        build_matrix_receipt(matrix_evidence=_evidence(_evidence()["rows"][:-1]), scope_id="scope")
    rows = _evidence()["rows"]
    rows[32]["matrix_index"] = 31
    with pytest.raises(ValueError, match="duplicate matrix_index"):
        build_matrix_receipt(matrix_evidence=_evidence(rows), scope_id="scope")
    rows = _evidence()["rows"]
    rows[24]["matrix_stage"] = "resolution_substep"
    with pytest.raises(ValueError, match="must use stage cadence"):
        build_matrix_receipt(matrix_evidence=_evidence(rows), scope_id="scope")


def test_boolean_acceptance_claim_is_not_a_row_evidence_record():
    rows = _evidence()["rows"]
    rows[0] = {"matrix_index": 0, "matrix_stage": "resolution_substep",
               "acceptance_receipt": True, "qualification_claim": "none"}
    with pytest.raises(ValueError, match="configuration_sha256"):
        build_matrix_receipt(matrix_evidence=_evidence(rows), scope_id="scope")


def test_artifacts_must_bind_the_comparison_as_well_as_trace_window_and_checkpoint():
    rows = _evidence()["rows"]
    rows[0]["evidence"]["artifact_bindings"] = rows[0]["evidence"]["artifact_bindings"][1:]
    with pytest.raises(ValueError, match="include comparison"):
        build_matrix_receipt(matrix_evidence=_evidence(rows), scope_id="scope")


def test_case_and_output_artifact_identities_cannot_be_reused_between_rows():
    rows = _evidence()["rows"]
    rows[1]["case_id"] = rows[0]["case_id"]
    with pytest.raises(ValueError, match="duplicate case_id"):
        build_matrix_receipt(matrix_evidence=_evidence(rows), scope_id="scope")

    rows = _evidence()["rows"]
    rows[1]["evidence"]["artifact_bindings"][0]["artifact_id"] = rows[0]["evidence"]["artifact_bindings"][0]["artifact_id"]
    with pytest.raises(ValueError, match="reuses a comparison artifact"):
        build_matrix_receipt(matrix_evidence=_evidence(rows), scope_id="scope")


def test_cli_writes_an_immutable_json_receipt(tmp_path):
    source = tmp_path / "matrix.json"
    output = tmp_path / "receipt.json"
    source.write_text(json.dumps(_evidence()), encoding="utf-8")
    assert main(["--input", str(source), "--scope-id", "scope", "--output", str(output)]) == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["schema"] == SCHEMA
    assert receipt["execution_constraints"]["hdf5_opened"] is False
    with pytest.raises(FileExistsError):
        main(["--input", str(source), "--scope-id", "scope", "--output", str(output)])
