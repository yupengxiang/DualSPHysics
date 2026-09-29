from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from scripts import f1_formal_run_readiness_evidence_bridge_v1 as bridge


LAB_ROOT = Path(__file__).parents[1]


def _checked_in_report() -> dict:
    return json.loads(bridge.DEFAULT_REPORT.read_text(encoding="utf-8"))


def test_default_projection_is_bounded_and_fail_closed() -> None:
    report = bridge.build_report()

    assert report["schema"] == bridge.REPORT_SCHEMA
    assert report["status"] == "blocked_fail_closed"
    assert report["scope_id"] == bridge.SCOPE_ID
    assert report["readiness"]["preparation"] == {
        "required_cells": 15,
        "prepared_cells": 15,
        "pass": True,
    }
    assert report["readiness"]["future_formal_run"]["formal_run_ready"] is False
    assert report["authorization"] == bridge.AUTHORIZATION
    assert [item["code"] for item in report["blockers"]] == list(bridge.BLOCKER_CODES)


def test_preparation_does_not_fill_formal_runtime_denominator() -> None:
    report = bridge.build_report()
    preparation = report["evidence"]["preparation"]
    runtime = report["evidence"]["runtime"]

    assert preparation["prepared_cells"] == 15
    assert preparation["evidence_class"] == "preparation_only_not_formal_runtime_or_T1"
    assert runtime["registered_rows"] == 15
    assert runtime["prepared_rows"] == 15
    assert runtime["formal_runtime_rows"] == 0
    assert runtime["formal_failed_rows"] == 0
    assert runtime["missing_runtime_rows"] == 15
    assert runtime["fixed_failure_denominator"] is True
    assert len(runtime["rows"]) == 15
    assert all(row["runtime_status"] == "missing_runtime_product" for row in runtime["rows"])
    assert all(row["T1_numerical"] is False and row["T2"] is False for row in runtime["rows"])
    assert all(row["credit"] == 0 for row in runtime["rows"])


def test_source_identity_and_terminal_evidence_are_explicitly_open() -> None:
    report = bridge.build_report()
    source = report["evidence"]["source_identity"]
    terminal = report["evidence"]["terminal_evidence"]

    assert source["source_definition_declared"] is True
    assert source["design_sha256_bound"] is True
    assert source["matrix_sha256_bound"] is True
    assert source["formal_core_manifest_bound"] is False
    assert source["known_inputs_closure_bound"] is False
    assert source["per_cell_source_hash_closure"] is False
    assert source["solver_runtime_identity_bound"] is False
    assert source["closed"] is False
    assert terminal["formal_terminal_rows"] == 0
    assert terminal["formal_terminal_evidence_complete"] is False
    assert terminal["historical_fullwindow_canary"]["event_window_complete"] is True
    assert terminal["historical_fullwindow_canary"]["hard_integrity_pass"] is False
    assert terminal["historical_g1_anchor"]["event_window_complete"] is True
    assert terminal["historical_g1_anchor"]["hard_integrity_pass"] is False
    assert terminal["historical_fullwindow_canary"]["numerator_eligible"] is False
    assert terminal["historical_g1_anchor"]["numerator_eligible"] is False


def test_temporal_case_aliases_are_not_silently_promoted() -> None:
    report = bridge.build_report()
    rows = report["evidence"]["runtime"]["rows"]

    assert rows[13]["design_cell"] == "internal_time"
    assert rows[13]["case_id"].endswith("_internal_time")
    assert rows[14]["design_cell"] == "native_output"
    assert rows[14]["case_id"].endswith("_native_output")
    assert all(row["formal_run_readiness"] == "blocked_by_missing_runtime_evidence" for row in rows)


