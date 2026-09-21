from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import core_f3_terminal_source_collector_v1 as collector


def _ledger(path: Path, *, status: str, attempt_dir: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY, spec TEXT NOT NULL, spec_hash TEXT NOT NULL,
            status TEXT NOT NULL, attempt_id TEXT, allocation TEXT, attempt_dir TEXT,
            heartbeat TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL
        );
        """
    )
    spec = {
        "argv": ["python", "source.py", "--prepared", str(attempt_dir / "prepared.json")],
    }
    result = {"execution_status": "succeeded", "returncode": 0, "outputs": []}
    con.execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("dense-source", json.dumps(spec), "spec-hash", status, "attempt", str(attempt_dir),
         None, None, json.dumps(result), 0.0, 0.0),
    )
    con.commit()
    con.close()


def test_running_source_is_status_only_and_does_not_touch_h5(tmp_path: Path) -> None:
    ledger = tmp_path / "queue.sqlite3"
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    # This path is intentionally a marker rather than valid H5.  A running
    # row must return before any product path is opened.
    (attempt / "trajectory.h5").write_bytes(b"must-not-be-opened")
    _ledger(ledger, status="running", attempt_dir=attempt)

    output = tmp_path / "status.json"
    result = collector.collect(ledger, "dense-source", output)

    assert result["terminal"] is False
    assert result["audit_performed"] is False
    assert result["source_h5_touched"] is False
    assert json.loads(output.read_text())["reason"].startswith("source job is not")


def test_missing_job_is_immutable_status_receipt(tmp_path: Path) -> None:
    ledger = tmp_path / "queue.sqlite3"
    con = sqlite3.connect(ledger)
    con.executescript(
        """
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY, spec TEXT NOT NULL, spec_hash TEXT NOT NULL,
            status TEXT NOT NULL, attempt_id TEXT, allocation TEXT, attempt_dir TEXT,
            heartbeat TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL
        );
        """
    )
    con.commit()
    con.close()
    out = tmp_path / "missing.json"
    result = collector.collect(ledger, "does-not-exist", out)
    assert result["status"] == "missing_job"
    with pytest.raises(FileExistsError):
        collector.collect(ledger, "does-not-exist", out)
