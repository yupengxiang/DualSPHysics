import json
import pathlib
import time

import scripts.core_runtime as runtime
from scripts.core_runtime import Coordinator, Store


def _active_store(tmp_path, *, job_id="job-test", attempt_id="attempt-test"):
    store = Store(tmp_path / "runtime")
    store.submit(
        {
            "job_id": job_id,
            "argv": ["/bin/true"],
            "cwd": "/tmp",
            "host": "ada",
            "resources": {"cpu_cores": 1, "ram_mib": 128, "gpu_peak_mib": 0, "io_weight": 0},
            "required_outputs": [],
            "timeout_seconds": 10,
        }
    )
    assert store.cas_update(
        job_id,
        "running",
        expected_status="queued",
        expected_attempt_id=None,
        expected_job_id=job_id,
        attempt_id=attempt_id,
        attempt_dir=str(tmp_path / "attempts" / job_id / attempt_id),
    )
    return store


def _receipt(job_id, attempt_id, *, status="succeeded", marker=None):
    return {
        "schema": "core.execution_receipt.v1",
        "job_id": job_id,
        "attempt_id": attempt_id,
        "execution_status": status,
        "scientific_status": "not_inferred_from_execution",
        "started": 1.0,
        "finished": 2.0,
        "returncode": 0 if status == "succeeded" else 1,
        "timeout": False,
        "error": None,
        "missing_outputs": [],
        "outputs": [],
        "artifact_index": [],
        "argv": ["/bin/true"],
        "source_snapshot": None,
        "usage": {
            "wall_seconds": 1.0,
            "cpu_seconds_children": 1.0,
            "gpu_process_reservation_hours": 0.0,
        },
        "allocation": {},
        **({"marker": marker} if marker is not None else {}),
    }


def test_scheduler_selected_routes_and_persists_effective_host(tmp_path):
    store = Store(tmp_path / "runtime")
    store.submit(
        {
            "job_id": "route-test",
            "argv": ["/bin/true"],
            "cwd": "/tmp",
            "host": "scheduler-selected",
            "resources": {"cpu_cores": 1, "ram_mib": 1024, "gpu_peak_mib": 4096, "io_weight": 1},
            "required_outputs": [],
            "timeout_seconds": 10,
        }
    )
    snapshot = {
        "time": 0,
        "hostname": "test",
        "cpu_count": 128,
        "ram_total_mib": 251000,
        "ram_available_mib": 200000,
        "disk_free_bytes": 10**12,
        "gpus": [{"index": 0, "uuid": "GPU-H", "name": "H200", "total_mib": 140000, "used_mib": 0, "utilization": 0}],
        "gpu_processes": [],
    }
    coordinator = Coordinator(
        store.root,
        {"ada": {"lab": "/tmp", "python": "python"}, "h200": {"lab": "/tmp", "python": "python"}},
    )
    coordinator.call = lambda name, *args: snapshot
    launched = []

    def fake_launch(job, allocation, host_name=None):
        launched.append((host_name, allocation))
        coordinator.store.update(
            job["job_id"],
            "reserved",
            allocation={**allocation, "_host": host_name},
            attempt_id="test-attempt",
            attempt_dir=str(pathlib.Path("/tmp") / "test-attempt"),
        )

    coordinator.launch = fake_launch
    coordinator.tick()

    assert launched and launched[0][0] == "h200"
    assert coordinator.job_host(store.jobs()[0]) == "h200"


def test_cas_transition_allows_only_one_observer_to_advance_attempt(tmp_path):
    first = Store(tmp_path / "runtime")
    first.submit(
        {
            "job_id": "cas-race",
            "argv": ["/bin/true"],
            "cwd": "/tmp",
            "resources": {"cpu_cores": 1, "ram_mib": 128, "gpu_peak_mib": 0, "io_weight": 0},
            "required_outputs": [],
            "timeout_seconds": 10,
        }
    )
    second = Store(tmp_path / "runtime")

    assert first.transition(
        "cas-race",
        "reserved",
        expected_status="queued",
        expected_attempt_id=None,
        expected_job_id="cas-race",
        attempt_id="attempt-a",
        attempt_dir=str(tmp_path / "attempt-a"),
    )
    assert not second.cas_update(
        "cas-race",
        "reserved",
        expected_status="queued",
        expected_attempt_id=None,
        expected_job_id="cas-race",
        attempt_id="attempt-b",
        attempt_dir=str(tmp_path / "attempt-b"),
    )
    assert not first.cas_update(
        "cas-race",
        "running",
        expected_status="reserved",
        expected_attempt_id="wrong-attempt",
        expected_job_id="cas-race",
    )
    assert not first.cas_update(
        "cas-race",
        "running",
        expected_status="reserved",
        expected_attempt_id="attempt-a",
        expected_job_id="another-job",
    )
    row = first.jobs()[0]
    assert row["status"] == "reserved"
    assert row["attempt_id"] == "attempt-a"


