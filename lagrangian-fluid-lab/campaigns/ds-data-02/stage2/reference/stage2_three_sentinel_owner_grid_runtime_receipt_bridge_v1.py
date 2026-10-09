#!/usr/bin/env python3
"""Exercise the frozen owner-grid worker with a runtime-v8 receipt shape.

The frozen initial-support worker only needs ``status`` and ``returncode``
from a GenCase receipt, but the parent runtime writes a larger
``ds02.execution-receipt.v1`` object.  This additive fixture writes that
runtime-shaped object into the worker's existing manufactured nine-row
fixture, refreshes the manifest's receipt records, and then runs the real
worker followed by the real verifier.  A second run changes one receipt to a
non-zero terminal code and proves that the worker/verifier retain that row as
FAILED.  No production path, native payload, VTK, BI4, or GenCase process is
opened by this module.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
WORKER_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
VERIFIER_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v1.py"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"


class BridgeFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BridgeFailure(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _receipt(path: Path, *, case_id: str, attempt_id: str, returncode: int = 0) -> dict[str, Any]:
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
    }
    request_raw = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request_sha = hashlib.sha256(request_raw).hexdigest()
    # These hashes intentionally describe only tiny manufactured metadata; the
    # bridge does not claim a parent reservation or a production input join.
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "completed" if returncode == 0 else "failed",
        "returncode": int(returncode),
        "request": request,
        "request_sha256": request_sha,
        "output_root": str(path.parent.absolute()),
        "input_hashes_at_launch": {"fixture/source.xml": "0" * 64},
        "input_hashes_after_run": {"fixture/source.xml": "0" * 64},
        "runner": {
            "schema": "ds02.runtime.v8",
            "source": "manufactured-runtime-shaped-receipt-bridge",
            "parent_reservation": "fixture_only",
        },
        "termination": {
            "reason": "completed" if returncode == 0 else "child_nonzero_returncode",
            "signal": None,
        },
        "resource": {"cpu_seconds": 0.001, "gpu": None},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _write_receipt(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.absolute()),
        "sha256": _digest(path),
        "stat": _stat(path),
        "hash_status": "BOUND_MANUFACTURED_RUNTIME_RECEIPT_FIXTURE",
        "payload_read_by_builder": False,
        "scope": "tiny_runtime_receipt_fixture",
    }


def _refresh_receipt_records(manifest: dict[str, Any], *, failed_key: str | None = None) -> None:
    for row in manifest["cases"]:
        key = f"{row['sentinel_id']}:{row['grid_label']}"
        path = Path(row["gencase_receipt"]["path"])
        case_id = str(row.get("physical_case_id") or key.replace(":", "_"))
        attempt_id = f"fixture-{row['sentinel_id'].lower()}-{row['grid_label']}"
        value = _receipt(path, case_id=case_id, attempt_id=attempt_id,
                         returncode=1 if key == failed_key else 0)
        _write_receipt(path, value)
        row["gencase_receipt"] = _record(path)


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_fixture() -> dict[str, Any]:
    worker = _load(WORKER_PATH, "owner_grid_runtime_receipt_bridge_worker")
    verifier = _load(VERIFIER_PATH, "owner_grid_runtime_receipt_bridge_verifier")
    with tempfile.TemporaryDirectory(prefix="owner-grid-runtime-receipt-bridge-") as value:
        root = Path(value)
        manifest_path = worker._fixture_manifest(root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise BridgeFailure("manufactured fixture manifest is not an object")
        _refresh_receipt_records(manifest)
        _write_manifest(manifest_path, manifest)
        positive_output = root / "positive-report.json"
        positive = worker.run(manifest_path, root / "positive-attempt", positive_output)
        verified = verifier.verify(manifest_path, positive_output)
        if verified.get("case_counts") != {"PASS_OR_DIAGNOSTIC": 9, "FAILED": 0}:
            raise BridgeFailure(f"runtime-shaped receipt positive counts are wrong: {verified.get('case_counts')!r}")
        for row in positive["cases"]:
            receipt = row.get("source_identity", {}).get("gencase_receipt", {})
            if receipt.get("sha256_pre") != receipt.get("sha256_post"):
                raise BridgeFailure("positive receipt did not have a stable worker guard")

        negative_manifest = copy.deepcopy(manifest)
        _refresh_receipt_records(negative_manifest, failed_key="F2-S2:original")
        negative_manifest_path = root / "negative-manifest.json"
        _write_manifest(negative_manifest_path, negative_manifest)
        negative_output = root / "negative-report.json"
        negative = worker.run(negative_manifest_path, root / "negative-attempt", negative_output)
        negative_verified = verifier.verify(negative_manifest_path, negative_output)
        expected = {"PASS_OR_DIAGNOSTIC": 8, "FAILED": 1}
        if negative_verified.get("case_counts") != expected:
            raise BridgeFailure(f"non-zero runtime receipt was not retained as failure: {negative_verified.get('case_counts')!r}")
        failed_rows = [row for row in negative["cases"] if row.get("status", "").startswith("FAILED")]
        if len(failed_rows) != 1 or "returncode 0" not in str(failed_rows[0].get("reason", "")):
            raise BridgeFailure("negative runtime receipt did not preserve its failure reason")
        return {
            "positive_case_counts": verified["case_counts"],
            "negative_case_counts": negative_verified["case_counts"],
            "receipt_schema": RECEIPT_SCHEMA,
            "production_payload_read": False,
            "solver_launch": False,
            "gencase_launch": False,
        }


def self_test() -> None:
    result = _run_fixture()
    assert result["positive_case_counts"] == {"PASS_OR_DIAGNOSTIC": 9, "FAILED": 0}
    assert result["negative_case_counts"] == {"PASS_OR_DIAGNOSTIC": 8, "FAILED": 1}
    print("PASS_THREE_SENTINEL_OWNER_GRID_RUNTIME_RECEIPT_BRIDGE_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.self_test:
        parser.error("only --self-test is available; production manifests are not accepted")
    try:
        self_test()
    except Exception as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_RUNTIME_RECEIPT_BRIDGE_SELFTEST: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
