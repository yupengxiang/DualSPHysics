"""CPU fake workers only; real budgets, inventory and GPU probes are forbidden."""

from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import f3_training_runner as training
from scripts import l1r_q2_mdbc_bridge as q2


def forbidden(*args, **kwargs):
    raise AssertionError("test attempted a real resource/GPU lookup")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    out = tmp_path / "continuation"
    out.mkdir()
    monkeypatch.setattr(training, "LAB", tmp_path)
    monkeypatch.setattr(training, "OUT", out)
    monkeypatch.setattr(training, "TRAINING_ROOT", tmp_path / "training-attempts")
    monkeypatch.setattr(training, "_shared_budget", forbidden)
    monkeypatch.setattr(training, "_gpu_snapshot", forbidden)
    monkeypatch.setattr(training, "_assert_no_solver", forbidden)
    monkeypatch.setattr(q2, "allowed_gpu_uuids", forbidden)


def bind(path, content):
    path.write_text(json.dumps(content))
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def contracts(tmp_path):
    return {
        "qualification_contract": bind(tmp_path / "domain.json", {
            "schema": "f3.nopen.domain_gate.v1", "status": "passed", "stage": "domain",
            "evidence_sha256": {"fixture": "a" * 64},
        }),
        "development_contract": bind(tmp_path / "development.json", {
            "schema": "f3.training.development_data.v1", "qualified_sources": True,
            "completed_case_ids": ["fixture-only"],
        }),
    }


def write_attempt(execution, *, logical="model", status="completed", elapsed=10.0,
                  timeout=100.0, cpu_cores=1, contracts=None):
    suffix = {"running": "partial", "completed": "complete", "failed": "failed"}[status]
    directory = training.TRAINING_ROOT / logical / f"{execution}.{suffix}"
    directory.mkdir(parents=True)
    record = {
        "schema": training.ATTEMPT_SCHEMA, "resource_category": "training",
        "logical_run_id": logical, "execution_attempt_id": execution, "status": status,
        "elapsed_seconds": None if status == "running" else elapsed,
        "timeout_seconds": timeout, "cpu_cores": cpu_cores, "gpu_index": 4,
        "gpu_uuid": "GPU-fixture-4", **training._reservation(timeout, cpu_cores),
        **(contracts or {}),
    }
    path = directory / "attempt.json"
    path.write_text(json.dumps(record))
    return path


def shared_budget(usage, *, cpu_base=2.0, gpu_base=1.0, **limits):
    return {
        "shared_training_accounting_version": training.ACCOUNTING_VERSION,
        "gpu_solver_budget_charge_hours": gpu_base,
        "cpu_base_core_hours_upper_bound": cpu_base,
        "gpu_budget_charge_hours": gpu_base + usage["gpu_budget_charge_hours"],
        "cpu_core_hours_upper_bound": cpu_base + usage["cpu_core_hours_upper_bound"],
        "limits": {"gpu_hours": 64, "cpu_core_hours": 768, "training": 12,
                   "qualification": 72, "development": 40, **limits},
        "conservative_expiry_utc": "2099-01-01T00:00:00+00:00",
    }


@pytest.fixture
def cpu_worker(monkeypatch):
    # This private gate replacement is local to these tests. The public launcher
    # has no bypass flag; these synthetic contracts establish no data qualification.
    monkeypatch.setattr(training, "_require_production_contracts", lambda *args: None)
    monkeypatch.setattr(training, "_assert_no_solver", lambda: None)
    monkeypatch.setattr(training, "_gpu_snapshot", lambda *args: [{
        "index": 4, "uuid": "GPU-fixture-4", "memory_free_mib": 20000,
        "memory_total_mib": 24000, "memory_used_mib": 4000, "utilization_percent": 0,
    }])
    monkeypatch.setattr(q2, "allowed_gpu_uuids", lambda: {"GPU-fixture-4"})
    monkeypatch.setattr(training.shutil, "disk_usage", lambda path: SimpleNamespace(
        total=1024**4, free=1024**4, used=0))
    snapshots = []

    def budget():
        usage = training.training_usage()
        snapshots.append(usage)
        return shared_budget(usage)

    monkeypatch.setattr(training, "_shared_budget", budget)
    monkeypatch.setattr(training, "POLL_SECONDS", 0.01)
    return snapshots


