from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_preflight_request_v3 as request


LAB = Path(__file__).resolve().parents[1]


def test_v3_native_commands_use_absolute_paths_and_the_verified_cap() -> None:
    value = request.build_request()
    commands = value["proposed_preflight_only"]["argv_templates_not_executed"]

    for role in ("gencase", "native_decode"):
        command = commands[role]
        assert command[:3] == ["systemd-run", "--user", "--scope"]
        assert f"--property=MemoryMax={4 * 1024**3}" in command
        assert "--property=MemoryAccounting=yes" in command
        payload = command[command.index("--") + 1 :]
        paths = payload[:-1] if role == "gencase" else payload
        assert all(Path(argument).is_absolute() for argument in paths)
    assert commands["gencase"][-1] == "-save:all"
    assert commands["gencase"][-2].endswith(
        "cpu-native-preflight-v3/generated/space-q0p5-dp0p0075"
    )
    assert commands["native_decode"][-1].endswith("cpu-native-preflight-v3/native-initial")
    assert all("cpu-native-preflight-v2/" not in item
               for role in ("gencase", "native_decode") for item in commands[role])


def test_v3_supersedes_unexecuted_v2_and_grants_no_execution_or_credit() -> None:
    value = request.build_request()

    assert value["schema"] == "core.cfd.f8.r008_cpu_native_preflight_request.v3"
    assert value["request_only"] is True
    assert value["supersedes"]["status"] == "superseded_not_executed"
    assert value["supersedes"]["v2_native_tool_invocations"] == 0
    assert value["authorization"]["this_request_grants_execution"] is False
    assert value["execution_controls"]["gencase_invoked"] is False
    assert value["execution_controls"]["native_decode_invoked"] is False
    assert value["permissions"]["gencase"] is False
    assert value["permissions"]["native_decode"] is False
    assert value["permissions"]["solver"] is False
    assert value["permissions"]["gpu"] is False
    assert value["target_case"]["qualification_only"] is True
    assert value["proposed_preflight_only"]["proposed_resource_envelope"]["cap_pressure_tested"] is False
    assert value["proposed_preflight_only"]["proposed_resource_envelope"]["native_peak_measured"] is False


def test_v3_hash_closes_inputs_v2_request_builder_and_tests() -> None:
    value = request.build_request()
    bindings = value["source_bindings"]
    by_path = {item["path"]: item for item in bindings}

    assert value["all_r008_inputs"]["input_count"] == 94
    assert len(bindings) == len(by_path)
    for item in bindings:
        path = LAB / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert request.sha256(path) == item["sha256"]
    assert request.REQUEST_V2.as_posix() in by_path
    assert request.BUILDER.as_posix() in by_path
    assert request.TESTS.as_posix() in by_path
    assert value["supersedes"]["request"]["path"] == request.REQUEST_V2.as_posix()


def test_v3_rejects_a_changed_superseded_request(monkeypatch: pytest.MonkeyPatch) -> None:
    original = request.reference

    def altered(path: Path, role: str) -> dict:
        value = original(path, role)
        if Path(path) == LAB / request.REQUEST_V2:
            value["sha256"] = "0" * 64
        return value

    monkeypatch.setattr(request, "reference", altered)
    with pytest.raises(ValueError, match="bound source changed"):
        request.build_request()


def test_v3_writer_refuses_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "request-v3" / "request.json"
    monkeypatch.setattr(request, "REQUEST", Path("request-v3/request.json"))
    monkeypatch.setattr(request, "LAB", tmp_path)
    monkeypatch.setattr(request, "RUNTIME_NAMESPACE", tmp_path / "runtime-v3")
    monkeypatch.setattr(request, "build_request", lambda: {"schema": request.SCHEMA})

    first = request.write_request()
    assert first == target
    assert json.loads(first.read_text())["schema"] == request.SCHEMA
    with pytest.raises(FileExistsError, match="overwrite immutable R008 v3 request"):
        request.write_request()
