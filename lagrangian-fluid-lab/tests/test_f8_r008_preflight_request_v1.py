from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f8_r008_preflight_request_v1 as request


_BINARY_SUFFIXES = {".h5", ".hdf5", ".hdf", ".npz"}
_PATH_ACCESSORS = (
    "stat", "lstat", "resolve", "exists", "is_file", "is_symlink",
    "open", "read_bytes", "read_text",
)


def test_build_request_never_accesses_hdf5_or_npz(monkeypatch):
    original_hash = request._sha256

    def guard_path_accessor(method_name, original):
        def guarded(path, *args, **kwargs):
            path = Path(path)
            if path.suffix.lower() in _BINARY_SUFFIXES:
                pytest.fail(f"static R008 request called {method_name} on {path}")
            return original(path, *args, **kwargs)
        return guarded

    for method_name in _PATH_ACCESSORS:
        monkeypatch.setattr(
            Path, method_name,
            guard_path_accessor(method_name, getattr(Path, method_name)),
        )

    def guarded_hash(path):
        path = Path(path)
        if path.suffix.lower() in _BINARY_SUFFIXES:
            pytest.fail(f"static R008 request hashed binary path {path}")
        return original_hash(path)

    monkeypatch.setattr(request, "_sha256", guarded_hash)
    built = request.build_request()
    assert built["execution_controls"]["request_builder_executed_native_tool"] is False
    assert built["permissions"]["gencase"] is False


def test_request_is_not_an_authorization_and_all_runtime_permissions_are_closed():
    built = request.build_request()
    assert built["status"] == "request_ready_requires_separate_explicit_runtime_authorization"
    assert built["request_only"] is True
    assert built["authorization"]["this_request_grants_execution"] is False
    assert built["authorization"]["separate_explicit_user_authorization_required_before_any_native_tool"] is True
    assert built["authorization"]["qualification_credit"] == 0
    for key, value in built["permissions"].items():
        assert value is False if isinstance(value, bool) else value == 0
    assert built["target_case"]["case_id"] == request.REPRESENTATIVE_CASE_ID
    assert built["target_case"]["qualification_only"] is True
    assert built["lineage_exclusions"]["r007_inputs_reused_as_r008_inputs"] is False
    assert built["lineage_exclusions"]["r007_native_outputs_reused"] is False


def test_request_binds_all_94_r008_inputs_and_17_text_sources():
    built = request.build_request()
    pack = json.loads((request.LAB / request.PACK_RECEIPT).read_text(encoding="utf-8"))
    bindings = built["all_r008_inputs"]["bindings"]
    assert len(bindings) == 94
    assert built["all_r008_inputs"]["definition_count"] == 47
    assert built["all_r008_inputs"]["control_count"] == 47
    assert built["all_r008_inputs"]["source_binding_count"] == 17
    assert {item["path"] for item in bindings} == {
        request._relative(item["path"]) for item in pack["input_bindings"]
    }
    assert all(Path(item["path"]).suffix.lower() in {".xml", ".csv"} for item in bindings)
    assert all(item["path"].startswith(str(request.ROOT) + "/") for item in bindings)


def test_request_proposes_one_fresh_cpu_preflight_but_no_solver_or_runtime():
    built = request.build_request()
    proposed = built["proposed_preflight_only"]
    assert proposed["max_gencase_invocations"] == 1
    assert proposed["max_native_decode_invocations"] == 1
    assert proposed["solver_invocations"] == 0
    assert proposed["runtime_output_namespace"] == str(request.RUNTIME_NAMESPACE)
    assert proposed["runtime_output_namespace_created_by_this_request"] is False
    assert proposed["retries_or_output_reuse_allowed"] is False
    assert proposed["proposed_resource_envelope"]["cpu_workers"] == 1
    assert proposed["proposed_resource_envelope"]["gpu_allowed"] is False
    assert built["execution_controls"]["runtime_namespace_created"] is False
    assert not (request.LAB / request.RUNTIME_NAMESPACE).exists()
    assert not (request.LAB / request.RUNTIME_NAMESPACE).is_symlink()


def test_written_request_matches_current_sources_and_all_input_hashes():
    receipt_path = request.LAB / request.REQUEST
    built = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert built == request.build_request()
    for item in built["all_r008_inputs"]["bindings"]:
        source = request.LAB / item["path"]
        assert source.stat().st_size == item["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"]
    for item in built["all_r008_inputs"]["source_bindings"]:
        source = request.LAB / item["path"]
        assert source.stat().st_size == item["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"]


def test_writer_refuses_to_overwrite_existing_request(tmp_path, monkeypatch):
    existing = tmp_path / "request.json"
    existing.write_text("immutable", encoding="utf-8")
    monkeypatch.setattr(request, "LAB", tmp_path)
    monkeypatch.setattr(request, "REQUEST", Path("request.json"))
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        request.write_request()
