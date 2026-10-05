#!/usr/bin/env python3
"""Source-only contract checks for the Root237 -> Root230 handoff."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARRAY_SUFFIXES = {".bi4", ".h5", ".vtk", ".csv"}
REQUIRED_MANIFEST_ROLES = {
    "canonical_owner", "metadata", "source_definition", "source_plan", "source_build_receipt",
    "registered_root_index", "actual_gencase_binding", "actual_gencase_receipt",
    "actual_prepared_input_report", "generated_xml", "generated_bi4", "qa_execution_receipt",
    "qa_index", "qa_binding", "qa_case_report", "qa_case_metadata", "source_qa_worker",
    "official_audit", "native_label_decoder", "root237_worker", "root237_contract_repair",
    "root236_worker", "root236_child_preflight", "f2_mass_audit", "safe_bi4_decoder",
    "root230_entry", "root230_home_policy", "root230_gpu_policy", "root230_contract",
    "runtime", "strict_dispatch", "resource_window", "solver_binary",
}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def test_package_contract() -> None:
    index = load(ROOT / "requests/index.json")
    assert index["schema"] == "ds02.f4.root237-root230-full1201-request-index.v1"
    assert index["case_count"] == 6
    assert index["launch_allowed"] is False
    assert index["independent_case_count_increment"] == 0
    assert index["qa_provider"]["status"] == "completed_pass"
    assert index["qa_provider"]["attempt_id"].endswith("-237")

    evidence = load(ROOT / "evidence/root235-root236-root237-status.json")
    assert evidence["root235"]["status"] == "failed"
    assert evidence["root235"]["returncode"] == 1
    assert evidence["root236"]["status"] == "failed"
    assert evidence["root236"]["returncode"] == 1
    assert evidence["root237"]["status"] == "completed_pass"
    assert evidence["root237"]["pass"] is True
    assert evidence["root216_negative_evidence_preserved"]["preserve_without_promotion"] is True

    rows = load(ROOT / "source-binding.json")["rows"]
    assert len(rows) == 6
    for row in rows:
        request_path = Path(row["request"])
        assert sha(request_path) == row["request_sha256"]
        manifest_path = Path(row["manifest"])
        assert sha(manifest_path) == row["manifest_sha256"]

        request = load(request_path)
        assert request["kind"] == "qualification"
        assert request["cpu_task_kind"] == "native_solver"
        assert request["launch"] is False
        assert request["launch_allowed"] is False
        assert request["execution_allowed"] is False
        assert request["launch_owner"] == "root"
        assert request["status"] == "source_only_disabled"
        assert request["independent_case_count_increment"] == 0
        assert request["root_gpu_selection_profile"] == "root_live_all_idle_uuid_leased_eight_solver_v2"
        assert request["root_solver_concurrency_cap"] == 8
        assert request["root_dataset_inventory_profile"] == "root_home_floor_no_legacy_dataset_walk_native_v1"
        assert request["root_home_free_gib_floor"] == 500
        assert request["root_nvme_free_gib_floor"] == 100
        assert request["root_nvme_peak_gib"] == 24
        assert request["command"][-2:] == ["-tmax:1.2", "-tout:0.001"]
        assert request["solver_recipe"]["native_frame_count"] == 1201
        assert request["native_initial_qa"]["provider_attempt_id"].endswith("-237")
        assert request["native_initial_qa"]["status"] == "completed_pass"
        assert request["native_initial_qa"]["pass"] is True
        assert request["gencase_receipt_sha256"]
        assert request["expected_outputs"]["execution_receipt_sha256"] is None
        assert request["expected_outputs"]["all_future_sha256"] is None
        assert all(Path(value).suffix.lower() not in ARRAY_SUFFIXES for value in request["input_files"])
        assert all(value is not None for value in request["input_sha256"].values())
        assert request["deferred_input_sha256"][request["deferred_input_files"][1]] is None
        assert request["deferred_bi4_producer_sha256"][request["deferred_input_files"][1]]

        manifest = load(manifest_path)
        assert set(entry["role"] for entry in manifest["entries"]) == REQUIRED_MANIFEST_ROLES
        bi4 = next(entry for entry in manifest["entries"] if entry["role"] == "generated_bi4")
        assert bi4["expected_sha256"] is None
        assert bi4["producer_sha256"]
        assert bi4["read_by_source"] is False
        assert manifest["arrays_read_by_source"] is False

    child_index = load(ROOT / "evidence/child-input-preflight-index.json")
    assert child_index["case_count"] == 6
    assert child_index["arrays_read_by_source"] is False
    assert all(row["status"] == "completed" and row["entry_count"] == 33 for row in child_index["rows"])


def test_workers_are_metadata_only() -> None:
    for path in (ROOT / "workers").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    preflight = (ROOT / "workers/preflight_f4_root237_child_inputs_v1.py").read_text(encoding="utf-8")
    assert "read_policy" in preflight
    assert "stat_only_producer_digest_no_open_no_rehash" in preflight
    assert "numpy" not in preflight and "memmap" not in preflight
    builder = (ROOT / "workers/build_f4_root237_full1201_bindings_v1.py").read_text(encoding="utf-8")
    assert "Root237" in builder and "Root230" in builder
    tree = ast.parse(builder)
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and any(alias.name == "subprocess" for alias in node.names) for node in tree.body)
    assert "subprocess." not in builder


if __name__ == "__main__":
    test_package_contract()
    test_workers_are_metadata_only()
    print("fresh089 contract: PASS")
