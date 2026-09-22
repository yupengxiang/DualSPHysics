from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import f8_cpu_native_preflight_authorization_v1 as authorization_module
from scripts import f8_cpu_native_preflight_runner_v1 as runner


ROOT = Path(__file__).resolve().parents[1]


def load_authorization() -> dict:
    return json.loads(authorization_module.OUTPUT.read_text(encoding="utf-8"))


def test_authorization_is_hash_closed_one_shot_and_zero_credit() -> None:
    authorization = load_authorization()
    assert authorization["status"] == "authorized_for_exactly_one_cpu_native_preflight"
    assert authorization["qualification_claim"] == "none"
    assert authorization["qualification_credit"] == 0
    assert authorization["single_input"]["old_xml_bi4_hdf5_reused_as_input"] is False
    assert authorization["output_namespace"]["reuse_or_retry_allowed"] is False
    assert authorization["hard_gates"]["one_fluid_marker_exactly"] == 1
    assert authorization["hard_gates"]["one_boundary_marker_exactly"] == 1
    assert authorization["hard_gates"]["periodic_axes"] == ["x", "y"]
    assert authorization["hard_gates"]["fixed_wall_axes"] == ["z"]
    native = authorization["hard_gates"]["native_initial_particle_checks"]
    assert native["fluid_particle_count_exact"] == 6144
    assert native["excluded_fluid_particle_count_exact"] == 0
    assert native["boundary_normals_nonzero"] is True
    permissions = authorization["permissions"]
    assert permissions["cpu_gencase"] is True
    assert permissions["native_decode"] is True
    assert all(permissions[key] is False for key in ("solver", "gpu", "queue", "registry", "ledger", "training", "qualification"))
    assert all(permissions[key] == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation"))
    for item in authorization["bindings"]:
        path = ROOT / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_authorization_cannot_be_overwritten() -> None:
    with pytest.raises(FileExistsError, match="immutable F8 CPU/native authorization"):
        authorization_module.write_authorization()


def test_runner_is_argv_only_before_execution_and_refuses_any_executed_namespace() -> None:
    # This repository may be inspected either before the one-shot execution or
    # after its retained result is committed.  In the latter lifecycle the
    # argv-only runner must fail closed rather than offer the same input again.
    if runner.OUTPUT_DIR.exists():
        receipt = json.loads((runner.OUTPUT_DIR / "receipt.json").read_text(encoding="utf-8"))
        assert receipt["status"] == "cpu_native_preflight_failed_hard_audit"
        assert receipt["execution_controls"]["cpu_gencase_invoked"] is True
        assert receipt["execution_controls"]["native_decode_invoked"] is True
        assert receipt["execution_controls"]["solver_invoked"] is False
        assert receipt["qualification_credit"] == 0
        with pytest.raises(RuntimeError, match="retry or reuse is forbidden"):
            runner.build_execution_plan()
    else:
        plan = runner.build_execution_plan()
        assert plan["status"] == "validated_argv_only_not_executed"
        assert plan["execution_controls"]["cpu_gencase_invoked"] is False
        assert plan["execution_controls"]["native_decode_invoked"] is False
        assert plan["execution_controls"]["solver_invoked"] is False
        assert plan["execution_controls"]["gpu_invoked"] is False
        assert plan["execution_controls"]["qualification_credit"] == 0
        assert plan["commands"]["cpu_gencase"][-1] == "-save:all"


def test_runner_rejects_changed_input_binding_and_existing_namespace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    changed = copy.deepcopy(load_authorization())
    changed["bindings"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="binding changed"):
        runner.validate_authorization(changed)

    occupied = tmp_path / "cpu-native-preflight-v1"
    occupied.mkdir()
    monkeypatch.setattr(runner, "OUTPUT_DIR", occupied)
    with pytest.raises(RuntimeError, match="retry or reuse is forbidden"):
        runner.validate_output_namespace(occupied)
