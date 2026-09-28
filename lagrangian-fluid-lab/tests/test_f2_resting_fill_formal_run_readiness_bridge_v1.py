from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from scripts import f2_resting_fill_formal_run_readiness_bridge_v1 as bridge


LAB_ROOT = Path(__file__).parents[1]


def _checked_in_report() -> dict:
    return json.loads(
        (LAB_ROOT / "reports/F2-RESTING-FILL-FORMAL-RUN-READINESS-BRIDGE-V1-2026-09-28.json").read_text(
            encoding="utf-8"
        )
    )


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


def test_fixed_denominator_preserves_preparation_failure_and_missing_rows() -> None:
    report = bridge.build_report()
    runtime = report["evidence"]["runtime"]
    rows = runtime["rows"]

    assert runtime["registered_rows"] == 15
    assert runtime["historical_runtime_pass_rows"] == 0
    assert runtime["historical_failed_rows"] == 1
    assert runtime["missing_runtime_rows"] == 14
    assert rows[0]["historical_runtime_status"] == "failed_static_gate"
    assert rows[0]["formal_run_readiness"] == "blocked_by_historical_failure"
    assert all(row["preparation_evidence"] == "prepared_input_only_not_T1" for row in rows)
    assert all(row["T1_numerical"] is False and row["T2"] is False for row in rows)
    assert all(row["credit"] == 0 for row in rows)


def test_checked_in_report_matches_current_projection() -> None:
    expected = bridge.build_report()
    checked_in = _checked_in_report()

    assert checked_in == expected
    assert bridge.verify_report() == expected
    assert bridge.validate_report(checked_in) == checked_in


def test_static_anchor_is_explicitly_excluded_from_numerator() -> None:
    report = bridge.build_report()
    anchor = report["evidence"]["static_anchor"]

    assert anchor["hard_integrity_pass"] is True
    assert anchor["event_window_complete"] is True
    assert anchor["static_settled"] is True
    assert anchor["numerator_eligible"] is False
    assert anchor["qualification_credit"] == 0


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


def test_non_json_dependency_is_rejected_before_open(tmp_path: Path) -> None:
    forbidden = tmp_path / "candidate.h5"
    forbidden.write_bytes(b"not an HDF5 product")

    with pytest.raises(bridge.ReadinessBridgeError, match="non-JSON input rejected"):
        bridge.build_report(dependency_paths={"candidate_card": forbidden})


def test_dependency_schema_drift_fails_closed(tmp_path: Path) -> None:
    source = LAB_ROOT / bridge.DEPENDENCY_SPECS["candidate_card"]["path"]
    tampered = json.loads(source.read_text(encoding="utf-8"))
    tampered["qualified"] = True
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(bridge.ReadinessBridgeError, match="candidate qualified marker drift"):
        bridge.build_report(dependency_paths={"candidate_card": path})


def test_promoting_t1_or_runtime_ready_is_rejected() -> None:
    promoted = copy.deepcopy(bridge.build_report())
    promoted["authorization"]["T1"] = True

    with pytest.raises(bridge.ReadinessBridgeError, match="authorization promotion"):
        bridge.validate_report(promoted)

    promoted = copy.deepcopy(bridge.build_report())
    promoted["readiness"]["future_formal_run"]["formal_run_ready"] = True
    with pytest.raises(bridge.ReadinessBridgeError, match="formal-run readiness promotion"):
        bridge.validate_report(promoted)


def test_writer_is_immutable_and_chinese_report_is_bounded(tmp_path: Path) -> None:
    report = bridge.build_report()
    output = tmp_path / "bridge.json"
    zh_output = tmp_path / "bridge.zh-CN.md"

    bridge.write_outputs(report, output, zh_output)

    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert output.stat().st_size < 100_000
    assert zh_output.stat().st_size < 20_000
    assert "T1=false" in zh_output.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        bridge.write_outputs(report, output, tmp_path / "second.zh-CN.md")

