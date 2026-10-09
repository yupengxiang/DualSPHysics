#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Compare the actual F5 q117/q124 geometry reports with q123 as an anchor.

Only small request, receipt-proof, and geometry-report JSON files are read.
No generated XML, VTK, BI4, HDF5, solver output, or array payload is opened.
The q123 proof is retained as a separate hard-fail producer anchor because it
has no geometry-report artifact; it is never silently treated as a third
geometry report or as a neighboring-grid truth value.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_f5_s1_yphase_shape_compare_v1.py"
SCHEMA = "ds02.stage2.f5-s1.yphase-shape-compare.v2"
REQUEST_SCHEMA = "ds02.request.v1"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
FAMILY_ID = "F5"
SENTINEL_ID = "F5-S1"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V1 = load_module("stage2_f5_shape_compare_v1_for_v2", V1_PATH)


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    return V1.load_json(regular(path, label), label)


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_json_only_hashed_by_worker_and_parent_v8",
    }


def _identity(value: dict[str, Any], label: str) -> None:
    expected = {"family_id": FAMILY_ID, "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID}
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise ValueError(f"{label} {key} mismatch: {value.get(key)!r} != {wanted!r}")


def _proof_binding(
    proof_path: Path,
    request_path: Path,
    report_path: Path | None,
    label: str,
    expected_status_prefix: str,
) -> dict[str, Any]:
    proof_path = regular(proof_path, f"{label} proof")
    request_path = regular(request_path, f"{label} request")
    proof = load_json(proof_path, f"{label} proof")
    if proof.get("schema") != PROOF_SCHEMA:
        raise ValueError(f"{label} proof schema mismatch")
    if not str(proof.get("status", "")).startswith(expected_status_prefix):
        raise ValueError(f"{label} proof status is not terminal: {proof.get('status')!r}")
    proof_request = proof.get("request")
    proof_request_sha = proof.get("request_sha256")
    actual_request_sha = sha256(request_path)
    if proof_request != str(request_path) or proof_request_sha != actual_request_sha:
        raise ValueError(f"{label} proof does not bind the supplied request and SHA")
    binding: dict[str, Any] = {
        "proof": record(proof_path, f"{label} actual verification proof"),
        "proof_schema": proof.get("schema"),
        "proof_status": proof.get("status"),
        "request": record(request_path, f"{label} producer request"),
        "request_sha256_exact": True,
    }
    if report_path is not None:
        report_path = regular(report_path, f"{label} geometry report")
        proof_report = proof.get("report")
        proof_report_sha = proof.get("report_sha256")
        actual_report_sha = sha256(report_path)
        if proof_report != str(report_path) or proof_report_sha != actual_report_sha:
            raise ValueError(f"{label} proof does not bind the supplied report and SHA")
        binding["report"] = record(report_path, f"{label} actual geometry report")
        binding["report_sha256_exact"] = True
    binding["receipt"] = {
        "path": proof.get("receipt"),
        "sha256": proof.get("receipt_sha256"),
        "proof_receipt_binding": True,
    }
    # These producer proofs must remain source/audit evidence, not an implicit
    # solver or field-qualification grant.
    binding["payload_read_or_hashed_by_root"] = proof.get("root_array_read_or_hash", proof.get("root_vtk_read_or_hash", False))
    binding["solver_started"] = proof.get("solver_started", False)
    return binding


def _report(request_path: Path, report_path: Path, proof_path: Path, label: str, prefix: str) -> tuple[dict[str, Any], dict[str, Any]]:
    request_path = regular(request_path, f"{label} request")
    report_path = regular(report_path, f"{label} report")
    request = load_json(request_path, f"{label} request")
    report = load_json(report_path, f"{label} report")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"{label} request schema mismatch")
    _identity(request, f"{label} request")
    _identity(report, f"{label} report")
    request["_source_path"] = str(request_path)
    summary = V1._report_summary(report, request, label)
    proof = _proof_binding(proof_path, request_path, report_path, label, prefix)
    return summary, proof


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    baseline, baseline_proof = _report(args.baseline_request, args.baseline_report, args.baseline_proof, "q117_yhalf_dp005", "VERIFIED_ACTUAL_F5_YHALF_GEOMETRY")
    candidate, candidate_proof = _report(args.candidate_request, args.candidate_report, args.candidate_proof, "q124_yzero_dp005", "VERIFIED_ACTUAL_F5_YZERO_V10")

    third_request_path = regular(args.third_request, "q123 Y-zero GenCase request")
    third_proof_path = regular(args.third_proof, "q123 Y-zero hard-fail proof")
    third_request = load_json(third_request_path, "q123 Y-zero GenCase request")
    third_proof = load_json(third_proof_path, "q123 Y-zero hard-fail proof")
    if third_request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("q123 request schema mismatch")
    _identity(third_request, "q123 request")
    third_binding = _proof_binding(third_proof_path, third_request_path, None, "q123_yzero_dp005", "VERIFIED_ACTUAL_F5_YZERO_INITIAL_MASS_HARDFAIL")
    if third_proof.get("mass_gate") != "HARDFAIL_OVER_TWO_PERCENT":
        raise ValueError(f"q123 hard-fail proof mass gate changed: {third_proof.get('mass_gate')!r}")
    third_binding["hardfail_anchor"] = {
        "mass_gate": third_proof.get("mass_gate"),
        "actual_fluid_count": third_proof.get("actual_fluid_count"),
        "actual_massfluid_kg": third_proof.get("actual_massfluid_kg"),
        "continuous_owner_mass_kg": third_proof.get("continuous_owner_mass_kg"),
        "relative_mass_error": third_proof.get("relative_mass_error"),
        "qualification_credit": third_proof.get("qualification_credit"),
        "not_a_geometry_report": True,
    }

    base_count = baseline.get("generated", {}).get("fluid_count")
    cand_count = candidate.get("generated", {}).get("fluid_count")
    base_mass = baseline.get("generated", {}).get("massfluid_kg")
    cand_mass = candidate.get("generated", {}).get("massfluid_kg")
    compare = {
        "q117_vs_q124": {
            "fluid_count_delta": cand_count - base_count if isinstance(base_count, (int, float)) and isinstance(cand_count, (int, float)) else None,
            "massfluid_kg_delta": cand_mass - base_mass if isinstance(base_mass, (int, float)) and isinstance(cand_mass, (int, float)) else None,
            "axis_and_per_mk_fields_are_diagnostic": True,
            "time_or_output_error_measured": False,
            "particle_position_or_velocity_error_measured": False,
        },
        "q123_anchor": {
            "status": "HARDFAIL_ANCHOR_ONLY",
            "geometry_report_available": False,
            "mass_gate": third_proof.get("mass_gate"),
            "must_not_be_joined_as_neighbor_truth": True,
        },
    }
    paths = [
        args.baseline_request, args.baseline_report, args.baseline_proof,
        args.candidate_request, args.candidate_report, args.candidate_proof,
        args.third_request, args.third_proof,
    ]
    input_records = {str(regular(path, "JSON input")): record(path, "F5 JSON-only compare input") for path in paths}
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_JSON_ONLY_TRI_SOURCE_SHAPE_DIAGNOSTIC",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "scope": {
            "payload_arrays_read": False,
            "vtk_read": False,
            "bi4_read": False,
            "hdf5_read": False,
            "source_reports_and_proofs_only": True,
            "neighbor_grid_is_not_truth": True,
        },
        "inputs": input_records,
        "baseline": baseline,
        "candidate": candidate,
        "third_hardfail_anchor": third_binding,
        "proof_bindings": {"q117": baseline_proof, "q124": candidate_proof, "q123": third_binding},
        "pair_diagnostics": compare,
        "all_shapes_comparison": {
            "status": "PARTIAL_REPORT_FIELDS_ONLY",
            "required_scopes": ["fluid", "fixed_boundary", "moving_boundary", "forcing", "shape_operations"],
            "bound_per_mk_assignment": "UNKNOWN_NO_BOUND_IDP",
            "fixed_boundary_shape_comparison": "UNKNOWN_NO_BOUND_IDP",
            "moving_boundary_shape_comparison": "UNKNOWN_NO_BOUND_IDP",
            "forcing_shape_comparison": "UNKNOWN_NOT_REPORTED_BY_THIS_WORKER",
            "shape_operation_comparison": "UNKNOWN_NOT_REPORTED_BY_THIS_WORKER",
            "q123_geometry": "UNKNOWN_NO_GEOMETRY_REPORT; hard-fail proof retained separately",
            "control_motion_identity_is_not_shape_comparison": True,
            "qualification_granted": False,
        },
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "three-source JSON-only diagnostic; q123 hardfail is preserved, while all-shape, integration, output and neighbor-truth qualification remain unknown",
        },
    }


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    result = V1.self_test()
    if result.get("status") != "PASS":
        raise AssertionError(result)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "proofs_required": ["q117", "q124", "q123"],
        "payload_arrays_read": False,
        "solver_started": False,
        "q123_hardfail_preserved": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    for name in ("baseline-request", "baseline-report", "baseline-proof", "candidate-request", "candidate-report", "candidate-proof", "third-request", "third-proof", "output"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = [args.baseline_request, args.baseline_report, args.baseline_proof, args.candidate_request, args.candidate_report, args.candidate_proof, args.third_request, args.third_proof, args.output]
    if any(value is None for value in required):
        parser.error("--run requires q117/q124 request+report+proof, q123 request+proof and output")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "schema": SCHEMA, "output": str(args.output.resolve()), "payload_arrays_read": False, "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
