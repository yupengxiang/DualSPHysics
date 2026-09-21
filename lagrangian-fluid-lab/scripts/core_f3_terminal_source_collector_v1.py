#!/usr/bin/env python3
"""Collect an independent F3 source audit only after a source job is terminal.

The collector reads the Core runtime ledger through SQLite's read-only URI.  A
queued or running job produces a status-only receipt and never opens its H5,
prepared record, or product directory.  A successful terminal job is audited
with the immutable streaming v2 source auditor and the audit is written to a
new evidence path; worker products and the central ledger are never modified.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


SCHEMA = "core.f3.cfd.native_volume_mls.terminal_source_collector.v1"
TERMINAL_SUCCESS = {"succeeded"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_immutable(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(f"collector output is immutable and already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def _ledger_row(ledger: Path, job_id: str) -> dict[str, Any] | None:
    # mode=ro is intentional: even SQLite bookkeeping cannot mutate the
    # central queue for this collector.
    uri = "file:" + str(Path(ledger).resolve()) + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        row = connection.execute(
            "SELECT job_id, spec, spec_hash, status, attempt_id, attempt_dir, result "
            "FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    job, spec_text, spec_hash, status, attempt_id, attempt_dir, result_text = row
    try:
        spec = json.loads(spec_text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"ledger spec for {job_id} is not JSON") from exc
    result = None
    if result_text:
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ledger result for {job_id} is not JSON") from exc
    return {
        "job_id": job,
        "spec": spec,
        "spec_sha256": spec_hash,
        "status": status,
        "attempt_id": attempt_id,
        "attempt_dir": attempt_dir,
        "result": result,
    }


def _argv_value(argv: list[Any], flag: str) -> str | None:
    try:
        index = argv.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    value = argv[index + 1]
    return str(value) if value is not None else None


def _output_path(attempt_dir: Path, result: dict[str, Any], suffix: str) -> Path | None:
    for output in result.get("outputs", []):
        if not isinstance(output, dict):
            continue
        relative = output.get("path")
        if isinstance(relative, str) and relative.endswith(suffix):
            return (attempt_dir / relative).resolve()
    return None


def collect(
    ledger: str | Path,
    job_id: str,
    status_output: str | Path,
    *,
    audit_output: str | Path | None = None,
) -> dict[str, Any]:
    """Read one ledger row and optionally audit its terminal source H5.

    ``audit_output`` is only used after the row is terminal and successful.
    In particular, checking whether a product H5 exists is deliberately after
    the terminal gate so an active H5 cannot be opened by accident.
    """
    ledger_path = Path(ledger).resolve()
    row = _ledger_row(ledger_path, job_id)
    if row is None:
        receipt = {
            "schema": SCHEMA,
            "collector_version": 1,
            "collected_at_utc": utc_now(),
            "ledger_path": str(ledger_path),
            "job_id": job_id,
            "status": "missing_job",
            "terminal": False,
            "audit_performed": False,
            "source_h5_touched": False,
            "central_ledger_mutation": 0,
            "gpu_started": False,
        }
        write_immutable(Path(status_output), receipt)
        return receipt

    status = str(row["status"])
    base = {
        "schema": SCHEMA,
        "collector_version": 1,
        "collected_at_utc": utc_now(),
        "ledger_path": str(ledger_path),
        "job_id": job_id,
        "status": status,
        "attempt_id": row.get("attempt_id"),
        "attempt_dir": row.get("attempt_dir"),
        "ledger_spec_sha256": row.get("spec_sha256"),
        "terminal": status in TERMINAL_SUCCESS,
        "audit_performed": False,
        "source_h5_touched": False,
        "central_ledger_mutation": 0,
        "gpu_started": False,
    }
    if status not in TERMINAL_SUCCESS:
        base["terminal_required"] = True
        base["reason"] = "source job is not a successful terminal attempt; H5 was not opened"
        write_immutable(Path(status_output), base)
        return base

    result = row.get("result") or {}
    if result.get("execution_status") not in (None, "succeeded") or result.get("returncode", 0) != 0:
        base["terminal"] = False
        base["reason"] = "ledger status is succeeded but worker receipt is not successful"
        write_immutable(Path(status_output), base)
        return base
    attempt_dir_text = row.get("attempt_dir")
    if not attempt_dir_text:
        raise ValueError("successful terminal source has no attempt_dir")
    attempt_dir = Path(attempt_dir_text).resolve()
    source_h5 = _output_path(attempt_dir, result, "product/trajectory.h5")
    prepared = _output_path(attempt_dir, result, "product/prepared.json")
    if source_h5 is None or prepared is None:
        argv = row["spec"].get("argv", [])
        source_h5 = source_h5 or Path(_argv_value(argv, "--hdf5") or "").resolve()
        prepared = prepared or Path(_argv_value(argv, "--prepared") or "").resolve()
    if source_h5 is None or prepared is None or not source_h5.is_file() or not prepared.is_file():
        raise FileNotFoundError("successful source does not expose terminal trajectory.h5 and prepared.json")
    if audit_output is None:
        raise ValueError("audit_output is required for a successful terminal source")

    script_root = Path(__file__).resolve().parents[1]
    if str(script_root) not in sys.path:
        sys.path.insert(0, str(script_root))
    from scripts.core_f3_cfd_source_audit_v2 import audit_file  # pylint: disable=import-outside-toplevel

    audit_path = Path(audit_output).resolve()
    audit = audit_file(prepared, source_h5, audit_path)
    audit_hash = sha256_file(audit_path)
    receipt = dict(base)
    receipt.update({
        "audit_performed": True,
        "source_h5_touched": True,
        "source_h5_path": str(source_h5),
        "source_h5_sha256": audit.get("hdf5_sha256"),
        "prepared_path": str(prepared),
        "prepared_sha256": audit.get("prepared_json_sha256"),
        "audit_path": str(audit_path),
        "audit_sha256": audit_hash,
        "audit_hard_integrity_pass": bool(audit.get("hard_integrity_pass", False)),
        "worker_usage": result.get("usage"),
        "worker_result_sha256": sha256_file(attempt_dir / "result.json")
        if (attempt_dir / "result.json").is_file() else None,
    })
    write_immutable(Path(status_output), receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--status-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args(argv)
    result = collect(args.ledger, args.job_id, args.status_output, audit_output=args.audit_output)
    print(json.dumps({
        "schema": result["schema"],
        "job_id": result["job_id"],
        "status": result["status"],
        "terminal": result["terminal"],
        "audit_performed": result["audit_performed"],
        "source_h5_touched": result["source_h5_touched"],
        "audit_hard_integrity_pass": result.get("audit_hard_integrity_pass"),
    }, sort_keys=True))
    return 0 if result["status"] in TERMINAL_SUCCESS and result["audit_performed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
