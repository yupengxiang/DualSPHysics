from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from scripts import f2_fallback_fail_closed_boundary_contract_v1 as contract


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT = LAB_ROOT / "campaigns/core-v1/cfd/f2-fallback-fail-closed-boundary-contract-v1.json"
MARKDOWN = LAB_ROOT / "reports/F2-FALLBACK-FAIL-CLOSED-BOUNDARY-CONTRACT-V1-2026-09-29.zh-CN.md"


def test_bounded_contract_is_fail_closed_and_all_checks_pass() -> None:
    value = contract.build_contract()

    assert value["schema"] == contract.REPORT_SCHEMA
    assert value["contract_schema"] == contract.SCHEMA
    assert value["status"] == "blocked_fail_closed"
    assert value["authorization"] == contract.AUTHORIZATION
    assert value["mutations"] == contract.MUTATIONS
    assert value["read_policy"] == contract.READ_POLICY
    assert len(value["checks"]) == 13
    assert all(value["checks"].values())
    assert value["evidence"]["static_full_cup"]["missing_runtime_rows"] == 14
    assert value["evidence"]["dynamic_dbc"]["numerator"] == 0
    assert value["evidence"]["pour_catch"]["proposal_credit"] == 0


def test_cell_00_missing_runtime_and_dynamic_boundary_are_explicit() -> None:
    value = contract.build_contract()
    static = value["evidence"]["static_full_cup"]
    dynamic = value["evidence"]["dynamic_dbc"]

    assert static["cell_00"]["status"] == "failed_static_gate"
    assert "open_cup_escape" in static["cell_00"]["failure_categories"]
    assert static["missing_runtime_rows"] == 14
    assert dynamic["boundary_method"] == 1
    assert dynamic["open_mouth_geometry"] is True
    assert dynamic["moving_mdbc_contact_failure"]["hard_integrity_pass"] is False
    assert dynamic["open_tray_position_loss"]["hard_integrity_pass"] is False
    assert dynamic["open_tray_position_loss"]["native_missing_fluid_count"] > 0


def test_dynamic_and_catch_rows_remain_non_promotable() -> None:
    value = contract.build_contract()
    dynamic = value["evidence"]["dynamic_dbc"]
    catch = value["evidence"]["pour_catch"]

    assert dynamic["denominator"] == 15
    assert dynamic["numerator"] == 0
    assert catch["route_status"] == "root_review_only_conditional_route"
    assert catch["gap_status"] == "blocked_before_new_definition"
    assert catch["worth_preflight_now"] is False
    assert catch["event_contract_gap"] is True
    assert catch["proposal_rows"] == 15
    assert catch["proposal_credit"] == 0


def test_checked_in_contract_matches_current_projection() -> None:
    expected = contract.build_contract()
    checked_in = json.loads(REPORT.read_text(encoding="utf-8"))

    assert checked_in == expected
    assert contract.validate_report(checked_in) == checked_in
    assert MARKDOWN.is_file()
    assert "blocked_fail_closed" in MARKDOWN.read_text(encoding="utf-8")


def test_validator_rejects_formal_or_credit_promotion() -> None:
    promoted = copy.deepcopy(contract.build_contract())
    promoted["authorization"]["T1"] = True
    with pytest.raises(contract.ContractError, match="authorization"):
        contract.validate_report(promoted)

    promoted = copy.deepcopy(contract.build_contract())
    promoted["evidence"]["dynamic_dbc"]["numerator"] = 1
    with pytest.raises(contract.ContractError, match="dynamic numerator"):
        contract.validate_report(promoted)


def test_writer_is_non_overwriting_and_markdown_is_bounded(tmp_path: Path) -> None:
    value = contract.build_contract()
    output = tmp_path / "contract.json"
    markdown = tmp_path / "contract.zh-CN.md"

    contract.write_outputs(value, output, markdown)
    assert json.loads(output.read_text(encoding="utf-8")) == value
    assert output.stat().st_size < 50_000
    assert markdown.stat().st_size < 10_000
    with pytest.raises(FileExistsError):
        contract.write_outputs(value, output, tmp_path / "second.md")


def test_validator_has_no_execution_or_large_artifact_surface() -> None:
    source = inspect.getsource(contract)
    for forbidden in (
        "import h5py",
        "import numpy",
        "import subprocess",
        "import torch",
        "nvidia-smi",
        "Popen(",
        "trajectory.h5",
        "os.system",
    ):
        assert forbidden not in source
    assert contract.READ_POLICY["nested_artifact_paths_followed"] is False
    assert contract.READ_POLICY["production_hdf5_bi4_trajectory_opened"] is False


def test_report_dependency_paths_are_fixed_f2_json_only() -> None:
    value = contract.build_contract()
    assert set(value["dependencies"]) == set(contract.DEPENDENCY_PATHS)
    for key, dependency in value["dependencies"].items():
        assert dependency["path"] == contract.DEPENDENCY_PATHS[key].as_posix()
        assert dependency["path"].startswith(("reports/", "campaigns/core-v1/cfd/"))
        assert dependency["path"].endswith(".json")
        assert dependency["nested_artifact_paths_followed"] is False
