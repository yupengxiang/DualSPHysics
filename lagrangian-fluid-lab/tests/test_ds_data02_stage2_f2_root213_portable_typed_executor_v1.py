"""Real ROOT213 executor coverage on an isolated manufactured V16 product.

The fixture is deliberately separate from the production ROOT200/V16 files.
It runs the executor as a directly supervised subprocess, then lets the
copied V2 process load copied V8, V12, V15/replay, and model-free scorer
modules.  This proves the executor is an executable handoff rather than a
metadata-only builder without reading any production payload.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REAL_V2_TEST = ROOT / "tests" / "test_ds_data02_stage2_f2_typed_only_portable_rebind_v2_real.py"
BUILDER_SCRIPT = SCRIPTS / "ds_data02_stage2_f2_root213_portable_typed_parent_v1.py"
EXECUTOR_SCRIPT = SCRIPTS / "ds_data02_stage2_f2_root213_portable_typed_executor_v1.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"bytes": value.st_size, "mode_bits": value.st_mode & 0o7777,
            "mtime_ns": value.st_mtime_ns, "ctime_ns": value.st_ctime_ns,
            "st_dev": value.st_dev, "st_ino": value.st_ino}


def _binding(path: Path, *, schema: str | None = None,
             canonical_sha256: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {"path": str(path), "file_sha256": _sha(path)}
    if schema is not None:
        result["schema"] = schema
    if canonical_sha256 is not None:
        result["canonical_sha256"] = canonical_sha256
    return result


def _root191_from_real_fixture(base: Path, real, builder) -> Path:
    """Build a real ROOT191-shaped input around the existing V2 fixture."""
    source = base / "source"
    inner_path = source / "inner.json"
    inner = json.loads(inner_path.read_text(encoding="utf-8"))
    result = source / "result.json"
    frozen = source / "frozen.json"

    def write_json(name: str, value: dict[str, object]) -> Path:
        path = source / name
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        return path

    wrapper = write_json("root200-wrapper.json", {"schema": "fixture.root200.wrapper.v1"})
    receipt = write_json("root200-receipt.json", {"schema": "fixture.root200.receipt.v1", "status": "COMPLETE"})
    checkpoint = write_json("root200-checkpoint.json", {"schema": "fixture.root200.checkpoint.v1", "status": "PASS"})
    proof = write_json("root200-proof.json", {"schema": "ds02.stage2.f2-fresh-v16-proof.v8", "status": "PASS"})
    producer_request = write_json("producer-request.json", {"schema": "fixture.producer.request.v1"})
    producer_receipt = write_json("producer-receipt.json", {"schema": "fixture.producer.receipt.v1", "status": "COMPLETE"})
    producer_report = write_json("producer-report.json", {"schema": "fixture.producer.report.v1", "status": "COMPLETE"})
    producer_proof = write_json("producer-proof.json", {"schema": "fixture.producer.proof.v1", "status": "PASS"})
    trajectory = source / "trajectory.h5"
    trajectory.write_bytes(b"fixture stat-only typed H5 placeholder\n")

    # The old V2 test has already made a patched V12 source and a copied V8
    # source in the fixture.  All other code roles are copied from the source
    # checkout into the executor's private runtime by its own contract.
    v12_copy = source / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"
    v8_copy = source / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
    runtime_specs = [
        ("fresh_v16_proof_consumer_v8", v8_copy),
        ("fresh_v16_proof_consumer_v12", v12_copy),
        ("typed_only_evaluator_v1", SCRIPTS / "ds_data02_stage2_f2_typed_only_evaluator_v1.py"),
        ("typed_only_evaluator_v3", SCRIPTS / "ds_data02_stage2_f2_no_model_evaluator_v3.py"),
        ("typed_only_evaluator_v2", SCRIPTS / "ds_data02_stage2_f2_no_model_evaluator_v2.py"),
        ("replay_v14", SCRIPTS / "ds_data02_stage2_f2_replay_v14.py"),
        ("replay_v15", SCRIPTS / "ds_data02_stage2_f2_replay_v15.py"),
    ]
    roles = [{"role": role, "path": str(path), "sha256": _sha(path)}
             for role, path in runtime_specs]
    closure = {
        "schema": "fixture.root191.runtime-closure.v1",
        "import_mode": "PRIVATE_COPIED_RUNTIME",
        "original_worktree_fallback": "FORBIDDEN",
        "preferred_entrypoint": "fresh_v16_proof_consumer_v8.py",
        "roles": roles,
        "literal_interpreter": {
            "invocation_path": str(source / "python"),
            "do_not_resolve_argv0": True,
            "pyvenv_cfg": {"path": str(source / "pyvenv.cfg"),
                            "sha256": _sha(source / "pyvenv.cfg")},
        },
    }
    root200 = {
        "inner_request": _binding(inner_path, schema=builder.ROOT200_INNER_SCHEMA,
                                   canonical_sha256=inner["sha256"]),
        "outer_wrapper": _binding(wrapper),
        "completed_execution_receipt": _binding(receipt),
        "actual_verification_checkpoint": _binding(checkpoint),
        "fresh_v12_proof": _binding(proof),
        "result": {"path": str(result), "sha256": _sha(result),
                   "bytes": result.stat().st_size, "stat": _stat(result)},
        "typed_h5": {"path": str(trajectory), "sha256": "c" * 64,
                      "bytes": trajectory.stat().st_size},
    }
    producer = {
        "request": _binding(producer_request),
        "completed_receipt": _binding(producer_receipt),
        "parent_report": _binding(producer_report),
        "root_proof": _binding(producer_proof),
        "same_source_case": "fixture-179c",
    }
    root191 = {
        "schema": builder.ROOT191_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "product_mode": "TYPED_ONLY_LABELS",
        "model_invoked": False,
        "cfd_invoked": False,
        "ledger_mutated": False,
        "old_proof_reuse": False,
        "fresh_cold_credit": False,
        "qualification": dict(builder.UNKNOWN),
        "quality": dict(builder.UNKNOWN),
        "execution": {"raw_opened": False, "read_hdf5_or_bi4": False},
        "root191_primary_builder": {"runtime_closure": closure},
        "root200_binding": root200,
        "producer_179c_binding": producer,
        "source_frozen_request": {"path": str(frozen), "file_sha256": _sha(frozen),
                                   "schema": builder.V15_SCHEMA},
    }
    root191["sha256"] = builder._canonical(root191)
    path = base / "root191.json"
    path.write_text(json.dumps(root191, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_root213_executor_runs_real_private_v8_v12_scorer(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch):
    """Run the additive executor against the existing real isolated fixture."""
    real = _load(REAL_V2_TEST, "root213_real_v2_fixture")
    builder = _load(BUILDER_SCRIPT, "root213_builder_executor_test")

    # The existing V2 test intentionally removes its fixture source before
    # launching its child.  Keep that source long enough to build/copy a
    # second, independently sealed ROOT213 bundle; the executor subprocess
    # itself still runs only copied runtime files.
    monkeypatch.setattr(real.shutil, "rmtree", lambda _path: None)
    original_guard = real.V2.run_guard
    executor_result: dict[str, object] = {}

    def guarded_v2(*args, **kwargs):
        first = original_guard(*args, **kwargs)
        overlay = Path(kwargs["request_path"])
        base = overlay.parent
        root191 = _root191_from_real_fixture(base, real, builder)
        request_path = base / "root213.json"
        builder.build_request(root191_request=root191, output=request_path,
                              fresh_output_root=base / "executor-root",
                              case_id="ROOT213-REAL-FIXTURE",
                              attempt_id="f2-s1-root213-real-fixture-root-forward-030-001")
        command = [sys.executable, str(EXECUTOR_SCRIPT), "run",
                   "--request", str(request_path),
                   "--output-root", str(base / "executor-root"),
                   "--parent-pid", str(os.getpid()), "--max-wall-seconds", "180"]
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=240, check=False)
        if completed.returncode != 0:
            raise AssertionError(f"ROOT213 executor failed\nstdout={completed.stdout}\nstderr={completed.stderr}")
        executor_result.update(json.loads(completed.stdout))
        report_path = base / "executor-root" / "reports" / "root213-executor-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == "COMPLETE_ROOT213_TYPED_ONLY_PORTABLE_EXECUTOR"
        assert report["v2_report_status"] == "PASS_RELOCATED_V8_V12_TYPED_SCORER"
        assert report["execution"]["model_invoked"] is False
        assert report["execution"]["hdf5_or_bi4_content_read"] is False
        assert report["execution"]["original_path_fallback"] == "REJECT"
        assert all(Path(item["target_relative_path"]).is_absolute() is False
                   for item in report["copy_contract"]["roles"])
        result_roles = [item for item in report["copy_contract"]["roles"]
                        if item["logical_role"] == "root179c_v16_result_deferred"]
        assert len(result_roles) == 1
        result_role = result_roles[0]
        assert result_role["deferred_payload"] is True
        assert result_role["source_pre_sha256"] == result_role["source_post_sha256"]
        assert result_role["source_pre_sha256"] == result_role["target_sha256"]
        assert result_role["source_pre_stat"] == result_role["source_post_stat"]
        return first

    monkeypatch.setattr(real.V2, "run_guard", guarded_v2)
    real.test_v2_real_relocated_v8_v12_typed_scorer_without_source(tmp_path)
    assert executor_result["status"] == "COMPLETE_ROOT213_TYPED_ONLY_PORTABLE_EXECUTOR"
