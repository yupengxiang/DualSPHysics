#!/usr/bin/env python3
"""Validate the fresh092 source handoff without opening scientific payloads.

This validator checks the request/worker contract and the producer metadata
closure.  It hashes only JSON, XML and source files listed as static inputs;
BI4/H5/VTK/CSV files may occur only as deferred producer inputs and are never
opened, hashed, copied or decoded here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parents[1]
RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv"}
STATIC_SUFFIXES = {".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log"}
HEX = set("0123456789abcdef")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    if path.suffix.lower() in RAW_SUFFIXES:
        raise AssertionError(f"scientific payload hash attempted: {path}")
    if path.suffix.lower() not in STATIC_SUFFIXES:
        raise AssertionError(f"non-static input in hash closure: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def main() -> int:
    manifest = load(HERE / "F4_STAGE1_FRESH092_ACTUAL_GENCASE_ROOT237_INITIAL_QA_BIND_MANIFEST.json")
    plan = load(HERE / "metadata/fresh092-actual-gencase-plan.json")
    binding = load(HERE / "metadata/fresh092-actual-gencase-binding.json")
    interface = load(HERE / "metadata/root237-interface-contract.json")
    partvtk = load(HERE / "metadata/partvtk-binary-contract.json")
    future = load(HERE / "evidence/future-native-plan.json")
    closure = load(HERE / "evidence/source-static-closure.json")

    check(manifest["case_count"] == 24, "manifest case count")
    check(plan["case_count"] == 24 and len(plan["cases"]) == 24, "plan case count")
    case_ids = [str(row["endpoint_id"]) for row in plan["cases"]]
    check(len(set(case_ids)) == 24, "plan identities are not unique")
    check(manifest["actual_gencase_completed0"] == 24, "actual GenCase completion count")
    check(manifest["initial_qa_requests"] == 24 and manifest["all_requests_disabled"] is True, "QA request summary")
    check(manifest["future_qa_hashes"] is None and manifest["future_native_hashes"] is None, "future hashes must be null")
    check(binding["aggregate_execution_receipt"]["status"] == "not_applicable", "aggregate receipt must remain unpromoted")
    check(binding["aggregate_execution_receipt"]["preserved_without_promotion"] is True, "aggregate provenance")
    rows = {str(row["endpoint_id"]): row for row in binding["per_case_actual_gencase_receipts"]}
    check(set(rows) == set(case_ids) and len(rows) == 24, "per-case binding identities")
    check(interface["binding_keys"]["row"] == ["endpoint_id", "gencase_receipt", "generated_xml", "generated_bi4", "solver_dimension_from_gencase", "total_particles", "fluid_particles"], "row contract")
    check(interface["audit_argv"] == ["audit", "--metadata", "--prefix", "--output"], "audit argv contract")
    check(interface["source_reads_or_hashes_bi4"] is False and interface["source_reads_or_hashes_h5"] is False, "source payload policy")
    check(partvtk["registered_sha256"] == "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e", "PartVTK producer SHA")
    check(partvtk["source_read_or_hashed"] is False and partvtk["root_job_must_validate"] is True, "PartVTK deferred policy")
    check(len(future["cases"]) == 24 and future["solver_launches_by_source"] == 0, "future native plan")
    for row in future["cases"]:
        check(row["status"] == "future_disabled_until_initial_qa_pass", f"future native status: {row['case_id']}")
        check(row["native_request"] is None and row["execution_receipt"] is None and row["output_hashes"] is None, f"future native output: {row['case_id']}")

    closure_files = closure["files"]
    check(str(HERE / "metadata/root237-interface-contract.json") in closure_files, "interface contract missing from static closure")
    check(str(HERE / "metadata/partvtk-binary-contract.json") in closure_files, "PartVTK contract missing from static closure")
    check(closure["scientific_payloads"] == [] and closure["bi4_read_or_hashed_by_source"] is False, "static closure payload policy")
    for raw_path, recorded in closure_files.items():
        path = Path(raw_path)
        check(path.suffix.lower() not in RAW_SUFFIXES, f"raw payload in static closure: {path}")
        check(path.is_file(), f"static closure path missing: {path}")
        check(recorded == sha(path), f"static closure digest drift: {path}")

    requests = sorted((HERE / "requests").glob("*-initial-native-qa-disabled.request.json"))
    check(len(requests) == 24, "request count")
    for request_path in requests:
        request = load(request_path)
        case_id = str(request["case_id"])
        check(case_id in rows, f"request case not bound: {case_id}")
        row = rows[case_id]
        check(request["disabled"] is True and request["execution_allowed"] is False and request["launch_allowed"] is False and request["launch"] is False, f"request disabled state: {case_id}")
        check(request["source_only"] is True and request["no_jobs_started_by_source"] is True and request["no_shared_registry_write"] is True, f"source-only state: {case_id}")
        check(request["launch_owner"] == "root" and request["root_only"] is True, f"root ownership: {case_id}")
        check(request["kind"] == "cpu" and request["cpu_task_kind"] == "audit" and request["cpu_threads"] == 2, f"CPU audit contract: {case_id}")
        check(request["physical_condition_sha256"] == row["physical_condition_sha256"], f"condition binding: {case_id}")
        check(request["depends_on_attempts"] == [row["gencase_receipt"]["path"].split("/")[-2]], f"GenCase dependency: {case_id}")
        command = request["command"]
        check(command == request["worker_argv_contract"]["argv_exact"], f"argv closure: {case_id}")
        check("--case-id" in command and command[-1] == case_id, f"case-specific argv: {case_id}")
        check(request["worker_argv_contract"]["accessed_binding_keys"] == interface["binding_keys"], f"accessed binding keys: {case_id}")
        check(request["worker_argv_contract"]["audit_argv"] == interface["audit_argv"], f"audit argv: {case_id}")

        static_inputs = request["input_files"]
        static_hashes = request["input_sha256"]
        check(set(static_inputs) == set(static_hashes), f"static input hash closure: {case_id}")
        for raw_path, recorded in static_hashes.items():
            path = Path(raw_path)
            check(path.suffix.lower() not in RAW_SUFFIXES, f"raw payload in request input: {path}")
            check(path.is_file(), f"request static input missing: {path}")
            check(recorded == sha(path), f"request static digest drift: {path}")
        deferred = request["deferred_input_files"]
        deferred_hashes = request["deferred_input_sha256"]
        check(any(path.endswith(".bi4") for path in deferred), f"BI4 not deferred: {case_id}")
        check(str(Path(partvtk["path"])) in deferred, f"PartVTK not deferred: {case_id}")
        check(set(deferred) == set(deferred_hashes) and all(value is None for value in deferred_hashes.values()), f"deferred hashes: {case_id}")
        producer_files = request["producer_input_files"]
        producer_hashes = request["producer_input_sha256"]
        check(producer_files == [row["generated_bi4"]["path"]], f"producer BI4 path: {case_id}")
        check(producer_hashes == {row["generated_bi4"]["path"]: row["generated_bi4"]["producer_sha256"]}, f"producer BI4 attestation: {case_id}")
        evidence = request["gencase_actual_evidence"]
        check(evidence["generated_bi4_producer_sha256"] == row["generated_bi4"]["producer_sha256"], f"evidence BI4 attestation: {case_id}")
        check(evidence["solver_dimension_from_gencase"] == 3 and evidence["total_particles"] == 83233 and evidence["fluid_particles"] == 59072, f"actual GenCase evidence: {case_id}")
        check(request["future_initial_qa_receipt"] is None and request["future_native_receipt"] is None, f"future receipt fields: {case_id}")
        check(request["expected_outputs"]["execution_receipt"] is None and request["expected_outputs"]["initial_native_qa_index"] is None, f"future output fields: {case_id}")
        check(request["arrays_read_by_source"] is False and request["bi4_read_by_source"] is False, f"source array policy: {case_id}")
        check(request["partvtk_binary"]["producer_sha256"] == partvtk["registered_sha256"], f"PartVTK request attestation: {case_id}")
        check(valid_sha(row["generated_bi4"]["producer_sha256"]), f"BI4 producer digest shape: {case_id}")

    print(json.dumps({
        "schema": "ds02.f4.fresh092.source-validation.v1",
        "status": "pass",
        "cases": 24,
        "disabled_initial_qa_requests": 24,
        "actual_gencase_completed0": 24,
        "static_input_hashes_checked": True,
        "scientific_payloads_opened_or_hashed": False,
        "future_native_requests": 0,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"schema": "ds02.f4.fresh092.source-validation.v1", "status": "failed", "error_type": type(error).__name__, "error": str(error)}, sort_keys=True))
        raise
