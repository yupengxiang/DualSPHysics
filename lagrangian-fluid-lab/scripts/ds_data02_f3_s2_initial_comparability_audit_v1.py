#!/usr/bin/env python3
"""Audit one source-bound, resolution-comparable F3-S2 initial state.

The worker consumes already-produced GenCase/preparation reports, their
completed receipts, and the existing three-resolution native-initial QA JSON.
It checks the exact Def/control/generated-XML lineage and compares a generated
DP=0.005 state against the generated DP=0.006 reference.  It deliberately
keeps per-particle sample mass separate from the continuous-owner mass.  The
existing VTK envelope is inherited from the bound QA product; this worker does
not open VTK, BI4, PartOut, H5, or a solver.

This is an input/source audit.  It does not assess QI/QN/QE, convergence,
physical fate, transport, or dynamics.
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


BINDING_SCHEMA = "ds02.stage2.f3-s2.initial-comparability-binding.v1"
AUDIT_SCHEMA = "ds02.stage2.f3-s2.initial-comparability-audit.v1"
AUDIT_STATUS = "PASS_SOURCE_BOUND_INITIAL_COMPARABILITY_NO_SCIENTIFIC_QUALIFICATION"


class AuditError(ValueError):
    """Raised when an input is not source-bound for this finite audit."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _reject_trajectory(path: Path, label: str) -> None:
    lower = path.name.lower()
    if path.suffix.lower() in {".h5", ".bi4"} or lower.startswith("partout_") or lower.startswith("part_"):
        raise AuditError(f"{label} points at forbidden trajectory/native content: {path}")
    if path.suffix.lower() == ".vtk":
        raise AuditError(f"{label} would open VTK; this audit only inherits QA VTK evidence: {path}")


