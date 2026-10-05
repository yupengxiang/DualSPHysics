#!/usr/bin/env python3
"""Metadata-only validator for the F4 fresh096 disabled native handoff."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

RAW = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv", ".dat"}


def load(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW:
        raise AssertionError(f"scientific payload loaded: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def digest(path: Path) -> str:
    path = Path(path).resolve()
    assert path.suffix.lower() not in RAW, path
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    package = Path(__file__).resolve().parents[1]
    manifest = load(package / "F4_STAGE1_FRESH096_ROOT502_BASICQA_TO_ROOT230_NATIVE_BIND_MANIFEST.json")
    plan = load(package / "metadata/fresh096-native-plan.json")
    binding = load(package / "metadata/fresh096-native-binding.json")
    root502 = load(package / "metadata/fresh096-root502-basicqa-evidence.json")
    stage = load(package / "metadata/fresh096-stage-contract.json")
    root230 = load(package / "metadata/fresh096-root230-contract.json")
    post_native = load(package / "metadata/fresh096-post-native-fresh094-contract.json")
    index = load(package / "evidence/request-index.json")
    closure = load(package / "evidence/source-static-closure.json")

    assert manifest["case_count"] == plan["case_count"] == binding["native_request_count"] == index["case_count"] == 24
    assert manifest["actual_root502_basicQA_completed0"] == 24
    assert manifest["all_requests_disabled"] is True and index["launch_allowed"] is False
    assert root502["actual_basicQA_completed0"] == 24 and root502["all_actual_basic_checks_true"] is True
    assert root502["old500_old501_failures_preserved"] is True
    assert root502["old471_strict_negative_preserved"] is True
    assert stage["native_gate"]
    assert stage["post_native"]["status"] == "future"
    assert post_native["required_phase"].startswith("after matching full1201 native receipt")
    assert post_native["pass"] is None
    assert root230["cpu_threads"] == root230["omp_threads"] == 2
    assert root230["native_recipe"]["native_frame_count"] == 1201
    assert root230["native_recipe"]["solver_options"] == ["-tmax:1.2", "-tout:0.001"]
    assert root230["uuid_policy"].startswith("Root resolves")

    for row in index["rows"]:
        case_id = row["case_id"]
        request = load(Path(row["request"]["path"]))
        assert request["case_id"] == case_id
        assert request["kind"] == "qualification" and request["cpu_task_kind"] == "native_solver"
        assert request["disabled"] is True and request["launch"] is False and request["execution_allowed"] is False
        assert request["launch_owner"] == "root" and request["root_only"] is True
        assert request["cpu_threads"] == 2
        assert request["command"][-2:] == ["-tmax:1.2", "-tout:0.001"]
        assert "-mdbc" not in " ".join(request["command"]).lower()
        assert request["solver_recipe"]["native_frame_count"] == 1201
        assert request["solver_recipe"]["no_mdbc"] is True and request["solver_recipe"]["no_forcing"] is True
        assert request["expected_outputs"]["full_native_frames"] == 1201
        assert request["expected_outputs"]["all_future_sha256"] is None
        assert request["frame0_velocity_audit"]["pass"] is None
        assert request["frame0_velocity_audit"]["post_native_contract"]["path"].endswith("root_followup_094_stage1_f4_basic_native_input_qa_v1/F4_STAGE1_FRESH094_BASIC_NATIVE_INPUT_QA_MANIFEST.json")
        gate = request["native_initial_qa"]
        assert gate["status"] == "completed_pass" and gate["pass"] is True and gate["checks_all_true"] is True
        assert gate["raw_mk_type_observed"] is False
        assert gate["strict_root471_is_not_substitute"] is True and gate["old500_old501_not_substitute"] is True
        assert gate["report"]["path"].endswith("gencase-basic-initial-qa.json")
        assert all("fresh094" not in attempt for attempt in request["depends_on_attempts"])
        assert len(request["depends_on_attempts"]) == 2
        assert request["native_initial_qa"]["attempt_id"] == request["depends_on_attempts"][1]
        assert request["gencase_actual_evidence"]["solver_dimension_from_gencase"] == 3
        assert request["gencase_actual_evidence"]["generated_bi4"]["content_rehashed_by_source"] is False
        assert request["deferred_input_sha256"][request["deferred_input_files"][1]] is None
        assert request["deferred_input_files"][1].endswith(".bi4")
        assert request["physical_condition_sha256"] and len(request["physical_condition_sha256"]) == 64
        assert set(request["input_files"]) == set(request["input_sha256"])
        for path_string, expected in request["input_sha256"].items():
            path = Path(path_string)
            assert path.suffix.lower() not in RAW, f"raw payload in source input: {path}"
            assert path.is_file(), path
            assert digest(path) == expected, path
        for path_string in request["deferred_input_files"]:
            assert Path(path_string).suffix.lower() in {".xml", ".bi4"}
        assert row["future_native_receipt_sha256"] is None and row["future_frame0_sha256"] is None

    assert closure["scientific_payloads"] == []
    assert closure["deferred_scientific_payloads"]["bi4_content_read_or_hashed_by_source"] is False
    assert closure["root230_native_receipts_bound"] == 0
    print(json.dumps({
        "schema": "ds02.f4.fresh096.source-contract-validation.v1",
        "status": "pass",
        "case_count": 24,
        "root502_basicqa_completed0_bound": 24,
        "all_native_requests_disabled": True,
        "root500_root501_failures_preserved": True,
        "fresh094_post_native_only": True,
        "native_frame_count": 1201,
        "future_hashes_null": True,
        "science_payloads_read_or_hashed": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
