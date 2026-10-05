#!/usr/bin/env python3
"""Synthetic lifecycle tests for the disabled fresh072 recovery contract."""
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


def module():
    spec = importlib.util.spec_from_file_location("fresh072_reconcile", MODULE_PATH)
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
    result = {
        "reservation_id": "infra/CASE/attempt-072",
        "reservation_host": host,
        "launcher_pid": 1101,
        "child_pid": 2202,
        "group_leader_pid": 2202,
        "process_group_id": 2202,
        "runtime_start_new_session": {
            "enabled": True,
            "group_leader_is_child": True,
            "source": "runtime_v2.subprocess.Popen(start_new_session=True)",
        },
        "historical_pid_provenance": {
            "launcher": {
                "pid": 1101,
                "start_ticks": None,
                "start_ticks_status": R.UNKNOWN_START_TICKS,
                "source": "resource-ledger.reservations[].launcher_pid",
            },
            "child": {
                "pid": 2202,
                "start_ticks": None,
                "start_ticks_status": R.UNKNOWN_START_TICKS,
                "source": "execution-receipt.pid",
            },
            "group_leader": {
                "pid": 2202,
                "start_ticks": None,
                "start_ticks_status": R.UNKNOWN_START_TICKS,
                "source": "runtime_v2.start_new_session; execution-receipt.pid",
            },
        },
        "runtime_v2_sha256": "runtime-sha",
    }
    if receipt_path is not None:
        result["receipt_path"] = str(receipt_path)
        result["receipt_sha256"] = sha(receipt_path)
    return result


def qualification() -> dict:
    return {"root_caller": True, "caller_euid": 0,
            "pid_namespace": "pid:[synthetic]", "proc_root": "/synthetic/proc"}


def dead_evidence(bind: dict) -> dict:
    identity = bind["historical_pid_provenance"]
    rows = {}
    for name in R.TARGETS:
        rows[name] = {
            "pid": bind[f"{name}_pid"], "present": False,
            "errno": "ENOENT", "state": None, "start_ticks": None,
            "stat_sha256": None, "historical_identity": identity[name],
        }

    def sample(captured_at: str):
        return {
            "schema": R.SAMPLE_SCHEMA,
            "probe_status": "qualified_host_namespace",
            "host": {"hostname": bind["reservation_host"],
                     "boot_id": "synthetic-boot-id"},
            "qualification": qualification(),
            "targets": copy.deepcopy(rows),
            "process_group": {"id": bind["process_group_id"],
                               "members": [], "scan_complete": True,
                               "scan_errors": []},
            "pid_reuse_guard": R.ABSENCE_GUARD,
            "captured_at_utc": captured_at,
        }

    return {"schema": R.SAMPLE_SCHEMA, "same_process_namespace": True,
            "fresh_probe": {"mode": "two_sequential_captures",
                            "in_lock_eligible": True, "interval_seconds": 0},
            "samples": [sample("2026-10-05T02:00:00+00:00"),
                        sample("2026-10-05T02:00:01+00:00")]}


def test_null_historical_ticks_and_double_absence_are_valid() -> None:
    bind = binding()
    for identity in bind["historical_pid_provenance"].values():
        assert identity["start_ticks"] is None
        assert identity["start_ticks_status"] == R.UNKNOWN_START_TICKS
    result = R.verify_dead_twice(bind, dead_evidence(bind))
    assert result["samples_verified"] == 2
    assert result["historical_start_ticks"] == "unknown_and_null"


