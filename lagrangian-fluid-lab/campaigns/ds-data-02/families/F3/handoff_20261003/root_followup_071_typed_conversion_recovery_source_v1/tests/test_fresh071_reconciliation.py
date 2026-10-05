#!/usr/bin/env python3
"""Synthetic lifecycle tests for the disabled fresh071 recovery contract."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import tempfile


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "reconcile_typed_conversion.py"
WORKER_PATH = HERE / "artifact_integrity_worker.py"


def module():
    spec = importlib.util.spec_from_file_location("fresh071_reconcile", MODULE_PATH)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


R = module()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(receipt_path: Path | None = None) -> dict:
    host = socket.gethostname()
    boot = "synthetic-boot-id"
    result = {
        "reservation_id": "infra/CASE/attempt-071",
        "reservation_host": host,
        "launcher_pid": 1101,
        "child_pid": 2202,
        "group_leader_pid": 2202,
        "process_group_id": 2202,
        "pid_anchors": {
            "launcher": {"pid": 1101, "start_ticks": 11, "boot_id": boot},
            "child": {"pid": 2202, "start_ticks": 22, "boot_id": boot},
            "group_leader": {"pid": 2202, "start_ticks": 22, "boot_id": boot},
        },
        "runtime_v2_sha256": "runtime-sha",
    }
    if receipt_path is not None:
        result["receipt_path"] = str(receipt_path)
        result["receipt_sha256"] = sha(receipt_path)
    return result


def dead_evidence(bind: dict) -> dict:
    rows = {}
    for name in R.TARGETS:
        rows[name] = {"pid": bind[f"{name}_pid"], "present": False,
                      "errno": "ENOENT", "state": None, "start_ticks": None,
                      "stat_sha256": None, "anchor": bind["pid_anchors"][name]}
    def sample():
        return {
            "schema": R.SAMPLE_SCHEMA,
            "probe_status": "qualified_host_namespace",
            "host": {"hostname": bind["reservation_host"], "boot_id": "synthetic-boot-id"},
            "targets": copy.deepcopy(rows),
            "process_group": {"id": bind["process_group_id"], "members": [],
                               "scan_complete": True, "scan_errors": []},
            "pid_reuse_guard": "exact-pid-start-ticks-absent-and-boot-bound",
            "captured_at_utc": "2026-10-05T02:00:00+00:00",
        }
    return {"schema": R.SAMPLE_SCHEMA, "same_process_namespace": True,
            "samples": [sample(), sample()]}


def test_double_sample_requires_absent_group_and_rejects_live_child() -> None:
    bind = binding()
    assert R.verify_dead_twice(bind, dead_evidence(bind))["samples_verified"] == 2
    live = dead_evidence(bind)
    live["samples"][0]["targets"]["child"].update(
        present=True, errno=None, state="D", start_ticks=22, stat_sha256="live")
    live["samples"][0]["process_group"]["members"] = [{
        "pid": 2202, "state": "D", "ppid": 3291, "pgid": 2202,
        "session": 2202, "start_ticks": 22, "stat_sha256": "live"}]
    try:
        R.verify_dead_twice(bind, live)
    except R.ReconciliationRefused as error:
        assert "dead child" in str(error)
    else:
        raise AssertionError("live child was incorrectly accepted")


def test_capture_reads_proc_stat_twice_without_launching() -> None:
    bind = binding()
    with tempfile.TemporaryDirectory() as directory:
        proc = Path(directory)
        (proc / "sys/kernel/random").mkdir(parents=True)
        (proc / "sys/kernel/random/boot_id").write_text("synthetic-boot-id\n")
        evidence = R.capture_two_samples(bind, proc, interval_seconds=0,
                                         sleep_fn=lambda _: None)
        assert R.verify_dead_twice(bind, evidence)["samples_verified"] == 2


def test_apply_is_idempotent_conservative_and_preserves_other_state() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime_dir = root / "runtime"
        runtime_dir.mkdir()
        receipt = root / "old-receipt.json"
        receipt.write_text(json.dumps({"status": "running", "returncode": None}) + "\n")
        bind = binding(receipt)
        row = {
            "id": bind["reservation_id"], "kind": "cpu", "cpu_task_kind": "conversion",
            "cpu_threads": 2, "cpu_core_seconds": 21600, "gpu_seconds": 0,
            "new_storage_bytes": 25769803776, "host": bind["reservation_host"],
            "reserved_at_utc": "2026-10-05T01:00:00+00:00",
        }
        other_reservation = {"id": "other/live", "kind": "cpu", "cpu_core_seconds": 7}
        ledger = {
            "schema": "ds02.resource-ledger.v1",
            "deadline_utc": "2026-10-14T07:23:48+00:00",
            "limits": {"cpu_core_seconds": 13824000, "gpu_seconds": 1843200},
            "adoption": {"unchanged": True}, "counters": {"qualification": 4},
            "charges": [], "reservations": [row, other_reservation],
            "attempts": [{"id": row["id"], "kind": "cpu", "status": "reserved"},
                         {"id": "other/live", "kind": "cpu", "status": "running"}],
        }
        # Use the actual runtime-v2 locking and atomic JSON implementation on
        # a temporary ledger, never the shared campaign ledger.
        runtime_path = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
        spec = importlib.util.spec_from_file_location("runtime_v2_test", runtime_path)
        assert spec and spec.loader
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        runtime.atomic_json(runtime_dir / "resource-ledger.json", ledger)
        result = R.apply_reconciliation(runtime_module=runtime, data_root=root,
                                        binding={**bind, "reservation_sha256": R.canonical_sha256(row)},
                                        evidence=dead_evidence({**bind, "reservation_sha256": R.canonical_sha256(row)}),
                                        sidecar_dir=root / "sidecars", tool_status=143,
                                        enable=True, authorization_token="ROOT_REVIEWED_FRESH071")
        assert result["status"] == "applied"
        settled = json.loads((runtime_dir / "resource-ledger.json").read_text())
        assert not any(item["id"] == row["id"] for item in settled["reservations"])
        charge = next(item for item in settled["charges"] if item["id"] == row["id"])
        assert charge["cpu_core_seconds"] == 21600
        assert charge["status"] == "interrupted_unfinalized"
        assert charge["child_returncode"] is None and charge["os_exit_zero"] is False
        attempt = next(item for item in settled["attempts"] if item["id"] == row["id"])
        assert attempt["status"] == "interrupted_unfinalized"
        assert attempt["returncode"] is None and attempt["tool_status"] == 143
        assert settled["limits"] == ledger["limits"]
        assert settled["deadline_utc"] == ledger["deadline_utc"]
        assert settled["adoption"] == ledger["adoption"]
        assert settled["counters"] == ledger["counters"]
        assert next(item for item in settled["reservations"] if item["id"] == "other/live") == other_reservation
        second = R.apply_reconciliation(runtime_module=runtime, data_root=root,
                                         binding={**bind, "reservation_sha256": R.canonical_sha256(row)},
                                         evidence=dead_evidence({**bind, "reservation_sha256": R.canonical_sha256(row)}),
                                         sidecar_dir=root / "sidecars", tool_status=143,
                                         enable=True, authorization_token="ROOT_REVIEWED_FRESH071")
        assert second["status"] == "already_applied"
        settled_again = json.loads((runtime_dir / "resource-ledger.json").read_text())
        assert len([item for item in settled_again["charges"] if item["id"] == row["id"]]) == 1
        sidecars = list((root / "sidecars").glob("original-receipt-*.json"))
        assert len(sidecars) == 1 and sidecars[0].read_bytes() == receipt.read_bytes()


def test_gpu_and_disabled_paths_refuse() -> None:
    bind = binding()
    try:
        R.apply_reconciliation(runtime_module=object(), data_root=Path("/tmp"),
                               binding=bind, evidence=dead_evidence(bind),
                               sidecar_dir=Path("/tmp"), tool_status=143)
    except R.ReconciliationRefused as error:
        assert "disabled" in str(error)
    else:
        raise AssertionError("disabled application path opened")


def main() -> int:
    test_double_sample_requires_absent_group_and_rejects_live_child()
    test_capture_reads_proc_stat_twice_without_launching()
    test_apply_is_idempotent_conservative_and_preserves_other_state()
    test_gpu_and_disabled_paths_refuse()
    request = json.loads((HERE / "requests/p03_artifact_integrity_request.json").read_text())
    assert request["execution_allowed"] is False and request["launch_allowed"] is False
    assert request["source_conversion_returncode"] is None
    assert request["strict_artifact_integrity"]["must_not_reclassify_source_conversion"] is True
    assert request["output_contract"]["worker_returncode"] is None
    assert not any(p.is_file() and p.suffix.lower() in {".h5", ".bi4", ".csv", ".npy", ".npz"}
                   for p in HERE.rglob("*"))
    print("fresh071 semantic contract: PASS (dead-twice proof, live-child refusal, conservative idempotent settlement, disabled P03 audit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