def bind_file(spec: dict[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
        raise AuditError(f"{label} must declare a path")
    path = _resolved(spec["path"])
    _reject_trajectory(path, label)
    if not path.is_file():
        raise AuditError(f"{label} is missing: {path}")
    actual = sha256(path)
    expected = spec.get("sha256")
    if not isinstance(expected, str) or actual != expected:
        raise AuditError(f"{label} SHA differs from its source binding: {path}")
    size = path.stat().st_size
    if spec.get("bytes") is not None and spec["bytes"] != size:
        raise AuditError(f"{label} byte count differs from its source binding: {path}")
    return {"path": str(path), "sha256": actual, "bytes": size}


def read_json(spec: dict[str, Any], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    bound = bind_file(spec, label)
    try:
        value = json.loads(Path(bound["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} must contain an object")
    return value, bound


def _lookup_digest(mapping: dict[str, Any], path: Path) -> str | None:
    resolved = str(path.resolve())
    for name, value in mapping.items():
        if str(Path(name).expanduser().resolve()) == resolved:
            return value
    return None


def _finite(value: Any, label: str) -> float:
    # Prepared XML reports preserve scalar constants as decimal strings.  Parse
    # those strings strictly while still rejecting booleans and non-numeric
    # values so a malformed report cannot silently enter the mass comparison.
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AuditError(f"{label} is not finite")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"{label} is not finite") from exc
    if not math.isfinite(parsed):
        raise AuditError(f"{label} is not finite")
    return parsed


def _equal(left: Any, right: Any) -> bool:
    return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(right, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _receipt_is_completed(receipt: dict[str, Any], label: str, report: dict[str, Any]) -> None:
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise AuditError(f"{label} has an unexpected receipt schema")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditError(f"{label} is not completed with return code 0")
    output_root = receipt.get("output_root")
    prefix = report.get("prefix")
    if not isinstance(output_root, str) or not isinstance(prefix, str):
        raise AuditError(f"{label} lacks output/prefix binding")
    # ``prefix`` names the generated XML/report stem inside ``<attempt>/prepared``;
    # the producer receipt owns the attempt directory one level above that.
    prefix_path = _resolved(prefix)
    if prefix_path.parent.name != "prepared" or _resolved(output_root) != prefix_path.parent.parent:
        raise AuditError(f"{label} output root does not own the prepared report")
    request = receipt.get("request")
    if not isinstance(request, dict) or request.get("case_id") != report.get("case_id"):
        raise AuditError(f"{label} request case does not match prepared report")


def _upstream_receipt_is_completed(receipt: dict[str, Any], label: str) -> None:
    """Check the upstream producer without confusing its own output root with a report prefix."""
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise AuditError(f"{label} has an unexpected receipt schema")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditError(f"{label} is not completed with return code 0")
    if not isinstance(receipt.get("output_root"), str) or not _resolved(receipt["output_root"]).is_dir():
        raise AuditError(f"{label} lacks a live output root")


def _source_report_projection(report: dict[str, Any]) -> dict[str, Any]:
    """Fields that must remain equal across the two resolution states."""
    physical = report["physical_binding"]
    initial = physical["initial_state"]
    return {
        "control_family_id": physical["control_family_id"],
        "controls": physical["controls"],
        "density_kg_m3": physical["density_kg_m3"],
        "geometry": physical["geometry"],
        "geometry_family_id": physical["geometry_family_id"],
        "gravity_m_s2": physical["gravity_m_s2"],
        "continuum_mass_by_source_kg": initial["continuum_mass_by_source_kg"],
        "initial_mass_by_source_kg": initial["initial_mass_by_source_kg"],
        "initial_mass_total_kg": initial["initial_mass_total_kg"],
        "mass_policy": initial["mass_policy"],
        "source_labels": initial["source_labels"],
        "source_regions": initial["source_regions"],
        "velocities_m_per_s": initial["velocities_m_per_s"],
        "mass_policy_top_level": physical["mass_policy"],
        "mechanism_id": physical["mechanism_id"],
        "open_inlet": physical["open_inlet"],
        "paired_background_id": physical["paired_background_id"],
        "periodic_boundary": physical["periodic_boundary"],
        "parameters": physical["parameters"],
        "physical_case_id": physical["physical_case_id"],
    }


def _validate_source_record(record: dict[str, Any], *, role: str, qa_cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    report_spec = record.get("prepared_report")
    receipt_spec = record.get("generation_receipt")
    upstream_spec = record.get("upstream_gencase_receipt")
    source_def_spec = record.get("source_def")
    generated_xml_spec = record.get("generated_xml")
    control_source_spec = record.get("control_source")
    control_output_spec = record.get("control_output")
    report, report_binding = read_json(report_spec, f"{role} prepared report")
    receipt, receipt_binding = read_json(receipt_spec, f"{role} generation receipt")
    upstream, upstream_binding = read_json(upstream_spec, f"{role} upstream GenCase receipt")
    _receipt_is_completed(receipt, f"{role} generation receipt", report)
    _upstream_receipt_is_completed(upstream, f"{role} upstream GenCase receipt")
    if report.get("schema") != "ds02.f3.root-exact-geometry-twoaxis-preparation.v1":
        raise AuditError(f"{role} prepared report schema differs")
    if report.get("case_id") != record.get("case_id"):
        raise AuditError(f"{role} case ID differs from the binding")
    physical = report.get("physical_binding")
    if not isinstance(physical, dict) or physical.get("family_id") != "F3":
        raise AuditError(f"{role} physical F3 binding is missing")
    source_def = bind_file(source_def_spec, f"{role} source Def")
    generated_xml = bind_file(generated_xml_spec, f"{role} generated XML")
    control_source = bind_file(control_source_spec, f"{role} source acceleration control")
    control_output = bind_file(control_output_spec, f"{role} generated acceleration control")
    if report.get("original_definition_sha256") != source_def["sha256"]:
        raise AuditError(f"{role} report does not bind the source Def digest")
    if report.get("xml_sha256") != generated_xml["sha256"]:
        raise AuditError(f"{role} report does not bind generated XML digest")
    forcing = report.get("forcing_transform")
    if not isinstance(forcing, dict) or forcing.get("status") != "success":
        raise AuditError(f"{role} acceleration transform is not successful")
    if forcing.get("input_file") != control_source["path"] or forcing.get("source_sha256_before") != control_source["sha256"] or forcing.get("source_sha256_after") != control_source["sha256"]:
        raise AuditError(f"{role} source acceleration control is not closed")
    if forcing.get("output_file") != control_output["path"] or forcing.get("output_sha256") != control_output["sha256"]:
        raise AuditError(f"{role} generated acceleration control is not closed")
    if report.get("forcing_sha256") != control_output["sha256"]:
        raise AuditError(f"{role} report forcing digest differs from generated control")
    request_hashes = receipt.get("request", {}).get("input_sha256", {})
    source_def_receipt_sha = _lookup_digest(request_hashes, _resolved(source_def["path"]))
    control_receipt_sha = _lookup_digest(request_hashes, _resolved(control_source["path"]))
    if source_def_receipt_sha != source_def["sha256"]:
        raise AuditError(f"{role} source Def is absent or mismatched in generation receipt")
    if control_receipt_sha != control_source["sha256"]:
        raise AuditError(f"{role} acceleration control is absent or mismatched in generation receipt")
    if report.get("source_gencase_receipt") != upstream_binding["path"]:
        raise AuditError(f"{role} upstream GenCase receipt path is not the exact report path")
    qa = qa_cases.get(record.get("case_id"))
    if qa is None or qa.get("passed") is not True:
        raise AuditError(f"{role} is absent or failed in the existing native initial QA")
    if qa.get("generated_xml_sha256") != generated_xml["sha256"]:
        raise AuditError(f"{role} QA XML digest differs from generated XML")
    if qa.get("native_initial_BI4_sha256") != report.get("bi4_sha256"):
        raise AuditError(f"{role} QA BI4 digest differs from the prepared report")
    constants = report.get("actual_generated_constants", {})
    counts = report.get("generated_xml_particle_counts", {})
    massfluid = _finite(constants.get("massfluid", {}).get("value"), f"{role} MassFluid")
    fluid_count = counts.get("fluid")
    if not isinstance(fluid_count, int) or fluid_count <= 0:
        raise AuditError(f"{role} generated fluid count is missing")
    sample_mass = massfluid * fluid_count
    qa_mass = _finite(qa.get("official_CSV_fluid_mass_sum_kg"), f"{role} official CSV mass")
    continuous_mass = _finite(qa.get("continuous_reference_mass_kg"), f"{role} continuous reference mass")
    report_continuous = _finite(physical["initial_state"]["continuum_mass_by_source_kg"]["fluid"], f"{role} report continuous mass")
    if abs(qa_mass - sample_mass) > 2e-6:
        raise AuditError(f"{role} sample mass does not match native initial QA")
    if abs(continuous_mass - report_continuous) > 1e-9:
        raise AuditError(f"{role} continuous-owner mass does not match its report")
    return {
        "role": role,
        "case_id": report["case_id"],
        "prepared_report": report_binding,
        "generation_receipt": receipt_binding,
        "upstream_gencase_receipt": upstream_binding,
        "source_def": source_def,
        "generated_xml": generated_xml,
        "control_source": control_source,
        "control_output": control_output,
        "physical_condition_sha256": report.get("physical_condition_sha256"),
        "forcing_sha256": report.get("forcing_sha256"),
        "geometry_family_id": physical.get("geometry_family_id"),
        "support_control_projection": _source_report_projection(report),
        "resolution": {
            "dp_m": _finite(constants.get("dp", {}).get("value"), f"{role} Dp"),
            "h_m": _finite(constants.get("h", {}).get("value"), f"{role} h"),
            "massfluid_kg_per_particle": massfluid,
            "fluid_particle_count": fluid_count,
            "native_particle_count": qa.get("native_particles"),
            "native_fluid_count": qa.get("native_fluid"),
        },
        "sample_mass": {
            "mass_kg": sample_mass,
            "qa_mass_kg": qa_mass,
            "difference_from_continuous_kg": sample_mass - continuous_mass,
            "continuous_owner_mass_kg": continuous_mass,
            "meaning": "per-particle native sample weights summed for this generated lattice; not a replacement for continuous-owner mass",
        },
        "continuous_owner": {
            "mass_kg": continuous_mass,
            "geometry": physical["geometry"],
            "source_regions": physical["initial_state"]["source_regions"],
            "mass_policy": physical["mass_policy"],
        },
        "qa_envelope_m": qa.get("actual_fluid_envelope_m"),
    }, report


def _validate_vtk_stat_only(vtk_spec: Any, role: str) -> list[dict[str, Any]]:
    if not isinstance(vtk_spec, list) or not vtk_spec:
        raise AuditError(f"{role} must declare existing VTK stat-only evidence")
    result: list[dict[str, Any]] = []
    for item in vtk_spec:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise AuditError(f"{role} VTK stat-only entry is malformed")
        path = _resolved(item["path"])
        if path.suffix.lower() != ".vtk" or not path.is_file():
            raise AuditError(f"{role} VTK stat-only path is missing or not VTK: {path}")
        stat = path.stat()
        if item.get("bytes") != stat.st_size or item.get("mtime_ns") != stat.st_mtime_ns:
            raise AuditError(f"{role} VTK stat-only evidence changed: {path}")
        if item.get("sha256") is not None:
            raise AuditError(f"{role} VTK must remain un-hashed in this preparation audit")
        result.append({"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": None, "content_opened": False})
    return result


def audit(binding_path: Path, output_path: Path) -> dict[str, Any]:
    binding, binding_bound = read_json({"path": str(binding_path), "sha256": sha256(binding_path), "bytes": binding_path.stat().st_size}, "F3-S2 binding")
    if binding.get("schema") != BINDING_SCHEMA or binding.get("status") != "READY_SOURCE_BOUND_FINITE_INITIAL_AUDIT":
        raise AuditError("F3-S2 binding schema/status differs")
    qa_report_spec = binding.get("three_tier_native_initial_qa", {}).get("report")
    qa_receipt_spec = binding.get("three_tier_native_initial_qa", {}).get("receipt")
    qa_report, qa_report_bound = read_json(qa_report_spec, "three-tier native initial QA report")
    qa_receipt, qa_receipt_bound = read_json(qa_receipt_spec, "three-tier native initial QA receipt")
    if qa_report.get("schema") != "ds02.f3.adaptive-spatial-native-initial-qa.v1" or qa_report.get("q_n") != "not_granted" or qa_report.get("production_approval") != "none":
        raise AuditError("three-tier native initial QA is not the expected diagnostic-only product")
    if qa_receipt.get("status") != "completed" or qa_receipt.get("returncode") != 0:
        raise AuditError("three-tier native initial QA receipt is not completed")
    if _resolved(qa_receipt.get("output_root", "")) != _resolved(qa_report_bound["path"]).parent:
        raise AuditError("three-tier QA receipt does not own the QA report")
    qa_cases_list = qa_report.get("cases")
    if not isinstance(qa_cases_list, list) or len(qa_cases_list) != 3:
        raise AuditError("three-tier native initial QA must contain exactly three tiers")
    qa_cases = {row.get("case_id"): row for row in qa_cases_list if isinstance(row, dict)}
    if set(qa_cases) != {"F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005", "F3_CELL3_LONG_DP005_AY0P50_ADAPTIVE_CFL05_COEF005", "F3_CELL3_LONG_DP0045_AY0P50_ADAPTIVE_CFL05_COEF005"}:
        raise AuditError("three-tier native initial QA case set differs")
    target, target_report = _validate_source_record(binding.get("target"), role="target", qa_cases=qa_cases)
    reference, reference_report = _validate_source_record(binding.get("reference"), role="reference", qa_cases=qa_cases)
    if target["case_id"] == reference["case_id"]:
        raise AuditError("target and reference must be distinct generated initial states")
    if target["physical_condition_sha256"] != reference["physical_condition_sha256"]:
        raise AuditError("target/reference physical condition differs")
    if target["forcing_sha256"] != reference["forcing_sha256"]:
        raise AuditError("target/reference acceleration control differs")
    if not _equal(target["support_control_projection"], reference["support_control_projection"]):
        raise AuditError("target/reference support/control/continuous geometry projection differs")
    if target["geometry_family_id"] != reference["geometry_family_id"]:
        raise AuditError("target/reference geometry family differs")
    if target["resolution"]["dp_m"] == reference["resolution"]["dp_m"]:
        raise AuditError("target/reference did not provide a finite resolution comparison")
    target_vtk = _validate_vtk_stat_only(binding.get("vtk_stat_only", {}).get("target"), "target")
    reference_vtk = _validate_vtk_stat_only(binding.get("vtk_stat_only", {}).get("reference"), "reference")
    return {
        "schema": AUDIT_SCHEMA,
        "status": AUDIT_STATUS,
        "binding": binding_bound,
        "three_tier_native_initial_qa": {"report": qa_report_bound, "receipt": qa_receipt_bound, "case_count": len(qa_cases_list), "q_n": "not_granted"},
        "target": target,
        "reference": reference,
        "comparison": {
            "target_is_generated_non_original_comparable_state": True,
            "target_case_id": target["case_id"],
            "reference_case_id": reference["case_id"],
            "physical_condition_exactly_shared": True,
            "acceleration_control_exactly_shared": True,
            "support_control_continuous_geometry_exactly_shared": True,
            "continuous_owner_mass_equal": abs(target["continuous_owner"]["mass_kg"] - reference["continuous_owner"]["mass_kg"]) <= 1e-9,
            "sample_particle_mass_is_separate": True,
            "sample_mass_total_difference_kg": target["sample_mass"]["mass_kg"] - reference["sample_mass"]["mass_kg"],
            "resolution_only_change_observed": {"dp_m": [reference["resolution"]["dp_m"], target["resolution"]["dp_m"]], "h_m": [reference["resolution"]["h_m"], target["resolution"]["h_m"]]},
            "vtk_evidence": "existing native-initial QA envelope plus stat-only files; raw VTK was not opened by this worker",
        },
        "vtk_stat_only": {"target": target_vtk, "reference": reference_vtk},
        "qualification": {
            "source_def_and_control": "SOURCE_CLOSED",
            "continuous_owner_mass": "SOURCE_CLOSED_DIAGNOSTIC",
            "sample_particle_mass": "SOURCE_CLOSED_DIAGNOSTIC_SEPARATE_FROM_CONTINUUM",
            "initial_geometry": "EXISTING_QA_ENVELOPE_SOURCE_BOUND",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN",
            "dynamical_impact": "UNKNOWN", "scientific_split_safe": "UNKNOWN",
            "research_score": "NOT_COMPUTED", "ranking": "NOT_COMPUTED",
        },
        "read_policy": {
            "content_reads_begin_after_reservation": True,
            "json_reports_and_receipts_opened": True,
            "xml_and_acceleration_csv_hashed_for_source_closure": True,
            "vtk_opened": False, "bi4_opened": False, "h5_opened": False,
            "raw_partout_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False,
        },
        "unknowns": [
            "The QA report's VTK-derived envelope is inherited; raw VTK content was not reopened and no new VTK SHA is claimed.",
            "This finite initial-state audit says nothing about later frames, convergence, physical transport/fate, or dynamics.",
            "Continuous-owner mass is not inferred from the summed sample weights; the two quantities are reported separately.",
        ],
    }


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path = _resolved(path)
    if path.exists():
        raise AuditError(f"preserve existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", choices=["audit"])
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.binding, args.output)
    write_atomic(args.output, result)
    print(json.dumps({"status": result["status"], "target": result["target"]["case_id"], "reference": result["reference"]["case_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
