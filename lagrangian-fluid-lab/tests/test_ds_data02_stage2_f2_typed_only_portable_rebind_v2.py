"""Metadata-only V2 request rebinding and bounded copied-runtime tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
V1_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_portable_rebind_v1.py"
V2_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
V8_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V12_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"
SCORE_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_v1.py"
FROZEN_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_replay_v15.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load(V1_SCRIPT, "portable_rebind_v1_v2_test")
V2 = _load(V2_SCRIPT, "portable_rebind_v2_test")


def _artifact(source: Path, role: str, target: str, *, kind: str = "runtime_source") -> dict:
    return {
        "logical_role": role, "source_kind": kind,
        "source_path_provenance": str(source), "source_sha256": V1._sha(source),
        "source_sha256_basis": "test_bounded_source", "source_stat_provenance": V1._stat(source),
        "target_relative_path": target, "actionable": True, "content_read_by_manifest": True,
    }


def _manifest(tmp_path: Path, source: Path, request: Path, current: Path,
              result: Path, frozen: Path, pyvenv: Path, python_copy: Path,
              sidecar: Path, nested: Path) -> Path:
    roles = [
        _artifact(request, "root200_inner_request", "evidence/root200/inner.json", kind="bounded_evidence"),
        _artifact(current, "current336_actionable_metadata", "evidence/current/CURRENT.json", kind="bounded_evidence"),
        _artifact(result, "root179c_typed_result_deferred", "products/result.json", kind="deferred_result_json"),
        _artifact(frozen, "frozen_v15_request", "evidence/frozen-v15/request.json", kind="bounded_evidence"),
        _artifact(pyvenv, "pinned_project_pyvenv_cfg", "environment/pyvenv.cfg", kind="external_environment"),
        _artifact(python_copy, "literal_project_venv_python", "environment/python", kind="external_environment_exception"),
        _artifact(sidecar, "v12_semantic_sidecar", "evidence/v12/semantic-sidecar.json", kind="bounded_evidence"),
        _artifact(nested, "producer_nested_report_v2", "evidence/v12/producer-report.json", kind="bounded_evidence"),
    ]
    for script, role in ((V2_SCRIPT, "portable_rebind_v2_entrypoint"),
                         (V8_SCRIPT, "fresh_v16_proof_consumer_v8"),
                         (V12_SCRIPT, "fresh_v16_proof_consumer_v12"),
                         (SCORE_SCRIPT, "typed_only_evaluator_v1"),
                         (ROOT / "scripts/ds_data02_stage2_f2_no_model_evaluator_v3.py", "typed_only_evaluator_v3"),
                         (ROOT / "scripts/ds_data02_stage2_f2_no_model_evaluator_v2.py", "typed_only_evaluator_v2"),
                         (ROOT / "scripts/ds_data02_stage2_f2_replay_v14.py", "replay_v14"),
                         (FROZEN_SCRIPT, "replay_v15")):
        roles.append(_artifact(script, role, f"runtime/{script.name}"))
    loading = {
        "entrypoint_logical_role": "fresh_v16_proof_consumer_v8",
        "entrypoint_target_relative_path": f"runtime/{V8_SCRIPT.name}",
        "request_target_relative_path": "evidence/root200/inner.json",
        "frozen_v15_target_relative_path": "evidence/frozen-v15/request.json",
        "current_target_relative_path": "evidence/current/CURRENT.json",
        "result_target_relative_path": "products/result.json",
        "typed_h5_target_relative_path": "products/result.h5",
        "fresh_proof_target_relative_path": "reports/proof.json",
        "operator_report_target_relative_path": "reports/operator.json",
        "runtime_sibling_directory": "runtime", "source_fallback": "REJECT",
        "no_model": True, "model_invoked": False,
    }
    value = {"schema": V1.MANIFEST_SCHEMA, "status": "PORTABLE_TYPED_ONLY_DEPENDENCY_AUDIT_METADATA_COMPLETE",
             "artifacts": roles, "portable_loading_entry": loading,
             "path_policy": {"original_absolute_path_fallback": "REJECT"}}
    value["sha256"] = V1._canonical(value)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixture(tmp_path: Path):
    source = tmp_path / "original-source"
    source.mkdir()
    current = source / "CURRENT.json"
    result = source / "result.json"
    frozen = source / "frozen-v15.json"
    pyvenv = source / "pyvenv.cfg"
    python_copy = source / "python"
    current.write_text("{\"catalog\":\"fixture\"}\n", encoding="utf-8")
    result.write_text("{\"fixture_result\":true}\n", encoding="utf-8")
    frozen.write_text("{\"fixture_frozen\":true}\n", encoding="utf-8")
    pyvenv.write_text("home = /fixture\ninclude-system-site-packages = false\n", encoding="utf-8")
    shutil.copyfile(sys.executable, python_copy)
    sidecar = source / "semantic-sidecar.json"
    nested = source / "producer-report.json"
    sidecar.write_text("{\"schema\":\"fixture.sidecar.v1\"}\n", encoding="utf-8")
    nested.write_text("{\"schema\":\"fixture.producer.v2\"}\n", encoding="utf-8")
    request = source / "inner.json"
    request_value = {
        "schema": "fixture.inner.v2", "sha256": "",
        "result": {"path": str(result), "sha256": hashlib.sha256(result.read_bytes()).hexdigest(),
                   "bytes": result.stat().st_size,
                   "stat": {"bytes": result.stat().st_size, "mtime_ns": result.stat().st_mtime_ns}},
        "current_manifest_binding": {"path": str(current), "sha256": hashlib.sha256(current.read_bytes()).hexdigest()},
        "source_frozen_request": {"path": str(frozen), "sha256": hashlib.sha256(frozen.read_bytes()).hexdigest()},
        "relocation": {"target_root": str(source / "old-runtime"), "output_root": str(source / "old-products"),
                        "original_roots": [str(source)]},
        "fresh_output_namespace": {"root": str(source / "old-reports")},
    }
    request_value["sha256"] = V1._canonical(request_value)
    request.write_text(json.dumps(request_value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = _manifest(tmp_path, source, request, current, result, frozen, pyvenv, python_copy,
                         sidecar, nested)
    relocated = tmp_path / "relocated"
    contract_path = tmp_path / "contract.json"
    contract = V1.build_contract(manifest_path=manifest, relocated_root=relocated,
                                 output=contract_path, contract_id="v2-fixture")
    for role in contract["roles"]:
        target = relocated / role["target_relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        source_path = Path(role["source_path_provenance"])
        shutil.copyfile(source_path, target)
    return contract_path, relocated, request, result


def test_v2_rebases_nested_actionable_paths_without_original_files(tmp_path: Path):
    contract_path, relocated, _request, _result = _fixture(tmp_path)
    output = tmp_path / "v2-request.json"
    built = V2.build_request_overlay(
        contract_path=contract_path, request_role="root200_inner_request", output=output,
        request_target_relative="requests/rebound-inner.json", request_id="ROOT191_V2_FIXTURE")
    assert built["status"] == "PENDING_PARENT_RELOCATION_TARGETS"
    request = json.loads(output.read_text(encoding="utf-8"))
    generated = relocated / "requests/rebound-inner.json"
    assert generated.is_file()
    inner = json.loads(generated.read_text(encoding="utf-8"))
    assert str(relocated / "products/result.json") == inner["result"]["path"]
    assert str(relocated / "evidence/current/CURRENT.json") == inner["current_manifest_binding"]["path"]
    assert str(relocated / "runtime") == inner["relocation"]["target_root"]
    assert str(relocated / "products") == inner["relocation"]["output_root"]
    assert str(relocated / "reports") == inner["fresh_output_namespace"]["root"]
    assert inner["relocation"]["original_roots"] == [str(tmp_path / "original-source")]
    shutil.rmtree(tmp_path / "original-source")
    checked = V2.validate_request_overlay(output)
    assert checked["payload_read"] is False
    assert checked["request"]["path_policy"]["original_absolute_path_fallback"] == "REJECT"


def test_v2_rejects_unregistered_nested_absolute_path(tmp_path: Path):
    contract_path, relocated, _request, _result = _fixture(tmp_path)
    output = tmp_path / "v2-request.json"
    V2.build_request_overlay(contract_path=contract_path, request_role="root200_inner_request",
                             output=output, request_target_relative="requests/rebound-inner.json",
                             request_id="ROOT191_V2_FIXTURE")
    value = json.loads(output.read_text(encoding="utf-8"))
    generated = relocated / "requests/rebound-inner.json"
    inner = json.loads(generated.read_text(encoding="utf-8"))
    inner["result"]["path"] = "/forbidden/original/result.json"
    # The generated request's own binding is changed too, so validation must
    # fail on the recursive path closure rather than silently using provenance.
    generated.write_text(json.dumps(inner, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(V2.PortableRebindV2Error, match="generated request target SHA differs|escapes|unregistered"):
        V2.validate_request_overlay(output)


def test_v2_bounded_stream_keeps_tail_and_reaps_child(tmp_path: Path):
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    child = subprocess.Popen([
        sys.executable, "-c",
        "import sys; sys.stdout.write('x'*5000000); sys.stderr.write('e'*1000000)",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    code, info = V2._drain_child(child, max_wall=10.0, stdout_path=stdout, stderr_path=stderr)
    assert code == 0
    assert info["stdout_bytes"] == 5_000_000
    assert info["stderr_bytes"] == 1_000_000
    assert info["stdout_tail_bytes"] <= V2.ROLLING_TAIL_BYTES
    assert info["stderr_tail_bytes"] <= V2.ROLLING_TAIL_BYTES
