#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ARRAY_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk"}
EXPECTED_COUNTS = {
    "F1_STAGE1_DUAL_H240_DP020": {"fixed": 87816, "moving": 0, "floating": 0, "fluid": 30000, "total": 117816},
    "F1_STAGE1_DUAL_H240_DP020_VX010": {"fixed": 87816, "moving": 0, "floating": 0, "fluid": 30000, "total": 117816},
    "F1_STAGE1_DUAL_H280_DP020": {"fixed": 87816, "moving": 0, "floating": 0, "fluid": 35000, "total": 122816},
    "F1_STAGE1_DUAL_H320_DP020": {"fixed": 87816, "moving": 0, "floating": 0, "fluid": 40000, "total": 127816},
    "F1_STAGE1_ECC_H120_DP010": {"fixed": 101436, "moving": 0, "floating": 0, "fluid": 32160, "total": 133596},
    "F1_STAGE1_ECC_H140_DP010": {"fixed": 101436, "moving": 0, "floating": 0, "fluid": 37520, "total": 138956},
    "F1_STAGE1_ECC_H160_DP010": {"fixed": 101436, "moving": 0, "floating": 0, "fluid": 42880, "total": 144316},
    "F1_STAGE1_ECC_H180_DP010": {"fixed": 101436, "moving": 0, "floating": 0, "fluid": 48240, "total": 149676},
}
ROOT230 = {
    "profile": "root_home_floor_no_legacy_dataset_walk_native_v1",
    "gpu_profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
    "entry_sha256": "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e",
    "gpu_sha256": "4e6f340222f7823ae9df1a145ccda884dcf401c9740fc78c51a88066ae1c88cd",
    "home_sha256": "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5",
    "resource_sha256": "2a35e26e36920d8ca40001fd7f28416f27bcf371b8b882eca37868f4a15152b8",
    "source_policy_sha256": "42f1af21e8e663234198b6a2f3f87a86b178d11fe3ca8a939467ae97d64e4326",
    "reservation_sha256": "46e62ea197862a833797556d09350126b3632b2e3b1d496d08816ee42f7abecf",
}
SCOPE = "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1"


def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def producer_hash(path: str, report: dict) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix == ".bi4":
        return report.get("bi4_sha256")
    if suffix == ".xml" and "/Projects/DualSPHysics-data/" in path:
        return report.get("xml_sha256")
    return None


def check_input_closure(request: dict, label: str, report: dict, package: Path):
    files = set(request.get("input_files", []))
    hashes = set(request.get("input_sha256", {}))
    require(files == hashes, f"{label}: input/hash closure mismatch")
    for raw in files:
        path = Path(raw)
        expected = request["input_sha256"][raw]
        opaque = producer_hash(raw, report)
        if opaque is not None:
            require(expected == opaque, f"{label}: producer hash mismatch {raw}")
            continue
        require(path.is_file(), f"{label}: missing input {raw}")
        require(path.suffix.lower() not in ARRAY_SUFFIXES, f"{label}: unapproved scientific-array input {raw}")
        require(expected == sha(path), f"{label}: stale input hash {raw}")
    for raw in request.get("future_input_files", []):
        require(request.get("future_input_sha256") is None, f"{label}: future input hash must be null")
        require(Path(raw).suffix.lower() not in {".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk"}, f"{label}: future scientific digest is forbidden")
    require(request.get("source_only") is True, f"{label}: source_only")
    require(request.get("execution_allowed") is False, f"{label}: execution enabled")
    require(request.get("launch_allowed") is False, f"{label}: launch enabled")
    require(request.get("disabled") is True and request.get("launch") is False, f"{label}: disabled/launch flags")
    require(request.get("future_input_sha256") is None, f"{label}: future input digest")
    for key, value in request.items():
        if key.endswith(("_receipt_sha256", "_report_sha256", "_xml_sha256", "_bi4_sha256")):
            if key.startswith("gencase_"):
                continue
            if key in {"generated_bi4_sha256", "generated_xml_sha256", "prepared_input_report_sha256"}:
                continue
            if key in {"gencase_receipt_sha256", "gencase_report_sha256", "gencase_xml_sha256", "gencase_bi4_sha256"}:
                continue
            require(value is None, f"{label}: future digest {key}")


