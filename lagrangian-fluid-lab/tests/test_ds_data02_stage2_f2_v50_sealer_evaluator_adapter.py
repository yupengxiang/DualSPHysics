"""Bounded metadata tests for the V50 sealer/evaluator hand-off."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SEALER_PATH = SCRIPTS / "ds_data02_stage2_f2_v50_terminal_sealer_v2.py"
ADAPTER_PATH = SCRIPTS / "ds_data02_stage2_f2_evaluator_v4_adapter_v1.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = _load(SEALER_PATH, "test_v50_sealer_v2")
A = _load(ADAPTER_PATH, "test_evaluator_v4_adapter_v1")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _binding(path: Path) -> dict:
    return {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size,
            "stat": {"bytes": path.stat().st_size,
                     "mtime_ns": path.stat().st_mtime_ns,
                     "mode_bits": path.stat().st_mode & 0o777}}


def test_v50_static_receipt_rejects_pre_reservation(tmp_path: Path) -> None:
    executor = _write(tmp_path / "executor.json", {})
    parent = _write(tmp_path / "parent.json", {})
    receipt = _write(tmp_path / "static.json", {
        "schema": S.STATIC_RECEIPT_SCHEMA,
        "status": S.STATIC_RECEIPT_STATUS,
        "phase": "BEFORE_ATOMIC_PARENT_RESERVATION",
        "static_content_verified": True,
        "request": str(parent), "executor": str(executor),
        "request_file_sha256": _sha(parent), "executor_file_sha256": _sha(executor),
        "same_parent_ledger": True, "verified_source_hashes": {"code": "a" * 64},
    })
    with pytest.raises(S.SealerV50Error, match="after-reservation PASS"):
        S._verify_static_receipt(
            receipt, executor_path=executor, parent_path=parent,
            parent_summary={"binding": {"physical_sha256": _sha(parent),
                                          "attempt_id": "a", "charge_id": "c"}})


def test_evaluator_v4_adapter_uses_relocated_v15_and_explicit_closure(tmp_path: Path) -> None:
    runtime = tmp_path / "private-runtime"
    roles = sorted(A.REQUIRED_CLOSURE_ROLES)
    role_rows = []
    for index, role in enumerate(roles):
        path = runtime / f"{role}-{index}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# metadata fixture\n", encoding="utf-8")
        role_rows.append({"role": role, **_binding(path)})
    closure = {
        "schema": A.CLOSURE_SCHEMA, "status": A.CLOSURE_STATUS,
        "runtime_root": str(runtime), "original_path_fallback": "FORBIDDEN",
        "roles": role_rows,
    }
    closure["sha256"] = A.canonical_sha(closure)
    closure_path = _write(tmp_path / "closure.json", closure)

    result_file = _write(tmp_path / "fresh-v16.json", {"schema": "placeholder"})
    proof_file = _write(tmp_path / "proof.json", {"schema": "placeholder"})
    raw_file = _write(tmp_path / "raw-report.json", {"schema": "placeholder"})
    v15_file = _write(tmp_path / "relocated-v15.json", {
        "schema": "ds02.stage2.f2-s1-replay-request.v15",
        "source_files": [], "current_binding": {}, "trajectory_h5": {},
        "cohort": {}, "case_identity": {}, "observer_profile": {},
    })
    manifest = {"artifacts": {"relocated_v15_request": _binding(v15_file)}}
    manifest["sha256"] = A.canonical_sha(manifest)
    manifest_path = _write(tmp_path / "manifest.json", manifest)

    v10 = {
        "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8",
        "status": "READY_FOR_PARENT_GUARD", "qualification": dict(A.UNKNOWN),
        "execution": {"original_path_fallback": "FORBIDDEN"},
        "result": {**_binding(result_file), "schema": "ds02.stage2.f2-s1-replay-result.v16"},
        "source_contract": {"schema": "fresh"},
    }
    v10["sha256"] = A.canonical_sha(v10)
    v10_path = _write(tmp_path / "fresh-v10.json", v10)

    descriptor = {
        "schema": "ds02.stage2.f2-v47-fresh-no-model-evaluator-request.v1",
        "status": "READY_FOR_PARENT_EVALUATOR_GUARD",
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(A.UNKNOWN),
        "target_evaluator_schema": A.REQUEST_SCHEMA,
        "source_identity": {"historical_overlay_input_policy": "FORBIDDEN; provenance only"},
        "fresh_v10_request": {"path": str(v10_path), "sha256": v10["sha256"]},
        "fresh_v10_proof": _binding(proof_file),
        "raw_to_label_report": _binding(raw_file),
        "source_contract": {"schema": "fresh"},
    }
    descriptor["sha256"] = A.canonical_sha(descriptor)
    descriptor_path = _write(tmp_path / "descriptor.json", descriptor)
    output = tmp_path / "evaluator-v4.json"
    result = A.build_request(descriptor=descriptor_path, fresh_v10_request=v10_path,
                             terminal_manifest=manifest_path, runtime_closure=closure_path,
                             output=output)
    built = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == A.REQUEST_SCHEMA
    assert built["schema"] == A.REQUEST_SCHEMA
    assert built["frozen_request"]["path"] == str(v15_file)
    assert built["execution"]["original_path_fallback"] == "FORBIDDEN"
    assert built["adapter"]["relocated_v15_request_used"] is True


def test_evaluator_v4_adapter_consumes_immutable_v50_seal_and_fresh_proof(tmp_path: Path) -> None:
    """The post-terminal path must use V50 seal+proof, not a V47 descriptor."""
    runtime = tmp_path / "private-runtime"
    rows = []
    for index, role in enumerate(sorted(A.REQUIRED_CLOSURE_ROLES)):
        path = runtime / f"{role}-{index}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# bounded fixture\n", encoding="utf-8")
        rows.append({"role": role, **_binding(path)})
    closure = {"schema": A.CLOSURE_SCHEMA, "status": A.CLOSURE_STATUS,
               "runtime_root": str(runtime), "original_path_fallback": "FORBIDDEN",
               "roles": rows}
    closure["sha256"] = A.canonical_sha(closure)
    closure_path = _write(tmp_path / "closure.json", closure)

    result_file = _write(tmp_path / "fresh-v16.json", {"schema": "placeholder"})
    raw_file = _write(tmp_path / "raw-report.json", {"schema": "placeholder"})
    v15_file = _write(tmp_path / "relocated-v15.json", {
        "schema": "ds02.stage2.f2-s1-replay-request.v15", "source_files": [],
        "current_binding": {}, "trajectory_h5": {}, "cohort": {},
        "case_identity": {}, "observer_profile": {},
    })
    manifest = {"artifacts": {"relocated_v15_request": _binding(v15_file)}}
    manifest["sha256"] = A.canonical_sha(manifest)
    manifest_path = _write(tmp_path / "manifest.json", manifest)

    relocated = "c" * 64
    v10 = {
        "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8",
        "status": "READY_FOR_PARENT_GUARD", "qualification": dict(A.UNKNOWN),
        "execution": {"original_path_fallback": "FORBIDDEN"},
        "result": {**_binding(result_file), "schema": "ds02.stage2.f2-s1-replay-result.v16"},
        "source_contract": {"schema": "fresh"},
        "expected": {"source_binding": {"current_catalog_sha256": relocated}},
        "v11_forward": {"actual_current_catalog_sha256": S.ACTUAL_CURRENT_SHA if hasattr(S, "ACTUAL_CURRENT_SHA") else "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"},
    }
    v10["sha256"] = A.canonical_sha(v10)
    v10_path = _write(tmp_path / "fresh-v10.json", v10)
    proof = {
        "schema": A.V10_PROOF_SCHEMA, "status": A.V10_PROOF_STATUS,
        "quality": dict(A.UNKNOWN), "qualification": dict(A.UNKNOWN),
        "source_result": {"path": str(result_file), "sha256": _sha(result_file),
                           "content_sha_verified": True},
        "source_binding": {"current_catalog_sha256": relocated,
                            "original_current_catalog_sha256": "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"},
        "parent_guard": {"supplied": True},
    }
    proof["sha256"] = A.canonical_sha(proof)
    proof_path = _write(tmp_path / "fresh-proof.json", proof)
    producer = {"schema": "ds02.stage2.f2-s1-typed-label-only-report.v1",
                "raw_to_label_report": _binding(raw_file)}
    producer["sha256"] = A.canonical_sha(producer)
    producer_path = _write(tmp_path / "producer-adapter.json", producer)
    seal = {
        "schema": "ds02.stage2.f2-v50-producer-terminal-seal.v2",
        "status": "READY_FOR_PARENT_V10_SEMANTIC_GUARD_V2",
        "v10_request": {"path": str(v10_path), "sha256": v10["sha256"]},
        "producer_adapter": {"path": str(producer_path), "sha256": _sha(producer_path)},
        "source_identity": {"actual_current_catalog_sha256": "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b",
                            "relocated_runtime_view_sha256": relocated},
        "fresh_v10_semantic_proof": {"old_root060_reuse": "FORBIDDEN"},
    }
    seal["sha256"] = A.canonical_sha(seal)
    seal_path = _write(tmp_path / "v50-seal.json", seal)

    output = tmp_path / "evaluator-v4-from-v50.json"
    result = A.build_request(v50_seal=seal_path, fresh_v10_request=v10_path,
                             fresh_proof=proof_path, terminal_manifest=manifest_path,
                             runtime_closure=closure_path, output=output)
    built = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == A.REQUEST_SCHEMA
    assert built["adapter"]["descriptor_schema"] == A.DESCRIPTOR_SCHEMA
    assert built["v50_producer_descriptor"]["binding_kind"] == "v50_terminal_seal_transformed_descriptor"
    assert built["independent_proof"]["path"] == str(proof_path)
