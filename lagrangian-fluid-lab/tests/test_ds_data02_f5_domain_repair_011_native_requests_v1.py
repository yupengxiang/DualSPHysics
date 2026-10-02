from __future__ import annotations

import json
from pathlib import Path


FAMILY = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F5"
ROOT = FAMILY / "native_conversion/domain_repair_011"
INDEX = ROOT / "registration-index-011.json"


def _rows() -> list[dict]:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert index["schema"] == "ds-data-02.f5.native-conversion-registration.reference-009.v1"
    assert index["qualification_claim"] == "none"
    assert index["q_n_status"] == "not_assessed"
    assert index["concurrency"]["runner_required"] is True
    return index["requests"]


def test_domain_repair_011_registers_two_complete_native_macro_references() -> None:
    rows = _rows()
    assert {row["mechanism_id"] for row in rows} == {"runup_return", "weir_pair"}
    for row in rows:
        assert row["raw_frame_count"] == 801
        assert row["runparts_rows"] == 801
        assert row["run_csv_part_files"] == 801
        assert row["run_csv_parts_out"] == 0
        assert row["all_solver_exclusion_counters_zero"] is True
        assert row["native_partout_artifact_count"] == 1
        assert row["q_i_status"] == "pending_conversion"
        assert row["q_n_status"] == "not_assessed"


def test_conversion_requests_bind_partout_and_full_typed_audit_prerequisites() -> None:
    for row in _rows():
        request = json.loads(Path(row["conversion_request"]).read_text(encoding="utf-8"))
        account = json.loads(Path(row["conversion_request"].replace(".conversion-request.json", ".native-exclusion-accounting.json")).read_text(encoding="utf-8"))
        assert request["kind"] == "cpu"
        assert request["cpu_task_kind"] == "conversion"
        assert request["command"][0].endswith("/.venv/bin/python")
        assert request["partvtkout_motive_prerequisites"]["partvtkout_required"] is True
        assert request["partvtkout_motive_prerequisites"]["motive_required"] is True
        assert request["partvtkout_motive_prerequisites"]["status"] == "pending_conversion_partvtkout_and_motive_audit"
        assert request["input_binding"]["raw_frame_count"] == 801
        assert request["input_binding"]["native_exclusion_accounting"]["solver_counters"]["row_count"] == 801
        assert account["solver_counters"]["all_exclusion_counters_zero"] is True
        assert account["unknown_exclusion_policy"].startswith("RunPARTs counters")
        partout = account["native_partout_artifacts"][0]
        assert partout["bytes"] == 584
        assert partout["path"] in request["input_files"]
        assert request["input_sha256"][partout["path"]] == partout["sha256"]
        assert request["actual_source"]["native_fluid_mass_kg"] == 2352.0
        assert request["actual_source"]["expected_frames"] == 801
        assert request["qualification_claim"] == "none"
        assert request["q_n_status"] == "not_assessed"


def test_label_requests_are_deferred_and_preserve_raw_exclusion_accounting() -> None:
    for row in _rows():
        request = json.loads(Path(row["label_request"]).read_text(encoding="utf-8"))
        assert request["kind"] == "cpu"
        assert request["cpu_task_kind"] == "labels"
        assert request["command"][0].endswith("/.venv/bin/python")
        assert request["status"].startswith("deferred_until_conversion_terminal")
        assert request["deferred_inputs"]["partvtkout_motive_audit_required"] is True
        assert request["deferred_inputs"]["native_exclusion_accounting"].endswith(".native-exclusion-accounting.json")
        assert request["qualification_claim"] == "none"
        assert request["q_n_status"] == "not_assessed"
