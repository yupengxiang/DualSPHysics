#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

PACKAGE_SCHEMA = "ds02.f5.c082s1.fresh121"
WORKER_INTERFACE_SCHEMA = "ds02.f5.c082s1.typed590-control-dynamic-binding.fresh120.v1"
SCIENCE_SUFFIXES = {".h5", ".dat", ".bi4", ".csv", ".vtk"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def sha_static(path: Path) -> str:
    """Hash a source/metadata file; callers never pass a science payload."""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def is_science_payload(path_text: str) -> bool:
    return Path(path_text).suffix.lower() in SCIENCE_SUFFIXES


def validate_input_closure(
    request: dict,
    *,
    tag: str,
    root: Path,
    worker: Path,
    worker_sha: str,
) -> dict:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    require(isinstance(files, list), f"{tag}: input_files must be a list")
    require(isinstance(hashes, dict), f"{tag}: input_sha256 must be an object")
    require(len(files) == len(set(files)), f"{tag}: duplicate input_files")
    require(set(files) == set(hashes), f"{tag}: input_files/input_sha256 key mismatch")

    static_hashed = []
    science_attested = []
    for path_text in files:
        require(isinstance(path_text, str) and path_text, f"{tag}: invalid input path")
        expected = hashes[path_text]
        require(isinstance(expected, str) and HEX64.fullmatch(expected), f"{tag}: invalid hash {path_text}")
        path = Path(path_text)
        if is_science_payload(path_text):
            # Deliberately do not stat, open, or hash H5/DAT/BI4/CSV/VTK.
            if path == Path(request["trajectory_h5"]):
                require(expected == request["trajectory_h5_sha256"], f"{tag}: H5 is not producer-attested")
            elif path == Path(request["motion_file"]):
                require(expected == request["motion_file_sha256"], f"{tag}: DAT is not producer-attested")
            else:
                raise ValueError(f"{tag}: unexpected science payload input {path}")
            science_attested.append(path_text)
            continue
        require(path.is_file(), f"{tag}: static input missing {path}")
        actual = sha_static(path)
        require(actual == expected, f"{tag}: static input hash mismatch {path}")
        static_hashed.append(path_text)

    command = request.get("command")
    require(isinstance(command, list) and len(command) >= 2, f"{tag}: command shape")
    command_worker = Path(command[1]).resolve()
    require(command_worker == worker.resolve(), f"{tag}: command worker path mismatch")
    worker_key = str(worker.resolve())
    require(hashes.get(worker_key) == worker_sha, f"{tag}: worker input hash mismatch")
    require(request.get("binding_sha256") == hashes.get(str(Path(request["binding"]).resolve())), f"{tag}: binding closure mismatch")
    return {
        "input_files": len(files),
        "static_inputs_hashed": len(static_hashed),
        "science_inputs_attested_without_open": len(science_attested),
        "science_paths": science_attested,
    }


def validate_case(root: Path, tag: str, worker: Path, worker_sha: str) -> dict:
    binding_path = (root / f"bindings/{tag}-typed590-control-dynamic-binding.json").resolve()
    request_path = (root / f"requests/{tag}-typed590-control-dynamic-audit-request.json").resolve()
    binding = load(binding_path)
    request = load(request_path)

    require(request["disabled"] is True, f"{tag}: request is enabled")
    require(request["execution_allowed"] is False and request["launch"] is False, f"{tag}: launch gate")
    require(request["solver_allowed"] is False and request["conversion_allowed"] is False, f"{tag}: solver/conversion gate")
    require(request["kind"] == "cpu" and request["cpu_task_kind"] == "audit" and request["cpu_threads"] == 2, f"{tag}: runtime kind")
    require(request["arrays_allowed"] is True and request["array_edit_allowed"] is False, f"{tag}: array contract")
    require(request["fullnative_gate"]["status"] == "WAIT" and request["full801_authorized"] is False, f"{tag}: full gate")
    require(binding["execution_allowed"] is False and binding["source_only"] is True, f"{tag}: binding gate")
    require(binding["schema"] == WORKER_INTERFACE_SCHEMA, f"{tag}: producer worker schema changed")
    require(request["binding"] == str(binding_path), f"{tag}: request binding path")
    require(request["binding_sha256"] == sha_static(binding_path), f"{tag}: binding sha")
    require(binding["native_bed_marker_mk"] == 50 and binding["source_mkbound"] == 40, f"{tag}: Mk mapping")
    require([item["frame"] for item in binding["focus_frames"]] == [0, 97, 153, 219, 400, 718, 800], f"{tag}: focus frames")
    require(request["future_output_hashes"]["audit_report_sha256"] is None, f"{tag}: future output hash")
    require(
        isinstance(binding.get("source_h5_condition_sha256"), str)
        and binding.get("source_h5_scope_schema") == "legacy-owner-scope.v0",
        f"{tag}: H5 legacy scope",
    )

    closure = validate_input_closure(request, tag=tag, root=root, worker=worker, worker_sha=worker_sha)

    conversion = load(Path(binding["conversion_report"]))
    motion = load(Path(binding["motion_transform_report"]))
    require(conversion["conversion_status"] == "completed", f"{tag}: conversion producer status")
    require(conversion["frames"] == 801 and conversion["particles"] == 194427, f"{tag}: conversion producer shape")
    require(conversion["solver_dimension"]["solver_dimension"] == 3, f"{tag}: conversion dimension")
    require(conversion["output_hdf5"] == binding["trajectory_h5"], f"{tag}: H5 producer path")
    require(conversion["output_sha256"] == binding["trajectory_h5_sha256"], f"{tag}: H5 producer SHA")
    require(motion["status"] == "completed" and motion["rows"] == 641, f"{tag}: motion producer shape")
    require(motion["output_motion"] == binding["motion_file"], f"{tag}: DAT producer path")
    require(motion["output_motion_sha256"] == binding["motion_file_sha256"], f"{tag}: DAT producer SHA")

    xml_path = root / f"inputs/{tag}-Definition.xml"
    xml = ET.parse(xml_path).getroot()
    obj = xml.find("./casedef/motion/objreal")
    require(obj is not None, f"{tag}: motion XML object")
    begin = obj.find("./begin")
    mv = obj.find("./mvpredef")
    file_node = None if mv is None else mv.find("./file")
    require(
        obj.attrib.get("ref") == "10"
        and begin is not None
        and begin.attrib.get("mov") == "1"
        and begin.attrib.get("start") == "0.00"
        and begin.attrib.get("finish") == "16",
        f"{tag}: motion XML window",
    )
    require(
        mv is not None
        and mv.attrib.get("id") == "1"
        and mv.attrib.get("duration") == "16"
        and file_node is not None
        and file_node.attrib.get("fieldtime") == "0"
        and file_node.attrib.get("fieldx") == "1",
        f"{tag}: motion XML fields",
    )

    # A synthetic stale worker hash must fail the same closure check that Root
    # will use. This mutates only an in-memory request copy.
    stale = copy.deepcopy(request)
    worker_key = str(worker.resolve())
    stale["input_sha256"][worker_key] = "0" * 64
    stale_rejected = False
    stale_error = ""
    try:
        validate_input_closure(stale, tag=f"{tag}/synthetic-stale-worker", root=root, worker=worker, worker_sha=worker_sha)
    except ValueError as exc:
        stale_rejected = True
        stale_error = str(exc)
    require(stale_rejected, f"{tag}: stale worker hash negative test did not fail")

    return {
        "tag": tag,
        "attempt_id": request["attempt_id"],
        "worker_sha256": worker_sha,
        "binding_sha256": request["binding_sha256"],
        "closure": closure,
        "synthetic_negative_test": {
            "name": "stale_worker_input_sha256",
            "passed": stale_rejected,
            "rejection": stale_error,
            "stale_value": "0" * 64,
        },
        "producer_attestation": {
            "typed_frames": conversion["frames"],
            "typed_particles": conversion["particles"],
            "solver_dimension": conversion["solver_dimension"]["solver_dimension"],
            "h5_opened_or_rehashed": False,
            "dat_opened_or_rehashed": False,
        },
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = load(root / "manifest.json")
    report_path = root / "metadata/fresh121-validator-report.json"
    plan = load(root / "metadata/fresh121-source-plan.json")
    actual = load(root / "metadata/fresh121-actual-typed590-metadata.json")
    require(plan["schema"].startswith(PACKAGE_SCHEMA), "fresh121 source-plan schema")
    require(actual["schema"].startswith(PACKAGE_SCHEMA), "fresh121 actual schema")
    require(len(actual["cases"]) == 2, "two typed590 cases required")
    require(report_path not in [root / item["path"] for item in manifest["files"]], "validator report self-reference")

    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SCIENCE_SUFFIXES:
            raise ValueError(f"science payload copied into source package: {path}")

    for item in manifest["files"]:
        path = root / item["path"]
        require(path.is_file(), f"manifest missing {path}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"manifest contains science payload {path}")
        require(sha_static(path) == item["sha256"], f"manifest hash mismatch {path}")
        require(path.stat().st_size == item["bytes"], f"manifest byte mismatch {path}")

    worker = (root / "workers/typed590_control_dynamic_audit.py").resolve()
    worker_sha = sha_static(worker)
    require(worker_sha == "d8ecb69288afeb4e5041a5c2b1e7527bdcfe9d59b86b34cd1f900a446846107f", "actual worker SHA")
    worker_text = worker.read_text(encoding="utf-8")
    require(f'BINDING_SCHEMA = "{WORKER_INTERFACE_SCHEMA}"' in worker_text, "producer worker interface")
    cases = [validate_case(root, tag, worker, worker_sha) for tag in ("A080", "A120")]

    report = {
        "schema": "ds02.f5.c082s1.fresh121-validator-report.v1",
        "status": "passed_metadata_only",
        "package": root.name,
        "cases": cases,
        "input_closure": {
            "all_input_files_checked": True,
            "static_metadata_code_inputs_hashed": True,
            "science_inputs_producer_attested_only": True,
            "science_suffixes_never_opened_or_hashed": sorted(SCIENCE_SUFFIXES),
        },
        "negative_tests": {
            "stale_worker_input_hash_rejected": all(c["synthetic_negative_test"]["passed"] for c in cases),
        },
        "fullnative_gate": "WAIT",
        "visual_mechanism_acceptance": False,
        "precision_granted": False,
        "case_increment": 0,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "worker_sha256": worker_sha,
        "cases": [c["tag"] for c in cases],
        "science_payloads_opened_or_hashed": False,
        "stale_worker_hash_negative": report["negative_tests"]["stale_worker_input_hash_rejected"],
        "fullnative_gate": report["fullnative_gate"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
