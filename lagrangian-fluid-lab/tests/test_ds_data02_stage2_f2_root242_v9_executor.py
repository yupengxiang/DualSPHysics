"""Manufactured end-to-end tests for the ROOT242 V9 executor.

The fixture is deliberately tiny.  It exercises the real V9 copy/manifest,
V1 contract, V2 overlay, copied V5 subprocess, JSON validators, and scorer;
it does not open any production result, HDF5, BI4, or native input.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
V9_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v9.py"
V9_SPEC = importlib.util.spec_from_file_location("root242_v9_test_executor", V9_PATH)
assert V9_SPEC is not None and V9_SPEC.loader is not None
V9 = importlib.util.module_from_spec(V9_SPEC)
V9_SPEC.loader.exec_module(V9)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: dict) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode()).hexdigest()


def _stat(path: Path, *, follow: bool = False) -> dict[str, int]:
    item = path.stat() if follow else path.lstat()
    return {"bytes": item.st_size, "mode_bits": stat.S_IMODE(item.st_mode),
            "mtime_ns": item.st_mtime_ns, "ctime_ns": item.st_ctime_ns,
            "st_dev": item.st_dev, "st_ino": item.st_ino}


def _fixture(tmp_path: Path, *, poison: bool = False) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    runtime = source / "runtime"
    runtime.mkdir()
    result = source / "result.json"
    result.write_text(json.dumps({"schema": "fixture-result", "ok": True,
                                  "value": 7}, sort_keys=True) + "\n")
    sidecar = source / "sidecar.json"
    sidecar.write_text(json.dumps({"schema": "fixture-sidecar"}) + "\n")
    frozen = source / "frozen.json"
    frozen.write_text(json.dumps({"schema": "fixture-frozen"}) + "\n")
    current = source / "current.json"
    current.write_text(json.dumps({"schema": "fixture-current"}) + "\n")
    producer = source / "producer.json"
    producer.write_text(json.dumps({"schema": "fixture-producer"}) + "\n")
    cfg = source / "pyvenv.cfg"
    cfg.write_text("home = fixture\ninclude-system-site-packages = false\n")

    (runtime / "fixture_v8.py").write_text(
        """import hashlib, json\nfrom pathlib import Path\n\ndef _load_object(path):\n    return json.loads(Path(path).read_text())\n\ndef _validate_request(value, verify_result_stat=True):\n    item = value['result']\n    p = Path(item['path'])\n    return {'result_path': p, 'result_sha256': item['sha256'],\n            'result_bytes': int(item['bytes']), 'max_result_bytes': 1024 * 1024}\n\ndef _read_result(path, maximum):\n    raw = Path(path).read_bytes()\n    if len(raw) > maximum: raise RuntimeError('fixture result limit')\n    return json.loads(raw), hashlib.sha256(raw).hexdigest(), len(raw)\n""")
    (runtime / "fixture_v12.py").write_text(
        """_ACTIVE_SCOPE = {}\n\ndef _load_marker(path):\n    return path, {}, {}\n\ndef _validate_result_v12(result, bound, result_sha, result_bytes):\n    if result.get('ok') is not True: raise RuntimeError('fixture V12 rejected')\n    return {'fixture_validated': True, 'value': result['value']}\n""")
    (runtime / "fixture_score.py").write_text(
        """def _score_typed_result(result, frozen):\n    return {'operator_score': result['value'], 'model_invoked': False}\n""")
    for name in ("fixture_v2.py", "fixture_v3.py", "replay14.py", "replay15.py"):
        (runtime / name).write_text("# sealed fixture sibling\n")

    inner = source / "inner.json"
    inner_value = {
        "schema": "fixture-inner-v1",
        "result": {"path": str(result), "sha256": _sha(result), "bytes": result.stat().st_size},
        "v12_forward": {"semantic_sidecar": {"path": str(sidecar)}},
        "frozen": {"path": str(frozen)},
        "current": {"path": str(current)},
        "fresh_output_root": str(source / "old-output"),
        "original_roots": [str(source / "old-input")],
    }
    if poison:
        inner_value["poison"] = {"path": str(source / "unbound-original.json")}
    inner.write_text(json.dumps(inner_value, indent=2, sort_keys=True) + "\n")

    roles: list[dict] = []
    def add(name: str, path: Path, target: str, *, deferred: bool = False,
            env: bool = False) -> None:
        st = _stat(path, follow=env)
        roles.append({
            "logical_role": name, "source_kind": "fixture_deferred" if deferred else "fixture",
            "actionable": True, "source_sha256": _sha(path),
            "source_stat_provenance": st, "source_path_provenance": str(path),
            "target_relative_path": target, "deferred_content": deferred,
        })
    add("root200_inner_request", inner, "evidence/root200/inner.json")
    add("v12_semantic_sidecar", sidecar, "evidence/v12/sidecar.json")
    add("frozen_v15_request", frozen, "evidence/frozen/request.json")
    add("current336_actionable_metadata", current, "evidence/current/CURRENT336.json")
    add("root200_fresh_v12_proof", producer, "evidence/root200/fresh-proof.json")
    add("producer_nested_report_v2", producer, "evidence/producer/report.json")
    add("root200_execution_receipt", producer, "evidence/root200/receipt.json")
    add("root200_outer_wrapper", producer, "evidence/root200/wrapper.json")
    add("root200_verification_checkpoint", producer, "evidence/root200/checkpoint.json")
    add("root179c_v16_result_deferred", result, "products/v16-result.json", deferred=True)
    add("closure_271d0ebcb1b99437", result, "products/typed-result.h5", deferred=True)
    add("operator_report", producer, "evidence/producer/operator.json")
    add("pinned_project_pyvenv_cfg", cfg, "environment/pyvenv.cfg")
    add("literal_project_venv_python", Path(sys.executable), "environment/python", env=True)
    add("typed_only_portable_rebind_v1", SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v1.py", "runtime/ds_data02_stage2_f2_typed_only_portable_rebind_v1.py")
    add("portable_rebind_v2_core", SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py", "runtime/ds_data02_stage2_f2_typed_only_portable_rebind_v2.py")
    add("portable_rebind_v2_entrypoint", SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v5.py", "runtime/ds_data02_stage2_f2_typed_only_portable_rebind_v5.py")
    add("fresh_v16_proof_consumer_v8", runtime / "fixture_v8.py", "runtime/fresh_v16_proof_consumer_v8.py")
    add("fresh_v16_proof_consumer_v12", runtime / "fixture_v12.py", "runtime/fresh_v16_proof_consumer_v12.py")
    add("typed_only_evaluator_v1", runtime / "fixture_score.py", "runtime/typed_only_evaluator_v1.py")
    add("typed_only_evaluator_v2", runtime / "fixture_v2.py", "runtime/typed_only_evaluator_v2.py")
    add("typed_only_evaluator_v3", runtime / "fixture_v3.py", "runtime/typed_only_evaluator_v3.py")
    add("replay_v14", runtime / "replay14.py", "runtime/replay_v14.py")
    add("replay_v15", runtime / "replay15.py", "runtime/replay_v15.py")
    add("root191_v1_binding", runtime / "fixture_v2.py", "runtime/root191_v1_binding.py")
    add("root191_v2_binding", runtime / "fixture_v2.py", "runtime/root191_v2_binding.py")
    add("root191_v3_entrypoint", runtime / "fixture_v2.py", "runtime/root191_v3_entrypoint.py")
    add("root191_v4_hardened_entrypoint", runtime / "fixture_v2.py", "runtime/root191_v4_hardened_entrypoint.py")
    add("flux_v16_source_contract", runtime / "fixture_v2.py", "runtime/flux.py")
    add("v8_executor", runtime / "fixture_v2.py", "runtime/v8_executor.py")
    add("v9_executor", V9_PATH, "runtime/ds_data02_stage2_f2_root242_portable_typed_executor_v9.py")
    for index in range(15):
        filler = runtime / f"filler{index}.json"
        filler.write_text(json.dumps({"role": index}) + "\n")
        add(f"filler_{index}", filler, f"evidence/filler/{index}.json")
    roles.sort(key=lambda item: item["logical_role"])
    roles_digest = hashlib.sha256(json.dumps(roles, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    contract = {
        "schema": "ds02.stage2.f2-root213-portable-typed-parent-request.v1",
        "status": "READY_FOR_PARENT_STAGE2_GUARD_V9",
        "root242_source_binding": {"schema": "ds02.stage2.f2-root242-v9-single-case-source-binding.v1",
                                    "roles": roles, "selected_roles_sha256": roles_digest},
        "v2_interface": {"literal_python": str(Path(sys.executable))},
    }
    contract["sha256"] = _canonical(contract)
    contract_path = tmp_path / "outer-contract.json"
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    fresh = tmp_path / "fresh"
    request = {
        "schema": "ds02.request.v1", "case_id": "fixture-case",
        "attempt_id": "fixture-attempt", "root213_metadata_contract": {
            "path": str(contract_path), "sha256": contract["sha256"]},
        "interpreter_binding": {"argv0_literal": True, "do_not_resolve_argv0": True,
                                 "invocation_path": str(Path(sys.executable))},
        "root242_v9_source_binding": {"schema": "ds02.stage2.f2-root242-v9-single-case-source-binding.v1",
                                      "selected_roles_sha256": roles_digest},
        "storage_scope": {"external_filesystem": str(fresh)},
        "scope": {"original_path_fallback": "REJECT"},
    }
    request["sha256"] = _canonical(request)
    request_path = tmp_path / "outer-request.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
    return request_path, contract_path, fresh


def test_v9_real_copy_overlay_worker_and_scorer(tmp_path: Path) -> None:
    request, contract, fresh = _fixture(tmp_path)
    code = (
        "import importlib.util,os,sys; "
        "s=importlib.util.spec_from_file_location('v9child',sys.argv[1]); "
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m); "
        "m.run(request=sys.argv[2],output_root=sys.argv[3],parent_pid=int(sys.argv[4]),max_wall_seconds=30)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(V9_PATH), str(request), str(fresh), str(os.getpid())],
        text=True, capture_output=True, timeout=45)
    assert completed.returncode == 0, completed.stderr
    report = json.loads((fresh / "reports/root242-v9-executor-report.json").read_text())
    assert report["status"] == "COMPLETE_RELOCATED_V9_V8_V12_TYPED_SCORER"
    assert report["execution"]["v8_validator"] is True
    assert report["execution"]["v12_validator"] is True
    assert report["execution"]["typed_scorer"] is True
    assert report["execution"]["original_path_fallback"] == "REJECT"
    assert report["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert (fresh / "reports/v2-worker-report.json").is_file()


def test_v9_rejects_unbound_original_path(tmp_path: Path) -> None:
    request, contract, fresh = _fixture(tmp_path, poison=True)
    code = (
        "import importlib.util,sys; "
        "s=importlib.util.spec_from_file_location('v9child',sys.argv[1]); "
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m); "
        "m.run(request=sys.argv[2],output_root=sys.argv[3],parent_pid=int(sys.argv[4]),max_wall_seconds=30)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(V9_PATH), str(request), str(fresh), str(os.getpid())],
        text=True, capture_output=True, timeout=45)
    assert completed.returncode != 0
    assert "unbound actionable" in completed.stderr


def test_v9_rejects_bound_source_stat_change(tmp_path: Path) -> None:
    request, contract, fresh = _fixture(tmp_path)
    # The request binds the original inner-request bytes/stat.  A changed
    # source must fail before any child worker or semantic scorer starts.
    inner = tmp_path / "source/inner.json"
    inner.write_text(inner.read_text() + "\n")
    code = (
        "import importlib.util,sys; "
        "s=importlib.util.spec_from_file_location('v9child',sys.argv[1]); "
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m); "
        "m.run(request=sys.argv[2],output_root=sys.argv[3],parent_pid=int(sys.argv[4]),max_wall_seconds=30)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(V9_PATH), str(request), str(fresh), str(os.getpid())],
        text=True, capture_output=True, timeout=45)
    assert completed.returncode != 0
    assert "source byte stat differs before copy" in completed.stderr


def test_v9_bounded_pipe_drain_and_owned_timeout_cleanup(tmp_path: Path) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import sys,time; sys.stdout.write('x'*5000000); sys.stdout.flush(); time.sleep(5)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    rc, info = V9._drain_child(
        child, deadline=time.monotonic() + 0.3,
        stdout_path=tmp_path / "stdout.tail", stderr_path=tmp_path / "stderr.tail")
    assert info["timed_out"] is True
    assert info["stdout_bytes"] >= 4 * 1024 * 1024
    assert info["stdout_tail_bytes"] <= V9.ROLLING_TAIL_BYTES
    assert child.poll() is not None
    assert rc != 0
