#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

SCIENCE_SUFFIXES = {".h5", ".dat", ".bi4", ".csv", ".vtk"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ROOT023_SHA = "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha_static(path: Path) -> str:
    require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science payload hash forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_closure(request: dict, tag: str, worker: Path) -> dict:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    require(isinstance(files, list) and len(files) == len(set(files)), f"{tag}: input_files")
    require(isinstance(hashes, dict) and set(files) == set(hashes), f"{tag}: input SHA key closure")
    static_count = 0
    science_paths = []
    for path_text in files:
        expected = hashes[path_text]
        require(isinstance(expected, str) and HEX64.fullmatch(expected), f"{tag}: malformed hash {path_text}")
        path = Path(path_text)
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            require(path == Path(request["trajectory_h5"]), f"{tag}: unexpected science input {path}")
            require(expected == request["trajectory_h5_sha256"], f"{tag}: H5 is not producer attested")
            science_paths.append(path_text)
            continue
        require(path.is_file(), f"{tag}: missing static input {path}")
        require(sha_static(path) == expected, f"{tag}: static input SHA mismatch {path}")
        static_count += 1
    command = request.get("command")
    require(isinstance(command, list) and len(command) >= 3, f"{tag}: command")
    require(Path(command[2]).resolve() == worker.resolve(), f"{tag}: worker argv path")
    require(hashes[str(worker.resolve())] == sha_static(worker), f"{tag}: worker input SHA")
    binding_path = Path(request["binding"]).resolve()
    require(request["binding_sha256"] == hashes[str(binding_path)], f"{tag}: binding input SHA")
    return {"input_files": len(files), "static_inputs_hashed": static_count, "science_inputs_attested_only": len(science_paths)}


def validate_case(root: Path, tag: str, worker: Path, source_plan: Path) -> dict:
    binding_path = (root / f"bindings/{tag}-focused-velocity-render-binding.json").resolve()
    request_path = (root / f"requests/{tag}-focused-velocity-render-request.json").resolve()
    binding = load(binding_path)
    request = load(request_path)
    require(binding["schema"] == "ds02.f5.c082s1.focused-velocity-render-binding.fresh122.v1", f"{tag}: binding schema")
    require(binding["source_only"] is True and binding["execution_allowed"] is False, f"{tag}: binding gate")
    require(binding["derived_view_only"] is True and binding["no_array_edit"] is True, f"{tag}: display gate")
    require(binding["no_particle_clipping_or_reader_filtering"] is True, f"{tag}: reader gate")
    require(request["disabled"] is True and request["execution_allowed"] is False and request["launch"] is False, f"{tag}: request gate")
    require(request["kind"] == "cpu" and request["cpu_task_kind"] == "audit" and request["cpu_threads"] == 2, f"{tag}: CPU contract")
    require(request["full801_authorized"] is False and request["fullnative_gate"]["status"] == "WAIT", f"{tag}: full gate")
    require(request["derived_view_only"] is True and request["diagnostic_only"] is True, f"{tag}: diagnostic gate")
    require(request["source_agent_did_not_read_science_payloads"] is True, f"{tag}: source science gate")
    require(request["binding"] == str(binding_path), f"{tag}: binding path")
    require(request["binding_sha256"] == sha_static(binding_path), f"{tag}: binding SHA")
    closure = validate_closure(request, tag, worker)

    actual_manifest = load(Path(binding["xmf_manifest"]))
    require(sha_static(Path(binding["xmf_manifest"])) == binding["xmf_manifest_sha256"], f"{tag}: XMF manifest SHA")
    require(actual_manifest["schema"] == "ds02.stage1.paraview-temporal-product.v1", f"{tag}: XMF schema")
    require(actual_manifest["xdmf"] == binding["xdmf"] and actual_manifest["xdmf_sha256"] == binding["xdmf_sha256"], f"{tag}: XMF attestation")
    require(actual_manifest["trajectory_h5"] == binding["trajectory_h5"], f"{tag}: H5 path")
    require(actual_manifest["trajectory_h5_sha256"] == binding["trajectory_h5_sha256"], f"{tag}: H5 producer SHA")
    require(actual_manifest["frames"] == 801 and actual_manifest["particles"] == 194427, f"{tag}: XMF dimensions")
    require(len(actual_manifest["actual_time_s"]) == 801, f"{tag}: actual time axis")
    require({"valid", "particle_id", "particle_zone", "type", "velocity"} <= set(actual_manifest["fields"]), f"{tag}: native fields")
    require(sha_static(Path(binding["xdmf"])) == binding["xdmf_sha256"], f"{tag}: case.xmf SHA")

    conversion = load(Path(binding["conversion_report"]))
    require(sha_static(Path(binding["conversion_report"])) == binding["conversion_report_sha256"], f"{tag}: conversion report SHA")
    require(conversion["conversion_status"] == "completed" and conversion["frames"] == 801 and conversion["particles"] == 194427, f"{tag}: conversion producer")
    receipt = load(Path(binding["typed_receipt"]))
    require(sha_static(Path(binding["typed_receipt"])) == binding["typed_receipt_sha256"], f"{tag}: typed receipt SHA")
    require(receipt.get("returncode", receipt.get("status")) in (0, "completed"), f"{tag}: typed receipt status")

    require(binding["root023_renderer_sha256"] == ROOT023_SHA, f"{tag}: Root023 source attestation")
    require(binding["focus_frames"] == [0, 97, 153, 219, 400, 718, 800], f"{tag}: focus frames")
    require(binding["focus_camera_bounds_m"] == [[2.4, 4.6], [-0.22, 0.22], [-0.04, 0.75]], f"{tag}: camera bounds")
    require(binding["velocity_color"]["array"] == "velocity" and binding["velocity_color"]["component"] == "Magnitude", f"{tag}: velocity color")
    require(binding["velocity_color"]["scale_mps"] == [0.0, 0.6], f"{tag}: velocity display scale")
    require(request["future_output_hashes"]["render_report_sha256"] is None, f"{tag}: future render SHA")
    require(request["future_output_hashes"]["focused_manifest_sha256"] is None, f"{tag}: future manifest SHA")

    stale = copy.deepcopy(request)
    worker_key = str(worker.resolve())
    stale["input_sha256"][worker_key] = "0" * 64
    stale_rejected = False
    stale_error = ""
    try:
        validate_closure(stale, f"{tag}/synthetic-stale-worker", worker)
    except ValueError as exc:
        stale_rejected = True
        stale_error = str(exc)
    require(stale_rejected, f"{tag}: stale worker hash was not rejected")

    return {
        "tag": tag,
        "attempt_id": request["attempt_id"],
        "worker_sha256": sha_static(worker),
        "binding_sha256": request["binding_sha256"],
        "closure": closure,
        "synthetic_negative_test": {
            "name": "stale_worker_input_sha256",
            "passed": stale_rejected,
            "rejection": stale_error,
            "stale_value": "0" * 64,
        },
        "source_h5_opened_or_rehashed": False,
        "actual_frames": actual_manifest["frames"],
        "actual_particle_axis": actual_manifest["particles"],
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = load(root / "manifest.json")
    report_path = root / "metadata/fresh122-validator-report.json"
    plan_path = root / "metadata/fresh122-source-plan.json"
    actual_path = root / "metadata/fresh122-actual-xmf-provenance.json"
    plan = load(plan_path)
    actual = load(actual_path)
    require(plan["schema"].startswith("ds02.f5.c082s1.fresh122"), "fresh122 source-plan schema")
    require(actual["schema"].startswith("ds02.f5.c082s1.fresh122"), "fresh122 provenance schema")
    require(len(actual["cases"]) == 2, "two Root598 cases required")
    require(report_path not in [root / row["path"] for row in manifest["files"]], "report self-reference")

    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SCIENCE_SUFFIXES:
            raise ValueError(f"science payload copied into source package: {path}")
    for row in manifest["files"]:
        path = root / row["path"]
        require(path.is_file(), f"manifest missing {path}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"manifest science payload {path}")
        require(sha_static(path) == row["sha256"], f"manifest SHA mismatch {path}")
        require(path.stat().st_size == row["bytes"], f"manifest byte mismatch {path}")

    worker = (root / "workers/focused_root023_velocity_renderer.py").resolve()
    require(sha_static(worker) == sha_static(worker), "worker source")
    cases = [validate_case(root, tag, worker, plan_path) for tag in ("A080", "A120")]
    report = {
        "schema": "ds02.f5.c082s1.fresh122-validator-report.v1",
        "status": "passed_metadata_only",
        "cases": cases,
        "input_closure": {
            "all_input_files_checked": True,
            "static_metadata_code_xmf_inputs_hashed": True,
            "H5_producer_attested_without_open_or_hash": True,
            "science_suffixes_never_opened_or_hashed": sorted(SCIENCE_SUFFIXES),
        },
        "display_contract": {
            "root023_renderer_unchanged": True,
            "camera_display_only": True,
            "velocity_color_magnitude_scale_mps": [0.0, 0.6],
            "focus_frames": [0, 97, 153, 219, 400, 718, 800],
            "all_801_requested": True,
            "arrays_edited_or_resampled": False,
        },
        "negative_tests": {"stale_worker_input_hash_rejected": all(c["synthetic_negative_test"]["passed"] for c in cases)},
        "fullnative_gate": "WAIT",
        "visual_mechanism_acceptance": False,
        "case_increment": 0,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"], "status": report["status"],
        "cases": [c["tag"] for c in cases],
        "science_payloads_opened_or_hashed": False,
        "stale_worker_hash_negative": report["negative_tests"]["stale_worker_input_hash_rejected"],
        "fullnative_gate": report["fullnative_gate"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
