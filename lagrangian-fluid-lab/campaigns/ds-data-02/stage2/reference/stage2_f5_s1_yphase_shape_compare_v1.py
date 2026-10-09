#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Compare two F5 initial-geometry reports without reopening payload arrays.

This worker consumes only the terminal GenCase request JSON and the bounded
geometry-report JSONs.  It deliberately keeps fixed/moving/forcing shape
assignment and per-MK boundary coordinates UNKNOWN when the producer report
does not expose an Idp mapping for the boundary VTK.  A control or motion
identity match is not treated as a shape comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f5-s1.yphase-shape-compare.v1"
REQUEST_SCHEMA = "ds02.request.v1"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
FAMILY_ID = "F5"
SENTINEL_ID = "F5-S1"
REQUIRED_SCOPES = ["fluid", "fixed_boundary", "moving_boundary", "forcing", "shape_operations"]


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
    path = regular(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        if math.isfinite(parsed):
            return int(parsed) if parsed.is_integer() else parsed
    return None


def _identity(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value.get(key) for key in ("family_id", "sentinel_id", "physical_case_id")}


def _require_identity(value: dict[str, Any], label: str) -> None:
    expected = {"family_id": FAMILY_ID, "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID}
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise ValueError(f"{label} {key} mismatch: {value.get(key)!r} != {wanted!r}")


def _report_summary(report: dict[str, Any], request: dict[str, Any], label: str) -> dict[str, Any]:
    _require_identity(report, f"{label} report")
    _require_identity(request, f"{label} request")
    if report.get("schema") not in {
        "ds02.stage2.f5-s1.clipplane-geometry-diagnostic.v8",
        "ds02.stage2.f5-s1.clipplane-yzero-geometry-diagnostic.v9",
        "ds02.stage2.f5-s1.clipplane-yzero-geometry-diagnostic.v10",
    }:
        raise ValueError(f"{label} report schema is not a supported geometry diagnostic")
    status = str(report.get("status", ""))
    if not status.startswith("COMPLETED"):
        raise ValueError(f"{label} report is not completed: {status}")
    generated = report.get("generated") if isinstance(report.get("generated"), dict) else {}
    geometry = report.get("geometry_diagnostic") if isinstance(report.get("geometry_diagnostic"), dict) else {}
    per_mk = geometry.get("per_mkfluid_blocks")
    if not isinstance(per_mk, list):
        per_mk = []
    generated_summary = geometry.get("selector_and_operation_trace", {}).get("generated", {})
    particle_summary = generated_summary.get("particles_summary") if isinstance(generated_summary, dict) else None
    particle_counts: dict[str, int | float | None] = {}
    if isinstance(particle_summary, dict):
        for source, target in (("nbf", "fixed_boundary"), ("nb", "fixed_plus_moving_boundary"), ("np", "total")):
            particle_counts[target] = _number(particle_summary.get(source))
        nb = particle_counts.get("fixed_plus_moving_boundary")
        np = particle_counts.get("total")
        fixed = particle_counts.get("fixed_boundary")
        particle_counts["moving_boundary"] = int(nb - fixed) if isinstance(nb, (int, float)) and isinstance(fixed, (int, float)) else None
        particle_counts["fluid"] = int(np - nb) if isinstance(np, (int, float)) and isinstance(nb, (int, float)) else None
    else:
        particle_counts = {key: None for key in ("fixed_boundary", "fixed_plus_moving_boundary", "moving_boundary", "fluid", "total")}
    control = report.get("control_audit") if isinstance(report.get("control_audit"), dict) else {}
    source_binding = request.get("source_binding") if isinstance(request.get("source_binding"), dict) else {}
    bound_idp = geometry.get("bound_vtk_idp", "UNKNOWN_NOT_PRESENT_IN_BOUND_READER")
    bound_assignment = "UNKNOWN_NO_BOUND_IDP" if str(bound_idp).startswith("UNKNOWN") else "AVAILABLE_FROM_REPORT"
    mass = report.get("mass_audit") if isinstance(report.get("mass_audit"), dict) else {}
    return {
        "label": label,
        "report_schema": report.get("schema"),
        "status": status,
        "request_path": str(request.get("_source_path", "UNKNOWN")),
        "grid": source_binding.get("grid", report.get("grid")),
        "dp_m": _number(source_binding.get("dp_m", generated.get("dp_m"))),
        "pointref_m": source_binding.get("pointref_m"),
        "generated": {
            "fluid_count": _number(generated.get("fluid_count")),
            "massfluid_kg": _number(generated.get("massfluid_kg")),
            "fluid_blocks": generated.get("fluid_blocks", []),
        },
        "particle_counts": particle_counts,
        "fluid_mk_blocks": per_mk,
        "generated_fluid_axis_summary": geometry.get("generated_fluid_axis_summary"),
        "generated_bound_axis_summary": geometry.get("generated_bound_axis_summary"),
        "bound_per_mk_assignment": bound_assignment,
        "bound_vtk_idp": bound_idp,
        "fluid_idp_mapping": geometry.get("fluid_vtk_idp_mapping"),
        "control_identity": {
            "motion_byte_identical": control.get("motion_byte_identical"),
            "source_candidate_controls_equal": control.get("source_candidate_controls_equal"),
            "source_candidate_boundary_equal": control.get("source_candidate_boundary_equal"),
            "normalized_source_candidate_representation_equal": control.get("normalized_source_candidate_representation_equal"),
            "source_parameters": control.get("source_parameters"),
            "candidate_parameters": control.get("candidate_parameters"),
            "generated_parameters": control.get("generated_parameters"),
            "identity_is_not_shape_comparison": True,
        },
        "mass_audit": {
            "gate": mass.get("gate"),
            "relative_error": mass.get("relative_error"),
            "relative_error_fraction": mass.get("relative_error_fraction"),
            "continuous_owner_mass_kg": mass.get("continuous_owner_mass_kg"),
            "generated_mass_kg": mass.get("generated_mass_kg", generated.get("massfluid_kg")),
        },
        "source_closure": {
            "report_source_closure": report.get("source_closure"),
            "request_source_binding": source_binding,
            "payload_reopened_by_comparator": False,
        },
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    baseline_request_path = regular(args.baseline_request, "baseline request")
    candidate_request_path = regular(args.candidate_request, "candidate request")
    baseline_report_path = regular(args.baseline_report, "baseline report")
    candidate_report_path = regular(args.candidate_report, "candidate report")
    baseline_request = load_json(baseline_request_path, "baseline request")
    candidate_request = load_json(candidate_request_path, "candidate request")
    baseline_report = load_json(baseline_report_path, "baseline report")
    candidate_report = load_json(candidate_report_path, "candidate report")
    for value, path in ((baseline_request, baseline_request_path), (candidate_request, candidate_request_path)):
        value["_source_path"] = str(path)
    base = _report_summary(baseline_report, baseline_request, "baseline")
    candidate = _report_summary(candidate_report, candidate_request, "candidate")
    base_mass = _number(base["generated"].get("massfluid_kg"))
    cand_mass = _number(candidate["generated"].get("massfluid_kg"))
    base_count = _number(base["generated"].get("fluid_count"))
    cand_count = _number(candidate["generated"].get("fluid_count"))
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_JSON_ONLY_SHAPE_DIAGNOSTIC",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "scope": {
            "payload_arrays_read": False,
            "vtk_read": False,
            "bi4_read": False,
            "hdf5_read": False,
            "source_reports_only": True,
            "neighbor_grid_is_not_truth": True,
        },
        "inputs": {
            "baseline_request": {"path": str(baseline_request_path), "sha256": sha256(baseline_request_path)},
            "baseline_report": {"path": str(baseline_report_path), "sha256": sha256(baseline_report_path)},
            "candidate_request": {"path": str(candidate_request_path), "sha256": sha256(candidate_request_path)},
            "candidate_report": {"path": str(candidate_report_path), "sha256": sha256(candidate_report_path)},
        },
        "baseline": base,
        "candidate": candidate,
        "pair_diagnostics": {
            "fluid_count_delta": cand_count - base_count if isinstance(base_count, (int, float)) and isinstance(cand_count, (int, float)) else None,
            "massfluid_kg_delta": cand_mass - base_mass if isinstance(base_mass, (int, float)) and isinstance(cand_mass, (int, float)) else None,
            "axis_and_per_mk_fields_are_diagnostic": True,
            "time_or_output_error_measured": False,
            "particle_position_or_velocity_error_measured": False,
        },
        "all_shapes_comparison": {
            "status": "PARTIAL_REPORT_FIELDS_ONLY",
            "required_scopes": REQUIRED_SCOPES,
            "bound_per_mk_assignment": "UNKNOWN_NO_BOUND_IDP",
            "fixed_boundary_shape_comparison": "UNKNOWN_NO_BOUND_IDP",
            "moving_boundary_shape_comparison": "UNKNOWN_NO_BOUND_IDP",
            "forcing_shape_comparison": "UNKNOWN_NOT_REPORTED_BY_THIS_WORKER",
            "shape_operation_comparison": "UNKNOWN_NOT_REPORTED_BY_THIS_WORKER",
            "control_motion_identity_is_not_shape_comparison": True,
            "qualification_granted": False,
        },
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "JSON-only field diagnostic; no all-shape, integration, output, or neighbor-truth qualification",
        },
    }


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable comparison report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
            handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    def report(bound_idp: str = "UNKNOWN_NOT_PRESENT_IN_BOUND_READER", mass: float = 2.0) -> dict[str, Any]:
        return {
            "schema": "ds02.stage2.f5-s1.clipplane-geometry-diagnostic.v8",
            "status": "COMPLETED_SYNTHETIC",
            "family_id": FAMILY_ID, "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID,
            "grid": "dp005", "generated": {"dp_m": 0.005, "fluid_count": 4, "massfluid_kg": 0.125, "fluid_blocks": [{"mkfluid": 0, "mk": 1, "count": 4}]},
            "geometry_diagnostic": {"bound_vtk_idp": bound_idp, "fluid_vtk_idp_mapping": "GLOBAL_XML_PARTICLE_IDS", "per_mkfluid_blocks": [{"mkfluid": 0, "mk": 1, "count": 4, "axis_summary": {}}], "selector_and_operation_trace": {"generated": {"particles_summary": {"nbf": "3", "nb": "5", "np": "9"}}}},
            "control_audit": {"motion_byte_identical": True, "source_candidate_controls_equal": True, "source_candidate_boundary_equal": True, "normalized_source_candidate_representation_equal": True},
            "mass_audit": {"gate": "DIAGNOSTIC", "relative_error": 0.0}, "source_closure": {},
        }
    with tempfile.TemporaryDirectory(prefix="f5-yphase-compare-") as directory:
        root = Path(directory)
        base_q = {"schema": REQUEST_SCHEMA, "family_id": FAMILY_ID, "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID, "source_binding": {"grid": "dp005", "dp_m": 0.005, "pointref_m": [0.0125, 0.0025, 0.0125]}}
        cand_q = {**base_q, "source_binding": {"grid": "dp005", "dp_m": 0.005, "pointref_m": [0.0125, 0.0, 0.0125]}}
        bp, cp = root / "base-q.json", root / "candidate-q.json"
        brp, crp = root / "base-report.json", root / "candidate-report.json"
        bp.write_text(json.dumps(base_q) + "\n", encoding="utf-8"); cp.write_text(json.dumps(cand_q) + "\n", encoding="utf-8")
        brp.write_text(json.dumps(report()) + "\n", encoding="utf-8"); crp.write_text(json.dumps(report(mass=3.0)) + "\n", encoding="utf-8")
        args = argparse.Namespace(baseline_request=bp, baseline_report=brp, candidate_request=cp, candidate_report=crp)
        value = build_report(args)
        if value["status"] != "COMPLETED_JSON_ONLY_SHAPE_DIAGNOSTIC" or value["all_shapes_comparison"]["bound_per_mk_assignment"] != "UNKNOWN_NO_BOUND_IDP":
            raise AssertionError(value)
        if value["scientific_qualification"]["QN"] != "UNKNOWN":
            raise AssertionError("synthetic comparator granted qualification")
    return {"status": "PASS", "schema": SCHEMA, "payload_arrays_read": False, "all_shapes_qualification": "UNKNOWN"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--baseline-request", type=Path)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--candidate-request", type=Path)
    parser.add_argument("--candidate-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.baseline_request, args.baseline_report, args.candidate_request, args.candidate_report, args.output]
    if any(value is None for value in required):
        parser.error("--run requires four JSON inputs and --output")
    value = build_report(args); write_new(args.output, value)
    print(json.dumps({"status": value["status"], "schema": SCHEMA, "output": str(args.output.resolve()), "qualification": value["scientific_qualification"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
