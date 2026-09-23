from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from scripts import f8_r008_cpu_native_preflight_authorization_v1 as auth
from scripts import f8_r008_cpu_native_preflight_execute_v1 as execute
from scripts import f8_r008_scoped_native_command_v1 as scoped


def _write_cgroup(root: Path, *, maximum: int = 4096 * 1024**2, peak: int = 1024 * 1024) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory.max").write_text(f"{maximum}\n", encoding="ascii")
    (root / "memory.peak").write_text(f"{peak}\n", encoding="ascii")
    (root / "memory.current").write_text("4096\n", encoding="ascii")
    (root / "memory.events").write_text(
        "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n", encoding="ascii",
    )
    return root


def _gate_snapshot(**updates):
    value = {
        "cpu_affinity_count": 128,
        "load_average_1_5_15_min": [1.0, 1.0, 1.0],
        "mem_available_bytes": 16 * 1024**3,
        "filesystem_free_bytes": 16 * 1024**3,
        "f3_material_row30_pids": [],
        "cgroup_v2_unified": True,
        "cgroup_v2_memory_controller": True,
        "systemd_user_manager_responsive": True,
        "systemd_scope_names_available": True,
    }
    value.update(updates)
    return value


def _minimal_auth():
    return {
        "resource_scope": {
            "prelaunch_gates": {
                "cpu_affinity_count_minimum": 1,
                "available_memory_bytes_minimum": 8 * 1024**3,
                "free_disk_bytes_minimum": 8 * 1024**3,
            },
        },
    }


