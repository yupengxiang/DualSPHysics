import json
import os
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.core_runtime import (Store, atomic_json, choose_resources, collect_attempt,
                                  digest, is_alive, proc_identity, validate_spec, worker,
                                  interval_union_seconds, usage_summary, concurrency_decision)


def spec(job_id="a", gpu=4000):
    return validate_spec({"job_id": job_id, "argv": [sys.executable, "-c", "pass"], "cwd": "/tmp",
                          "resources": {"gpu_peak_mib": gpu, "cpu_cores": 2, "ram_mib": 512}})


@pytest.mark.parametrize("name", ["result.json", "./result.json", "launch.json",
                                  "heartbeat.json", "spec.json", "worker.log", "worker.lock"])
def test_job_outputs_cannot_overwrite_worker_metadata(name):
    job = spec()
    job["required_outputs"] = [name]
    with pytest.raises(ValueError, match="reserved worker metadata"):
        validate_spec(job)


def test_nested_scientific_result_is_not_worker_metadata():
    job = spec()
    job["required_outputs"] = ["product/result.json"]
    assert validate_spec(job)["required_outputs"] == ["product/result.json"]


def snapshot(used=0):
    return {"cpu_count": 128, "ram_total_mib": 250000, "ram_available_mib": 230000,
            "disk_free_bytes": 10**12, "gpus": [{"index": 0, "uuid": "GPU-a", "total_mib": 48000, "used_mib": used}],
            "gpu_processes": []}


def test_colocation_does_not_require_idle_gpu():
    first = spec()
    allocated = choose_resources(first, snapshot(), [])
    active = [{"spec": first, "allocation": allocated, "heartbeat": {"process_ids": [91]}}]
    current = snapshot(20000)
    current["gpu_processes"] = [{"pid": 91, "uuid": "GPU-a", "used_mib": 4000}]
    assert choose_resources(spec("second"), current, active)["gpu_uuid"] == "GPU-a"
    assert choose_resources(spec("large", gpu=24000), current, active) is None


def test_reservations_prevent_last_slot_double_admission():
    job = spec(gpu=20000)
    first = choose_resources(job, snapshot(), [])
    assert first
    assert choose_resources(spec("b", gpu=20000), snapshot(), [{"spec": job, "allocation": first}]) is None


def test_external_memory_is_not_mistaken_for_owned_memory():
    assert choose_resources(spec(gpu=10000), snapshot(35000), []) is None


def test_observed_growth_and_retained_peak_override_initial_reservation():
    job = spec(gpu=2000)
    active = [{"spec": job, "allocation": choose_resources(job, snapshot(), []),
               "heartbeat": {"process_ids": [91]}}]
    current = snapshot(30000)
    current['gpu_processes'] = [{'pid': 91, 'uuid': 'GPU-a', 'used_mib': 30000}]
    assert choose_resources(spec('new', gpu=8000), current, active) is None
    active[0]['heartbeat']['peak_gpu_mib'] = 30000
    assert choose_resources(spec('new', gpu=8000), snapshot(), active) is None
    assert choose_resources(spec('small', gpu=2000), snapshot(), active) is not None


def test_worker_gpu_queries_are_shared_and_expire(tmp_path, monkeypatch):
    from scripts import core_runtime as runtime
    calls = []
    def sample():
        calls.append(1)
        time.sleep(.02)
        return [{'uuid': 'GPU-a'}], [{'pid': 91, 'uuid': 'GPU-a', 'used_mib': 4000}]
    monkeypatch.setattr(runtime, 'gpu_snapshot', sample)
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: runtime.shared_worker_gpu_snapshot(tmp_path), range(8)))
    assert len(calls) == 1 and all(value == values[0] for value in values)
    path = tmp_path/'worker-gpu-snapshot.json'
    stale = json.loads(path.read_text()); stale['monotonic_sample_end'] -= 10
    atomic_json(path, stale)
    runtime.shared_worker_gpu_snapshot(tmp_path)
    assert len(calls) == 2
    reboot = json.loads(path.read_text()); reboot['boot_id'] = 'previous-boot'
    atomic_json(path, reboot)
    runtime.shared_worker_gpu_snapshot(tmp_path)
    assert len(calls) == 3
    path.write_text('damaged cache')
    runtime.shared_worker_gpu_snapshot(tmp_path)
    assert len(calls) == 4


