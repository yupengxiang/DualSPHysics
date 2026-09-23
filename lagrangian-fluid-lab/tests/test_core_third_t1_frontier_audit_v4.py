from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts import core_third_t1_frontier_audit_v4 as audit_module


ROOT = Path(__file__).resolve().parents[1]


def test_frontier_v4_records_completed_preflight_without_t1_or_solver_credit() -> None:
    value = audit_module.build_audit()
    assert value["schema"] == "core.third_t1.frontier_audit.v4"
    assert value["status"] == "user_selected_candidate_cpu_native_preflight_complete_t1_qualification_pending"
    assert value["current_t1_families"] == ["F3", "F4"]
    assert value["third_family_established"] is False
    assert value["qualification_credit"] == 0

    f8 = value["route_decisions"]["F8"]
    assert f8["cpu_native_preflight_completed"] is True
    assert f8["cpu_native_preflight_one_shot_consumed"] is True
    assert f8["cpu_native_preflight_invocations"] == 1
    assert f8["same_input_retry_forbidden"] is True
    assert f8["cpu_native_preflight_status"] == "cpu_native_preflight_verified_zero_credit_no_solver_authorized"
    assert f8["solver_t1_execution_authorized"] is False
    assert f8["t1_qualification"] is False
    assert f8["qualification_credit"] == 0

    controls = value["execution_controls"]
    assert controls["gencase_invoked"] is True
    assert controls["native_decode_invoked"] is True
    assert controls["preflight_one_shot_authorization_consumed"] is True
    assert controls["solver_invoked"] is False
    assert controls["gpu_started"] is False
    assert controls["worker_started"] is False
    assert controls["qualification_credit"] == 0
    assert controls["denominator_mutation"] == 0


def test_frontier_v4_binds_current_receipts_and_preserves_v3_as_history() -> None:
    value = audit_module.build_audit()
    roles = {item["role"] for item in value["evidence"]}
    assert "immutable v3 frontier snapshot from before the R008 CPU/native preflight" in roles
    assert "immutable R008 CPU/native preflight execution receipt; exactly one invocation per native stage" in roles
    assert "consumed R008 one-shot lock; same-input retry forbidden and solver budget zero" in roles
    assert "strict read-only postrun closure audit for the R008 CPU/native preflight" in roles
    assert any(role.startswith("historical Sep 23 status snapshot:") for role in roles)
    assert audit_module.OUTPUT.is_file()
    assert audit_module.verify_audit()["schema"] == audit_module.SCHEMA


def test_frontier_v4_builder_does_not_import_runtime_or_heavy_data_tools() -> None:
    source = (ROOT / "scripts/core_third_t1_frontier_audit_v4.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {"subprocess", "numpy", "h5py"} & imported


def test_frontier_v4_writer_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "audit" / "receipt.json"
    audit_module.write_audit(target)
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable F8 post-preflight frontier audit"):
        audit_module.write_audit(target)