def test_production_gate_rejects_plausible_but_unverified_contracts(contracts):
    with pytest.raises(RuntimeError, match="source domain gate|domain gate"):
        training.run_training("model", [sys.executable, "-c", "pass"],
                              timeout_seconds=10, **contracts)
    assert not training.TRAINING_ROOT.exists()
    assert not (training.OUT / "solver.lock").exists()


def test_production_contracts_follow_current_recipe_resolution(monkeypatch, tmp_path):
    """A passed prospective recipe must reach the training gate unchanged."""
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}")
    domain = {
        "schema": "f3.nopen.domain_gate.v1", "stage": "domain", "status": "passed",
        "recipe_id": "F3_CELL3_NS_visco1_native_nopen_revision075",
        "production_resolution_m": 0.0075, "time_window_s": [0, 8.35],
        "scoring_interval_s": 0.01,
        "evidence_sha256": {"evidence.json": training._sha256(evidence)},
    }
    qualification_path = tmp_path / "domain.json"
    qualification_path.write_text(json.dumps(domain))
    qualification = {"path": str(qualification_path), "sha256": training._sha256(qualification_path),
                     "content": domain}
    development_content = {
        "schema": "f3.training.development_data.v1", "status": "passed",
        "qualified_sources": True, "recipe_id": domain["recipe_id"],
        "production_resolution_m": domain["production_resolution_m"], "scope": "pilot",
        "source_domain_gate": {"path": "domain.json", "sha256": qualification["sha256"]},
    }
    development_path = tmp_path / "development.json"
    development_path.write_text(json.dumps(development_content))
    development = {"path": str(development_path), "sha256": training._sha256(development_path),
                   "content": development_content}

    from scripts import f3_nopen_development
    from scripts import f3_training_data
    monkeypatch.setattr(f3_nopen_development, "verify_domain_gate", lambda: domain)
    monkeypatch.setattr(f3_training_data, "validate_development_contract",
                        lambda path: development_content)

    result = training._require_production_contracts(qualification, development)
    assert result["domain"]["recipe_id"] == domain["recipe_id"]
    assert result["domain"]["production_resolution_m"] == 0.0075
    assert result["development"]["recipe_id"] == domain["recipe_id"]


@pytest.mark.parametrize("reference", [True, {}, {"path": "missing", "sha256": ""}])
def test_contracts_require_file_and_digest(reference, contracts):
    contracts["qualification_contract"] = reference
    with pytest.raises(ValueError, match="requires"):
        training.run_training("model", [sys.executable], timeout_seconds=10, **contracts)


def test_changed_or_empty_contract_is_rejected(contracts):
    path = Path(contracts["qualification_contract"]["path"])
    path.write_text("{}")
    with pytest.raises(ValueError, match="differs"):
        training.run_training("model", [sys.executable], timeout_seconds=10, **contracts)
    contracts["qualification_contract"] = bind(path, {})
    with pytest.raises(ValueError, match="nonempty JSON"):
        training.run_training("model", [sys.executable], timeout_seconds=10, **contracts)


def test_empty_usage_is_read_only_and_all_statuses_are_charged():
    empty = training.training_usage()
    assert empty["attempts_used"] == empty["gpu_budget_charge_hours"] == 0
    assert not training.TRAINING_ROOT.exists()
    write_attempt("complete", elapsed=1800)
    write_attempt("failed", status="failed", elapsed=900)
    write_attempt("resume", status="running", timeout=3600, cpu_cores=2)
    usage = training.training_usage()
    assert usage["attempts_used"] == 3
    assert usage["gpu_elapsed_hours"] == pytest.approx(0.75)
    assert usage["gpu_reserved_hours"] == pytest.approx(3605 / 3600)
    assert usage["cpu_elapsed_core_hours_upper_bound"] == pytest.approx(0.75 * 2.2)
    assert usage["cpu_reserved_core_hours"] == pytest.approx(3605 / 3600 * 3.3)
    assert usage["gpu_budget_charge_hours"] == pytest.approx(0.75 + 3605 / 3600)
    assert usage["manifest_sha256"] == training.training_usage()["manifest_sha256"]
    for row in usage["attempts"]:
        assert row["record_sha256"] == training._sha256(row["record_path"])
    assert "double-count" in usage["cpu_accounting_note"]


