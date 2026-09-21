#!/usr/bin/env python3
"""Repair only a completed F6 receipt's missing native-audit hash binding.

The v4 worker wrote the native frame audit after constructing its receipt.  A
completed attempt can therefore have a scientifically valid audit with a
``native_frame_audit`` reference whose hash is ``null``.  This one-shot tool
copies the original receipt, verifies the existing audit, updates only that
binding, and records both receipt hashes.  It never opens a solver, decoder,
queue, registry, ledger, or qualification matrix.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
SCHEMA = "core.f6.observation_axis.receipt_integrity_repair.v1"
LOCK_NAME = "receipt-integrity-repair.json"
ORIGINAL_NAME = "execution-receipt-pre-repair.json"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def relative_ref(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    try:
        display = path.relative_to(LAB.resolve()).as_posix()
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def repair(attempt: str | Path) -> dict[str, Any]:
    attempt = Path(attempt).expanduser().resolve()
    receipt_path = attempt / "execution-receipt.json"
    audit_path = attempt / "native-frame-audit.json"
    lock_path = attempt / LOCK_NAME
    original_path = attempt / ORIGINAL_NAME
    if lock_path.exists():
        raise RuntimeError(f"integrity repair already consumed: {lock_path}")
    if not receipt_path.is_file() or not audit_path.is_file():
        raise FileNotFoundError("completed receipt and native audit are required")

    receipt = load(receipt_path)
    if receipt.get("schema") != "core.f6.observation_axis.protected_solver_canary_receipt.v1":
        raise ValueError("unexpected F6 receipt schema")
    controls = receipt.get("execution_controls", {})
    if controls.get("solver_invoked") is not True or controls.get("gpu_started") is not False:
        raise ValueError("integrity repair requires an already executed CPU attempt")
    if any(controls.get(key) not in (False, 0) for key in (
        "queue_mutation", "registry_mutation", "ledger_mutation", "matrix_submission",
    )):
        raise ValueError("integrity repair cannot touch protected state")
    if receipt.get("qualification_claim") != "none" or receipt.get("qualification_credit") != 0 or receipt.get("T1") is not False:
        raise ValueError("integrity repair cannot operate on a credited receipt")

    original_hash = sha256(receipt_path)
    binding = receipt.get("native_frame_audit")
    if not isinstance(binding, dict):
        raise ValueError("receipt has no native_frame_audit binding")
    try:
        expected_path = str(audit_path.relative_to(LAB))
    except ValueError as error:
        raise ValueError("attempt and native audit must be under LAB") from error
    if binding.get("path") != expected_path:
        raise ValueError("native audit path does not match this attempt")
    actual_hash = sha256(audit_path)
    actual_bytes = audit_path.stat().st_size
    if binding.get("sha256") == actual_hash and binding.get("bytes") == actual_bytes:
        raise ValueError("receipt already has an exact native audit binding")

    # Preserve the exact pre-repair JSON as evidence before replacing the
    # receipt.  Its hash is also recorded in the repair lock.
    atomic_write(original_path, receipt)
    original_copy_hash = sha256(original_path)
    if original_copy_hash != original_hash:
        raise RuntimeError("pre-repair receipt copy hash mismatch")

    repaired = deepcopy(receipt)
    repaired["native_frame_audit"] = relative_ref(audit_path, "per-frame native audit")
    repaired["metadata_integrity_repair"] = {
        "schema": SCHEMA,
        "repair_id": f"{receipt.get('receipt_id', 'receipt')}_native_audit_hash",
        "original_receipt_sha256": original_hash,
        "pre_repair_receipt_path": str(original_path.relative_to(LAB)),
        "solver_reinvoked": False,
        "scientific_fields_changed": [],
        "qualification_credit": 0,
    }
    atomic_write(receipt_path, repaired)
    repaired_hash = sha256(receipt_path)
    lock = {
        "schema": SCHEMA,
        "created_at_utc": stamp(),
        "attempt": str(attempt.relative_to(LAB)),
        "original_receipt_sha256": original_hash,
        "pre_repair_receipt_sha256": original_copy_hash,
        "repaired_receipt_sha256": repaired_hash,
        "native_frame_audit_sha256": actual_hash,
        "native_frame_audit_bytes": actual_bytes,
        "fields_repaired": ["native_frame_audit.sha256", "native_frame_audit.bytes"],
        "solver_reinvoked": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "matrix_submission": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
    }
    atomic_write(lock_path, lock)
    return lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    results = [repair(path) for path in args.attempt]
    print(json.dumps({"schema": SCHEMA, "repaired_count": len(results), "attempts": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
