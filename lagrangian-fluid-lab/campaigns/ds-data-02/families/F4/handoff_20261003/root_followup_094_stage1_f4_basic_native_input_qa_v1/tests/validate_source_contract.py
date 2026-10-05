#!/usr/bin/env python3
"""Metadata-only validator for F4 fresh094 disabled requests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

RAW = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv"}
HEX = set("0123456789abcdef")


def fail(message: str) -> None:
    raise AssertionError(message)


def load(path: Path) -> dict:
    if path.suffix.lower() in RAW:
        fail(f"raw scientific payload loaded: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"metadata object required: {path}")
    return value


def sha(path: Path) -> str:
    if path.suffix.lower() in RAW:
        fail(f"raw scientific payload hashed: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    package = Path(__file__).resolve().parents[1]
    manifest = load(package / "F4_STAGE1_FRESH094_BASIC_NATIVE_INPUT_QA_MANIFEST.json")
    index = load(package / "evidence/request-index.json")
    contract = load(package / "metadata/fresh094-stage1-contract.json")
    strict = load(package / "metadata/root470-strict-diagnostic-negative.json")
    closure = load(package / "evidence/source-static-closure.json")
    worker = package / "workers/run_f4_fresh094_stage1_native_input_qa.py"
    assert manifest["schema"] == "ds02.f4.fresh094.manifest.v1"
    assert index["schema"] == "ds02.f4.fresh094.request-index.v1"
    assert manifest["case_count"] == index["case_count"] == 24
    assert manifest["all_requests_disabled"] is True and index["all_disabled"] is True and index["launch_allowed"] is False
    assert contract["not_stage1_gates"] == ["native mass equals nominal continuum", "exact continuum center/lattice", "strict continuum center bounds", "saved frame-0 velocity", "precision", "Q-N", "production", "visual"]
    strict_ref = contract["root470_strict_diagnostic"]
    assert strict_ref["status"] == "negative_diagnostic_only" and len(strict_ref["sha256"]) == 64
    assert strict_ref["sha256"] == sha(Path(strict_ref["path"]))
    assert strict["pass"] is False and strict["returncode"] == 1
    assert strict["checks"]["all_source_population_checks"] is False
    rows = index["rows"]
    assert len(rows) == 24 and len({row["case_id"] for row in rows}) == 24
    expected_request_names = {Path(row["request"]).name for row in rows}
    assert len(expected_request_names) == 24
    for row in rows:
        request_path = Path(row["request"])
        binding_path = Path(row["binding"])
        request = load(request_path)
        binding = load(binding_path)
        assert request["schema"] == "ds02.runner-request.v2"
        assert request["case_id"] == row["case_id"] == binding["case_id"]
        assert request["cpu_task_kind"] == "audit"
        assert request["disabled"] is True and request["launch"] is False and request["execution_allowed"] is False and request["source_only"] is True
        assert request["launch_owner"] == "root" and request["root_only"] is True and request["independent_case_count_increment"] == 0
        assert "run_f4_fresh094_stage1_native_input_qa.py" in " ".join(request["command"])
        assert "{native_frame0_sha256}" in request["command"]
        assert binding["schema"] == "ds02.f4.fresh094.stage1-native-input-binding.v1"
        assert binding["execution_allowed"] is False and binding["source_only"] is True
        assert binding["expected"]["total_particles"] == 83233
        assert binding["expected"]["fixed_particles"] == 24161
        assert binding["expected"]["fluid_particles"] == 59072
        assert binding["expected"]["solver_dimension"] == 3
        assert set(binding["expected"]["sources"]) == {"drop", "pool"}
        assert binding["decoder"]["registered_sha256"] == "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
        assert request["stage1_qa_contract"]["pass"] is None
        assert request["stage1_qa_contract"]["saved_frame0_velocity_audit"]["pass"] is None
        assert request["stage1_qa_contract"]["native_mass_vs_nominal_continuum"] == "report_separately_without_rescale"
        assert request["stage1_qa_contract"]["strict_precision"] == "diagnostic_only"
        assert request["stage1_qa_contract"]["q_n_status"] == "not_assessed"
        assert request["expected_outputs"]["future_report_sha256"] is None
        assert request["deferred_input_sha256"][next(key for key in request["deferred_input_sha256"] if key.endswith("Part_0000.bi4"))] is None
        for path_string in request["input_files"]:
            assert Path(path_string).suffix.lower() not in RAW, f"raw payload in active input files: {path_string}"
        for path_string in request["deferred_input_files"]:
            assert Path(path_string).suffix.lower() in RAW or path_string.endswith("execution-receipt.json")
        for path_string, digest in request["input_sha256"].items():
            path = Path(path_string)
            assert path.is_file(), path
            if path == Path(binding["decoder"]["path"]):
                assert digest == binding["decoder"]["registered_sha256"]
            else:
                assert sha(path) == digest, f"input digest drift: {path}"
        assert row["native_frame0_sha256"] is None and row["qa_report_sha256"] is None
    assert closure["scientific_payloads_opened_or_hashed_by_source"] == []
    assert closure["native_frame0_hashes"] is None
    assert closure["registered_gencase_bi4_producer_digests_bound"] == 24
    assert closure["strict_root470"]["sha256"] == strict_ref["sha256"]
    print(json.dumps({"schema": "ds02.f4.fresh094.source-contract-validation.v1", "status": "pass", "case_count": 24, "all_disabled": True, "strict_root470_preserved_negative": True, "science_payloads_read_or_hashed": False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"schema": "ds02.f4.fresh094.source-contract-validation.v1", "status": "failed", "error_type": type(error).__name__, "error": str(error)}, sort_keys=True))
        raise
