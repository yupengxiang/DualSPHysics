#!/usr/bin/env python3
"""Source-only contract validator for F1 fresh086.

It reads JSON/XML and hashes small source/request files.  Registered GenCase
BI4 bytes are never opened or rehashed here; their producer-recorded digest is
checked against the binding and request closure.  No runner, GenCase, PartVTK,
solver, ledger, or shared registry is invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REQUESTS = HERE / "requests"
CASES = [
    "F1_STAGE1_DUAL_H240_DP020", "F1_STAGE1_DUAL_H240_DP020_VX010",
    "F1_STAGE1_DUAL_H280_DP020", "F1_STAGE1_DUAL_H320_DP020",
    "F1_STAGE1_ECC_H120_DP010", "F1_STAGE1_ECC_H140_DP010",
    "F1_STAGE1_ECC_H160_DP010", "F1_STAGE1_ECC_H180_DP010",
]
ARRAY_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON: {path}") from exc
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    require(path.suffix.lower() not in ARRAY_SUFFIXES, f"scientific array opened by validator: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_small_inputs(request: dict[str, Any], label: str, producer_digests: dict[str, str]) -> None:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    require(isinstance(files, list) and isinstance(hashes, dict), f"{label}: input closure missing")
    require(set(files) == set(hashes), f"{label}: input hash keys differ from files")
    for raw in files:
        path = Path(raw)
        require(path.is_file(), f"{label}: input missing: {path}")
        expected = hashes[raw]
        require(isinstance(expected, str) and HEX64.fullmatch(expected), f"{label}: invalid digest: {raw}")
        if path.suffix.lower() in ARRAY_SUFFIXES:
            require(producer_digests.get(str(path)) == expected, f"{label}: array digest is not producer-bound: {path}")
        else:
            require(sha(path) == expected, f"{label}: stale source digest: {path}")


def check_future(request: dict[str, Any], label: str) -> None:
    require(request.get("future_input_sha256") is None, f"{label}: future input digest is populated")
    future = request.get("future_outputs")
    require(isinstance(future, dict), f"{label}: future_outputs missing")
    require(future.get("status") == "not_generated" and future.get("sha256") is None, f"{label}: future output is not null")
    for key, value in request.items():
        if key.endswith("_receipt_sha256") and value is not None:
            # Actual Root283/GenCase producer receipts are inputs.  Only future
            # solver/QA receipt fields may be null in this source package.
            if key not in {"gencase_receipt_sha256", "prepared_input_report_sha256"}:
                raise ContractError(f"{label}: future receipt digest populated: {key}")


def case_data(case_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    binding = load(HERE / "gencase-bindings" / f"{case_id}.actual-root283.json")
    owner = load(HERE / "owners" / f"{case_id}.actual-root283.owner.json")
    plan = load(HERE / "source-plans" / f"{case_id}.json")
    return binding, owner, plan


def check_case(case_id: str) -> dict[str, Any]:
    binding, owner, plan = case_data(case_id)
    qa_binding = load(HERE / "gencase-initial-qa-bindings" / f"{case_id}.json")
    frame_binding = load(HERE / "native-frame0-qa-bindings" / f"{case_id}.json")
    genqa = load(REQUESTS / f"{case_id}.initial-qa.request.json")
    native = load(REQUESTS / f"{case_id}.full-native-qualification.request.json")
    frame = load(REQUESTS / f"{case_id}.native-frame0-qa.request.json")
    label = case_id
    actual = binding["actual_gencase"]
    report = Path(binding["prepared_input_report"])
    receipt = Path(binding["gencase_receipt"])
    require(binding["case_id"] == case_id and owner["case_id"] == case_id, f"{label}: case mismatch")
    require(owner["source_only"] and not owner["execution_allowed"] and not owner["launch_allowed"], f"{label}: owner enabled")
    require(binding["status"] == "actual_root283_completed_no_gencase_rerun", f"{label}: actual binding status changed")
    require(actual["status"] == "completed" and actual["returncode"] == 0, f"{label}: Root283 not completed/0")
    require(report.is_file() and receipt.is_file(), f"{label}: actual report/receipt missing")
    require(actual["generated_bi4_sha256"] == binding["generated_bi4_sha256"], f"{label}: BI4 producer digest mismatch")
    require(actual["generated_xml_sha256"] == binding["generated_xml_sha256"], f"{label}: XML producer digest mismatch")
    counts = binding["actual_particle_counts"]
    require(int(binding["actual_total_particles"]) == sum(int(v) for v in counts.values()), f"{label}: count sum mismatch")
    require(binding["data2d"] is False and actual["data2d"] is False, f"{label}: not genuine 3-D source report")
    definition = Path(binding["source_definition"])
    require(definition.is_file(), f"{label}: source definition missing")
    root = ET.parse(definition).getroot()
    # GenCase definitions do not carry the generated report's data2d node.
    # Check the source geometry has nonzero z extent; the registered report
    # above is the authority for actual data2d=false.
    sizes = root.findall(".//geometry//size")
    require(any(float(node.get("z", "0")) > 0 for node in sizes), f"{label}: source geometry has no z extent")
    require(Path(binding["source_plan"]).is_file(), f"{label}: source plan missing")

    # The pre-native worker has no native receipt or native output dependency.
    require(qa_binding["stage"] == "pre_native_gencase_initial", f"{label}: wrong GenCase QA stage")
    require(qa_binding["native_solver_receipt_required"] is False, f"{label}: GenCase QA requires native receipt")
    require(qa_binding["worker"].endswith("/workers/gencase_initial_qa.py"), f"{label}: wrong GenCase QA worker")
    require(len(qa_binding["cases"]) == 1 and qa_binding["cases"][0]["case_id"] == case_id, f"{label}: GenCase QA binding case mismatch")
    require(qa_binding["cases"][0]["gencase_raw_velocity_claim"] == "not_used_as_solver_initial_velocity_proof", f"{label}: velocity misused")
    require(genqa["cpu_task_kind"] == "audit" and genqa["kind"] == "cpu", f"{label}: GenQA task contract")
    require(genqa["status"] == "source_only_disabled_waiting_root_gencase_initial_qa", f"{label}: GenQA enabled")
    require(genqa["disabled"] and not genqa["execution_allowed"] and not genqa["launch_allowed"], f"{label}: GenQA enabled flags")
    require(genqa["attempt_id"].endswith("-gencase-initial-qa-086"), f"{label}: GenQA attempt id")
    require(genqa["depends_on_attempts"] == [actual["attempt_id"]], f"{label}: GenQA dependency is not only Root283")
    require("native" not in " ".join(genqa["command"]).lower(), f"{label}: GenQA command mentions native solver")
    require("native_solver_receipt" not in genqa and "native_data_dir" not in genqa, f"{label}: GenQA has native dependency")
    check_small_inputs(genqa, label + " GenQA", {str(binding["generated_bi4"]): binding["generated_bi4_sha256"], str(binding["generated_xml"]): binding["generated_xml_sha256"]})
    check_future(genqa, label + " GenQA")

    # Native solver depends on GenCase QA; native frame-0 QA is downstream.
    genqa_path = HERE / "requests" / f"{case_id}.initial-qa.request.json"
    frame_path = HERE / "requests" / f"{case_id}.native-frame0-qa.request.json"
    genqa_attempt = genqa["attempt_id"]
    native_attempt = native["attempt_id"]
    frame_attempt = frame["attempt_id"]
    require(native["depends_on_attempts"] == [actual["attempt_id"], genqa_attempt], f"{label}: native dependency graph is not acyclic")
    require(frame_attempt not in native["depends_on_attempts"], f"{label}: native depends on downstream frame-0 QA")
    require(native["initial_qa_request"] == str(genqa_path), f"{label}: native initial_qa_request is not GenQA")
    require(native["native_frame0_qa_request"] == str(frame_path), f"{label}: native frame-0 pointer mismatch")
    require(native["gencase_initial_qa_required"] is True and native["native_frame0_qa_downstream_only"] is True, f"{label}: native QA stage flags")
    require(any("GenCase initial QA completed/0" in gate for gate in native["gates"]), f"{label}: GenQA gate missing")
    require(any("downstream" in gate.lower() for gate in native["gates"]), f"{label}: downstream gate explanation missing")
    require(native["disabled"] and not native["execution_allowed"] and not native["launch_allowed"], f"{label}: native enabled")
    require(native["command"][-2:] == [f"-tmax:{native['numerical_recipe']['actual_execution_parameters']['TimeMax']}", "-tout:0.01"], f"{label}: native options changed")
    require(native["gencase_receipt"] == str(receipt), f"{label}: gencase receipt not string/path bound")
    require(native["initial_qa_receipt_sha256"] is None and native["native_frame0_qa_receipt_sha256"] is None, f"{label}: future QA digest populated")
    check_small_inputs(native, label + " native", {str(binding["generated_bi4"]): binding["generated_bi4_sha256"], str(binding["generated_xml"]): binding["generated_xml_sha256"]})
    check_future(native, label + " native")

    require(frame["depends_on_attempts"] == [native_attempt], f"{label}: frame-0 QA does not depend only on native")
    require(frame["native_solver_receipt"] == native["future_outputs"]["native_execution_receipt"], f"{label}: frame-0 receipt path mismatch")
    require(frame["status"] == "source_only_disabled_waiting_root_native_frame0_qa", f"{label}: frame-0 status changed")
    require(frame["disabled"] and not frame["execution_allowed"] and not frame["launch_allowed"], f"{label}: frame-0 enabled")
    require(frame_binding["stage"] == "downstream_native_frame0", f"{label}: frame binding stage")
    require(frame_binding["native_solver_attempt_id"] == native_attempt, f"{label}: frame binding native attempt")
    check_small_inputs(frame, label + " frame0", {str(binding["generated_bi4"]): binding["generated_bi4_sha256"], str(binding["generated_xml"]): binding["generated_xml_sha256"]})
    check_future(frame, label + " frame0")

    return {
        "case_id": case_id,
        "actual_root283_attempt": actual["attempt_id"],
        "gencase_initial_qa_attempt": genqa_attempt,
        "native_attempt": native_attempt,
        "native_frame0_qa_attempt": frame_attempt,
        "actual_counts": counts,
        "actual_total": int(binding["actual_total_particles"]),
        "genqa_request": str(genqa_path),
        "native_request": str(HERE / "requests" / f"{case_id}.full-native-qualification.request.json"),
        "frame0_request": str(frame_path),
    }


def run() -> dict[str, Any]:
    require(not (HERE / "requests" / "*.native.request.json").exists(), "legacy native request pattern present")
    result = [check_case(case_id) for case_id in CASES]
    all_native = [load(REQUESTS / f"{case}.full-native-qualification.request.json") for case in CASES]
    all_genqa = [load(REQUESTS / f"{case}.initial-qa.request.json") for case in CASES]
    all_frame = [load(REQUESTS / f"{case}.native-frame0-qa.request.json") for case in CASES]
    require(len({row["gencase_initial_qa_attempt"] for row in result}) == 8, "GenQA attempts are not independent")
    require(len({row["native_attempt"] for row in result}) == 8, "native attempts are not independent")
    require(all(n["numerical_recipe"]["expected_native_frames"] == (401 if "DUAL" in n["case_id"] else 161) for n in all_native), "frame recipes changed")
    require(all(n["numerical_recipe"]["command_options"] == [f"-tmax:{n['numerical_recipe']['actual_execution_parameters']['TimeMax']}", "-tout:0.01"] for n in all_native), "recipe options changed")
    return {
        "schema": "ds02.f1.fresh086-source-validation.v1",
        "fresh_id": "fresh086",
        "family_id": "F1",
        "passed": True,
        "case_count": 8,
        "gencase_initial_qa_requests_disabled": len(all_genqa),
        "native_requests_disabled": len(all_native),
        "native_frame0_requests_disabled": len(all_frame),
        "dependency_graph": "Root283 -> GenCase initial QA -> native solver -> native frame-0 QA",
        "fresh085_circular_source_preserved": True,
        "arrays_read": False,
        "arrays_hashed": False,
        "jobs_started": False,
        "shared_registry_or_ledger_modified": False,
        "independent_case_count_increment": 0,
        "q_n": "not_assessed",
        "production_approval": "none",
        "cases": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    value = run()
    if args.output:
        Path(args.output).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except ContractError as exc:
        raise SystemExit(f"fresh086 contract failed: {exc}")
