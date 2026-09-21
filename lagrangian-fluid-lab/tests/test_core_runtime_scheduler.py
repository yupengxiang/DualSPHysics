import pathlib

from scripts.core_runtime import Coordinator, Store


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
