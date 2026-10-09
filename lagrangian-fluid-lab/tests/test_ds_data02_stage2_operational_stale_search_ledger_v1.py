from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ds_data02_stage2_operational_stale_search_ledger_v1.py"
spec = importlib.util.spec_from_file_location("ds02_operational_ledger_v1", SCRIPT)
assert spec is not None and spec.loader is not None
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    rows = []
    for pid, start, utime, stime, cwd in (
        (101, 1001, 20, 30, "/work/one"),
        (102, 1002, 7, 13, "/work/two"),
    ):
        rows.append({
            "pid": pid, "ppid": pid - 1, "cwd": cwd,
            "argv": ["rg", "-n", "small-pattern", cwd],
            "io": "rchar: 100\nread_bytes: 0\n",
            "clock_ticks_per_second": 100,
            "sampled_utime_ticks": utime, "sampled_stime_ticks": stime,
            "sampled_process_cpu_seconds": (utime + stime) / 100,
            "process_starttime_ticks": start,
            "parent_argv": ["/usr/bin/zsh", "-lc", "rg -n small-pattern"],
        })
    snapshot = {
        "schema": ledger.SNAPSHOT_SCHEMA,
        "status": "OWNERSHIP_VERIFIED_SNAPSHOT_BEFORE_SIGNAL",
        "utc": "2026-10-09T00:00:00+00:00",
        "budget_scope": "unreserved operational search, no scientific credit",
        "array_content_read_by_root": False,
        "io_not_equal_decoded_scientific_arrays": True,
        "rows": rows,
    }
    snapshot_path = tmp_path / "snapshot.json"
    _write(snapshot_path, snapshot)
    signal = {
        "schema": ledger.SIGNAL_SCHEMA,
        "snapshot": str(snapshot_path),
        "foreign_processes_signalled": False,
        "whole_process_terminal_confirmation": "pending additive observation",
        "results": [
            {"pid": 101, "signal": "SIGTERM", "only_exact_verified_rg_process_signalled": True},
            {"pid": 102, "signal": "SIGTERM", "only_exact_verified_rg_process_signalled": True},
        ],
    }
    signal_path = tmp_path / "signal.json"
    _write(signal_path, signal)
    return snapshot_path, signal_path


def test_append_is_operational_only_and_preserves_identity(tmp_path: Path) -> None:
    snapshot, signal = _inputs(tmp_path)
    output = tmp_path / "operational-ledger-v1.json"
    result = ledger.append_snapshot(snapshot_path=snapshot, signal_path=signal, output_ledger=output)
    assert result["status"] == "APPENDED_OPERATIONAL_SAMPLE_ONLY"
    assert result["sampled_cpu_seconds_total"] == pytest.approx(0.7)
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["resource_ledger_mutated"] is False
    assert value["reservation_created"] is False
    assert value["qualification_credit"] == "NONE"
    assert {(row["pid"], row["process_starttime_ticks"]) for row in value["rows"]} == {(101, 1001), (102, 1002)}
    assert all(row["post_signal_cpu"] == "UNKNOWN" for row in value["rows"])


def test_duplicate_snapshot_and_identity_are_rejected(tmp_path: Path) -> None:
    snapshot, signal = _inputs(tmp_path)
    first = tmp_path / "first.json"
    ledger.append_snapshot(snapshot_path=snapshot, signal_path=signal, output_ledger=first)
    with pytest.raises(ledger.OperationalLedgerError, match="already been appended"):
        ledger.append_snapshot(snapshot_path=snapshot, signal_path=signal,
                               base_ledger=first, output_ledger=tmp_path / "second.json")


def test_signal_mismatch_and_nonoperational_snapshot_are_rejected(tmp_path: Path) -> None:
    snapshot, signal = _inputs(tmp_path)
    bad_signal = json.loads(signal.read_text(encoding="utf-8"))
    bad_signal["results"][1]["pid"] = 999
    bad_signal_path = tmp_path / "bad-signal.json"
    _write(bad_signal_path, bad_signal)
    with pytest.raises(ledger.OperationalLedgerError, match="signal PID"):
        ledger.append_snapshot(snapshot_path=snapshot, signal_path=bad_signal_path,
                               output_ledger=tmp_path / "bad-signal-ledger.json")

    bad_snapshot = json.loads(snapshot.read_text(encoding="utf-8"))
    bad_snapshot["budget_scope"] = "scientific qualification attempt"
    bad_snapshot_path = tmp_path / "bad-snapshot.json"
    _write(bad_snapshot_path, bad_snapshot)
    with pytest.raises(ledger.OperationalLedgerError, match="operational/unreserved"):
        ledger.append_snapshot(snapshot_path=bad_snapshot_path, signal_path=signal,
                               output_ledger=tmp_path / "bad-snapshot-ledger.json")


def test_existing_nonoperational_base_is_rejected(tmp_path: Path) -> None:
    snapshot, signal = _inputs(tmp_path)
    base = tmp_path / "base.json"
    _write(base, {"schema": ledger.SCHEMA, "resource_ledger_mutated": True,
                  "reservation_created": False, "qualification_credit": "NONE", "rows": []})
    with pytest.raises(ledger.OperationalLedgerError, match="not operational"):
        ledger.append_snapshot(snapshot_path=snapshot, signal_path=signal,
                               base_ledger=base, output_ledger=tmp_path / "out.json")
