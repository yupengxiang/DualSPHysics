#!/usr/bin/env python3
"""Metadata-only structural validator for the F6 fresh100 handoff.

This validator reads JSON/source metadata and hashes only declared non-payload
metadata. It never opens or hashes H5, BI4, CSV, IBI4, or DAT payloads and never
launches a runner, converter, XMF exporter, or renderer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FORBIDDEN = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat"}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"JSON object required: {path}")
    return value


def digest(path: Path) -> str:
    if path.suffix.lower() in FORBIDDEN:
        raise AssertionError(f"payload hash attempted: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_hash_closure(obj: dict[str, Any], label: str, *, bound: bool = False) -> None:
    files = obj.get("input_files", [])
    hashes = obj.get("input_sha256", {})
    require(isinstance(files, list) and isinstance(hashes, dict), f"{label}: input closure types")
    require(set(files) == set(hashes), f"{label}: input_files/input_sha256 set mismatch")
    for text in files:
        path = Path(text)
        require(path.suffix.lower() not in FORBIDDEN, f"{label}: payload in input_files: {path}")
        require(path.is_file(), f"{label}: missing metadata input: {path}")
        actual = digest(path)
        require(actual == hashes[text], f"{label}: stale metadata digest: {path}")
    if bound:
        require(obj.get("bound_metadata_sha256") == hashes, f"{label}: bound metadata closure differs")


def check_future_closure(obj: dict[str, Any], label: str) -> None:
    files = obj.get("future_input_files", [])
    hashes = obj.get("future_input_sha256", {})
    require(isinstance(files, list) and isinstance(hashes, dict), f"{label}: future closure types")
    require(set(files) == set(hashes), f"{label}: future input set mismatch")
    require(all(value is None for value in hashes.values()), f"{label}: future hash is non-null")
    for text in files:
        # A future JSON receipt/report may already exist with a running or failed
        # state; the contract remains future until a terminal pass is explicitly
        # rebound. Only the null hash and path-shape guards are authoritative here.
        require(isinstance(text, str) and bool(text),
                f"{label}: malformed future input path: {text}")


def check_actual_typed(binding: dict[str, Any], label: str) -> dict[str, Any]:
    report_path = Path(binding["conversion_report"])
    receipt_path = Path(binding["typed_receipt"])
    require(report_path.is_file() and receipt_path.is_file(), f"{label}: typed producer metadata missing")
    report = read_json(report_path)
    receipt = read_json(receipt_path)
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            f"{label}: Root607 receipt is not completed/0")
    require(report.get("conversion_status") == "completed", f"{label}: conversion report not completed")
    require(report.get("frames") == 241 and report.get("particles") == 417505,
            f"{label}: typed count/frame mismatch")
    require(report.get("solver_dimension", {}).get("solver_dimension") == 3,
            f"{label}: typed report is not 3D")
    require(report.get("partvtk_validation", {}).get("all_passed") is True,
            f"{label}: typed PartVTK is not passed")
    scopes = report.get("hash_scopes", {})
    physical = scopes.get("physical_condition", {})
    require(scopes.get("physical_condition_sha256") == binding.get("physical_condition_sha256"),
            f"{label}: actual producer scope mismatch")
    require(binding.get("producer_scope_sha256") == scopes.get("physical_condition_sha256"),
            f"{label}: producer scope alias mismatch")
    require(physical.get("schema") == binding.get("producer_scope_schema"),
            f"{label}: producer scope schema mismatch")
    require(physical.get("physical_case_id") == binding.get("physical_case_id"),
            f"{label}: producer physical case mismatch")
    require(report.get("output_hdf5") == binding.get("trajectory_h5"),
            f"{label}: producer H5 path mismatch")
    require(binding.get("trajectory_h5_sha256") is None,
            f"{label}: source package independently hashed H5")
    return report


def check_audit(dep: dict[str, Any], label: str) -> str:
    status = dep.get("status")
    require(status in {"actual_root658_pass", "future_root658_terminal_pass_required"},
            f"{label}: invalid Root658 status")
    require(dep.get("source_package_did_not_read_or_hash_h5") is True,
            f"{label}: H5 source-read guard missing")
    if status == "actual_root658_pass":
        report_path = Path(dep["report"])
        receipt_path = Path(dep["execution_receipt"])
        require(report_path.is_file() and receipt_path.is_file(), f"{label}: actual audit files missing")
        report = read_json(report_path)
        receipt = read_json(receipt_path)
        require(report.get("status") == "pass", f"{label}: audit report not pass")
        checks = report.get("checks")
        require(isinstance(checks, dict) and checks and all(value is True for value in checks.values()),
                f"{label}: audit checks are not all true")
        require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
                f"{label}: audit receipt is not completed/0")
        require(dep.get("audit_status") == "pass" and dep.get("checks_all_pass") is True,
                f"{label}: actual audit status fields inconsistent")
        require(dep.get("report_sha256") == digest(report_path), f"{label}: audit report digest stale")
        require(dep.get("execution_receipt_sha256") == digest(receipt_path), f"{label}: audit receipt digest stale")
        return "actual"
    require(dep.get("report_sha256") is None and dep.get("execution_receipt_sha256") is None,
            f"{label}: future audit has a fabricated SHA")
    require(dep.get("audit_status") is None and dep.get("checks_all_pass") is None,
            f"{label}: future audit has fabricated pass fields")
    return "future"


def validate(root: Path) -> dict[str, Any]:
    xmf_requests = sorted((root / "requests/xmf").glob("*.json"))
    xmf_bindings = sorted((root / "bindings/xmf").glob("*.json"))
    render_requests = sorted((root / "requests/render").glob("*.json"))
    render_bindings = sorted((root / "bindings/render").glob("*.json"))
    require(len(xmf_requests) == len(xmf_bindings) == len(render_requests) == len(render_bindings) == 24,
            "fresh100 must contain 24 XMF and 24 render request/binding pairs")
    worker_xmf = root / "workers/export_xmf.py"
    worker_render = root / "workers/render_native023.py"
    xmf_digest = digest(worker_xmf)
    render_digest = digest(worker_render)
    actual_audits = 0
    future_audits = 0
    cases = []
    for request_path in xmf_requests:
        request = read_json(request_path)
        case = request.get("case_id")
        require(case and request.get("fresh_id") == "fresh100", f"{request_path}: identity")
        require(request.get("disabled") is True and request.get("execution_allowed") is False
                and request.get("launch_allowed") is False, f"{case}: XMF is enabled")
        require(request.get("worker_sha256") == xmf_digest, f"{case}: XMF worker digest")
        require(request.get("worker_contract", {}).get("dynamic_vector_dimensions") == "417505 3",
                f"{case}: XMF vector contract")
        require(request.get("worker_contract", {}).get("dynamic_scalar_dimensions") == "417505",
                f"{case}: XMF scalar contract")
        require(request.get("future_hashes_null") is True, f"{case}: XMF future guard")
        require(all(value is None for key, value in request.get("future_outputs", {}).items()
                    if key.endswith("_sha256")), f"{case}: XMF future output digest")
        check_hash_closure(request, f"{case}: XMF request")
        check_future_closure(request, f"{case}: XMF request")
        binding_path = Path(request["xmf_binding"])
        require(binding_path.is_file(), f"{case}: XMF binding missing")
        binding = read_json(binding_path)
        require(binding.get("schema") == "ds02.f6.fresh100.xmf-binding.v1", f"{case}: XMF schema")
        require(binding.get("worker_sha256") == xmf_digest, f"{case}: XMF binding worker digest")
        require(binding.get("trajectory_h5_sha256") is None, f"{case}: binding H5 digest")
        check_hash_closure(binding, f"{case}: XMF binding", bound=True)
        check_future_closure(binding, f"{case}: XMF binding")
        report = check_actual_typed(binding, f"{case}: XMF binding")
        audit_kind = check_audit(binding["audit658_dependency"], f"{case}: XMF audit")
        actual_audits += audit_kind == "actual"
        future_audits += audit_kind == "future"
        require(binding.get("source_canonical_physical_condition_sha256") != binding.get("physical_condition_sha256"),
                f"{case}: canonical and producer scopes were collapsed")
        require(request.get("audit658_dependency") == binding.get("audit658_dependency"),
                f"{case}: request/binding audit dependency differs")
        # Render pair.
        render_path = root / "requests/render" / f"{case}-root-native023-render-request.json"
        render_binding_path = root / "bindings/render" / f"{case}.render-binding.json"
        require(render_path.is_file() and render_binding_path.is_file(), f"{case}: render pair missing")
        render_request = read_json(render_path)
        render_binding = read_json(render_binding_path)
        require(render_request.get("disabled") is True and render_request.get("execution_allowed") is False,
                f"{case}: render is enabled")
        require(render_request.get("worker_sha256") == render_digest, f"{case}: render worker digest")
        require(render_request.get("declared_cpu_cores") == 24, f"{case}: render CPU declaration")
        require(render_request.get("cpu_task_kind") == "audit" and render_request.get("cpu_threads") == 2,
                f"{case}: render CPU task contract")
        require(render_request.get("source_h5_sha256") is None, f"{case}: render H5 digest")
        command = render_request.get("command", [])
        required_env = {"OMP_NUM_THREADS=2", "OPENBLAS_NUM_THREADS=2", "MKL_NUM_THREADS=2",
                        "NUMEXPR_NUM_THREADS=2", "VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2",
                        "MESA_GLTHREAD=false"}
        require(required_env <= set(command), f"{case}: render environment contract")
        require("{attempt_root}/render" in command, f"{case}: render output child")
        require(render_request.get("camera_policy", {}).get("fixed_camera_override") is False,
                f"{case}: fixed camera override")
        require("camera_bounds" not in render_request and "domain_bounds" not in render_request,
                f"{case}: fixed bounds present")
        check_hash_closure(render_request, f"{case}: render request")
        check_future_closure(render_request, f"{case}: render request")
        require(render_binding.get("schema") == "ds02.f6.fresh100.render-binding.v1",
                f"{case}: render binding schema")
        require(render_binding.get("worker_sha256") == render_digest, f"{case}: render binding digest")
        require(render_binding.get("trajectory_h5_sha256") is None, f"{case}: render binding H5 digest")
        check_hash_closure(render_binding, f"{case}: render binding", bound=True)
        check_future_closure(render_binding, f"{case}: render binding")
        require(render_binding.get("xmf_dependency", {}).get("status") == "future_root_owned_xmf_required",
                f"{case}: render XMF dependency")
        require(render_binding.get("camera_policy", {}).get("camera_bounds_in_manifest") is False,
                f"{case}: render fixed manifest bounds")
        cases.append({'case_id': case, 'audit': audit_kind, 'typed_report_frames': report['frames']})
    return {
        'status': 'pass', 'fresh_id': 'fresh100', 'cases': len(cases),
        'actual_root658_audits': actual_audits, 'future_root658_audits': future_audits,
        'xmf_worker_sha256': xmf_digest, 'render_worker_sha256': render_digest,
        'no_scientific_payload_read_or_hashed': True, 'cases_detail': cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(validate(args.root.resolve()), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