def test_finalize_receipt_is_idempotent_and_does_not_double_count(tmp_path):
    store = _active_store(tmp_path, job_id="finalize-job", attempt_id="attempt-1")
    receipt = _receipt("finalize-job", "attempt-1")

    accepted = store.finalize_receipt(
        "finalize-job", receipt, expected_attempt_id="attempt-1", expected_job_id="finalize-job"
    )
    duplicate = store.finalize_receipt(
        "finalize-job", json.loads(json.dumps(receipt)), expected_attempt_id="attempt-1"
    )
    other_connection = Store(tmp_path / "runtime")
    duplicate_after_restart = other_connection.finalize_receipt(
        "finalize-job", receipt, expected_attempt_id="attempt-1"
    )
    conflicting = dict(receipt, marker="tampered")
    conflict = store.finalize_receipt("finalize-job", conflicting, expected_attempt_id="attempt-1")
    repeated_conflict = store.finalize_receipt(
        "finalize-job", dict(conflicting), expected_attempt_id="attempt-1"
    )

    assert accepted["action"] == "accepted"
    assert duplicate["action"] == "noop"
    assert duplicate_after_restart["action"] == "noop"
    assert conflict["action"] == "attention"
    assert repeated_conflict["action"] == "noop"
    row = store.jobs()[0]
    assert row["status"] == "attention"
    assert row["result"] == receipt
    assert runtime.usage_summary(store.jobs())["cpu_children_core_hours"] == 1 / 3600
    events = store.db.execute("SELECT event FROM events WHERE job_id=? ORDER BY id", ("finalize-job",)).fetchall()
    assert [row[0] for row in events] == ["submitted", "succeeded", "receipt_conflict"]


def test_wrong_attempt_and_job_receipts_are_quarantined(tmp_path):
    store = _active_store(tmp_path, job_id="identity-job", attempt_id="attempt-1")
    wrong_attempt = _receipt("identity-job", "attempt-forged")
    outcome = store.finalize_receipt("identity-job", wrong_attempt, expected_attempt_id="attempt-1")
    assert outcome["action"] == "attention"
    row = store.jobs()[0]
    assert row["status"] == "attention"
    assert row["result"]["schema"] == "core.reconciliation_attention.v1"
    assert "attempt_id_mismatch" in row["result"]["errors"]
    assert runtime.usage_summary(store.jobs())["cpu_children_core_hours"] == 0

    second = _active_store(tmp_path / "second", job_id="job-2", attempt_id="attempt-2")
    wrong_job = _receipt("not-job-2", "attempt-2")
    outcome = second.finalize_receipt("job-2", wrong_job, expected_attempt_id="attempt-2")
    assert outcome["action"] == "attention"
    assert "job_id_mismatch" in second.jobs()[0]["result"]["errors"]


def test_corrupt_receipt_registers_recovery_once_without_relaunch(tmp_path, monkeypatch):
    coordinator = Coordinator(
        tmp_path / "runtime",
        {"ada": {"lab": str(tmp_path), "python": "python"}},
    )
    store = coordinator.store
    store.submit(
        {
            "job_id": "corrupt-job",
            "argv": ["/bin/true"],
            "cwd": "/tmp",
            "host": "ada",
            "resources": {"cpu_cores": 1, "ram_mib": 128, "gpu_peak_mib": 0, "io_weight": 0},
            "required_outputs": [],
            "timeout_seconds": 10,
        }
    )
    assert store.cas_update(
        "corrupt-job", "running", expected_status="queued", expected_attempt_id=None,
        expected_job_id="corrupt-job", attempt_id="attempt-corrupt",
        attempt_dir=str(tmp_path / "corrupt-attempt"),
    )
    observed = {"receipt_errors": [{"file": "result.json", "error": "JSONDecodeError"}],
                "worker_alive": False, "child_alive": False}
    monkeypatch.setattr(coordinator, "call", lambda name, *args: observed)

    coordinator.reconcile()
    first = store.jobs()[0]
    assert first["status"] == "attention"
    assert first["result"]["reason"] == "corrupt_receipt"
    before = store.db.execute(
        "SELECT COUNT(*) FROM events WHERE job_id=? AND event='recovery_registered'", ("corrupt-job",)
    ).fetchone()[0]

    coordinator.reconcile()
    after = store.db.execute(
        "SELECT COUNT(*) FROM events WHERE job_id=? AND event='recovery_registered'", ("corrupt-job",)
    ).fetchone()[0]
    assert before == after == 1
    assert not any(row["status"] == "queued" for row in store.jobs())


def test_missing_receipt_after_recovery_window_stays_attention(tmp_path, monkeypatch):
    store = _active_store(tmp_path, job_id="missing-job", attempt_id="attempt-missing")
    coordinator = Coordinator(
        store.root,
        {"ada": {"lab": str(tmp_path), "python": "python"}},
    )
    store = coordinator.store
    with store.db:
        store.db.execute("UPDATE jobs SET updated=? WHERE job_id=?", (time.time() - 61, "missing-job"))
    monkeypatch.setattr(
        coordinator,
        "call",
        lambda name, *args: {"worker_alive": False, "child_alive": False},
    )

    coordinator.reconcile()
    row = store.jobs()[0]
    assert row["status"] == "attention"
    assert row["result"]["reason"] == "missing_receipt_requires_reconciliation"
