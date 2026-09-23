from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_preflight_request_v2 as request


LAB = Path(__file__).resolve().parents[1]


def test_v2_binds_the_verified_cap_but_grants_no_runtime_authority() -> None:
    value = request.build_request()
    envelope = value["proposed_preflight_only"]["proposed_resource_envelope"]

    assert value["schema"] == "core.cfd.f8.r008_cpu_native_preflight_request.v2"
    assert value["request_only"] is True
    assert value["status"] == "request_ready_with_cgroup_cap_mechanism_verified_peak_unmeasured"
    assert envelope["ram_limit_mib"] == 4096
    assert envelope["ram_limit_bytes"] == 4 * 1024**3
    assert envelope["cap_pressure_tested"] is False
    assert envelope["native_peak_measured"] is False
    assert value["execution_controls"]["gencase_invoked"] is False
    assert value["execution_controls"]["native_decode_invoked"] is False
    assert value["permissions"]["gencase"] is False
    assert value["permissions"]["native_decode"] is False
    assert value["permissions"]["solver"] is False
    assert value["permissions"]["gpu"] is False
    assert value["target_case"]["case_id"] == "space-q0p5-dp0p0075"
    assert value["target_case"]["qualification_only"] is True
    assert value["proposed_preflight_only"]["runtime_output_namespace"].endswith(
        "cpu-native-preflight-v2"
    )


def test_v2_tool_templates_place_each_native_command_in_4g_scope() -> None:
    value = request.build_request()
    commands = value["proposed_preflight_only"]["argv_templates_not_executed"]

    for role in ("gencase", "native_decode"):
        command = commands[role]
        assert command[:3] == ["systemd-run", "--user", "--scope"]
        assert f"--property=MemoryMax={4 * 1024**3}" in command
        assert "--property=MemoryAccounting=yes" in command
        assert "--" in command
    assert commands["gencase"].count("-save:all") == 1
    assert commands["native_decode"][0] == "systemd-run"
    assert commands["gencase"][-2].endswith(
        "cpu-native-preflight-v2/generated/space-q0p5-dp0p0075"
    )
    assert commands["native_decode"][-1].endswith("cpu-native-preflight-v2/native-initial")
    assert all("cpu-native-preflight-v1/" not in value for value in commands["gencase"] + commands["native_decode"])


def test_v2_preserves_the_94_input_and_static_source_bindings() -> None:
    value = request.build_request()

    assert value["all_r008_inputs"]["input_count"] == 94
    assert len(value["source_bindings"]) == len({item["path"] for item in value["source_bindings"]})
    for item in value["source_bindings"]:
        path = LAB / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert request.sha256(path) == item["sha256"]
    assert value["request_v1_reference"]["path"].endswith(
        "cpu-native-preflight-request-v1/request.json"
    )


def test_v2_refuses_a_stale_or_overclaiming_capability_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    original = request._load_object

    def changed(path: Path) -> dict:
        value = original(path)
        if Path(path) == LAB / request.CAPABILITY_PROBE:
            value["probe"]["cgroup_memory_max_bytes"] = 2 * 1024**3
        return value

    monkeypatch.setattr(request, "_load_object", changed)
    with pytest.raises(ValueError, match="resource cap evidence"):
        request.build_request()


def test_v2_request_writer_refuses_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "request-v2" / "request.json"
    monkeypatch.setattr(request, "REQUEST", Path("request-v2/request.json"))
    monkeypatch.setattr(request, "LAB", tmp_path)
    monkeypatch.setattr(request, "ROOT", Path("candidate"))
    monkeypatch.setattr(request, "RUNTIME_NAMESPACE", tmp_path / "candidate/runtime-v2")
    monkeypatch.setattr(request, "build_request", lambda: {"schema": request.SCHEMA})

    # Bind the writer to the temporary lab without changing the immutable source inputs.
    first = request.write_request()
    assert first == target
    assert json.loads(first.read_text())["schema"] == request.SCHEMA
    with pytest.raises(FileExistsError, match="overwrite immutable R008 v2 request"):
        request.write_request()
