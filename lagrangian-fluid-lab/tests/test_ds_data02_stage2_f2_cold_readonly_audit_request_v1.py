from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_cold_readonly_audit_request_v1.py"
SPEC = importlib.util.spec_from_file_location("f2_cold_audit_request_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _role(path: Path, role: str, target: str, executable: bool = False) -> dict[str, object]:
    mode = 0o755 if executable else 0o644
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(role, encoding="utf-8")
    path.chmod(mode)
    info = builder._stat(path, role)
    return {"role": role, "path": str(path), "target_relative_path": target,
            "bytes": info["bytes"], "mtime_ns": info["mtime_ns"],
            "source_mode_bits": info["mode_bits"], "required_executable": executable,
            "preserve_mode": True, "source_stat_expected": info}


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    source = tmp_path / "sources"
    runtime = tmp_path / "runtime"
    target = tmp_path / "relocated" / "target"
    output = tmp_path / "relocated" / "output"
    target.mkdir(parents=True)
    output.mkdir(parents=True)
    py = _role(runtime / "python", "python_executable", "runtime/python/python", executable=True)
    py["invocation_path"] = str(runtime / "python")
    source_entries = [
        _role(source / "Part_0000.bi4", "raw_frame_input", "raw/Part_0000.bi4"),
        _role(source / "PartOut_000.obi4", "v2:native_partout", "raw/PartOut_000.obi4"),
        _role(source / "converter.py", "raw_converter", "runtime/raw/converter.py"),
        _role(source / "decoder", "native_bi4_decoder", "runtime/native/decoder", executable=True),
        _role(source / "strace", "os_strace", "runtime/os/strace", executable=True),
    ]
    runtime_sources = [
        py,
        _role(runtime / "executor.py", "executor_v34", "runtime/executor.py"),
        _role(runtime / "worker.py", "raw_worker_v2", "runtime/worker.py"),
        _role(runtime / "evaluator.py", "evaluator_v4", "runtime/evaluator.py"),
    ]
    request = {
        "schema": builder.V34_SCHEMA, "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_STAGE2_GUARD", "source_entries": source_entries,
        "runtime_sources": runtime_sources,
        "execution": {
            "command": [str(runtime / "python"), "-B", "-I", str(runtime / "executor.py"),
                        "run", "--request", "<this-request>"],
            "fresh_subprocess": True, "isolated_python": "-I",
            "original_path_fallback": "FORBIDDEN", "os_open_audit_required": True,
        },
    }
    request["sha256"] = builder.canonical_sha(request)
    request_path = tmp_path / "v34-request.json"
    _write(request_path, request)
    provenance = {"schema": "ds02.stage2.provenance.v1", "status": "DECLARED",
                  "license_scope_status": "DECLARED", "bindings": []}
    provenance_path = tmp_path / "provenance.json"
    _write(provenance_path, provenance)
    return request_path, provenance_path, target, output, runtime / "python"


def test_builder_emits_real_ff_role_contract_without_payload_reads(tmp_path: Path) -> None:
    request, provenance, target, output, _ = _fixture(tmp_path)
    trace = output / "os-trace"
    output_request = tmp_path / "audit-request.json"
    value = builder.build_request(v34_request=request, provenance_sidecar=provenance,
                                  target_root=target, output_root=output,
                                  trace_prefix=trace, output=output_request)
    assert value["status"] == "READY_FOR_PARENT_TRACE_GUARD"
    result = json.loads(output_request.read_text(encoding="utf-8"))
    assert result["trace"]["command_template"][1:3] == ["-ff", "-yy"]
    assert "trace=%file,%process" in result["trace"]["command_template"]
    assert result["trace"]["follows_forks"] is True
    assert {item["role_id"] for item in result["role_bindings"]} >= {
        "executor", "source_copy", "converter", "decoder", "evaluator", "strace",
    }
    assert result["runtime_binding"]["literal_invocation_path"].endswith("runtime/python")
    assert result["runtime_binding"]["preserve_literal_argv0"] is True
    assert result["scratch_policy"]["whole_tmp_whitelist"] is False
    assert result["hdf5_or_bi4_content_read"] is False
    assert result["sha256"] == builder.canonical_sha(result)


def test_builder_rejects_missing_decoder_or_unbound_fallback(tmp_path: Path) -> None:
    request, provenance, target, output, _ = _fixture(tmp_path)
    value = json.loads(request.read_text(encoding="utf-8"))
    value["source_entries"] = [item for item in value["source_entries"]
                               if item["role"] != "native_bi4_decoder"]
    value["sha256"] = builder.canonical_sha(value)
    broken = tmp_path / "broken-request.json"
    _write(broken, value)
    with pytest.raises(builder.AuditRequestError, match="decoder"):
        builder.build_request(v34_request=broken, provenance_sidecar=provenance,
                              target_root=target, output_root=output,
                              trace_prefix=output / "trace", output=tmp_path / "out.json")

    value = json.loads(request.read_text(encoding="utf-8"))
    value["execution"]["original_path_fallback"] = "ALLOWED"
    value["sha256"] = builder.canonical_sha(value)
    broken.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(builder.AuditRequestError, match="fallback"):
        builder.build_request(v34_request=broken, provenance_sidecar=provenance,
                              target_root=target, output_root=output,
                              trace_prefix=output / "trace2", output=tmp_path / "out2.json")