def test_registered_source_survives_later_worktree_edits(tmp_path):
    from scripts.core_runtime import freeze_job
    lab=tmp_path/'lab';(lab/'scripts').mkdir(parents=True)
    source=lab/'scripts/core_example.py';source.write_text('VALUE = 1\n')
    job=spec(gpu=0);job['argv']=[sys.executable,str(source)]
    job['input_files']=[{'path':str(source),'sha256':digest(source)}]
    frozen=freeze_job(job,lab,tmp_path/'runtime')
    source.write_text('VALUE = 2\n')
    again=freeze_job(frozen,lab,tmp_path/'runtime')
    assert again['source_snapshot']==frozen['source_snapshot']
    assert Path(again['argv'][1]).read_text()=='VALUE = 1\n'
    assert again['input_files'][0]['path']==again['argv'][1]
    assert digest(again['input_files'][0]['path'])==again['input_files'][0]['sha256']
    Path(again['argv'][1]).write_text('VALUE = 3\n')
    with pytest.raises(ValueError,match='snapshot content mismatch'):
        freeze_job(frozen,lab,tmp_path/'runtime')


def test_pinned_snapshot_rejects_new_entrypoint_before_launch(tmp_path):
    from scripts.core_runtime import freeze_job
    lab=tmp_path/'lab'; (lab/'scripts').mkdir(parents=True)
    old=lab/'scripts/old.py'; old.write_text('pass\n')
    job=spec(gpu=0); job['argv']=[sys.executable,str(old)]
    frozen=freeze_job(job,lab,tmp_path/'runtime')
    new=lab/'scripts/new.py'; new.write_text('pass\n')
    frozen['argv']=[sys.executable,str(new)]
    with pytest.raises(ValueError,match='absent from registered source snapshot'):
        freeze_job(frozen,lab,tmp_path/'runtime')
    frozen.pop('source_snapshot')
    updated=freeze_job(frozen,lab,tmp_path/'runtime')
    assert Path(updated['argv'][1]).is_file()


def test_measured_host_io_capacity_remains_a_reservation_gate():
    running=spec('existing',gpu=0);running['resources']['io_weight']=2
    request=spec('new',gpu=0);request['resources']['io_weight']=0.25
    active=[{'spec':running,'allocation':{}}]
    assert choose_resources(request,snapshot(),active) is None
    current=dict(snapshot(),io_capacity=2.25)
    allocation=choose_resources(request,current,active)
    assert allocation is not None
    assert choose_resources(request,current,active+[{'spec':request,'allocation':allocation}]) is None
    with pytest.raises(ValueError,match='io_capacity'):
        choose_resources(request,dict(snapshot(),io_capacity=float('nan')),active)


def test_duplicate_submission_transaction_is_idempotent(tmp_path):
    Store(tmp_path)
    def submit(_):
        store = Store(tmp_path)
        try:
            return store.submit(spec())
        finally:
            store.db.close()
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(submit, range(6))) == 1
    store = Store(tmp_path)
    assert len(store.jobs()) == 1
    changed = spec()
    changed["argv"][-1] = "print('different')"
    with pytest.raises(ValueError, match="different inputs"):
        store.submit(changed)


def test_worker_receipt_and_duplicate_do_not_rerun(tmp_path):
    job = spec(gpu=0)
    job["argv"] = [sys.executable, "-c", "from pathlib import Path; Path('value').write_text('one')"]
    job["cwd"] = str(tmp_path)
    job["required_outputs"] = ["value"]
    path = tmp_path / "spec.json"
    atomic_json(path, job)
    assert worker(path, tmp_path) == 0
    receipt = json.loads((tmp_path / "result.json").read_text())
    assert receipt["execution_status"] == "succeeded"
    assert receipt["scientific_status"] == "not_inferred_from_execution"
    assert receipt["outputs"][0]["sha256"] == digest(tmp_path / "value")
    (tmp_path / "value").write_text("changed")
    assert worker(path, tmp_path) == 0
    assert (tmp_path / "value").read_text() == "changed"


def test_required_output_and_input_hash_failure(tmp_path):
    job = spec(gpu=0)
    job["required_outputs"] = ["missing.json"]
    path = tmp_path / "spec.json"
    atomic_json(path, job)
    assert worker(path, tmp_path / "attempt") == 1
    result = json.loads((tmp_path / "attempt/result.json").read_text())
    assert result["missing_outputs"] == ["missing.json"]
    job["input_files"] = [{"path": str(path), "sha256": "bad"}]
    atomic_json(path, job)
    assert worker(path, tmp_path / "attempt2") == 1
    assert "hash mismatch" in json.loads((tmp_path / "attempt2/result.json").read_text())["error"]


