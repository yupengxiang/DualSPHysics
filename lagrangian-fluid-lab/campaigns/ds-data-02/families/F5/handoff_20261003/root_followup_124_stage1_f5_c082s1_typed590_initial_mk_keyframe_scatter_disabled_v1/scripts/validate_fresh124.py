#!/usr/bin/env python3
"""Metadata-only validator for the disabled fresh124 initial_mk keyframe audit."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

PACKAGE_SCHEMA = "ds02.f5.c082s1.fresh124"
BINDING_SCHEMA = "ds02.f5.c082s1.initial-mk-keyframe-scatter-binding.fresh124.v1"
REPORT_SCHEMA = "ds02.f5.c082s1.initial-mk-keyframe-scatter-audit.fresh124.v1"
SCIENCE_SUFFIXES = {".h5", ".dat", ".bi4", ".csv", ".vtk"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FOCUS_FRAMES = [0, 97, 153, 219, 400, 718, 800]
EXPECTED_COUNTS = {"total": 194427, "fixed": 158559, "moving": 4210, "fluid": 31658, "floating": 0}
EXPECTED_DATASETS = ["time", "position", "velocity", "valid", "particle_id", "type", "initial_mk"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def sha_static(path: Path) -> str:
    require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"source validator must not hash science payload: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def is_science(path_text: str) -> bool:
    return Path(path_text).suffix.lower() in SCIENCE_SUFFIXES


def validate_input_closure(request: dict, *, tag: str, worker: Path, worker_sha: str) -> dict:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    require(isinstance(files, list) and files, f"{tag}: input_files")
    require(isinstance(hashes, dict), f"{tag}: input_sha256")
    require(len(files) == len(set(files)), f"{tag}: duplicate input_files")
    require(set(files) == set(hashes), f"{tag}: input/hash key mismatch")
    static_inputs = []
    science_inputs = []
    for path_text in files:
        require(isinstance(path_text, str) and path_text, f"{tag}: invalid input path")
        expected = hashes[path_text]
        require(isinstance(expected, str) and HEX64.fullmatch(expected), f"{tag}: invalid digest {path_text}")
        path = Path(path_text)
        if is_science(path_text):
            require(path == Path(request["trajectory_h5"]), f"{tag}: unexpected science input {path}")
            require(expected == request["trajectory_h5_sha256"], f"{tag}: H5 must use producer attestation")
            science_inputs.append(path_text)
            continue
        require(path.is_file(), f"{tag}: static input missing {path}")
        require(sha_static(path) == expected, f"{tag}: static input digest mismatch {path}")
        static_inputs.append(path_text)

    command = request.get("command")
    require(isinstance(command, list) and len(command) >= 10, f"{tag}: command shape")
    require(command[0] == "/usr/bin/env", f"{tag}: command must use env wrapper")
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VTK_SMP_MAX_THREADS"):
        require(f"{variable}=1" in command, f"{tag}: single-thread override {variable}")
    worker_index = command.index(str(worker))
    require(worker_index > 0 and str(Path(command[worker_index - 1]).resolve()) == str(Path(request["python_executable"]).resolve()), f"{tag}: worker interpreter binding")
    require(str(Path(request["python_executable"]).resolve()) in {str(Path(item).resolve()) for item in files}, f"{tag}: interpreter input closure")
    require(command[worker_index + 1:worker_index + 5] == ["--binding", request["binding"], "--output-dir", "{attempt_root}/audit-output"], f"{tag}: worker argv")
    worker_key = str(worker.resolve())
    require(hashes.get(worker_key) == worker_sha, f"{tag}: worker digest closure")
    require(request.get("binding_sha256") == hashes.get(str(Path(request["binding"]).resolve())), f"{tag}: binding digest closure")
    return {"input_files": len(files), "static_inputs_hashed": len(static_inputs), "science_inputs_attested_without_open": len(science_inputs)}


def validate_binding_contract(binding: dict, manifest: dict, *, tag: str) -> None:
    require(binding["datasets_required"] == EXPECTED_DATASETS, f"{tag}: dataset contract must use initial_mk")
    require(binding["marker_field"] == "initial_mk" and binding["marker_time_varying"] is False, f"{tag}: marker semantics")
    fields = manifest.get("fields", {})
    require(fields.get("initial_mk", {}).get("shape") == [194427], f"{tag}: manifest initial_mk shape")
    require(fields.get("initial_mk", {}).get("dtype") == "int16", f"{tag}: manifest initial_mk dtype")
    require("mk" not in fields, f"{tag}: manifest incorrectly advertises temporal mk")


def validate_case(root: Path, tag: str, worker: Path, worker_sha: str) -> dict:
    binding_path = (root / f"bindings/{tag}-initial-mk-keyframe-scatter-binding.json").resolve()
    request_path = (root / f"requests/{tag}-initial-mk-keyframe-scatter-audit-request.json").resolve()
    binding = load(binding_path)
    request = load(request_path)
    manifest = load(Path(binding["xmf_manifest"]))
    validate_binding_contract(binding, manifest, tag=tag)
    require(binding["schema"] == BINDING_SCHEMA, f"{tag}: binding schema")
    require(binding["source_only"] is True and binding["read_only"] is True and binding["execution_allowed"] is False, f"{tag}: binding gate")
    require(request["schema"] == "ds02.runner-request.v2", f"{tag}: request schema")
    require(request["binding"] == str(binding_path), f"{tag}: binding path")
    require(request["kind"] == "cpu" and request["cpu_task_kind"] == "audit" and request["cpu_threads"] == 2, f"{tag}: CPU audit contract")
    require(request["disabled"] is True and request["execution_allowed"] is False and request["launch"] is False and request["launch_allowed"] is False, f"{tag}: disabled gate")
    require(request["solver_allowed"] is False and request["conversion_allowed"] is False and request["diagnostic_only"] is True, f"{tag}: science gate")
    require(request["arrays_allowed"] is True and request["array_edit_allowed"] is False, f"{tag}: read-only array policy")
    require(request["root_dataset_inventory_profile"] == "root_home_floor_no_legacy_dataset_walk_v1" and request["launch_owner"] == "root", f"{tag}: Root142 profile")
    require(request["root_dataset_inventory_profile"] == request["root_inventory_profile"], f"{tag}: profile aliases")
    require(request["fullnative_gate"]["status"] == "WAIT" and request["full801_authorized"] is False and request["independent_case_count_increment"] == 0, f"{tag}: fullnative gate")
    require(binding["expected_frames"] == 801 and binding["expected_particles"] == 194427 and binding["expected_dimension"] == 3, f"{tag}: producer shape")
    require(binding["expected_counts"] == EXPECTED_COUNTS, f"{tag}: counts")
    require(binding["focus_frames"] == FOCUS_FRAMES and request["focus_frames"] == FOCUS_FRAMES, f"{tag}: focus frames")
    require(request["datasets_required"] == EXPECTED_DATASETS, f"{tag}: request dataset contract")
    require(request["marker_field"] == "initial_mk" and request["marker_time_varying"] is False, f"{tag}: request marker semantics")
    require(request["manifest_initial_mk_shape"] == [194427] and request["manifest_initial_mk_dtype"] == "int16", f"{tag}: request manifest marker contract")
    require("mk" in request["manifest_forbids_dataset"], f"{tag}: request temporal Mk negative contract")
    require(binding["native_bed_marker_mk"] == 50 and binding["source_mkbound"] == 40, f"{tag}: native/source Mk mapping")
    require(binding["source_h5_scope_schema"] == "legacy-owner-scope.v0", f"{tag}: legacy H5 scope")
    require(binding["source_h5_scope_status"].startswith("legacy_incomplete"), f"{tag}: legacy H5 qualification")
    require(request["future_output_hashes"]["audit_report_sha256"] is None and request["future_output_hashes"]["scatter_png_sha256"] is None, f"{tag}: future output hashes")
    require(request["trajectory_h5_sha256"] == binding["trajectory_h5_sha256"], f"{tag}: H5 binding SHA")
    require(request["xmf_manifest_sha256"] == binding["xmf_manifest_sha256"], f"{tag}: XMF binding SHA")
    require(request["conversion_report_sha256"] == binding["conversion_report_sha256"], f"{tag}: conversion binding SHA")
    require(request["typed_receipt_sha256"] == binding["typed_receipt_sha256"], f"{tag}: receipt binding SHA")
    for field, path_field in (
        ("python_executable_sha256", "python_executable"),
        ("root_inventory_policy_source_sha256", "root_inventory_policy_source"),
        ("root_actual_launch_source_sha256", "root_actual_launch_source"),
        ("strict_dispatch_source_sha256", "strict_dispatch_source"),
        ("runtime_source_sha256", "runtime_source"),
        ("resource_window_approval_sha256", "resource_window_approval"),
    ):
        resolved = str(Path(request[path_field]).resolve())
        require(request[field] == request["input_sha256"].get(resolved), f"{tag}: {field} closure")

    conversion = load(Path(binding["conversion_report"]))
    receipt = load(Path(binding["typed_receipt"]))
    require(manifest["trajectory_h5"] == binding["trajectory_h5"], f"{tag}: manifest H5 path")
    require(manifest["trajectory_h5_sha256"] == binding["trajectory_h5_sha256"], f"{tag}: manifest H5 attestation")
    require(manifest["frames"] == 801 and manifest["particles"] == 194427, f"{tag}: manifest shape")
    validate_binding_contract(binding, manifest, tag=f"{tag}/producer")
    require(conversion["conversion_status"] == "completed", f"{tag}: conversion status")
    require(conversion["output_hdf5"] == binding["trajectory_h5"] and conversion["output_sha256"] == binding["trajectory_h5_sha256"], f"{tag}: conversion H5 attestation")
    require(conversion["frames"] == 801 and conversion["particles"] == 194427, f"{tag}: conversion shape")
    require(conversion["solver_dimension"]["solver_dimension"] == 3 and conversion["solver_dimension"]["xml_data2d"] == "false", f"{tag}: 3D conversion")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, f"{tag}: typed receipt")

    wrong_mk = copy.deepcopy(binding)
    wrong_mk["datasets_required"] = ["time", "position", "velocity", "valid", "particle_id", "type", "mk"]
    wrong_mk_rejected = False
    wrong_mk_error = ""
    try:
        validate_binding_contract(wrong_mk, manifest, tag=f"{tag}/original123-mk-negative")
    except ValueError as exc:
        wrong_mk_rejected = True
        wrong_mk_error = str(exc)
    require(wrong_mk_rejected, f"{tag}: original123 temporal-mk contract was not rejected")

    closure = validate_input_closure(request, tag=tag, worker=worker, worker_sha=worker_sha)
    stale = copy.deepcopy(request)
    stale[str("input_sha256")][str(worker.resolve())] = "0" * 64
    stale_rejected = False
    stale_error = ""
    try:
        validate_input_closure(stale, tag=f"{tag}/synthetic-stale-worker", worker=worker, worker_sha=worker_sha)
    except ValueError as exc:
        stale_rejected = True
        stale_error = str(exc)
    require(stale_rejected, f"{tag}: stale worker digest negative test")
    return {
        "tag": tag,
        "attempt_id": request["attempt_id"],
        "binding_sha256": request["binding_sha256"],
        "worker_sha256": worker_sha,
        "closure": closure,
        "producer_attestation": {
            "typed_frames": conversion["frames"],
            "typed_particles": conversion["particles"],
            "solver_dimension": conversion["solver_dimension"]["solver_dimension"],
            "h5_opened_or_rehashed_by_source": False,
        },
        "synthetic_negative_test": {"stale_worker_input_sha256_rejected": stale_rejected, "error": stale_error},
        "original123_mk_contract_negative": {"temporal_mk_binding_rejected": wrong_mk_rejected, "error": wrong_mk_error},
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = load(root / "manifest.json")
    report_path = root / "metadata/fresh124-validator-report.json"
    require(plan_schema := load(root / "metadata/fresh124-source-plan.json"), "source plan")
    actual = load(root / "metadata/fresh124-actual-producer-provenance.json")
    require(plan_schema["schema"].startswith(PACKAGE_SCHEMA), "source plan schema")
    require(actual["schema"].startswith(PACKAGE_SCHEMA), "producer provenance schema")
    require(set(actual["cases"]) == {"A080", "A120"}, "two actual producer cases")
    require(report_path not in [root / item["path"] for item in manifest["files"]], "validator report self-reference")
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SCIENCE_SUFFIXES:
            raise ValueError(f"science payload copied into package: {path}")
    for item in manifest["files"]:
        path = root / item["path"]
        require(path.is_file(), f"manifest missing {path}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"manifest science suffix {path}")
        require(sha_static(path) == item["sha256"], f"manifest digest mismatch {path}")
        require(path.stat().st_size == item["bytes"], f"manifest byte mismatch {path}")
    worker = (root / "workers/initial_mk_keyframe_scatter_audit.py").resolve()
    worker_sha = sha_static(worker)
    worker_text = worker.read_text(encoding="utf-8")
    require('BINDING_SCHEMA = "' + BINDING_SCHEMA + '"' in worker_text, "worker binding schema")
    require('"initial_mk"' in worker_text and "actual_time_step_index" in worker_text, "worker actual field contract")
    require('h5["mk"]' not in worker_text and re.search(r"(?<![A-Za-z0-9_])mk_ds(?![A-Za-z0-9_])", worker_text) is None, "worker must not read temporal mk")
    cases = [validate_case(root, tag, worker, worker_sha) for tag in ("A080", "A120")]
    report = {
        "schema": "ds02.f5.c082s1.fresh124-validator-report.v1",
        "status": "passed_metadata_only",
        "package": root.name,
        "cases": cases,
        "input_closure": {"all_request_inputs_checked": True, "static_metadata_code_binaries_hashed": True, "science_inputs_producer_attested_only": True, "science_suffixes_never_opened_or_hashed": sorted(SCIENCE_SUFFIXES)},
        "negative_tests": {
            "stale_worker_input_hash_rejected": all(row["synthetic_negative_test"]["stale_worker_input_sha256_rejected"] for row in cases),
            "original123_temporal_mk_contract_rejected": all(row["original123_mk_contract_negative"]["temporal_mk_binding_rejected"] for row in cases),
        },
        "science_payloads_opened_or_hashed": False,
        "fullnative_gate": "WAIT",
        "visual_mechanism_acceptance": False,
        "precision_granted": False,
        "q_n_granted": False,
        "case_increment": 0,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schema": report["schema"], "status": report["status"], "worker_sha256": worker_sha, "cases": [row["tag"] for row in cases], "science_payloads_opened_or_hashed": False, "stale_worker_hash_negative": report["negative_tests"]["stale_worker_input_hash_rejected"], "original123_mk_negative": report["negative_tests"]["original123_temporal_mk_contract_rejected"], "fullnative_gate": "WAIT"}, sort_keys=True))


if __name__ == "__main__":
    main()
