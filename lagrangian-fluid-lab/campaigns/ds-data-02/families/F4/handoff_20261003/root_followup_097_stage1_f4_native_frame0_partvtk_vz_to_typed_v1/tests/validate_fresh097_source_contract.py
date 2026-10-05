#!/usr/bin/env python3
"""Metadata-only validation for F4 fresh097.

This validator intentionally does not call the shared runtime, PartVTK,
converter, or any scientific decoder.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv", ".dat"}


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    if path.suffix.lower() in RAW_SUFFIXES:
        raise AssertionError(f"scientific payload encountered in source validator: {path}")
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def check_request(path: Path, expected_kind: str) -> dict:
    request = load(path)
    assert request["schema"] == "ds02.runner-request.v2"
    assert request["family_id"] == "F4"
    assert request["kind"] == "cpu"
    assert request["cpu_task_kind"] == expected_kind
    assert request["disabled"] is True
    assert request["execution_allowed"] is False
    assert request["launch"] is False
    assert request["launch_allowed"] is False
    assert request["source_only"] is True
    assert request["launch_owner"] == "root"
    files = [Path(value).resolve() for value in request["input_files"]]
    assert files
    for path_value in files:
        assert path_value.suffix.lower() not in RAW_SUFFIXES, path_value
        assert path_value.is_file(), path_value
        assert str(path_value) in request["input_sha256"], path_value
        assert digest(path_value) == request["input_sha256"][str(path_value)], path_value
    assert set(request["input_sha256"]) == {str(path_value) for path_value in files}
    assert request.get("arrays_read_by_source") is False
    assert request.get("jobs_started_by_source") is False
    assert request.get("shared_registry_write_by_source") is False
    return request


def main() -> None:
    manifest = load(PACKAGE / "metadata/fresh097-manifest.json")
    assert manifest["schema"] == "ds02.f4.fresh097.manifest.v1"
    assert manifest["case_count"] == 24
    assert manifest["source_only"] is True
    assert manifest["scientific_payloads_read_or_hashed"] is False
    frame = manifest["frame0_requests"]
    typed = manifest["typed_requests"]
    assert len(frame) == len(typed) == 24
    statuses = []
    for row in frame:
        request = check_request(Path(row["path"]), "audit")
        binding = load(Path(row["binding"]))
        assert binding["source_only"] is True and binding["execution_allowed"] is False
        assert binding["case_id"] == request["case_id"]
        assert binding["native_solver_status"] in {"completed/0", "WAIT"}
        if binding["native_solver_status"] == "completed/0":
            assert binding["native_solver_receipt"]
            assert binding["native_solver_receipt_sha256"]
        else:
            assert binding["native_solver_receipt"] is None
            assert binding["native_solver_receipt_sha256"] is None
        statuses.append(binding["native_solver_status"])
        assert request["native_frame0_audit_contract"]["future_report_sha256"] is None
    for row in typed:
        request = check_request(Path(row["path"]), "conversion")
        binding = load(Path(row["binding"]))
        assert binding["source_only"] is True and binding["execution_allowed"] is False
        assert binding["case_id"] == request["case_id"]
        assert binding["actual_converter_scope"]["canonical_hash"] is None
        assert binding["actual_converter_scope"]["legacy_scope_hash"] is None
        assert all(value is None for value in binding["future_hashes"].values())
        assert request["frame0_velocity_audit"]["status"] == "WAIT"
        assert request["frame0_velocity_audit"]["report_sha256"] is None
        assert all(value is None for value in request["output_contract"].values()
                   if "sha" in str(value).lower())
    assert manifest["root471_negative_preserved"] is True
    assert manifest["root500_history_preserved"] is True
    print(json.dumps({
        "schema": "ds02.f4.fresh097.source-contract-validation.v1",
        "case_count": 24,
        "native_completed0_count": statuses.count("completed/0"),
        "native_wait_count": statuses.count("WAIT"),
        "all_requests_disabled": True,
        "future_hashes_null": True,
        "scientific_payloads_read_or_hashed": False,
        "status": "pass",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
