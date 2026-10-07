#!/usr/bin/env python3
"""Run bounded provenance tuple counterexamples before any frame decoder read."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

import stage2_sentinel_initial_v2_3 as audit


SCHEMA = "ds02.stage2.sentinel.initial-provenance-counterexamples.v1"
REPO = Path(__file__).resolve().parents[5]
DEFAULT_CURRENT = Path(__file__).resolve().parents[1] / "CURRENT336.json"
DEFAULT_REVIEW = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
    "STAGE2_SENTINEL_INPUTS/sentinel-inputs-001/sentinel-input-review.json"
)
DEFAULT_INDEX = Path(__file__).with_name("stage2-sentinel-initial-provenance-v2_3.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def entry_for(index: dict[str, Any], sentinel_id: str) -> dict[str, Any]:
    matches = [entry for entry in index["cases"] if entry.get("sentinel_id") == sentinel_id]
    if len(matches) != 1:
        raise ValueError(f"expected one {sentinel_id}, got {len(matches)}")
    return copy.deepcopy(matches[0])


def report_for(entry: dict[str, Any]) -> dict[str, Any]:
    return load(Path(entry["source_bindings"]["conversion_report"]))


def expect_source_failure(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    try:
        fn()
    except audit.SourceBindingError as error:
        return {
            "status": "PASS",
            "expected_failure": "SourceBindingError",
            "error": str(error),
            "raw_decoder_called": False,
            "hdf5_dataset_read": False,
        }
    except Exception as error:  # an unexpected error is evidence of a broken counterexample
        return {
            "status": "FAIL",
            "expected_failure": "SourceBindingError",
            "error_type": type(error).__name__,
            "error": str(error),
            "raw_decoder_called": False,
            "hdf5_dataset_read": False,
        }
    return {
        "status": "FAIL",
        "expected_failure": "SourceBindingError",
        "error": "mutated tuple was accepted",
        "raw_decoder_called": False,
        "hdf5_dataset_read": False,
    }


def run_check(current_path: Path, review_path: Path, index_path: Path) -> dict[str, Any]:
    index = load(index_path)
    entries = index.get("cases", [])
    if not isinstance(entries, list) or len(entries) != 14:
        raise ValueError("v2.3 provenance index must contain 14 cases")
    f2_s1 = entry_for(index, "F2-S1")
    f2_s1_report = report_for(f2_s1)
    f2_s2 = entry_for(index, "F2-S2")
    cases: dict[str, Any] = {}

    wrong_physical = copy.deepcopy(f2_s1)
    wrong_physical["physical_case_id"] = f2_s2["physical_case_id"]
    cases["wrong_physical_case_id"] = expect_source_failure(
        "wrong_physical_case_id",
        lambda: audit.verify_provenance_entry(current_path, review_path, wrong_physical, f2_s1_report),
    )

    wrong_family = copy.deepcopy(f2_s1)
    wrong_family["family_id"] = "F1"
    cases["wrong_family_id"] = expect_source_failure(
        "wrong_family_id",
        lambda: audit.verify_provenance_entry(current_path, review_path, wrong_family, f2_s1_report),
    )

    wrong_sentinel_tuple = copy.deepcopy(f2_s1)
    wrong_sentinel_tuple["sentinel_id"] = "F2-S2"
    cases["wrong_sentinel_tuple"] = expect_source_failure(
        "wrong_sentinel_tuple",
        lambda: audit.verify_provenance_entry(current_path, review_path, wrong_sentinel_tuple, f2_s1_report),
    )

    wrong_report_path = copy.deepcopy(f2_s1_report)
    wrong_report_path["output_hdf5"] = "/tmp/ds02-manufactured-wrong-trajectory.h5"
    cases["wrong_report_path"] = expect_source_failure(
        "wrong_report_path",
        lambda: audit.verify_provenance_entry(current_path, review_path, f2_s1, wrong_report_path),
    )

    wrong_digest = copy.deepcopy(f2_s1)
    wrong_digest["typed_hdf5"]["producer_declared_sha256"] = "0" * 64
    cases["wrong_producer_digest"] = expect_source_failure(
        "wrong_producer_digest",
        lambda: audit.verify_provenance_entry(current_path, review_path, wrong_digest, f2_s1_report),
    )

    positive: dict[str, Any] = {}
    for entry in entries:
        sentinel_id = entry["sentinel_id"]
        try:
            verified_entry, review, source_check, _paths = audit.verify_and_read_source(
                current_path, review_path, index_path, sentinel_id
            )
            positive[sentinel_id] = {
                "status": "PASS",
                "physical_case_id": verified_entry["physical_case_id"],
                "family_id": verified_entry["family_id"],
                "source_binding": source_check.get("status"),
                "raw_decoder_called": False,
                "hdf5_dataset_read": False,
                "full_hdf5_rehash": source_check.get("full_hdf5_rehash"),
            }
        except Exception as error:
            positive[sentinel_id] = {"status": "FAIL", "error_type": type(error).__name__, "error": str(error)}

    negative_pass = all(value.get("status") == "PASS" for value in cases.values())
    positive_pass = len(positive) == 14 and all(value.get("status") == "PASS" for value in positive.values())
    return {
        "schema": SCHEMA,
        "status": "PASS" if negative_pass and positive_pass else "FAIL",
        "scope": {
            "negative_checks_fail_before_decoder": True,
            "raw_decoder_called": False,
            "hdf5_dataset_read": False,
            "full_time_scan": False,
            "full_hdf5_rehash": False,
            "solver_started": False,
            "partvtk_started": False,
        },
        "negative_counterexamples": cases,
        "positive_real_14_tuples": positive,
    }


def request(current: Path, review: Path, index: Path, output: Path) -> dict[str, Any]:
    input_files = [
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(),
        Path(audit.__file__).resolve(),
        current.resolve(),
        review.resolve(),
        index.resolve(),
    ]
    loaded = load(index)
    for entry in loaded["cases"]:
        input_files.append(Path(entry["source_bindings"]["conversion_report"]).resolve())
    credit = [entry.get("fullscan_hash_credit", {}) for entry in loaded["cases"]]
    for item in credit:
        if item.get("status") == "PASS":
            input_files.append(Path(item["path"]).resolve())
    unique = []
    seen: set[str] = set()
    for path in input_files:
        if not path.is_file():
            raise FileNotFoundError(path)
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return {
        "schema": "ds02.request.v1",
        "family_id": "F2",
        "case_id": "F2_S1_INITIAL_PROVENANCE_COUNTEREXAMPLES_V2",
        "attempt_id": "f2-s1-initial-provenance-counterexamples-v2-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 8388608,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(Path(__file__).resolve()),
            "--run",
            "--current", str(current.resolve()),
            "--review", str(review.resolve()),
            "--provenance-index", str(index.resolve()),
            "--output", "{attempt_root}/counterexample-check.json",
        ],
        "input_files": [str(path) for path in unique],
        "input_hashes": {str(path): sha256_file(path) for path in unique},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "full_hdf5_hash": "forbidden_by_scope",
            "estimated_cpu_core_hours": 2 * 300 / 3600,
        },
        "scope": {"provenance_only": True, "raw_decoder": False, "hdf5_dataset_read": False, "solver_started": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--emit-request", type=Path)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--provenance-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.emit_request is not None:
        value = request(args.current, args.review, args.provenance_index, args.emit_request)
        atomic_json(args.emit_request, value)
        print(json.dumps({"status": "PASS", "request": str(args.emit_request), "inputs": len(value["input_files"])}, ensure_ascii=False))
        return 0
    if not args.run or args.output is None:
        raise SystemExit("choose --emit-request or --run with --output")
    value = run_check(args.current, args.review, args.provenance_index)
    atomic_json(args.output, value)
    print(json.dumps({"status": value["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if value["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
