from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f7_pump_runtime_canary_v1 import (
    DECODER,
    GENCASE,
    SCHEMA,
    SOLVER_CPU,
    prepare_plan,
    write_plan,
)


def test_prepare_plan_is_hash_bound_and_execution_closed(tmp_path):
    payload = prepare_plan(tmp_path / "outside-lab", time_max_s=0.6, time_out_s=0.02)
    assert payload["schema"] == SCHEMA
    assert payload["status"] == "prepared_only_not_executed"
    assert payload["source_contract"]["official_source_hashes_verified"] is True
    assert payload["source_contract"]["fluid_mk"] == 1
    assert payload["source_contract"]["moving_boundary_mk"] == 2
    assert payload["execution_boundary"] == {
        "prepare_invoked": True,
        "gencase_invoked": False,
        "solver_invoked": False,
        "native_decoder_invoked": False,
        "gpu_started": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "qualification_credit": 0,
        "runtime_evidence": False,
    }
    assert payload["execution_plan"]["destructive_wrapper_used"] is False
    assert payload["execution_plan"]["recursive_cleanup_requested"] is False
    assert payload["execution_plan"]["gencase_argv"][0] == str(GENCASE)
    assert payload["execution_plan"]["solver_cpu_argv"][0] == str(SOLVER_CPU)
    assert payload["execution_plan"]["native_decode_executable"] == str(DECODER)


def test_prepare_plan_rejects_source_lab_and_unsafe_windows(tmp_path):
    with pytest.raises(ValueError, match="inside the source lab"):
        prepare_plan(Path(__file__).resolve().parents[1] / "f7-runtime-output")
    with pytest.raises(ValueError, match="no greater than the official"):
        prepare_plan(tmp_path / "out", time_max_s=6.1)
    with pytest.raises(ValueError, match="no greater than time_max_s"):
        prepare_plan(tmp_path / "out2", time_max_s=0.5, time_out_s=0.6)


def test_write_plan_is_create_once_and_does_not_execute(tmp_path):
    plan_path = tmp_path / "plan.json"
    output_root = tmp_path / "runtime"
    payload = write_plan(plan_path, output_root=output_root, time_max_s=0.5, time_out_s=0.01)
    assert json.loads(plan_path.read_text()) == payload
    assert plan_path.is_file()
    assert not output_root.exists()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_plan(plan_path, output_root=tmp_path / "runtime2")
