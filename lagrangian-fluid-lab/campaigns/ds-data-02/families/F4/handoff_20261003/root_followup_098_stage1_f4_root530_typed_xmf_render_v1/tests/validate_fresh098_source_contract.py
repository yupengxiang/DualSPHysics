#!/usr/bin/env python3
"""Static fresh098 contract checks; no scientific payload access."""

from __future__ import annotations

import json
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def test_fresh098_static_contract() -> None:
    source = load(PACKAGE / "source-binding.json")
    index = load(PACKAGE / "requests/index.json")
    frame = load(PACKAGE / "evidence/root530-frame0-snapshot.json")
    typed = load(PACKAGE / "evidence/root533-typed-snapshot.json")

    assert source["case_count"] == 24
    assert index["request_count"] == 48
    assert index["launch_allowed"] is False
    assert source["arrays_read_by_source"] is False
    assert source["jobs_started_by_source"] is False
    assert source["shared_registry_write_by_source"] is False
    assert len(frame["cases"]) == 24
    assert all(row["status"] == "completed_pass" for row in frame["cases"])
    assert len(typed["cases"]) == 24

    requests = []
    for path in sorted((PACKAGE / "requests").glob("*.request.json")):
        request = load(path)
        requests.append(request)
        assert request["disabled"] is True
        assert request["launch"] is False
        assert request["launch_allowed"] is False
        assert request["execution_allowed"] is False
        assert request["source_only"] is True
        assert request["arrays_read_by_source"] is False
        assert request["jobs_started_by_source"] is False
        assert request["shared_registry_write_by_source"] is False
        assert request["input_files"]
        for input_path in request["input_files"]:
            assert Path(input_path).suffix.lower() not in RAW_SUFFIXES, input_path
        for value in request["deferred_input_sha256"].values():
            assert value is None
        assert request["expected_outputs"]["all_sha256"] is None
        assert request["physical_condition_sha256"] != request["source_owner_physical_condition_sha256"]

    assert len(requests) == 48
    assert {request["cpu_task_kind"] for request in requests} == {"conversion", "audit"}
    assert all(request["future_sha256_values"].startswith("null") for request in requests)

    binding_files = sorted((PACKAGE / "bindings").glob("*.json"))
    assert len(binding_files) == 72
    for path in binding_files:
        binding = load(path)
        assert binding["arrays_read_by_source"] is False
        assert binding["jobs_started_by_source"] is False
        if "future_output_hashes" in binding:
            assert all(value is None for value in binding["future_output_hashes"].values())
        if "actual_converter_scope" in binding:
            scope = binding["actual_converter_scope"]
            assert scope["source_owner_sha256_must_not_be_reused_as_converter_scope"] is True
            assert scope["legacy_scope_hash"] != scope["source_owner_physical_condition_sha256"]
        if path.name.endswith("-xmf-binding.json"):
            assert binding["vector_contract"]["semantic_type"] == "N3"
            assert binding["expected_frames"] == 1201
            assert binding["expected_dimension"] == 3
            assert binding["typed_gate"]["receipt_only_is_insufficient"] is True


if __name__ == "__main__":
    test_fresh098_static_contract()
    print("fresh098 static contract: PASS")