@pytest.mark.parametrize("change", [
    {"schema": "unknown"}, {"status": "forgotten"}, {"elapsed_seconds": -1},
    {"cpu_reserved_core_hours": 0}, {"execution_attempt_id": "different"},
    {"gpu_index": 0},
])
def test_invalid_record_is_not_silently_excluded(change):
    path = write_attempt("attempt")
    record = json.loads(path.read_text())
    record.update(change)
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        training.training_usage()


def test_orphan_directory_and_duplicate_identity_require_reconciliation():
    orphan = training.TRAINING_ROOT / "model" / "missing.partial"
    orphan.mkdir(parents=True)
    with pytest.raises(ValueError, match="lacks its record"):
        training.training_usage()
    orphan.rmdir()
    write_attempt("same", logical="one")
    write_attempt("same", logical="two")
    with pytest.raises(ValueError, match="duplicate"):
        training.training_usage()


def test_shared_budget_requires_version_and_includes_training_totals():
    write_attempt("old", status="failed", elapsed=3600)
    usage = training.training_usage()
    shared = shared_budget(usage)
    shared.pop("shared_training_accounting_version")
    with pytest.raises(RuntimeError, match="integration"):
        training.check_training_budget(shared, usage, timeout_seconds=10, cpu_cores=1)
    shared = shared_budget(usage)
    shared["gpu_budget_charge_hours"] = shared["gpu_solver_budget_charge_hours"]
    with pytest.raises(RuntimeError, match="include current training"):
        training.check_training_budget(shared, usage, timeout_seconds=10, cpu_cores=1)
    shared = shared_budget(usage)
    shared["cpu_core_hours_upper_bound"] = shared["cpu_base_core_hours_upper_bound"]
    with pytest.raises(RuntimeError, match="include current training"):
        training.check_training_budget(shared, usage, timeout_seconds=10, cpu_cores=1)


def test_training_attempt_cap_includes_failures_and_resumes():
    for index in range(12):
        write_attempt(f"attempt{index}", status="failed", elapsed=0)
    usage = training.training_usage()
    with pytest.raises(RuntimeError, match="including failures and resumes"):
        training.check_training_budget(shared_budget(usage), usage, timeout_seconds=10, cpu_cores=1)


def test_forward_reserve_includes_gpu_termination_and_existing_cpu_base_growth():
    usage = training.training_usage()
    with pytest.raises(RuntimeError, match="timeout reserve"):
        training.check_training_budget(shared_budget(usage, gpu_base=63.999), usage,
                                       timeout_seconds=1, cpu_cores=1)
    # Worker/controller alone fit in 10 core hours; the preserved 17.6-core
    # activity window keeps growing too, so this one-hour run must be refused.
    with pytest.raises(RuntimeError, match="activity-window growth"):
        training.check_training_budget(shared_budget(usage, cpu_base=758), usage,
                                       timeout_seconds=3600, cpu_cores=1)
    reserve = training.check_training_budget(shared_budget(usage), usage,
                                            timeout_seconds=3600, cpu_cores=1)
    assert reserve["cpu_base_growth_reserve_core_hours"] == pytest.approx(3605 * 17.6 / 3600)
    assert reserve["cpu_reserved_core_hours"] == pytest.approx(3605 * 2.2 / 3600)
    # CFD category limits do not consume the independent training count.
    shared = shared_budget(usage, qualification=0, development=0)
    assert training.check_training_budget(shared, usage, timeout_seconds=1, cpu_cores=1)


def test_full_timeout_must_fit_before_expiry():
    usage = training.training_usage()
    shared = shared_budget(usage)
    shared["conservative_expiry_utc"] = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()
    with pytest.raises(RuntimeError, match="past campaign expiry"):
        training.check_training_budget(shared, usage, timeout_seconds=60, cpu_cores=1)


@pytest.mark.parametrize("gpu_index", [0, 1, 2, 3, 8, True])
def test_protected_gpu_cannot_be_requested(gpu_index, contracts):
    with pytest.raises(ValueError, match="physical GPUs 4-7"):
        training.run_training("model", [sys.executable], timeout_seconds=10,
                              gpu_index=gpu_index, **contracts)