def test_present_pid_and_namespace_ambiguity_refuse() -> None:
    bind = binding()
    live = dead_evidence(bind)
    live["samples"][0]["targets"]["child"].update(
        present=True, errno=None, state="D", start_ticks=22,
        stat_sha256="live")
    live["samples"][0]["process_group"]["members"] = [{
        "pid": 2202, "state": "D", "ppid": 3291, "pgid": 2202,
        "session": 2202, "start_ticks": 22, "stat_sha256": "live"}]
    try:
        R.verify_dead_twice(bind, live)
    except R.ReconciliationRefused as error:
        assert "dead child" in str(error)
    else:
        raise AssertionError("live child was incorrectly accepted")

    ambiguous = dead_evidence(bind)
    ambiguous["samples"][1]["qualification"]["pid_namespace"] = "pid:[changed]"
    try:
        R.verify_dead_twice(bind, ambiguous)
    except R.ReconciliationRefused as error:
        assert "namespace" in str(error)
    else:
        raise AssertionError("changed PID namespace was incorrectly accepted")


def test_capture_requires_qualified_root_and_records_namespace() -> None:
    bind = binding()
    with tempfile.TemporaryDirectory() as directory:
        proc = Path(directory)
        (proc / "sys/kernel/random").mkdir(parents=True)
        (proc / "sys/kernel/random/boot_id").write_text("synthetic-boot-id\n")
        (proc / "1/ns").mkdir(parents=True)
        (proc / "1/ns/pid").symlink_to("pid:[synthetic]")
        (proc / "self/ns").mkdir(parents=True)
        (proc / "self/ns/pid").symlink_to("pid:[synthetic]")
        # A complete synthetic numeric /proc census needs a parseable init row.
        (proc / "1/stat").write_text(
            "1 (init) S 0 1 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 100 0\n")
        old_geteuid = R.os.geteuid
        R.os.geteuid = lambda: 0
        try:
            evidence = R.capture_two_samples(bind, proc, interval_seconds=0,
                                             sleep_fn=lambda _: None)
        finally:
            R.os.geteuid = old_geteuid
    assert evidence["same_process_namespace"] is True
    assert R.verify_dead_twice(bind, evidence)["samples_verified"] == 2


def test_stale_caller_evidence_is_refused_before_application() -> None:
    bind = binding()
    try:
        R.apply_reconciliation(runtime_module=object(), data_root=Path("/tmp"),
                               binding=bind, evidence=dead_evidence(bind),
                               sidecar_dir=Path("/tmp"), tool_status=143,
                               enable=True,
                               authorization_token=R.AUTHORIZATION_TOKEN)
    except R.ReconciliationRefused as error:
        assert "stale" in str(error)
    else:
        raise AssertionError("stale caller liveness evidence was accepted")


