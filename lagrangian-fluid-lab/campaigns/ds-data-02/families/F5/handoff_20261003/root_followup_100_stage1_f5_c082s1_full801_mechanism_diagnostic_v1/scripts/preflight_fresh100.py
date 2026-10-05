#!/usr/bin/env python3
"""Metadata-only contract check for the F5 fresh100 package.

This preflight never opens H5/BI4/CSV/VTK/DAT and never launches a runner.
It hashes only source/Python/JSON/XML metadata and copies the producer-declared
H5 digest as provenance.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
BINDING = PKG / "metadata/full801-shoreline-mechanism-binding.json"
WORKER = PKG / "workers/runup_mechanism_diagnostic.py"
H5_SUFFIXES = {".h5", ".hdf5", ".bi4", ".csv", ".vtk", ".dat", ".npy", ".npz"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def check_input_hashes(request: dict[str, Any]) -> int:
    checked = 0
    files = set(str(value) for value in request.get("input_files", []))
    hashes = request.get("input_sha256", {})
    require(isinstance(hashes, dict), "request input_sha256 must be an object")
    for raw_path in files:
        path = Path(raw_path)
        if raw_path.startswith("<"):
            continue
        require(path.exists(), f"request input is missing: {path}")
        if path.suffix.lower() in H5_SUFFIXES:
            # The value is copied from producer metadata only.  Do not open or hash it here.
            require(isinstance(hashes.get(raw_path), str) and len(hashes[raw_path]) == 64,
                    f"producer-declared science hash missing: {path}")
            continue
        expected = hashes.get(raw_path)
        if expected is None:
            continue
        require(path.is_file(), f"hashed input is not a file: {path}")
        require(sha(path) == expected, f"metadata input SHA mismatch: {path}")
        checked += 1
    return checked


def main() -> int:
    binding = load(BINDING)
    require(binding["schema"] == "ds02.f5.c082s1.full801-shoreline-mechanism-binding.fresh100.v1",
            "binding schema mismatch")
    require(binding["source_arrays_read_or_hashed_by_source_agent"] is False,
            "source array policy changed")
    require(binding["future_output_hashes"] is None, "future output hashes must remain null")
    require(binding["expected_counts"] == {
        "total": 194427, "fixed": 158559, "moving": 4210, "fluid": 31658, "floating": 0,
    }, "actual Root-bound counts changed")
    require(binding["native_bed_marker_mk"] == 50 and binding["source_mkbound"] == 40,
            "Mk mapping changed")
    require(len(binding["focus_frame_evidence"]) == 4, "focus metadata missing")
    require(len({int(row["frame"]) for row in binding["focus_frame_evidence"]}) == 4,
            "focus frames duplicated")

    compile(WORKER.read_text(encoding="utf-8"), str(WORKER), "exec")
    metadata_records = binding.get("metadata_records", [])
    require(metadata_records, "metadata records missing")
    checked_records = 0
    for entry in metadata_records:
        path = Path(str(entry["path"]))
        require(path.is_file(), f"metadata record missing: {path}")
        require(path.suffix.lower() not in H5_SUFFIXES, "science artifact entered metadata records")
        require(sha(path) == str(entry["sha256"]), f"metadata record SHA mismatch: {path}")
        checked_records += 1

    request_paths = sorted((PKG / "requests").glob("*.json"))
    require(len(request_paths) == 3, "fresh100 must contain exactly three disabled requests")
    checked_inputs = 0
    for path in request_paths:
        request = load(path)
        require(request.get("schema") == "ds02.runner-request.v2", f"request schema mismatch: {path}")
        require(request.get("kind") == "cpu" and request.get("cpu_task_kind") == "audit",
                f"request kind is outside the documented CPU audit contract: {path}")
        require(request.get("disabled") is True and request.get("launch") is False and
                request.get("launch_allowed") is False and request.get("execution_allowed") is False,
                f"request is not disabled: {path}")
        require(request.get("solver_allowed") is False and request.get("conversion_allowed") is False,
                f"request enables solver/conversion: {path}")
        require(request.get("future_output_hashes") is None and
                request.get("future_receipts_and_hashes") is None,
                f"future result was invented: {path}")
        require(request.get("independent_case_count_increment") == 0 and
                request.get("precision_granted") is False,
                f"acceptance boundary changed: {path}")
        checked_inputs += check_input_hashes(request)

    for path in sorted((PKG / "manifests").glob("*.json")):
        manifest = load(path)
        require(manifest["schema"] == "ds02.stage1.paraview-temporal-product.v1",
                f"renderer manifest schema mismatch: {path}")
        require(manifest["frames"] == 801 and manifest["particles"] == 194427,
                f"renderer dimensions mismatch: {path}")
        require(manifest["source_h5_sha256"] == binding["trajectory_h5_sha256"],
                f"manifest H5 provenance mismatch: {path}")
        require(manifest["xdmf_sha256"] == binding["xdmf_sha256"],
                f"manifest XMF provenance mismatch: {path}")
        require(manifest["camera_bounds_policy"].startswith("camera-only"),
                f"manifest camera policy changed: {path}")
        require(manifest["all_native_fluid_points_preserved_in_reader"] is True,
                f"manifest source preservation missing: {path}")
        times = manifest["actual_time_s"]
        require(len(times) == 801 and all(float(b) > float(a) for a, b in zip(times, times[1:])),
                f"manifest time axis is not strictly increasing: {path}")

    report = {
        "schema": "ds02.f5.c082s1.fresh100-source-preflight.v1",
        "status": "pass",
        "source_only": True,
        "jobs_started_by_source_agent": False,
        "shared_state_modified": False,
        "science_arrays_read_or_hashed_by_source_agent": False,
        "science_hashes_copied_only_from_producer_metadata": True,
        "metadata_records_checked": checked_records,
        "request_metadata_inputs_checked": checked_inputs,
        "request_count": len(request_paths),
        "worker_ast_compiles": True,
        "all_requests_disabled": True,
        "renderer": "Root023 verified renderer SHA 5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66",
        "case_credit": 0,
        "precision_granted": False,
        "full_event_runup_acceptance": "not evaluated",
    }
    out = PKG / "metadata/fresh100-preflight-report.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