def test_historical_negative_evidence_is_not_denominator_credit() -> None:
    report = bridge.build_report()
    negative = report["evidence"]["historical_negative_evidence"]
    denominator = report["evidence"]["denominator"]

    assert negative["fullwindow_canary"]["hard_integrity_pass"] is False
    assert negative["h2_repair_stop"]["hard_integrity_pass"] is False
    assert negative["g1_negative_anchor"]["hard_integrity_pass"] is False
    assert negative["evidence_class"] == "historical_negative_only_not_formal_T1"
    assert denominator["historical_negative_anchors_excluded"] is True
    assert denominator["preparation_credit"] == 0
    assert denominator["qualification_credit"] == 0


def test_no_production_artifact_or_execution_surface() -> None:
    source = inspect.getsource(bridge)

    for forbidden in (
        "import h5py",
        "import numpy",
        "import subprocess",
        "import torch",
        "CUDA_VISIBLE_DEVICES",
        "nvidia-smi",
        "os.system",
    ):
        assert forbidden not in source
    assert "production_hdf5_bi4_trajectory_opened" in source
    assert bridge.READ_POLICY["production_hdf5_bi4_trajectory_opened"] is False
    assert bridge.READ_POLICY["nested_artifact_paths_followed"] is False
    assert bridge.SIDE_EFFECTS["production_trajectory_opened"] is False


def test_non_json_dependency_is_rejected_before_open(tmp_path: Path) -> None:
    forbidden = tmp_path / "trajectory.h5"
    forbidden.write_bytes(b"not an HDF5 product")

    with pytest.raises(bridge.ReadinessBridgeError, match="non-JSON input rejected"):
        bridge.build_report(dependency_paths={"candidate_card": forbidden})


def test_dependency_schema_drift_fails_closed(tmp_path: Path) -> None:
    source = LAB_ROOT / bridge.DEPENDENCY_SPECS["candidate_card"]["path"]
    tampered = json.loads(source.read_text(encoding="utf-8"))
    tampered["candidate_status"] = "qualified"
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(bridge.ReadinessBridgeError, match="candidate status drift"):
        bridge.build_report(dependency_paths={"candidate_card": path})


def test_promoting_formal_readiness_or_source_identity_is_rejected() -> None:
    promoted = copy.deepcopy(bridge.build_report())
    promoted["authorization"]["T1_numerical"] = True

    with pytest.raises(bridge.ReadinessBridgeError, match="authorization promotion"):
        bridge.validate_report(promoted)

    promoted = copy.deepcopy(bridge.build_report())
    promoted["readiness"]["future_formal_run"]["formal_run_ready"] = True
    with pytest.raises(bridge.ReadinessBridgeError, match="formal-run readiness promotion"):
        bridge.validate_report(promoted)

    promoted = copy.deepcopy(bridge.build_report())
    promoted["evidence"]["source_identity"]["closed"] = True
    with pytest.raises(bridge.ReadinessBridgeError, match="source identity promotion"):
        bridge.validate_report(promoted)


def test_checked_in_report_matches_current_projection() -> None:
    expected = bridge.build_report()
    checked_in = _checked_in_report()

    assert checked_in == expected
    assert bridge.verify_report() == expected
    assert bridge.validate_report(checked_in) == checked_in


def test_historical_report_is_retained_as_a_stale_snapshot() -> None:
    historical = json.loads(bridge.HISTORICAL_REPORT.read_text(encoding="utf-8"))

    assert bridge.HISTORICAL_REPORT.exists()
    assert bridge.HISTORICAL_ZH_REPORT.exists()
    assert historical["created_at"] != bridge.OBSERVED_AT_UTC
    assert historical != bridge.build_report()


def test_writer_is_immutable_and_chinese_report_is_bounded(tmp_path: Path) -> None:
    report = bridge.build_report()
    output = tmp_path / "bridge.json"
    zh_output = tmp_path / "bridge.zh-CN.md"

    bridge.write_outputs(report, output, zh_output)

    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert output.stat().st_size < 150_000
    assert zh_output.stat().st_size < 20_000
    zh = zh_output.read_text(encoding="utf-8")
    assert "formal_run_ready=false" in zh
    assert "source_identity_closure_missing" in zh
    with pytest.raises(FileExistsError):
        bridge.write_outputs(report, output, tmp_path / "second.zh-CN.md")