def test_cgroup_v2_path_rejects_escape(tmp_path):
    root = tmp_path / "cgroup"
    root.mkdir()
    proc = tmp_path / "self.cgroup"
    proc.write_text("0::/user.slice/test.scope\n", encoding="utf-8")
    (root / "user.slice/test.scope").mkdir(parents=True)
    assert scoped.cgroup_v2_directory(proc, root) == root / "user.slice/test.scope"

    proc.write_text("0::/../../outside\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="safe relative path"):
        scoped.cgroup_v2_directory(proc, root)


def test_collect_metrics_binds_mount_root_and_reports_pressure(tmp_path):
    root = _write_cgroup(tmp_path / "mounted" / "scope")
    result = scoped.collect_metrics(
        root,
        sampled_peak_rss_bytes=123456,
        sample_count=7,
        expected_memory_max_bytes=4096 * 1024**2,
        cgroup_root=tmp_path / "mounted",
    )
    assert result["cgroup_path"] == "/scope"
    assert result["memory_peak_bytes"] == 1024 * 1024
    assert result["cap_pressure_observed"] is False
    (root / "memory.events").write_text("low 0\nhigh 1\nmax 0\noom 0\noom_kill 0\n", encoding="ascii")
    pressured = scoped.collect_metrics(
        root,
        sampled_peak_rss_bytes=123456,
        sample_count=7,
        expected_memory_max_bytes=4096 * 1024**2,
        cgroup_root=tmp_path / "mounted",
    )
    assert pressured["cap_pressure_observed"] is True


def test_collect_metrics_rejects_mismatched_cap_and_peak(tmp_path):
    root = _write_cgroup(tmp_path / "scope", maximum=8192, peak=8193)
    with pytest.raises(RuntimeError, match="memory.max mismatch"):
        scoped.collect_metrics(root, sampled_peak_rss_bytes=0, sample_count=1, expected_memory_max_bytes=4096 * 1024**2, cgroup_root=tmp_path)
    (root / "memory.max").write_text("4096\n", encoding="ascii")
    with pytest.raises(RuntimeError, match="memory.peak exceeds"):
        scoped.collect_metrics(root, sampled_peak_rss_bytes=0, sample_count=1, expected_memory_max_bytes=4096, cgroup_root=tmp_path)


def test_scoped_runner_records_full_scope_and_cpu_environment(tmp_path, monkeypatch):
    cgroup = _write_cgroup(tmp_path / "scope")
    (cgroup / "cgroup.procs").write_text(f"{os.getpid()}\n", encoding="ascii")
    monkeypatch.setattr(scoped, "cgroup_v2_directory", lambda: cgroup)
    monkeypatch.setattr(scoped, "_sample_cgroup_rss", lambda path: 8192)
    monkeypatch.setattr(scoped.time, "sleep", lambda _: None)

    class FakeProcess:
        pid = 999999

        def __init__(self):
            self.poll_count = 0
            self.environment = None

        def poll(self):
            self.poll_count += 1
            return None if self.poll_count == 1 else 0

        def wait(self, timeout=None):
            return 0

    fake = FakeProcess()

    def fake_popen(argv, *, cwd, env, start_new_session, preexec_fn):
        assert argv == ["/bin/true"]
        assert Path(cwd) == tmp_path
        assert start_new_session is True
        assert callable(preexec_fn)
        fake.environment = env
        return fake

    monkeypatch.setattr(scoped.subprocess, "Popen", fake_popen)
    target = tmp_path / "metrics.json"
    result = scoped.run_payload(
        ["/bin/true"], cwd=tmp_path, metrics_json=target, timeout_seconds=2,
        expected_memory_max_bytes=4096 * 1024**2, sample_interval_seconds=0.001,
        cgroup_root=tmp_path,
    )
    assert result["child_return_code"] == 0
    assert result["scope_process_tree_clean"] is True
    assert result["metrics"]["sampled_cgroup_process_rss_peak_bytes"] == 8192
    assert fake.environment["CUDA_VISIBLE_DEVICES"] == ""
    assert fake.environment["OMP_NUM_THREADS"] == "1"
    assert json.loads(target.read_text())["child_argv"] == ["/bin/true"]
    with pytest.raises(FileExistsError):
        scoped.run_payload(["/bin/true"], cwd=tmp_path, metrics_json=target, timeout_seconds=2, expected_memory_max_bytes=4096 * 1024**2)


def test_authorization_builder_verifies_frozen_request_and_review():
    value = auth.build_authorization()
    assert value["status"] == "authorized_for_exactly_one_r008_cpu_native_preflight"
    assert value["qualification_credit"] == 0
    assert len(value["bindings"]) >= 118
    assert value["target_case"]["case_id"] == "space-q0p5-dp0p0075"
    assert value["resource_scope"]["memory_max_bytes"] == 4096 * 1024**2
    assert value["permissions"]["cpu_gencase"] is True
    assert value["permissions"]["native_decode"] is True
    assert value["permissions"]["solver"] is False
    assert value["geometry_analogue"]["r007_outputs_not_reused"] is True
    plan = execute.build_execution_plan(value)
    command = execute._scope_command(plan, "gencase", execute.OUTPUT / "gencase.scope-metrics.json", value)
    assert command[0] == value["runtime_bindings"]["systemd_run"]["path"]
    assert "--property=MemoryMax=4294967296" in command
    assert command[-5:] == ["--", *plan["gencase"]["payload"]]
    assert not execute.OUTPUT.exists()


def test_current_resource_gate_blocks_live_f3_and_overload():
    authorization = _minimal_auth()
    blockers = execute.gate_blockers(
        _gate_snapshot(load_average_1_5_15_min=[140, 140, 140], f3_material_row30_pids=[1151871]),
        authorization,
    )
    assert any("load" in item for item in blockers)
    assert any("F3 material row30" in item for item in blockers)


def test_resource_gate_blocks_a_preexisting_exact_systemd_scope():
    blockers = execute.gate_blockers(
        _gate_snapshot(systemd_scope_names_available=False, occupied_transient_scope_units=["f8-r008-cpu-preflight-v3-gencase.scope"]),
        _minimal_auth(),
    )
    assert any("scope names" in item for item in blockers)


def test_blocked_preflight_creates_no_namespace_or_lock(tmp_path, monkeypatch):
    output = tmp_path / "fresh-output"
    monkeypatch.setattr(execute, "load_authorization", lambda _path: _minimal_auth())
    monkeypatch.setattr(execute, "build_execution_plan", lambda _value: {
        "output_namespace": output,
        "authorization": str(tmp_path / "authorization.json"),
        "request": str(tmp_path / "request.json"),
    })
    result = execute.run_once(
        execute=True,
        resource_provider=lambda _parent: _gate_snapshot(f3_material_row30_pids=[1234]),
        authorization_path=tmp_path / "authorization.json",
    )
    assert result["status"] == "deferred_resource_gate_blocked"
    assert result["output_namespace_created"] is False
    assert result["one_shot_lock_created"] is False
    assert not output.exists()


def test_ready_preflight_does_not_consume_authorized_one_shot(tmp_path, monkeypatch):
    output = tmp_path / "fresh-output"
    monkeypatch.setattr(execute, "load_authorization", lambda _path: _minimal_auth())
    monkeypatch.setattr(execute, "build_execution_plan", lambda _value: {"output_namespace": output})
    result = execute.run_once(
        execute=False,
        resource_provider=lambda _parent: _gate_snapshot(),
        authorization_path=tmp_path / "authorization.json",
    )
    assert result["status"] == "preflight_ready_not_started"
    assert result["output_namespace_created"] is False
    assert result["one_shot_lock_created"] is False
    assert not output.exists()


def test_second_live_gate_is_rechecked_before_namespace_creation(tmp_path, monkeypatch):
    output = tmp_path / "fresh-output"
    monkeypatch.setattr(execute, "load_authorization", lambda _path: _minimal_auth())
    monkeypatch.setattr(execute, "build_execution_plan", lambda _value: {
        "output_namespace": output,
        "authorization": str(tmp_path / "authorization.json"),
        "request": str(tmp_path / "request.json"),
    })
    snapshots = iter((_gate_snapshot(), _gate_snapshot(load_average_1_5_15_min=[129, 120, 100])))
    calls = []

    def provide(_parent):
        calls.append(True)
        return next(snapshots)

    result = execute.run_once(execute=True, resource_provider=provide, authorization_path=tmp_path / "authorization.json")
    assert result["status"] == "deferred_resource_gate_blocked"
    assert result["resource_gate_rechecked"] is True
    assert len(calls) == 2
    assert not output.exists()


def test_two_passed_gates_consume_once_and_run_only_the_two_native_stages(tmp_path, monkeypatch):
    output = tmp_path / "fresh-output"
    auth_file, request_file = tmp_path / "authorization.json", tmp_path / "request.json"
    auth_file.write_text("{}", encoding="utf-8")
    request_file.write_text("{}", encoding="utf-8")
    definition, control = tmp_path / "case_Def.xml", tmp_path / "case.csv"
    definition.write_text("<case />", encoding="utf-8")
    control.write_text("control", encoding="utf-8")
    authorization = _minimal_auth()
    authorization.update({"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008", "target_case": {}})
    plan = {
        "output_namespace": output,
        "authorization": str(auth_file),
        "request": str(request_file),
        "input": {"definition": definition, "control": control},
        "input_contract": {"definition_xml_parses": True, "hswl_explicit_zero": True, "control_reference_exact": True, "control_is_colocated": True},
        "generated": {"definition": output / "generated/case.xml"},
        "working_directory": tmp_path,
        "gencase": {"payload": ["GenCase"]},
        "native_decode": {"payload": ["bi4_dump"], "output_base": output / "native-initial"},
    }
    monkeypatch.setattr(execute, "load_authorization", lambda _path: authorization)
    monkeypatch.setattr(execute, "build_execution_plan", lambda _value: plan)
    calls = []

    def stage(_plan, name, _authorization, _output):
        calls.append(name)
        return {"native_payload_invoked": True, "resource_gate_pass": True, "stage": name}

    monkeypatch.setattr(execute, "_invoke_stage", stage)
    monkeypatch.setattr(execute, "_audit_generated", lambda *_: {"pass": True})
    from scripts import f8_r006_cpu_native_preflight_execute_v1 as auditor
    monkeypatch.setattr(auditor, "native_checks", lambda *_: {"pass": True})
    snapshots = iter((_gate_snapshot(), _gate_snapshot()))
    result = execute.run_once(execute=True, resource_provider=lambda _parent: next(snapshots), authorization_path=auth_file)
    assert result["status"] == "cpu_native_preflight_passed_zero_credit", result.get("failure")
    assert calls == ["gencase", "native_decode"]
    assert result["execution_controls"]["solver_invoked"] is False
    assert result["execution_controls"]["gpu_invoked"] is False
    assert result["qualification_credit"] == 0
    assert (output / "one-shot-lock.json").is_file()
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["execution_controls"]["native_decode_invoked"] is True
    assert not (output / "solver").exists()


def test_exclusive_json_refuses_attempt_reuse(tmp_path):
    path = tmp_path / "one-shot-lock.json"
    execute._write_exclusive(path, {"budget": 1})
    with pytest.raises(FileExistsError):
        execute._write_exclusive(path, {"budget": 1})
    assert json.loads(path.read_text())["budget"] == 1
