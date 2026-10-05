#!/usr/bin/env python3
"""Synthetic owner/namespace checks for the disabled fresh074 contract."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import socket
import tempfile


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "reconcile_typed_conversion.py"


def module():
    spec = importlib.util.spec_from_file_location("fresh074_reconcile", MODULE_PATH)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


R = module()


def _status(pid: int, ppid: int, nspid: list[int]) -> str:
    return (
        f"Name:\t{'codex-linux-san' if pid == 1 else 'python3'}\n"
        f"Pid:\t{pid}\nPPid:\t{ppid}\n"
        f"Uid:\t1001\t1001\t1001\t1001\n"
        f"Gid:\t1001\t1001\t1001\t1001\n"
        f"NSpid:\t{' '.join(map(str, nspid))}\n"
    )


def _binding(root: Path, receipt: Path) -> dict:
    return {
        "reservation_id": "F3/AY0270/typed-154",
        "reservation_host": socket.gethostname(),
        "launcher_pid": 91101,
        "child_pid": 92202,
        "group_leader_pid": 92202,
        "process_group_id": 92202,
        "data_root": str(root),
        "receipt_path": str(receipt),
        "os_owner": {
            "uid": 1001,
            "gid": 1001,
            "paths": {
                "ledger": str(root / "runtime" / "resource-ledger.json"),
                "receipt": str(receipt),
            },
        },
        "runtime_start_new_session": {
            "enabled": True,
            "group_leader_is_child": True,
            "source": "runtime_v2.subprocess.Popen(start_new_session=True)",
        },
        "historical_pid_provenance": {
            name: {
                "pid": pid,
                "start_ticks": None,
                "start_ticks_status": R.UNKNOWN_START_TICKS,
                "source": "immutable runtime receipt/ledger; ticks not persisted",
            }
            for name, pid in {
                "launcher": 91101,
                "child": 92202,
                "group_leader": 92202,
            }.items()
        },
    }


def _proc_tree(proc: Path) -> None:
    (proc / "sys/kernel/random").mkdir(parents=True)
    (proc / "sys/kernel/random/boot_id").write_text("synthetic-boot-id\n")
    (proc / "self/ns").mkdir(parents=True)
    (proc / "self/ns/pid").symlink_to("pid:[synthetic]")
    (proc / "self/status").write_text(_status(__import__("os").getpid(), 1,
                                                [__import__("os").getpid()]))
    (proc / "1/status").parent.mkdir(parents=True)
    (proc / "1/status").write_text(_status(1, 0, [1]))
    (proc / "1/stat").write_text(
        "1 (codex-linux-san) S 0 1 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 100 0\n"
    )


def _dead_evidence(binding: dict) -> dict:
    identity = binding["historical_pid_provenance"]
    rows = {
        name: {
            "pid": binding[f"{name}_pid"], "present": False,
            "errno": "ENOENT", "state": None, "start_ticks": None,
            "stat_sha256": None, "historical_identity": identity[name],
        }
        for name in R.TARGETS
    }

    def sample():
        return {
            "schema": R.SAMPLE_SCHEMA,
            "probe_status": "qualified_owner_host_namespace",
            "host": {"hostname": binding["reservation_host"], "boot_id": "synthetic-boot-id"},
            "qualification": {
                "root_caller": False, "owner_caller": True,
                "caller_euid": 1001, "caller_egid": 1001,
                "owner_uid": 1001, "owner_gid": 1001,
                "pid_namespace": "pid:[synthetic]",
            },
            "owner_proof": {
                "files": {
                    name: {"uid": 1001, "gid": 1001, "stable": True}
                    for name in ("ledger", "receipt")
                },
                "namespace": {
                    "proof": "synthetic status/stat",
                    "self_status": {"NSpid": [__import__("os").getpid()]},
                    "pid1_status": {"NSpid": [1]},
                    "pid1_stat": {"pid": 1, "ppid": 0},
                },
            },
            "targets": copy.deepcopy(rows),
            "process_group": {"id": binding["process_group_id"],
                               "members": [], "scan_complete": True,
                               "scan_errors": []},
            "pid_reuse_guard": R.ABSENCE_GUARD,
        }

    return {
        "schema": R.SAMPLE_SCHEMA,
        "same_process_namespace": True,
        "samples": [sample(), sample()],
    }


def test_real_owner_capture_never_claims_root() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "runtime").mkdir()
        (root / "runtime/resource-ledger.json").write_text("{}\n")
        receipt = root / "receipt.json"
        receipt.write_text("{}\n")
        bind = _binding(root, receipt)
        with tempfile.TemporaryDirectory() as proc_directory:
            proc = Path(proc_directory)
            _proc_tree(proc)
            evidence = R.capture_two_samples(bind, proc, interval_seconds=0,
                                             sleep_fn=lambda _: None)
        assert evidence["same_process_namespace"] is True
        sample = evidence["samples"][0]
        assert sample["qualification"]["root_caller"] is False
        assert sample["qualification"]["owner_caller"] is True
        assert sample["qualification"]["caller_euid"] == 1001
        assert sample["owner_proof"]["files"]["ledger"]["uid"] == 1001
        assert R.verify_dead_twice(bind, evidence)["historical_start_ticks"] == "unknown_and_null"


def test_foreign_owner_refuses_even_with_empty_process_group() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "runtime").mkdir()
        ledger = root / "runtime/resource-ledger.json"
        ledger.write_text("{}\n")
        receipt = root / "receipt.json"
        receipt.write_text("{}\n")
        bind = _binding(root, receipt)
        bind["os_owner"]["uid"] = 1000
        try:
            R.validate_owner_binding(bind, data_root=root, receipt_path=receipt)
        except R.ReconciliationRefused as error:
            assert "1001:1001" in str(error)
        else:
            raise AssertionError("foreign owner was accepted")


def test_missing_or_nested_nspid_refuses() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "runtime").mkdir()
        (root / "runtime/resource-ledger.json").write_text("{}\n")
        receipt = root / "receipt.json"
        receipt.write_text("{}\n")
        bind = _binding(root, receipt)
        with tempfile.TemporaryDirectory() as proc_directory:
            proc = Path(proc_directory)
            _proc_tree(proc)
            (proc / "self/status").write_text(_status(__import__("os").getpid(), 1,
                                                       [7, __import__("os").getpid()]))
            try:
                R.capture_sample(bind, proc)
            except R.ReconciliationRefused as error:
                assert "NSpid" in str(error)
            else:
                raise AssertionError("nested NSpid was accepted")


def test_synthetic_unknown_ticks_and_double_absence_valid() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "runtime").mkdir()
        (root / "runtime/resource-ledger.json").write_text("{}\n")
        receipt = root / "receipt.json"
        receipt.write_text("{}\n")
        bind = _binding(root, receipt)
        result = R.verify_dead_twice(bind, _dead_evidence(bind))
        assert result["samples_verified"] == 2
        assert result["historical_start_ticks"] == "unknown_and_null"


def main() -> int:
    test_real_owner_capture_never_claims_root()
    test_foreign_owner_refuses_even_with_empty_process_group()
    test_missing_or_nested_nspid_refuses()
    test_synthetic_unknown_ticks_and_double_absence_valid()
    print("fresh074 semantic contract: PASS (owner 1001:1001, no root claim, status/stat namespace proof, null ticks, negative guards)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