def validate(package: Path):
    cases = sorted(EXPECTED_COUNTS)
    summary = load(package / "metadata/root283-actual-summary.json")
    require(summary["schema"] == "ds02.f1.fresh085.root283-actual-summary.v1", "summary schema")
    require(summary["actual_case_count"] == 8, "summary count")
    results = []
    for case_id in cases:
        expected = EXPECTED_COUNTS[case_id]
        owner = load(package / f"owners/{case_id}.actual-root283.owner.json")
        binding = load(package / f"gencase-bindings/{case_id}.actual-root283.json")
        qa_binding = load(package / f"qa-bindings/{case_id}.json")
        qa_request = load(package / f"requests/{case_id}.initial-qa.request.json")
        native_request = load(package / f"requests/{case_id}.full-native-qualification.request.json")
        report_path = Path(binding["prepared_input_report"])
        receipt_path = Path(binding["gencase_receipt"])
        report = load(report_path)
        receipt = load(receipt_path)
        require(report_path.name == "prepared-input-report.json" and report_path.parent.name == "prepared", f"{case_id}: report is not nested prepared report")
        require(receipt["status"] == "completed" and receipt["returncode"] == 0, f"{case_id}: Root283 receipt")
        require(report["case_id"] == case_id, f"{case_id}: report identity")
        counts = report["generated_xml_particle_counts"]
        actual = {"fixed": int(counts["fixed"]), "moving": int(counts.get("moving", 0)), "floating": int(counts.get("floating", 0)), "fluid": int(counts["fluid"]), "total": int(report["actual_total_particles"])}
        require(actual == expected, f"{case_id}: dynamic counts {actual} != {expected}")
        require(actual["total"] == actual["fixed"] + actual["moving"] + actual["floating"] + actual["fluid"], f"{case_id}: count sum")
        require(str(report["actual_generated_constants"]["data2d"]["value"]).lower() == "false", f"{case_id}: report data2d")
        require(report["xml_sha256"] and report["bi4_sha256"], f"{case_id}: producer hashes")
        require(owner["actual_total_particles"] == actual["total"], f"{case_id}: owner count")
        require(owner["actual_particle_counts"] == {k: actual[k] for k in ("fixed", "moving", "floating", "fluid")}, f"{case_id}: owner counts")
        require(binding["actual_total_particles"] == actual["total"], f"{case_id}: binding count")
        require(binding["actual_particle_counts"] == {k: actual[k] for k in ("fixed", "moving", "floating", "fluid")}, f"{case_id}: binding counts")
        require(binding["generated_xml_sha256"] == report["xml_sha256"] and binding["generated_bi4_sha256"] == report["bi4_sha256"], f"{case_id}: producer artifact hash")
        require(binding["prepared_input_report_sha256"] == sha(report_path), f"{case_id}: report hash")
        require(binding["gencase_receipt_sha256"] == sha(receipt_path), f"{case_id}: receipt hash")
        require(owner["physical_condition_sha256"] == binding["physical_condition_sha256"], f"{case_id}: owner condition")
        require(owner["physical_binding"] and hashlib.sha256(canonical(owner["physical_binding"]).encode()).hexdigest() == owner["physical_condition_sha256"], f"{case_id}: physical hash")
        require(owner["source_only"] is True and owner["execution_allowed"] is False, f"{case_id}: owner enabled")
        require("prepared/prepared-input-report.json" in binding["prepared_input_report"], f"{case_id}: nested report")
        require("genuine-gencase-084/prepared-input-report.json" in binding["source084_forecast_report_path"], f"{case_id}: forecast provenance missing")
        require("prepared/prepared-input-report.json" in binding["source084_forecast_root_actual_report_path"], f"{case_id}: forecast root correction missing")
        qa_case = qa_binding["cases"][0]
        require(qa_case["actual_total_particles"] == actual["total"], f"{case_id}: QA count")
        require(qa_case["prepared_input_report"] == binding["prepared_input_report"], f"{case_id}: QA report")
        require(qa_case["generated_xml_sha256"] == report["xml_sha256"] and qa_case["generated_bi4_sha256"] == report["bi4_sha256"], f"{case_id}: QA producer hash")
        require(qa_binding["worker"].endswith("workers/native_initial_height_frame0_audit.py"), f"{case_id}: QA worker")
        require(qa_binding["partvtk_sha256"] == "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00", f"{case_id}: PartVTK")
        check_input_closure(qa_request, case_id + " QA", report, package)
        require(qa_request["cpu_task_kind"] == "audit", f"{case_id}: QA task kind")
        require(qa_request["command"][1].endswith("workers/native_initial_height_frame0_audit.py"), f"{case_id}: QA command")
        require(qa_request["future_outputs"]["sha256"] is None, f"{case_id}: QA future hash")
        require(qa_request["future_outputs"]["status"] == "not_generated", f"{case_id}: QA future status")
        require(native_request["kind"] == "qualification", f"{case_id}: native kind")
        require(native_request["scope_id"] == SCOPE, f"{case_id}: native scope")
        require(native_request["actual_total_particles"] == actual["total"], f"{case_id}: native count")
        require(native_request["gencase_receipt_sha256"] == sha(receipt_path), f"{case_id}: native receipt")
        require(native_request["gencase_xml_sha256"] == report["xml_sha256"] and native_request["gencase_bi4_sha256"] == report["bi4_sha256"], f"{case_id}: native producer hashes")
        require(native_request["cwd"].endswith("/prepared"), f"{case_id}: native cwd")
        require(native_request["root230_dispatch"]["entry_sha256"] == ROOT230["entry_sha256"], f"{case_id}: Root230 entry")
        require(native_request["root230_dispatch"]["gpu_policy_sha256"] == ROOT230["gpu_sha256"], f"{case_id}: GPU policy")
        require(native_request["root230_dispatch"]["home_floor_policy_sha256"] == ROOT230["home_sha256"], f"{case_id}: home policy")
        require(native_request["root230_dispatch"]["resource_window_sha256"] == ROOT230["resource_sha256"], f"{case_id}: resource")
        require(native_request["root230_dispatch"]["source_policy_contract_sha256"] == ROOT230["source_policy_sha256"], f"{case_id}: source policy")
        require(native_request["root_effective_reservation_function_sha256"] == ROOT230["reservation_sha256"], f"{case_id}: reservation")
        require(native_request["root_dataset_inventory_profile"] == ROOT230["profile"], f"{case_id}: inventory profile")
        require(native_request["root_gpu_selection_profile"] == ROOT230["gpu_profile"], f"{case_id}: GPU profile")
        require(native_request["root_solver_concurrency_cap"] == 8, f"{case_id}: cap")
        require(native_request["command"][-2:] == [f"-tmax:{'4.0' if 'DUAL' in case_id else '1.6'}", "-tout:0.01"], f"{case_id}: solver recipe")
        require(not any(any(flag in item for flag in ("-mdbc", "-dbc", "-forcing", "-motion", "-cpu")) for item in native_request["command"]), f"{case_id}: forbidden solver option")
        require(native_request["expected_output"]["frame_count"] == (401 if "DUAL" in case_id else 161), f"{case_id}: frames")
        check_input_closure(native_request, case_id + " native", report, package)
        require(native_request["initial_qa_request_sha256"] == sha(package / f"requests/{case_id}.initial-qa.request.json"), f"{case_id}: QA request hash")
        for field in ("initial_qa_receipt_sha256", "initial_qa_report_sha256", "gencase_bi4_sha256", "gencase_xml_sha256"):
            if field.startswith("initial_qa"):
                require(native_request[field] is None, f"{case_id}: future QA digest")
        results.append({"case_id": case_id, "actual_particle_counts": actual, "gencase_receipt_sha256": sha(receipt_path), "generated_xml_sha256": report["xml_sha256"], "generated_bi4_sha256": report["bi4_sha256"], "qa_request_disabled": True, "native_request_disabled": True})
    manifest = load(package / "manifest.json")
    for entry in manifest["files"]:
        path = package / entry["path"]
        require(path.is_file(), f"manifest missing {entry['path']}")
        require(path.stat().st_size == entry["bytes"], f"manifest bytes {entry['path']}")
        require(sha(path) == entry["sha256"], f"manifest hash {entry['path']}")
    worker = (package / "workers/native_initial_height_frame0_audit.py").read_text(encoding="utf-8")
    ast.parse(worker)
    require("generated_xml_particle_counts" in worker and "actual_fluid_particles" not in worker, "worker did not use dynamic count contract")
    require("PartVTK" in worker and "mass_rescaling" in worker, "worker contract")
    result = {
        "schema": "ds02.f1.fresh085-source-validation.v1",
        "passed": True,
        "family_id": "F1",
        "fresh_id": "fresh085",
        "actual_root283_cases": results,
        "actual_case_count": 8,
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "gencase_rerun": False,
        "native_solver_launched": False,
        "initial_qa_launched": False,
        "scientific_arrays_read": False,
        "scientific_arrays_hashed": False,
        "shared_registry_or_ledger_modified": False,
        "root230_disabled_requests": 8,
        "dynamic_counts_from_prepared_reports": True,
        "nested_prepared_report_correction": True,
        "independent_case_count_increment": 0,
        "q_n": "not_assessed",
        "production_approval": "none",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    validate(args.package)
