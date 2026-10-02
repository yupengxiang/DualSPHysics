#!/usr/bin/env python3
"""Audit an F1 DBC fallback input against the immutable mDBC mother.

The fallback changes the official ``Boundary`` parameter from 2 (mDBC) to 1
(DBC) while reusing the exact initial BI4/main particle cloud.  This audit is
deliberately input-only: it checks the XML delta, typed particle metadata,
physical/numerical fields, source hashes, and an independently produced finite
face coverage report.  It never launches GenCase, a solver, or a GPU and does
not make a Q-N decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.f1.finite-center.dbc-fallback-input-audit.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parameter_map(root: ET.Element) -> dict[str, str]:
    rows = root.findall(".//execution/parameters/parameter")
    return {str(row.get("key")): str(row.get("value")) for row in rows}


def _particle_summary(root: ET.Element) -> dict[str, Any]:
    particles = root.find(".//execution/particles")
    if particles is None:
        raise ValueError("generated XML has no execution/particles block")
    fixed = [node for node in particles.findall("fixed")]
    fluid = [node for node in particles.findall("fluid")]
    return {
        "np": int(particles.get("np", "-1")),
        "nb": int(particles.get("nb", "-1")),
        "nbf": int(particles.get("nbf", "-1")),
        "mkboundfirst": particles.get("mkboundfirst"),
        "mkfluidfirst": particles.get("mkfluidfirst"),
        "fixed": [
            {
                "mkbound": node.get("mkbound"),
                "mk": node.get("mk"),
                "begin": node.get("begin"),
                "count": int(node.get("count", "-1")),
            }
            for node in fixed
        ],
        "fluid": [
            {
                "mkfluid": node.get("mkfluid"),
                "mk": node.get("mk"),
                "begin": node.get("begin"),
                "count": int(node.get("count", "-1")),
            }
            for node in fluid
        ],
    }


def _constants_summary(root: ET.Element) -> dict[str, Any]:
    constants = root.find(".//execution/constants")
    if constants is None:
        raise ValueError("generated XML has no execution/constants block")
    values: dict[str, Any] = {}
    for node in constants:
        key = str(node.tag)
        if node.get("value") is not None:
            raw = str(node.get("value"))
            try:
                values[key] = float(raw)
            except ValueError:
                values[key] = raw
        else:
            values[key] = {str(k): str(v) for k, v in sorted(node.attrib.items())}
    motion = root.find(".//execution/motion")
    return {"values": values, "motion": ET.tostring(motion, encoding="unicode") if motion is not None else None}


def _canonical_without_boundary(root: ET.Element) -> bytes:
    clone = ET.fromstring(ET.tostring(root, encoding="utf-8"))
    for node in clone.findall(".//execution/parameters/parameter"):
        if node.get("key") == "Boundary":
            node.set("value", "<boundary-ignored>")
    return ET.tostring(clone, encoding="utf-8")


def _same_except_boundary(baseline_xml: Path, dbc_xml: Path) -> bool:
    baseline_bytes = baseline_xml.read_bytes()
    dbc_bytes = dbc_xml.read_bytes()
    expected = baseline_bytes.replace(
        b'<parameter key="Boundary" value="2" />',
        b'<parameter key="Boundary" value="1" />',
    )
    return expected == dbc_bytes


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def audit(
    *,
    baseline_xml: Path,
    dbc_xml: Path,
    baseline_bi4: Path,
    dbc_bi4: Path,
    baseline_all_vtk: Path,
    dbc_all_vtk: Path,
    baseline_bound_vtk: Path,
    dbc_bound_vtk: Path,
    baseline_fluid_vtk: Path,
    dbc_fluid_vtk: Path,
    baseline_hdp_vtk: Path,
    dbc_hdp_vtk: Path,
    binding: Path,
    coverage_report: Path,
    output: Path,
) -> dict[str, Any]:
    baseline_root = ET.parse(baseline_xml).getroot()
    dbc_root = ET.parse(dbc_xml).getroot()
    baseline_params = _parameter_map(baseline_root)
    dbc_params = _parameter_map(dbc_root)
    baseline_particles = _particle_summary(baseline_root)
    dbc_particles = _particle_summary(dbc_root)
    baseline_constants = _constants_summary(baseline_root)
    dbc_constants = _constants_summary(dbc_root)
    binding_data = _load_json(binding)
    coverage = _load_json(coverage_report)

    parameter_keys = sorted(set(baseline_params) | set(dbc_params))
    other_parameter_diffs = {
        key: {"baseline": baseline_params.get(key), "dbc": dbc_params.get(key)}
        for key in parameter_keys
        if key != "Boundary" and baseline_params.get(key) != dbc_params.get(key)
    }
    binary_names = {
        "bi4": (baseline_bi4, dbc_bi4),
        "all_vtk": (baseline_all_vtk, dbc_all_vtk),
        "bound_vtk": (baseline_bound_vtk, dbc_bound_vtk),
        "fluid_vtk": (baseline_fluid_vtk, dbc_fluid_vtk),
        "hdp_vtk": (baseline_hdp_vtk, dbc_hdp_vtk),
    }
    binary_hashes = {
        name: {
            "baseline": sha256(left),
            "dbc": sha256(right),
            "equal": sha256(left) == sha256(right),
        }
        for name, (left, right) in binary_names.items()
    }
    expected_physical_hash = binding_data.get("canonical_physical_payload_sha256")
    coverage_checks = coverage.get("checks", {})
    sampled_outer_pass = bool(coverage.get("all_five_finite_faces_covered"))
    sampled_separator_pass = bool(coverage.get("separator_face_coverage_pass"))
    exact_outer_pass = bool(coverage_checks.get("exact_outer_five_generated_nonempty")) and bool(
        coverage_checks.get("exact_outer_five_native_nonempty")
    )
    exact_separator_pass = bool(coverage_checks.get("layer_band_outer_five_rectangle_coverage"))
    sampled_source_hash = coverage.get("native_source_sha256")
    candidate_bound_hash = sha256(dbc_bound_vtk)
    checks = {
        "xml_boundary_baseline_is_mdbc": baseline_params.get("Boundary") == "2",
        "xml_boundary_candidate_is_dbc": dbc_params.get("Boundary") == "1",
        "xml_only_boundary_byte_delta": _same_except_boundary(baseline_xml, dbc_xml),
        "other_execution_parameters_equal": not other_parameter_diffs,
        "particle_cloud_metadata_equal": baseline_particles == dbc_particles,
        "physical_constants_and_motion_equal": baseline_constants == dbc_constants,
        "initial_bi4_equal": binary_hashes["bi4"]["equal"],
        "all_vtk_equal": binary_hashes["all_vtk"]["equal"],
        "bound_vtk_equal": binary_hashes["bound_vtk"]["equal"],
        "fluid_vtk_equal": binary_hashes["fluid_vtk"]["equal"],
        "hdp_vtk_equal": binary_hashes["hdp_vtk"]["equal"],
        "coverage_outer_five_sampled": sampled_outer_pass or exact_outer_pass,
        "coverage_separator_five_sampled": sampled_separator_pass or exact_separator_pass,
        "coverage_report_source_matches_candidate_bound": sampled_source_hash == candidate_bound_hash,
        "coverage_typed_identity_unique": bool(
            coverage_checks.get("native_identity_axis_unique")
            or coverage.get("selected_native_boundary_points")
        ),
        "canonical_physical_binding_present": bool(expected_physical_hash),
    }
    report = {
        "schema": SCHEMA,
        "case_id": "F1_DUAL_FINITE_CENTER_DP001_003_DBC_V1",
        "physical_case_id": "F1_DUAL_FINITE_CENTER_QUADRATURE",
        "model_profile": "gpt-5.6-luna/max",
        "claim_boundary": "Input and initial particle-cloud equivalence only; no solver, Q-N, or production qualification.",
        "checks": checks,
        "status": "pass_dbc_input_gate" if all(checks.values()) else "failed_dbc_input_gate",
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
        "boundary_model_delta": {
            "baseline": "mDBC",
            "baseline_parameter": baseline_params.get("Boundary"),
            "candidate": "DBC",
            "candidate_parameter": dbc_params.get("Boundary"),
            "slip_mode_value_retained": dbc_params.get("SlipMode"),
            "slip_mode_semantics": "official source applies SlipMode only to mDBC; candidate retains XML value for byte-locality but it is non-operative under DBC",
        },
        "typed_particle_cloud": {
            "baseline": baseline_particles,
            "dbc": dbc_particles,
            "initial_fluid_mass_kg": float(dbc_particles["fluid"][0]["count"])
            * float(dbc_constants["values"].get("massfluid", 0.0)),
            "expected_fluid_mass_kg": 616.0,
            "source": "exact BI4 byte equality plus generated XML typed particle metadata",
        },
        "physical_numeric_binding": {
            "canonical_physical_payload_sha256": expected_physical_hash,
            "binding_path": str(binding),
            "boundary_is_the_only_numerical_change": not other_parameter_diffs,
            "physical_constants_and_motion": dbc_constants,
            "other_parameter_diffs": other_parameter_diffs,
            "continuous_geometry_source": "same immutable BI4/main particle cloud and same generated geometry VTK/hdp files",
        },
        "finite_coverage": {
            "report_path": str(coverage_report),
            "report_sha256": sha256(coverage_report),
            "checks": coverage_checks,
            "mode": "sampled_finite_faces" if sampled_outer_pass or sampled_separator_pass else "exact_or_layer_audit",
            "native_source_sha256": sampled_source_hash,
            "candidate_bound_vtk_sha256": candidate_bound_hash,
            "outer_five_sampled_pass": sampled_outer_pass,
            "separator_five_sampled_pass": sampled_separator_pass,
            "source": "read-only native BI4 decode and finite-face audit",
        },
        "source_hashes": {
            "baseline_xml": sha256(baseline_xml),
            "dbc_xml": sha256(dbc_xml),
            "baseline_bi4": sha256(baseline_bi4),
            "dbc_bi4": sha256(dbc_bi4),
            "binding": sha256(binding),
            "binary_artifacts": binary_hashes,
        },
        "source_immutability": {
            "baseline_inputs_untouched": True,
            "candidate_is_new_prefix": True,
            "solver_started": False,
            "gpu_started": False,
        },
        "limitations": [
            "DBC is a numerical boundary-model change and requires independent solver behavior and scientific validation; input equivalence does not imply mDBC equivalence.",
            "The finite coverage report characterizes the reused initial cloud; it does not establish solver-time penetration or Q-N.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in (
        "baseline-xml", "dbc-xml", "baseline-bi4", "dbc-bi4", "baseline-all-vtk",
        "dbc-all-vtk", "baseline-bound-vtk", "dbc-bound-vtk", "baseline-fluid-vtk",
        "dbc-fluid-vtk", "baseline-hdp-vtk", "dbc-hdp-vtk", "binding", "coverage-report",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(
        baseline_xml=args.baseline_xml,
        dbc_xml=args.dbc_xml,
        baseline_bi4=args.baseline_bi4,
        dbc_bi4=args.dbc_bi4,
        baseline_all_vtk=args.baseline_all_vtk,
        dbc_all_vtk=args.dbc_all_vtk,
        baseline_bound_vtk=args.baseline_bound_vtk,
        dbc_bound_vtk=args.dbc_bound_vtk,
        baseline_fluid_vtk=args.baseline_fluid_vtk,
        dbc_fluid_vtk=args.dbc_fluid_vtk,
        baseline_hdp_vtk=args.baseline_hdp_vtk,
        dbc_hdp_vtk=args.dbc_hdp_vtk,
        binding=args.binding,
        coverage_report=args.coverage_report,
        output=args.output,
    )
    print(json.dumps({"status": report["status"], "checks": report["checks"]}, sort_keys=True))
    return 0 if report["status"] == "pass_dbc_input_gate" else 2


if __name__ == "__main__":
    raise SystemExit(main())
