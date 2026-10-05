#!/usr/bin/env python3
"""Metadata-only validator for F4 fresh093 Root230 disabled native handoff."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

RAW = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv"}


def load(path: Path) -> dict:
    if path.suffix.lower() in RAW:
        raise AssertionError(f"raw payload loaded: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"metadata object required: {path}")
    return value


def sha(path: Path) -> str:
    if path.suffix.lower() in RAW:
        raise AssertionError(f"raw payload hashed: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    package = Path(__file__).resolve().parents[1]
    manifest = load(package / "F4_STAGE1_FRESH093_FUTURE_ROOT237_QA_TO_ROOT230_NATIVE_BIND_MANIFEST.json")
    plan = load(package / "metadata/fresh093-native-plan.json")
    binding = load(package / "metadata/fresh093-native-binding.json")
    index = load(package / "evidence/request-index.json")
    gate = load(package / "metadata/fresh092-qa-consumer-gate.json")
    closure = load(package / "evidence/source-static-closure.json")
    assert manifest["case_count"] == plan["case_count"] == binding["native_request_count"] == index["case_count"] == 24
    assert manifest["all_requests_disabled"] is True and index["launch_allowed"] is False
    assert plan["stage1_gate"]["required_result"] == "per_case actual native-input structural QA pass"
    assert plan["stage1_gate"]["strict_root237_result_is_not_a_substitute"] is True
    assert gate["case_selection"]["one_row_binding_view_required"] is True
    assert gate["strict_diagnostic_boundary"]["precision_status"] == "not_accepted"
    assert gate["strict_diagnostic_boundary"]["fallback_stage1_gate"].endswith("root_followup_094_stage1_f4_basic_native_input_qa_v1/F4_STAGE1_FRESH094_BASIC_NATIVE_INPUT_QA_MANIFEST.json")
    for row in index["rows"]:
        request = load(Path(row["request"]["path"]))
        assert request["case_id"] == row["case_id"]
        assert request["kind"] == "qualification" and request["cpu_task_kind"] == "native_solver"
        assert request["disabled"] is True and request["launch"] is False and request["execution_allowed"] is False
        assert request["launch_owner"] == "root" and request["root_only"] is True
        assert request["native_initial_qa"]["fresh094_stage1_gate"]["required"] is True
        assert request["native_initial_qa"]["fresh094_stage1_gate"]["pass"] is None
        assert request["native_initial_qa"]["fresh094_stage1_gate"]["sha256"] is None
        assert request["frame0_velocity_audit"]["pass"] is None
        assert request["expected_outputs"]["execution_receipt_sha256"] is None
        assert request["expected_outputs"]["all_future_sha256"] is None
        assert request["precision_status"] == "not_accepted"
        assert request["q_n_status"] == "not_assessed"
        assert request["no_jobs_started_by_source"] is True and request["no_shared_registry_write"] is True
        for path_string in request["input_files"]:
            assert Path(path_string).suffix.lower() not in RAW, f"raw payload in active native inputs: {path_string}"
        deferred = request["deferred_input_sha256"]
        assert any(str(path).endswith(".bi4") and value is None for path, value in deferred.items())
        assert any(str(path).endswith(".xml") and isinstance(value, str) and len(value) == 64 for path, value in deferred.items())
    assert closure["scientific_payloads"] == []
    assert closure["bi4_read_or_hashed_by_source"] is False
    print(json.dumps({"schema": "ds02.f4.fresh093.source-contract-validation.v1", "status": "pass", "case_count": 24, "all_native_requests_disabled": True, "fresh094_stage1_gate_bound": True, "strict_root237_not_promoted": True, "science_payloads_read_or_hashed": False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