def test_gpu_policy_checks_inventory_uuid_and_launch_and_runtime_memory(monkeypatch):
    row = {"index": 4, "uuid": "GPU-fixture-4", "memory_free_mib": 6144}
    monkeypatch.setattr(training, "_gpu_snapshot", lambda *args: [row])
    monkeypatch.setattr(q2, "allowed_gpu_uuids", lambda: {"GPU-fixture-4"})
    assert training._select_gpu(4)["gpu_uuid"] == "GPU-fixture-4"
    row["memory_free_mib"] = 6143
    with pytest.raises(RuntimeError, match="launch memory"):
        training._select_gpu(4)
    row["memory_free_mib"] = 4096
    assert training._gpu_guard(4, "GPU-fixture-4")["ok"]
    assert not training._gpu_guard(4, "GPU-different")["ok"]
    row["memory_free_mib"] = 4095
    assert not training._gpu_guard(4, "GPU-fixture-4")["ok"]
    row.update(memory_free_mib=20000, uuid="GPU-not-allowed")
    with pytest.raises(RuntimeError, match="UUID"):
        training._select_gpu(4)
    assert not training._gpu_guard(4, "GPU-not-allowed")["ok"]
    assert not training._gpu_guard(5, "GPU-fixture-4")["ok"]


def test_shared_lock_and_unresolved_attempt_block_launch(cpu_worker, contracts):
    with (training.OUT / "solver.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="lock is busy"):
            training.run_training("model", [sys.executable], timeout_seconds=10, **contracts)
    write_attempt("unresolved", status="running")
    with pytest.raises(RuntimeError, match="process reconciliation"):
        training.run_training("another-model", [sys.executable], timeout_seconds=10, **contracts)
    assert not cpu_worker


def test_cpu_worker_records_reservation_before_spawn_and_terminal_usage(cpu_worker, contracts):
    code = (
        "import json,os,pathlib,sys; p=pathlib.Path(sys.argv[1]); "
        "r=json.loads((p/'attempt.json').read_text()); "
        "payload={'registration':r, 'affinity':sorted(os.sched_getaffinity(0)), "
        "'device':sys.argv[2], 'cuda':os.environ['CUDA_VISIBLE_DEVICES'], "
        "'cublas':os.environ['CUBLAS_WORKSPACE_CONFIG'], "
        "'omp':os.environ['OMP_NUM_THREADS'], 'openblas':os.environ['OPENBLAS_NUM_THREADS'], "
        "'lock_inode':os.fstat(r['inherited_solver_lock_fd']).st_ino}; "
        "(p/'worker.json').write_text(json.dumps(payload))"
    )
    result = training.run_training("pilot-local", [sys.executable, "-c", code, "{output}", "{device}"],
                                   timeout_seconds=10, env={"CUDA_VISIBLE_DEVICES": "0", "OMP_NUM_THREADS": "80"},
                                   **contracts)
    directory = Path(result["attempt_directory"])
    actual = json.loads((directory / "worker.json").read_text())
    assert result["status"] == "completed" and result["returncode"] == 0
    assert directory.name == result["execution_attempt_id"] + ".complete"
    assert result["elapsed_seconds"] > 0
    assert result["gpu_uuid"] == actual["cuda"] == "GPU-fixture-4"
    assert actual["device"] == "cuda:0" and actual["omp"] == actual["openblas"] == "1"
    assert actual["cublas"] == ":4096:8"
    assert actual["affinity"] == result["cpu_affinity"] and len(actual["affinity"]) == 1
    assert actual["lock_inode"] == (training.OUT / "solver.lock").stat().st_ino
    assert actual["registration"]["status"] == "running"
    assert actual["registration"]["elapsed_seconds"] is None
    assert result["command"][1:3] == ["--cpu-list", str(actual["affinity"][0])]
    assert [row["attempts_used"] for row in cpu_worker] == [0, 1, 1]
    assert cpu_worker[1]["attempts"][0]["status"] == "running"
    assert cpu_worker[1]["gpu_reserved_hours"] == pytest.approx(15 / 3600)
    assert cpu_worker[2]["attempts"][0]["status"] == "completed"
    assert cpu_worker[2]["gpu_reserved_hours"] == 0
    assert cpu_worker[2]["gpu_elapsed_hours"] == pytest.approx(result["elapsed_seconds"] / 3600)
    assert json.loads((directory / "attempt.json").read_text()) == result
    assert not list(training.TRAINING_ROOT.glob("*/*.partial"))
    assert not list(directory.glob("*.partial"))
    with (training.OUT / "solver.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_failure_and_explicit_resume_are_distinct_charged_attempts(cpu_worker, contracts):
    first = training.run_training("model", [sys.executable, "-c",
        "import pathlib,sys; pathlib.Path(sys.argv[1],'checkpoint.bin').write_bytes(b'checkpoint'); sys.exit(7)",
        "{output}"], timeout_seconds=10, **contracts)
    assert first["status"] == "failed" and first["returncode"] == 7
    checkpoint = Path(first["attempt_directory"]) / "checkpoint.bin"
    resume = {"execution_attempt_id": first["execution_attempt_id"],
              "checkpoint": {"path": str(checkpoint), "sha256": training._sha256(checkpoint)}}
    with pytest.raises(ValueError, match="explicit resume_from"):
        training.run_training("model", [sys.executable], timeout_seconds=10, **contracts)
    second = training.run_training("model", [sys.executable, "-c",
        "import pathlib,sys; assert pathlib.Path(sys.argv[1]).read_bytes()==b'checkpoint'", "{resume_checkpoint}"],
        resume_from=resume, timeout_seconds=10, **contracts)
    assert second["status"] == "completed"
    assert first["execution_attempt_id"] != second["execution_attempt_id"]
    assert second["resume_from"] == resume
    assert training.training_usage()["attempts_used"] == 2
    changed = dict(contracts)
    changed["development_contract"] = bind(training.LAB / "changed.json", {"different": True})
    with pytest.raises(ValueError, match="contracts changed"):
        training.run_training("model", [sys.executable], resume_from=resume,
                              timeout_seconds=10, **changed)
    assert training.training_usage()["attempts_used"] == 2


@pytest.mark.parametrize("failure_mode", ["timeout", "gpu_guard", "probe_timeout"])
def test_stopped_cpu_worker_is_terminal_and_billed(failure_mode, monkeypatch, cpu_worker, contracts):
    if failure_mode == "gpu_guard":
        monkeypatch.setattr(training, "_gpu_guard", lambda *args, **kwargs: {"ok": False, "reason": "fixture"})
    elif failure_mode == "probe_timeout":
        def timeout(*args, **kwargs):
            assert 0 < kwargs["timeout_seconds"] <= 0.12
            raise subprocess.TimeoutExpired("fake GPU probe", kwargs["timeout_seconds"])
        monkeypatch.setattr(training, "_gpu_guard", timeout)
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    if failure_mode == "probe_timeout":
        with pytest.raises(subprocess.TimeoutExpired):
            training.run_training("stopped", command, timeout_seconds=0.12, **contracts)
        result = training.training_usage()["attempts"][0]
    else:
        result = training.run_training("stopped", command, timeout_seconds=0.12, **contracts)
    assert result["status"] == "failed"
    assert result["stop_reason"] == ("exception" if failure_mode == "probe_timeout" else failure_mode)
    assert result["elapsed_seconds"] > 0
    assert result["returncode"] is not None
    with pytest.raises(ProcessLookupError):
        os.kill(result["pid"], 0)
    assert training.training_usage()["attempts_used"] == 1
    assert training.training_usage()["gpu_reserved_hours"] == 0


def test_spawn_failure_is_a_counted_atomic_terminal_attempt(monkeypatch, cpu_worker, contracts):
    def fail_spawn(*args, **kwargs):
        raise OSError("fixture spawn failed")
    monkeypatch.setattr(training.subprocess, "Popen", fail_spawn)
    with pytest.raises(OSError, match="fixture spawn failed"):
        training.run_training("spawn-failed", [sys.executable], timeout_seconds=10, **contracts)
    usage = training.training_usage()
    assert usage["attempts_used"] == 1
    assert usage["attempts"][0]["status"] == "failed"
    assert usage["attempts"][0]["returncode"] is None
    assert usage["gpu_reserved_hours"] == 0
    assert len(cpu_worker) == 3


def test_post_registration_budget_failure_does_not_spawn(monkeypatch, cpu_worker, contracts):
    def budget():
        usage = training.training_usage()
        # Shared accounting can change between registration and process launch.
        return shared_budget(usage, cpu_base=767.99 if usage["attempts_used"] else 2)
    monkeypatch.setattr(training, "_shared_budget", budget)
    monkeypatch.setattr(training.subprocess, "Popen", forbidden)
    with pytest.raises(RuntimeError, match="CPU/GPU budget|activity-window growth"):
        training.run_training("no-spawn", [sys.executable], timeout_seconds=10, **contracts)
    row = training.training_usage()["attempts"][0]
    assert row["status"] == "failed" and row["elapsed_seconds"] == 0
    assert "pid" not in row