def test_in_lock_application_is_conservative_idempotent_and_non_target_safe() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime_dir = root / "runtime"
        runtime_dir.mkdir()
        receipt = root / "old-receipt.json"
        receipt.write_text(json.dumps({"pid": 2202, "status": "running",
                                       "returncode": None}) + "\n")
        bind = binding(receipt)
        row = {
            "id": bind["reservation_id"], "kind": "cpu",
            "cpu_task_kind": "conversion", "cpu_threads": 2,
            "cpu_core_seconds": 21600, "gpu_seconds": 0,
            "new_storage_bytes": 25769803776,
            "host": bind["reservation_host"],
            "launcher_pid": bind["launcher_pid"],
            "reserved_at_utc": "2026-10-05T01:00:00+00:00",
        }
        other_reservation = {"id": "other/live", "kind": "cpu",
                             "cpu_core_seconds": 7}
        ledger = {
            "schema": "ds02.resource-ledger.v1",
            "deadline_utc": "2026-10-14T07:23:48+00:00",
            "limits": {"cpu_core_seconds": 13824000, "gpu_seconds": 1843200},
            "adoption": {"unchanged": True}, "counters": {"qualification": 4},
            "charges": [], "reservations": [row, other_reservation],
            "attempts": [{"id": row["id"], "kind": "cpu", "status": "reserved"},
                         {"id": "other/live", "kind": "cpu", "status": "running"}],
        }
        runtime_path = Path(
            "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
            "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
        spec = importlib.util.spec_from_file_location("runtime_v2_test", runtime_path)
        assert spec and spec.loader
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        runtime.atomic_json(runtime_dir / "resource-ledger.json", ledger)

        original_capture = R.capture_two_samples
        R.capture_two_samples = lambda *args, **kwargs: dead_evidence(bind)
        try:
            result = R.apply_reconciliation(
                runtime_module=runtime, data_root=root,
                binding={**bind, "reservation_sha256": R.canonical_sha256(row)},
                evidence=None, sidecar_dir=root / "sidecars", tool_status=143,
                enable=True, authorization_token=R.AUTHORIZATION_TOKEN,
                proc_root=root / "synthetic-proc", probe_interval_seconds=0,
                sleep_fn=lambda _: None)
            assert result["status"] == "applied"
            assert result["fresh_liveness"]["historical_start_ticks"] == "unknown_and_null"
            settled = json.loads((runtime_dir / "resource-ledger.json").read_text())
            assert not any(item["id"] == row["id"]
                           for item in settled["reservations"])
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
            assert next(item for item in settled["reservations"]
                        if item["id"] == "other/live") == other_reservation

            second = R.apply_reconciliation(
                runtime_module=runtime, data_root=root,
                binding={**bind, "reservation_sha256": R.canonical_sha256(row)},
                evidence=None, sidecar_dir=root / "sidecars", tool_status=143,
                enable=True, authorization_token=R.AUTHORIZATION_TOKEN,
                proc_root=root / "synthetic-proc", probe_interval_seconds=0,
                sleep_fn=lambda _: None)
            assert second["status"] == "already_applied"
            settled_again = json.loads((runtime_dir / "resource-ledger.json").read_text())
            assert len([item for item in settled_again["charges"]
                        if item["id"] == row["id"]]) == 1
            sidecars = list((root / "sidecars").glob("original-receipt-*.json"))
            assert len(sidecars) == 1 and sidecars[0].read_bytes() == receipt.read_bytes()
        finally:
            R.capture_two_samples = original_capture


def test_disabled_path_and_artifact_request_remain_closed() -> None:
    bind = binding()
    try:
        R.apply_reconciliation(runtime_module=object(), data_root=Path("/tmp"),
                               binding=bind, evidence=None,
                               sidecar_dir=Path("/tmp"), tool_status=143)
    except R.ReconciliationRefused as error:
        assert "disabled" in str(error)
    else:
        raise AssertionError("disabled application path opened")
    # The P03 audit is intentionally the byte-identical fresh071 request;
    # fresh072 does not alter or reclassify that independent CPU audit.
    request = json.loads((HERE / "requests/p03_artifact_integrity_request.json").read_text())
    assert request["fresh_id"] == "fresh071"
    assert request["execution_allowed"] is False and request["launch_allowed"] is False
    assert request["source_conversion_returncode"] is None
    assert request["strict_artifact_integrity"]["must_not_reclassify_source_conversion"] is True
    assert request["output_contract"]["worker_returncode"] is None
    root166 = json.loads((HERE / "requests/root166_p03_artifact_integrity_binding.json").read_text())
    assert root166["launch_allowed"] is False and root166["execution_allowed"] is False
    assert root166["worker_output"]["worker_returncode"] is None
    assert not any(p.is_file() and p.suffix.lower() in {".h5", ".bi4", ".csv", ".npy", ".npz"}
                   for p in HERE.rglob("*"))


def main() -> int:
    test_null_historical_ticks_and_double_absence_are_valid()
    test_present_pid_and_namespace_ambiguity_refuse()
    test_capture_requires_qualified_root_and_records_namespace()
    test_stale_caller_evidence_is_refused_before_application()
    test_in_lock_application_is_conservative_idempotent_and_non_target_safe()
    test_disabled_path_and_artifact_request_remain_closed()
    print("fresh072 semantic contract: PASS (null historical ticks, qualified in-lock double absence, stale/live refusal, conservative idempotent settlement)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
