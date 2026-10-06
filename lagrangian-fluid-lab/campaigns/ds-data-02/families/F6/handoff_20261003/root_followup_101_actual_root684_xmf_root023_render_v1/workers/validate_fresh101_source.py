#!/usr/bin/env python3
"""Metadata-only validator for the F6 fresh101 Root684 -> Root023 handoff.

The validator hashes only declared JSON/source metadata. It never opens or hashes
H5, BI4, CSV, IBI4, or DAT payloads and never launches XMF or render jobs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FORBIDDEN = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat"}
REQUIRED_ENV = {
    "OMP_NUM_THREADS=2", "OPENBLAS_NUM_THREADS=2", "MKL_NUM_THREADS=2",
    "NUMEXPR_NUM_THREADS=2", "VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2",
    "MESA_GLTHREAD=false",
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"JSON object required: {path}")
    return value


def digest(path: Path) -> str:
    if path.suffix.lower() in FORBIDDEN:
        raise AssertionError(f"scientific payload hash attempted: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_input_closure(obj: dict[str, Any], label: str, *, bound: bool = False) -> None:
    files = obj.get("input_files")
    hashes = obj.get("input_sha256")
    require(isinstance(files, list) and isinstance(hashes, dict), f"{label}: closure types")
    require(set(files) == set(hashes), f"{label}: input set mismatch")
    for text in files:
        path = Path(text)
        require(path.suffix.lower() not in FORBIDDEN, f"{label}: scientific payload in input closure")
        require(path.is_file(), f"{label}: missing metadata input: {path}")
        require(digest(path) == hashes[text], f"{label}: stale metadata digest: {path}")
    if bound:
        require(obj.get("bound_metadata_sha256") == hashes, f"{label}: bound closure mismatch")


def check_future_closure(obj: dict[str, Any], label: str) -> None:
    files = obj.get("future_input_files")
    hashes = obj.get("future_input_sha256")
    require(isinstance(files, list) and isinstance(hashes, dict), f"{label}: future closure types")
    require(set(files) == set(hashes), f"{label}: future input set mismatch")
    require(all(value is None for value in hashes.values()), f"{label}: future input hash is non-null")
    require(all(isinstance(text, str) and text for text in files), f"{label}: malformed future input path")


def check_future_outputs(obj: dict[str, Any], label: str) -> None:
    require(obj.get("future_hashes_null") is True, f"{label}: future guard missing")
    outputs = obj.get("future_outputs")
    require(isinstance(outputs, dict), f"{label}: future outputs missing")
    require(all(value is None for key, value in outputs.items() if key.endswith("_sha256")),
            f"{label}: future output hash is non-null")


def check_root684_registration(obj: dict[str, Any], case: str, label: str) -> dict[str, Any]:
    reg = obj.get("xmf_registration_684")
    require(isinstance(reg, dict), f"{label}: Root684 registration missing")
    require(reg.get("schema") == "ds02.f6.fresh101.root684-xmf-registration.v1", f"{label}: registration schema")
    require(reg.get("case_id") == case, f"{label}: registration case")
    req_path = Path(reg["registered_request"])
    bind_path = Path(reg["registered_binding"])
    require(req_path.is_file() and bind_path.is_file(), f"{label}: Root684 metadata missing")
    require(digest(req_path) == reg.get("registered_request_sha256"), f"{label}: Root684 request digest")
    require(digest(bind_path) == reg.get("registered_binding_sha256"), f"{label}: Root684 binding digest")
    root_request = read_json(req_path)
    root_binding = read_json(bind_path)
    require(root_request.get("case_id") == case, f"{label}: Root684 request case")
    require(root_request.get("xmf_binding") == str(bind_path), f"{label}: Root684 binding path")
    require(root_request.get("disabled") is False and root_request.get("execution_allowed") is True
            and root_request.get("launch_allowed") is True, f"{label}: Root684 request was not registered enabled")
    require(root_request.get("future_hashes_null") is True, f"{label}: Root684 future guard")
    require(root_binding.get("case_id") == case, f"{label}: Root684 binding case")
    require(reg.get("attempt_id") == root_request.get("attempt_id"), f"{label}: Root684 attempt id")
    require(reg.get("attempt_root") == root_request.get("attempt_root"), f"{label}: Root684 attempt root")
    require(reg.get("future_manifest") == root_request.get("actual_manifest"), f"{label}: Root684 manifest path")
    require(reg.get("future_case") == str(Path(reg["future_manifest"]).with_name("case.xmf")),
            f"{label}: Root684 case path")
    require(reg.get("future_receipt") == str(Path(reg["attempt_root"]) / "execution-receipt.json"),
            f"{label}: Root684 receipt path")
    for key in ("future_receipt_sha256", "future_case_sha256", "future_manifest_sha256"):
        require(reg.get(key) is None, f"{label}: fabricated Root684 future hash: {key}")
    require(reg.get("future_hashes_null") is True, f"{label}: Root684 registration future guard")
    require(reg.get("status") == "root684_registered_waiting_terminal_xmf_receipt_and_manifest",
            f"{label}: Root684 registration status")
    return reg


def validate(root: Path) -> dict[str, Any]:
    requests = sorted((root / "requests/render").glob("*.json"))
    bindings = sorted((root / "bindings/render").glob("*.json"))
    require(len(requests) == len(bindings) == 24, "fresh101 must contain 24 request/binding pairs")
    worker = root / "workers/render_native023.py"
    worker_sha = digest(worker)
    details = []
    for request_path in requests:
        request = read_json(request_path)
        case = request.get("case_id")
        require(case and request.get("fresh_id") == "fresh101", f"{request_path}: identity")
        require(request.get("disabled") is True and request.get("execution_allowed") is False
                and request.get("launch_allowed") is False, f"{case}: renderer enabled")
        require(request.get("worker") == str(worker), f"{case}: worker path")
        require(request.get("worker_sha256") == worker_sha, f"{case}: worker digest")
        require(request.get("cpu_threads") == 24 and request.get("declared_cpu_cores") == 24,
                f"{case}: CPU declaration")
        require(request.get("max_wall_seconds") == 14400, f"{case}: wall limit")
        require(request.get("cpu_task_kind") == "audit", f"{case}: task kind")
        require(REQUIRED_ENV <= set(request.get("command", [])), f"{case}: render environment")
        require("{attempt_root}/render" in request.get("command", []), f"{case}: output child")
        require(request.get("source_h5_sha256") is None, f"{case}: source H5 hash")
        require(request.get("xmf_shape_contract", {}).get("dynamic_vector_dimensions") == "417505 3",
                f"{case}: N3 vector contract")
        require(request.get("camera_policy", {}).get("fixed_camera_override") is False,
                f"{case}: fixed camera")
        require("camera_bounds" not in request and "domain_bounds" not in request,
                f"{case}: fixed bounds")
        check_input_closure(request, f"{case}: request")
        check_future_closure(request, f"{case}: request")
        check_future_outputs(request, f"{case}: request")
        reg = check_root684_registration(request, case, f"{case}: request")
        binding_path = root / "bindings/render" / f"{case}.render-binding.json"
        require(binding_path.is_file(), f"{case}: binding missing")
        binding = read_json(binding_path)
        require(binding.get("schema") == "ds02.f6.fresh101.render-binding.v1", f"{case}: binding schema")
        require(binding.get("worker") == str(worker) and binding.get("worker_sha256") == worker_sha,
                f"{case}: binding worker")
        require(binding.get("disabled") is True and binding.get("execution_allowed") is False
                and binding.get("launch_allowed") is False, f"{case}: binding enabled")
        require(binding.get("cpu_threads") == 24 and binding.get("declared_cpu_cores") == 24
                and binding.get("max_wall_seconds") == 14400, f"{case}: binding CPU contract")
        require(binding.get("xmf_registration_684") == reg, f"{case}: request/binding registration mismatch")
        require(binding.get("xmf_dependency", {}).get("status") ==
                "future_root684_xmf_receipt_and_manifest_required", f"{case}: XMF dependency")
        require(binding.get("xmf_case_sha256") is None and binding.get("xmf_manifest_sha256") is None,
                f"{case}: fabricated XMF output hash")
        require(binding.get("trajectory_h5_sha256") is None, f"{case}: H5 hash")
        check_input_closure(binding, f"{case}: binding", bound=True)
        check_future_closure(binding, f"{case}: binding")
        check_future_outputs(binding, f"{case}: binding")
        require(request.get("render_binding") == str(binding_path), f"{case}: request binding path")
        require(request.get("render_binding_sha256") == digest(binding_path), f"{case}: request binding digest")
        details.append({'case_id': case, 'root684_status': reg['status'], 'future_render_hashes_null': True})
    return {
        'status': 'pass', 'fresh_id': 'fresh101', 'cases': len(details),
        'root684_registered_cases': len(details), 'future_render_outputs_null': True,
        'renderer_worker_sha256': worker_sha,
        'declared_cpu_cores': 24, 'cpu_threads': 24, 'max_wall_seconds': 14400,
        'environment_threads': 2, 'no_scientific_payload_read_or_hashed': True,
        'details': details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(validate(args.root.resolve()), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