def test_pid_reuse_guard():
    identity = proc_identity(os.getpid())
    assert is_alive(identity)
    assert not is_alive(dict(identity, start_ticks=identity["start_ticks"] + 1))


def test_interrupted_attempt_not_silently_reexecuted(tmp_path):
    job = spec(gpu=0)
    path = tmp_path / "spec.json"
    atomic_json(path, job)
    atomic_json(tmp_path / "launch.json", {"worker_identity": {"pid": 999999999, "start_ticks": 0, "boot_id": "none"}})
    assert worker(path, tmp_path) == 2
    assert not collect_attempt(tmp_path)["worker_alive"]


def test_worker_timeout_is_failure(tmp_path):
    job = spec(gpu=0)
    job["argv"] = [sys.executable, "-c", "import time; time.sleep(30)"]
    job["timeout_seconds"] = .1
    path = tmp_path / "spec.json"
    atomic_json(path, job)
    assert worker(path, tmp_path) == 1
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["timeout"]
    assert not collect_attempt(tmp_path)["child_alive"]


def test_shell_and_unsafe_artifact_paths_rejected():
    invalid = spec()
    invalid["argv"] = "echo hello"
    with pytest.raises(ValueError):
        validate_spec(invalid)


def test_overlap_accounting_is_not_sum_of_process_hours():
    assert interval_union_seconds([(0, 10), (5, 15), (20, 25)]) == 20
    jobs = []
    for start, stop in [(0, 3600), (1800, 5400)]:
        jobs.append({"spec": {"host": "ada"}, "result": {
            "schema": "core.execution_receipt.v1", "started": start, "finished": stop,
            "allocation": {"gpu_uuid": "GPU-a"}, "usage": {"gpu_process_reservation_hours": 1, "cpu_seconds_children": 30},
            "artifact_index": [{"sha256": "same", "bytes": 100}]}})
    report = usage_summary(jobs)
    assert report["completed_attempts_gpu_process_reservation_hours"] == 2
    assert report["completed_attempts_gpu_device_reservation_union_hours"] == 1.5
    assert report["indexed_replica_bytes"] == 200 and report["indexed_unique_content_bytes"] == 100


def test_usage_accounting_uses_frozen_scheduler_host():
    jobs = []
    for host, start, stop in [("h200", 0, 10), ("ada", 5, 15)]:
        jobs.append({"spec": {"host": "scheduler-selected"},
                     "allocation": {"_host": host},
                     "result": {
                         "schema": "core.execution_receipt.v1", "started": start,
                         "finished": stop, "allocation": {"gpu_uuid": "GPU-same"},
                         "usage": {"gpu_process_reservation_hours": 0,
                                   "cpu_seconds_children": 0}, "artifact_index": []}})
    # The two intervals are on different effective hosts even though a test
    # fixture reuses a UUID; they must not be merged into one device union.
    assert usage_summary(jobs)["completed_attempts_gpu_device_reservation_union_hours"] == 20 / 3600


def test_throughput_plateau_stops_increasing_colocation():
    rows = [{"concurrency": n, "qualified_units_per_hour": v, "oom": False} for n,v in [(1,100),(2,108),(3,110)]]
    assert not concurrency_decision(rows)["increase"]
    rows[-1]["qualified_units_per_hour"] = 130
    assert concurrency_decision(rows)["increase"]
    invalid = spec()
    invalid["required_outputs"] = ["../escape"]
    with pytest.raises(ValueError):
        validate_spec(invalid)


def test_oom_at_higher_concurrency_stops_upscaling_despite_throughput_gain():
    rows = [
        {"concurrency": 1, "qualified_units_per_hour": 100, "oom": False},
        {"concurrency": 2, "qualified_units_per_hour": 180, "oom": True},
    ]

    decision = concurrency_decision(rows)

    assert decision["increase"] is False
    assert decision["reason"] == "failure_or_oom"


def test_repair_canary_unblocks_before_bulk_cells_without_changing_fifo_ties():
    from scripts.core_runtime import queue_priority
    jobs=[{'job_id':'bulk','created':1,'spec':{'category':'qualification'}},
          {'job_id':'matched','created':4,'spec':{'category':'matched_stack_canary'}},
          {'job_id':'repair_b','created':3,'spec':{'category':'repair_canary'}},
          {'job_id':'repair_a','created':2,'spec':{'category':'repair_canary'}}]
    assert [j['job_id'] for j in sorted(jobs,key=queue_priority)]==['repair_a','repair_b','matched','bulk']
