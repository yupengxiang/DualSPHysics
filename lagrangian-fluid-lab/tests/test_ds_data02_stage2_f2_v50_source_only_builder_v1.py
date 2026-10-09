"""Source-only tests for the V50 post-terminal hand-off builders.

Fixtures are bounded JSON/code files.  They deliberately contain no HDF5,
BI4, raw frame, typed-result, or large-result payload.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BUILDER_PATH = SCRIPTS / "ds_data02_stage2_f2_v50_source_only_postterminal_builder_v1.py"
ADAPTER_V2_PATH = SCRIPTS / "ds_data02_stage2_f2_evaluator_v4_adapter_v2.py"
STRICT_BUILDER_PATH = SCRIPTS / "ds_data02_stage2_f2_v50_source_only_postterminal_builder_v2.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = _load(BUILDER_PATH, "test_v50_source_only_builder")
A = _load(ADAPTER_V2_PATH, "test_v50_evaluator_adapter_v2")
SB = _load(STRICT_BUILDER_PATH, "test_v50_strict_source_builder_v2")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _write_bytes(path: Path, data: bytes = b"bounded fixture\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _canonical(value: dict) -> dict:
    value["sha256"] = B.canonical_sha(value)
    return value


def _binding(path: Path, *, sha: str | None = None) -> dict:
    return {
        "path": str(path), "sha256": sha or _sha(path), "bytes": path.stat().st_size,
        "stat": {"bytes": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns,
                  "mode_bits": stat.S_IMODE(path.stat().st_mode)},
    }


def _executor(tmp_path: Path) -> tuple[Path, dict]:
    value = {
        "schema": "ds02.stage2.f2-portable-executor-request.v34",
        "execution": {"raw_tree_binding": {
            "tree_sha256": B.RAW_TREE_SHA, "file_count": B.RAW_TREE_FILES,
            "frame_count": B.RAW_TREE_FRAMES,
        }},
        "runtime_sources": [],
    }
    return _write(tmp_path / "requests" / "executor.json", _canonical(value)), value


def _parent_request(tmp_path: Path) -> tuple[Path, dict]:
    value = {
        "schema": "ds02.stage2.f2-portable-executor-parent-request.v3",
        "request_id": "fixture-parent",
    }
    return _write(tmp_path / "requests" / "parent.json", value), value


def _runtime_closure_fixture(tmp_path: Path, executor_path: Path) -> tuple[Path, dict, Path]:
    runtime = tmp_path / "runtime"
    roles = sorted(B.REQUIRED_RUNTIME_ROLES - {"interpreter_abi_smoke"})
    role_args: list[str] = []
    for index, role in enumerate(roles):
        if role == "python_executable":
            target = _write_bytes(runtime / "venv-target" / "python-bin", b"#!/bin/sh\n")
            target.chmod(0o755)
            literal = runtime / ".venv" / "bin" / "python"
            literal.parent.mkdir(parents=True, exist_ok=True)
            literal.symlink_to(target)
            role_args.append(f"{role}={literal}")
        else:
            role_path = _write_bytes(runtime / "runtime" / f"{role}-{index}.py")
            role_args.append(f"{role}={role_path}")
    literal = Path(role_args[[r.split("=", 1)[0] for r in role_args].index("python_executable")].split("=", 1)[1])
    abi = _write(tmp_path / "runtime" / "runtime" / "abi-smoke.json", {
        "schema": B.ABI_SMOKE_SCHEMA, "status": B.ABI_SMOKE_STATUS,
        "literal_argv0": str(literal), "numpy_h5py_abi": "pinned-venv-fixture",
    })
    closure_path = tmp_path / "closure.json"
    result = B.build_runtime_closure(
        executor_request=executor_path, runtime_root=runtime, output=closure_path,
        role_bindings=role_args, pinned_sources=[], abi_smoke=abi)
    value = json.loads(closure_path.read_text(encoding="utf-8"))
    return closure_path, value, literal


def test_runtime_closure_accepts_only_explicit_literal_venv_exception(tmp_path: Path) -> None:
    executor_path, _ = _executor(tmp_path)
    closure_path, closure, literal = _runtime_closure_fixture(tmp_path, executor_path)
    root, rows = A._validate_closure_external(closure_path, closure)
    assert root == (tmp_path / "runtime").resolve()
    python_row = next(row for row in rows if row["role"] == "python_executable")
    assert python_row["path"] == str(literal)
    assert python_row["literal_invocation_path"] == str(literal)
    assert python_row["resolved_path_provenance_only"] is True
    assert python_row["resolved_path"] != python_row["literal_invocation_path"]
    assert "interpreter_abi_smoke" in {row["role"] for row in rows}

    mutated = json.loads(closure_path.read_text(encoding="utf-8"))
    python_raw = next(row for row in mutated["roles"] if row["role"] == "python_executable")
    python_raw["resolved_path"] = str(tmp_path / "wrong-python")
    mutated["sha256"] = A.canonical_sha(mutated)
    with pytest.raises(A.EvaluatorAdapterV2Error, match="resolved-path provenance"):
        A._validate_closure_external(closure_path, mutated)


def test_source_only_terminal_builder_derives_sidecar_without_payload_read(tmp_path: Path) -> None:
    executor_path, _ = _executor(tmp_path)
    parent_path, _ = _parent_request(tmp_path)
    preflight = _write(tmp_path / "requests" / "preflight.json", {
        "schema": "ds02.stage2.root.v50-metadata-preflight.v1",
        "status": "ACTUAL_PARENT_V3_METADATA_VALIDATOR_PASS",
        "array_payload_read": False,
        "qualification_credit": "NONE",
        "content_hash_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
        "namespace_absent": True,
    })
    namespace = tmp_path / "fresh-namespace"
    output_root = namespace / "products"
    output_root.mkdir(parents=True)
    source_contract = _write(namespace / "source-contract.json", _canonical({
        "schema": "ds02.stage2.f2-fresh-source-contract.v4",
        "expected": {"source_binding": {
            "current_catalog_sha256": "c" * 64,
            "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND",
            "source_files": {"current_catalog": "c" * 64},
        }},
        "current_catalog_provenance": {
            "actual_current_catalog": {"sha256": B.CURRENT_SHA},
            "relocated_runtime_view": {"sha256": "c" * 64},
        },
    }))
    relocated_v15 = _write(output_root / "relocated-v15.json", {"schema": "v15"})
    current_view = _write(output_root / "current-view.json", {"schema": "current"})
    engine_report = _write(output_root / "engine-report.json", {"status": "complete"})
    typed = _write_bytes(output_root / "typed-output.fixture", b"typed metadata fixture")
    v15 = _write(output_root / "v15-result.json", {"status": "labels"})
    v16 = _write(output_root / "v16-result.json", {"status": "unknown"})
    converter = _write(output_root / "converter-report.json", {"status": "complete"})
    worker = _write(namespace / "worker-report.json", {
        "schema": B.WORKER_REPORT_SCHEMA,
        "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "execution_boundary": {"raw_opened": True, "hdf5_opened": True,
                                "model_invoked": False, "cfd_invoked": False},
        "typed_output": _binding(typed),
        "typed_to_label": {
            "status": "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN",
            "result": str(v15), "result_sha256": _sha(v15),
            "v16_forward": {"status": "COMPLETE_DEVELOPMENT_UNKNOWN",
                             "result": str(v16), "result_sha256": _sha(v16)},
        },
        "raw_to_typed": {"converter_report": str(converter)},
    })
    parent_report = _write(tmp_path / "parent-report.json", {
        "schema": B.PARENT_REPORT_SCHEMA,
        "status": "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN",
        "request": {"path": str(parent_path), "sha256": _sha(parent_path)},
        "executor": {"path": str(executor_path), "sha256": _sha(executor_path)},
        "execution": {"hard_wall_covers": ["metadata/stat preflight", "same-parent reservation",
                                             "v34 child copy/hash/worker/evaluator"]},
        "charge": {"ledger_mutated": True, "id": "charge-fixture"},
        "parent": {"same_parent_ledger": True, "attempt_id": "attempt-fixture"},
        "model_invoked": False, "cfd_invoked": False,
    })
    pinned = _write_bytes(tmp_path / "pinned-code.py", b"# pinned source\n")
    static_out = tmp_path / "static.json"
    manifest_out = tmp_path / "manifest.json"
    result = B.build_terminal_inputs(
        executor_request=executor_path, parent_request=parent_path, preflight=preflight,
        parent_report=parent_report, worker_report=worker,
        source_contract=source_contract, output_root=output_root,
        namespace_root=namespace, static_output=static_out, manifest_output=manifest_out,
        pinned_sources=[f"worker={pinned}"],
        artifact_bindings=[f"current_runtime_view={current_view}",
                           f"relocated_v15_request={relocated_v15}",
                           f"engine_report={engine_report}"])
    static = json.loads(static_out.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_out.read_text(encoding="utf-8"))
    assert result["payload_read"] is False
    assert result["derived_sidecar"] is True
    assert static["derived_sidecar"] is True
    assert static["instrumented_receipt"] is False
    assert static["phase"] == B.STATIC_PHASE
    assert manifest["terminal"]["payload_read_after_reservation"] is True
    assert manifest["terminal"]["derived_static_attestation"] is True
    assert manifest["qualification"] == B.UNKNOWN


def test_v2_adapter_build_preserves_literal_venv_argv0(tmp_path: Path) -> None:
    executor_path, _ = _executor(tmp_path)
    closure_path, closure, literal = _runtime_closure_fixture(tmp_path, executor_path)
    runtime = tmp_path / "runtime"
    result_file = _write(runtime / "product" / "v16.json", {"result": "development"})
    proof_file = _write(runtime / "product" / "proof.json", {"proof": "development"})
    raw_file = _write(runtime / "product" / "raw.json", {"worker": "development"})
    v15_file = _write(runtime / "product" / "relocated-v15.json", {
        "schema": "ds02.stage2.f2-s1-replay-request.v15",
        "source_files": [], "current_binding": {}, "trajectory_h5": {},
        "cohort": {}, "case_identity": {}, "observer_profile": {},
    })
    manifest = {"artifacts": {"relocated_v15_request": _binding(v15_file)}}
    manifest["sha256"] = B.canonical_sha(manifest)
    manifest_path = _write(runtime / "product" / "manifest.json", manifest)
    v10 = {
        "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8",
        "status": "READY_FOR_PARENT_GUARD", "qualification": dict(A.UNKNOWN),
        "execution": {"original_path_fallback": "FORBIDDEN"},
        "result": {**_binding(result_file), "schema": "ds02.stage2.f2-s1-replay-result.v16"},
        "source_contract": {"schema": "fresh"},
    }
    v10["sha256"] = B.canonical_sha(v10)
    v10_path = _write(runtime / "product" / "fresh-v10.json", v10)
    descriptor = {
        "schema": "ds02.stage2.f2-v47-fresh-no-model-evaluator-request.v1",
        "status": "READY_FOR_PARENT_EVALUATOR_GUARD", "model_invoked": False,
        "cfd_invoked": False, "qualification": dict(A.UNKNOWN),
        "target_evaluator_schema": A.REQUEST_SCHEMA,
        "source_identity": {"historical_overlay_input_policy": "FORBIDDEN; provenance only"},
        "fresh_v10_request": {"path": str(v10_path), "sha256": v10["sha256"]},
        "fresh_v10_proof": _binding(proof_file),
        "raw_to_label_report": _binding(raw_file), "source_contract": {"schema": "fresh"},
    }
    descriptor["sha256"] = B.canonical_sha(descriptor)
    descriptor_path = _write(runtime / "product" / "descriptor.json", descriptor)
    output = tmp_path / "evaluator-v4-v2.json"
    result = A.build_request(descriptor=descriptor_path, fresh_v10_request=v10_path,
                             terminal_manifest=manifest_path, runtime_closure=closure_path,
                             output=output)
    built = json.loads(output.read_text(encoding="utf-8"))
    assert result["interpreter_mode"] == A.EXTERNAL_MODE
    assert built["execution"]["command"][0] == str(literal)
    assert built["interpreter_contract"]["literal_argv0"] == str(literal)
    assert built["interpreter_contract"]["resolved_path_provenance_only"] != str(literal)
    assert built["adapter"]["schema"].endswith("adapter.v2")


def test_strict_source_builder_binds_registry_sha_and_v2_adapter(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    roles = sorted(B.REQUIRED_RUNTIME_ROLES - {"interpreter_abi_smoke"})
    role_args: list[str] = []
    runtime_sources: list[dict] = []
    for index, role in enumerate(roles):
        if role == "python_executable":
            target = _write_bytes(runtime / "python-target", b"#!/bin/sh\n")
            target.chmod(0o755)
            literal = runtime / ".venv" / "bin" / "python"
            literal.parent.mkdir(parents=True, exist_ok=True)
            literal.symlink_to(target)
            path = literal
        else:
            path = _write_bytes(runtime / "runtime" / f"{role}-{index}.py")
        role_args.append(f"{role}={path}")
        runtime_sources.append({"role": role, "path": str(path),
                                "target_relative_path": f"runtime/{role}-{index}",
                                "sha256": _sha(path), "bytes": path.stat().st_size})
    executor = _canonical({
        "schema": "ds02.stage2.f2-portable-executor-request.v34",
        "runtime_sources": runtime_sources,
        "execution": {"raw_tree_binding": {
            "tree_sha256": B.RAW_TREE_SHA, "file_count": B.RAW_TREE_FILES,
            "frame_count": B.RAW_TREE_FRAMES,
        }},
    })
    executor_path = _write(tmp_path / "executor-strict.json", executor)
    parent = _canonical({"schema": "ds02.stage2.f2-portable-executor-parent-request.v3",
                         "static_bindings": []})
    parent_path = _write(tmp_path / "parent-strict.json", parent)
    abi_path = _write(runtime / "runtime" / "abi.json", {
        "schema": B.ABI_SMOKE_SCHEMA, "status": B.ABI_SMOKE_STATUS,
        "literal_argv0": str(literal),
    })
    output = tmp_path / "strict-closure.json"
    result = SB.build_runtime_closure(
        executor_request=executor_path, parent_request=parent_path, runtime_root=runtime,
        output=output, role_bindings=role_args, pinned_sources=[], abi_smoke=abi_path)
    closure = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == SB.CLOSURE_SCHEMA
    assert closure["source_closure"]["original_path_fallback"] == "FORBIDDEN"
    assert all(row.get("source_provenance") for row in closure["roles"]
               if row["role"] != "interpreter_abi_smoke")
    root, rows = A._validate_closure_external(output, closure)
    assert root == runtime.resolve()
    assert next(row for row in rows if row["role"] == "python_executable")["path"] == str(literal)
