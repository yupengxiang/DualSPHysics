#!/usr/bin/env python3
"""Validate fresh102 JSON/XML closures without opening scientific payloads."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


RAW_SUFFIXES = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
STATIC_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt"}
GUARD = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object required: {path}")
    return value


def check_input_closure(request: dict[str, Any]) -> int:
    files = {str(Path(path).resolve()) for path in request.get("input_files", [])}
    hashes = {str(Path(path).resolve()): value for path, value in (request.get("input_sha256") or {}).items()}
    assert files == set(hashes), "input_files/input_sha256 mismatch"
    checked = 0
    for raw_path, expected in hashes.items():
        path = Path(raw_path)
        assert path.is_file(), f"missing input: {path}"
        assert isinstance(expected, str) and len(expected) == 64, f"invalid digest: {path}"
        suffix = path.suffix.lower()
        if suffix in RAW_SUFFIXES:
            # Fresh102 carries the prepared-report producer digest. It does
            # not open or rehash .dat/BI4/H5/CSV/VTK/XMF input.
            continue
        if suffix not in STATIC_SUFFIXES:
            # Official solver/PartVTK binaries have no metadata suffix. Their
            # digest is inherited from fresh100 and checked by Root at launch.
            continue
        assert sha(path) == expected, f"static input changed: {path}"
        checked += 1
    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    manifest = load(manifest_path)
    assert manifest["schema"] == "ds02.f2.stage1.fresh102.gencase-runtime-evidence-qa-manifest.v1"
    assert manifest["fresh_id"] == "fresh102" and manifest["family_id"] == "F2" and manifest["case_count"] == 16
    assert manifest["all_requests_disabled"] and manifest["future_hashes_null"]
    package = manifest_path.parent
    forbidden = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf"}
    assert not [path for path in package.rglob("*") if path.is_file() and path.suffix.lower() in forbidden], "scientific payload copied into source package"
    checked = 0
    qa_count = native_count = 0
    seen_cases: set[str] = set()
    for row in manifest["cases"]:
        cid = row["case_id"]
        assert cid not in seen_cases
        seen_cases.add(cid)
        sidecar_path = Path(row["runtime_evidence_sidecar"]["path"])
        sidecar = load(sidecar_path)
        assert sidecar["schema"] == "ds02.f2.stage1.fresh102.gencase-runtime-evidence.v1"
        assert sidecar["case_id"] == cid and sidecar["source_only"] and not sidecar["execution_allowed"]
        assert sidecar["raw_gencase_receipt"]["raw_receipt_immutable"]
        assert sidecar["raw_gencase_receipt"]["partition_counts_used_for_binding"] is False
        assert sidecar["contract_checks"]["raw_receipt_partition_not_used"]
        counts = sidecar["prepared_input_report"]["generated_xml_particle_counts"]
        assert sum(counts[key] for key in ("fixed", "moving", "floating", "fluid")) == sidecar["prepared_input_report"]["actual_total_particles"]
        assert sidecar["prepared_generated_xml"]["matches_prepared_report"]
        assert sidecar["motion_asset_provenance"]["read_or_hashed_here"] is False
        for key in ("initial_qa_request", "native_request"):
            request_path = Path(row[key]["path"])
            request = load(request_path)
            assert request["schema"] == "ds02.runner-request.v3"
            assert request["case_id"] == cid and request["disabled"] and not request["execution_allowed"] and not request["launch_allowed"]
            assert request["future_hashes_null"] and request["strict_guard_digest"] == GUARD
            assert request["strict_guard"]["runtime_v2"]["sha256"]
            assert request["strict_guard"]["strict_dispatch"]["sha256"]
            checked += check_input_closure(request)
            if key == "initial_qa_request":
                qa_count += 1
                assert request["kind"] == "cpu" and request["cpu_task_kind"] == "audit"
                assert request["depends_on_attempts"] == [row["gencase_attempt_id"]]
                assert request["gencase_receipt_sha256"] == row["gencase_receipt"]["sha256"]
                assert request["prepared_input_report_sha256"] == row["prepared_input_report"]["sha256"]
                assert request["prepared_generated_xml_sha256"] == row["prepared_generated_xml"]["sha256"]
                assert request["runtime_evidence_sidecar_sha256"] == row["runtime_evidence_sidecar"]["sha256"]
            else:
                native_count += 1
                assert request["kind"] == "qualification" and request["cpu_task_kind"] == "solver"
                assert request["depends_on_attempts"][0] == row["gencase_attempt_id"]
                assert request["depends_on_attempts"][1].endswith("-prepared-report-qa-102")
                assert request["expected_output"]["frame_count"] == 401
                assert request["expected_output"]["full_window_s"] == 4.0
                assert request["expected_output"]["save_interval_s"] == 0.01
                assert all("mdbc" not in arg and "noslip" not in arg for arg in request["command"])
                assert request["gencase_receipt_sha256"] == row["gencase_receipt"]["sha256"]
                assert request["initial_qa_report_sha256"] is None
    assert seen_cases == {row["case_id"] for row in manifest["cases"]}
    assert qa_count == native_count == 16
    print(json.dumps({"status": "pass", "cases": len(seen_cases), "initial_qa_requests": qa_count, "native_requests": native_count, "static_metadata_hashes_checked": checked, "scientific_payloads_read": []}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
