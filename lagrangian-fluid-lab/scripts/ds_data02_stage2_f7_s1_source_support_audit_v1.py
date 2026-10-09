#!/usr/bin/env python3
"""Audit the exact F7-S1 source recipe and initial-support evidence.

This is a bounded source/JSON audit.  It joins the fourteen-sentinel source
status, the F7-S1 next request, CURRENT336, the actual F7 label proof, the
initial-MK/control audit, the source-control audit, and the existing F7 mass
probes.  It reads one small source XML and its referenced motion asset so the
control values are checked against the declared source, but it never opens
H5, BI4, PartOut, VTK, raw solver output, or a solver.

The source XML's particle sample mass and the owner metadata's continuum mass
are intentionally reported as separate quantities.  A matching discrete
sample, or a passing GenCase mass screen, does not establish continuous-owner
equivalence, boundary support, QI/QN/QE, physical fate, or dynamics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f7.s1.source-support-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.source-support-audit.manifest.v1"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".bi2", ".bi1", ".vtk"}


class AuditError(ValueError):
    """Raised when the exact F7-S1 source closure is not reproducible."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_ref(path: Path, role: str) -> dict[str, Any]:
    st = path.stat()
    return {
        "role": role,
        "path": str(path),
        "bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "ctime_ns": st.st_ctime_ns,
        "st_dev": st.st_dev,
        "st_ino": st.st_ino,
        "sha256": sha256_file(path),
    }


def require_file(path_value: Any, label: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise AuditError(f"{label} path is missing")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise AuditError(f"{label} is not an existing file: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise AuditError(f"{label} points to forbidden scientific payload: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} is not a JSON object")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise AuditError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def expect(value: Any, wanted: Any, label: str) -> None:
    if value != wanted:
        raise AuditError(f"{label}: expected {wanted!r}, got {value!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise AuditError(f"{label} is not finite")
    return result


def q_unknown(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise AuditError(f"{label} is not a qualification object")
    for key in ("QI", "QN", "QE"):
        if value.get(key) not in ("UNKNOWN", "NOT_ASSESSED"):
            raise AuditError(f"{label}.{key} grants unsupported qualification: {value.get(key)!r}")


def find_sentinel(value: Any, sentinel_id: str) -> dict[str, Any]:
    if isinstance(value, dict):
        if value.get("sentinel_id") == sentinel_id:
            return value
        for child in value.values():
            try:
                return find_sentinel(child, sentinel_id)
            except AuditError:
                pass
    elif isinstance(value, list):
        for child in value:
            try:
                return find_sentinel(child, sentinel_id)
            except AuditError:
                pass
    raise AuditError(f"sentinel {sentinel_id} is missing")


def load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    manifest = read_json(path, "F7-S1 source audit manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    entries = manifest.get("source_refs")
    if not isinstance(entries, list) or not entries:
        raise AuditError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    docs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise AuditError("malformed source reference")
        key = entry["key"]
        if key in paths:
            raise AuditError(f"duplicate source key: {key}")
        path_value = require_file(entry.get("path"), key)
        expect(entry.get("sha256"), sha256_file(path_value), f"{key} SHA")
        paths[key] = path_value
        if entry.get("kind", "json") == "json":
            if path_value.suffix.lower() != ".json":
                raise AuditError(f"{key} declared JSON but is not JSON")
            docs[key] = read_json(path_value, key)
    required = {
        "source_status",
        "next_requests",
        "initial_mk_audit",
        "source_control_audit",
        "current336",
        "f7_label_proof",
        "f7_label_report",
        "f7_label_receipt",
        "mass_fit_proof",
        "owner_metadata",
        "source_xml",
        "motion_asset",
    }
    missing = required - set(paths)
    if missing:
        raise AuditError(f"manifest source closure missing {sorted(missing)}")
    return manifest, paths, docs


def parse_source_xml(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise AuditError(f"F7-S1 source XML cannot be parsed: {path}") from exc
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise AuditError("F7-S1 source XML lacks geometry definition")
    expect(definition.get("dp"), "0.02", "F7-S1 source dp")
    params: dict[str, str] = {}
    for parameter in root.findall(".//execution/parameters/parameter"):
        key = parameter.get("key")
        if key:
            params[key] = parameter.get("value", "")
    expected_parameters = {
        "SavePosDouble": "2",
        "Boundary": "1",
        "StepAlgorithm": "2",
        "Kernel": "2",
        "Visco": "0.05",
        "DensityDT": "3",
        "DensityDTvalue": "0.1",
        "TimeMax": "12",
        "TimeOut": "0.02",
        "MinFluidStop": "0",
    }
    for key, wanted in expected_parameters.items():
        expect(params.get(key), wanted, f"F7-S1 XML parameter {key}")
    motion_file = root.find(".//motion//mvrotfile/file")
    if motion_file is None:
        raise AuditError("F7-S1 source XML lacks motion file reference")
    expect(motion_file.get("name"), "motion_obstacle_quintic.dat", "F7-S1 motion asset reference")
    axis1 = root.find(".//motion//mvrotfile/axisp1")
    axis2 = root.find(".//motion//mvrotfile/axisp2")
    if axis1 is None or axis2 is None:
        raise AuditError("F7-S1 source XML lacks motion axis")
    return {
        "definition_dp_m": finite(definition.get("dp"), "F7-S1 source dp"),
        "parameters": {key: params[key] for key in expected_parameters},
        "motion_file": motion_file.get("name"),
        "motion_axis": {
            "p1_m": [finite(axis1.get(axis), f"axis p1 {axis}") for axis in ("x", "y", "z")],
            "p2_m": [finite(axis2.get(axis), f"axis p2 {axis}") for axis in ("x", "y", "z")],
        },
    }


def validate_source_status(docs: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    status = docs["source_status"]
    expect(status.get("schema"), "ds02.stage2.fourteen-source-status.v3", "source status schema")
    expect(status.get("scope", {}).get("sentinel_count"), 14, "source status sentinel count")
    scope = status.get("scope", {})
    for key in ("reads_bi4", "reads_hdf5", "reads_native_payloads", "reads_vtk", "starts_gpu", "starts_solver"):
        expect(scope.get(key), False, f"source status scope.{key}")
    f7 = find_sentinel(status, "F7-S1")
    expect(f7.get("family_id"), "F7", "F7-S1 family")
    expect(f7.get("physical_case_id"), "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1", "F7-S1 physical case")
    q_unknown(f7.get("terminal_state", {}).get("scientific_qualification"), "F7-S1 status qualification")
    expect(f7.get("terminal_state", {}).get("status"), "ACTUAL LABEL/MASS PROBES; FULL SOURCE-MATCHED RUN UNKNOWN", "F7-S1 terminal status")
    next_requests = docs["next_requests"]
    f7_next = find_sentinel(next_requests, "F7-S1")
    expect(f7_next.get("request_id"), "stage2-f7-s1-next-13", "F7-S1 next request id")
    expect(f7_next.get("launch_disabled"), True, "F7-S1 prepared request launch state")
    expect(f7_next.get("solver_launch"), False, "F7-S1 prepared request solver state")
    q_unknown(f7_next.get("qualification_after_task"), "F7-S1 next qualification")
    return f7, f7_next


def validate_current(docs: dict[str, dict[str, Any]], proof: dict[str, Any], source_xml_path: Path) -> dict[str, Any]:
    current = docs["current336"]
    expect(current.get("schema"), "ds02.stage2.current336.v1", "CURRENT336 schema")
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise AuditError("CURRENT336 is not exactly 336 cases")
    matches = [(index, row) for index, row in enumerate(rows) if isinstance(row, dict) and row.get("physical_case_id") == "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"]
    if len(matches) != 1:
        raise AuditError(f"F7-S1 CURRENT mapping is not unique: {len(matches)}")
    index, row = matches[0]
    expect(row.get("family_id"), "F7", "F7 CURRENT family")
    expect(row.get("runtime_case_alias"), "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE", "F7 CURRENT alias")
    expect(row.get("frames"), 601, "F7 CURRENT frames")
    expect(row.get("particles"), 70179, "F7 CURRENT particles")
    expect(row.get("actual_time_window_s"), [0.0, 12.00001411017073], "F7 CURRENT time window")
    bindings = row.get("source_bindings", {})
    generated_xml = bindings.get("generated_xml", {})
    expect(generated_xml.get("sha256"), sha256_file(source_xml_path), "F7 CURRENT XML binding")
    trajectory = row.get("trajectory", {})
    expect(trajectory.get("producer_declared_sha256"), proof.get("source_current_H5", {}).get("sha256"), "F7 current H5 declared SHA")
    return {
        "current_index": index,
        "family_id": row["family_id"],
        "physical_case_id": row["physical_case_id"],
        "runtime_case_alias": row["runtime_case_alias"],
        "frames": row["frames"],
        "particles": row["particles"],
        "actual_time_window_s": row["actual_time_window_s"],
        "amplitude_deg": row.get("known_numeric_physical_parameters", {}).get("amplitude_deg"),
        "trajectory_declared_sha256": trajectory.get("producer_declared_sha256"),
        "trajectory_opened_by_this_worker": False,
        "scientific_scan_status": row.get("scientific_scan_status"),
    }


def validate_initial_audit(docs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    audit = docs["initial_mk_audit"]
    expect(audit.get("schema"), "ds02.stage2.fourteen-initial-mk-control-audit.v3", "initial audit schema")
    f7 = audit.get("families", {}).get("F7-S1")
    if not isinstance(f7, dict):
        raise AuditError("initial audit lacks F7-S1")
    expect(f7.get("physical_case_id"), "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1", "initial audit case")
    source = f7.get("source_initial_state", {})
    xml = source.get("xml", {})
    expect(xml.get("definition_dp_m"), 0.02, "F7 source audit dp")
    expect(xml.get("fluid_particle_count"), 40700, "F7 source fluid count")
    expect(xml.get("sample_mass_kg"), 325.6, "F7 source sample mass")
    blocks = xml.get("fluid_blocks")
    if not isinstance(blocks, list) or len(blocks) != 1:
        raise AuditError("F7 source fluid block scope is not one block")
    expect(blocks[0].get("mkfluid"), "1", "F7 source mkfluid")
    expect(blocks[0].get("mk"), "2", "F7 source MK")
    control = f7.get("source_terminal_control_and_window", {})
    expect(control.get("status"), "completed", "F7 source control status")
    expect(control.get("returncode"), 0, "F7 source control returncode")
    expect(control.get("actual_cli_tmax_s"), 12.0, "F7 source tmax")
    expect(control.get("actual_cli_tout_s"), 0.02, "F7 source tout")
    candidates = {}
    for candidate in f7.get("candidate_initial_and_mk_audits", []):
        candidates[candidate.get("label")] = candidate
    if set(candidates) != {"coarse", "original", "fine"}:
        raise AuditError("F7 initial audit does not expose coarse/original/fine candidates")
    candidate_summary = {}
    for label, candidate in candidates.items():
        mass = candidate.get("whole_initial_mass", {})
        candidate_summary[label] = {
            "requested_dp_m": candidate.get("requested_dp_m"),
            "candidate_mass_kg": mass.get("candidate_kg"),
            "error_pct": mass.get("error_pct"),
            "gate": mass.get("gate"),
            "control_match": candidate.get("control_match", {}).get("continuous_geometry", {}).get("strict_continuous_equivalence"),
            "candidate_solver_status": candidate.get("control_match", {}).get("candidate_solver_status"),
        }
    expect(candidate_summary["original"]["gate"], "PASS_TARGET_1PCT_DIAGNOSTIC", "F7 original mass gate")
    expect(candidate_summary["coarse"]["gate"], "HARD_FAIL_GT2PCT", "F7 coarse mass gate")
    expect(candidate_summary["fine"]["gate"], "HARD_FAIL_GT2PCT", "F7 fine mass gate")
    return {
        "source_xml": stat_ref(Path(xml["file"]["path"]), "F7 source XML from initial audit"),
        "source_initial": {
            "dp_m": xml["definition_dp_m"],
            "fluid_particle_count": xml["fluid_particle_count"],
            "sample_mass_kg": xml["sample_mass_kg"],
            "massfluid_kg": xml.get("massfluid_kg"),
            "fluid_block": blocks[0],
        },
        "source_terminal_window": {
            "tmax_s": control["actual_cli_tmax_s"],
            "tout_s": control["actual_cli_tout_s"],
            "saved_window_s": control.get("actual_saved_window_s"),
            "frames": control.get("output_frame_count"),
        },
        "candidate_mass_diagnostics": candidate_summary,
        "continuous_equivalence": "UNKNOWN_PRECHECKED_INPUT_COPY_ONLY",
    }


def validate_source_control(docs: dict[str, dict[str, Any]], source_xml_path: Path, motion_path: Path) -> dict[str, Any]:
    audit = docs["source_control_audit"]
    expect(audit.get("schema"), "ds02.stage2.fourteen-source-control-audit.v5", "source-control audit schema")
    expect(audit.get("scope", {}).get("source_xml_count"), 14, "source-control XML count")
    expect(audit.get("scope", {}).get("native_or_h5_read_by_this_worker"), False, "source-control payload read")
    row = next((entry for entry in audit.get("sources", []) if entry.get("sentinel_id") == "F7-S1"), None)
    if not isinstance(row, dict):
        raise AuditError("source-control audit lacks F7-S1")
    expect(row.get("physical_case_id"), "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1", "source-control case")
    expect(row.get("source_xml", {}).get("path"), str(source_xml_path), "source-control XML path")
    expect(row.get("source_xml", {}).get("sha256"), sha256_file(source_xml_path), "source-control XML SHA")
    motion = row.get("motion_file_resolution", {}).get("references", [])
    if len(motion) != 1 or motion[0].get("status") != "AVAILABLE":
        raise AuditError("F7-S1 motion reference is not exactly available")
    expect(motion[0].get("unique_declared_or_actual_sha256"), [sha256_file(motion_path)], "F7-S1 motion SHA")
    expect(row.get("control_equivalence"), "UNKNOWN; extracted source dependencies do not prove cross-grid equivalence", "F7 source control equivalence")
    return {
        "source_xml": stat_ref(source_xml_path, "F7 source-control XML"),
        "motion_asset": stat_ref(motion_path, "F7 source-control motion asset"),
        "control_node_count": row.get("control_node_count"),
        "motion_file_refs": row.get("motion_file_refs"),
        "motion_metadata_status": row.get("motion_metadata_status"),
        "control_equivalence": "UNKNOWN",
        "auxiliary_file_resolution": row.get("auxiliary_file_resolution"),
    }


def validate_owner(docs: dict[str, dict[str, Any]], owner_path: Path) -> dict[str, Any]:
    owner = docs["owner_metadata"]
    binding = owner.get("physical_binding", owner)
    # The actual owner artifact is a wrapper whose physical_binding carries
    # the binding schema and identity.  Do not accept a wrapper-only schema or
    # infer identity from the filename.
    expect(binding.get("schema"), "ds-data-02.physical-binding.v1", "F7 owner schema")
    expect(binding.get("family_id"), "F7", "F7 owner family")
    expect(binding.get("physical_case_id"), "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1", "F7 owner case")
    initial = binding.get("initial_state", {})
    owner_mass = finite(initial.get("initial_mass_total_kg"), "F7 continuum owner mass")
    sample_mass = finite(owner.get("actual_initial_qa", {}).get("official_CSV_fluid_mass_sum_kg"), "F7 official sample mass")
    return {
        "source": stat_ref(owner_path, "F7 physical owner metadata"),
        "mechanism_id": owner.get("mechanism_id"),
        "geometry_family_id": owner.get("geometry_family_id"),
        "geometry": binding.get("geometry"),
        "continuous_owner_mass_kg": owner_mass,
        "discrete_source_sample_mass_kg": sample_mass,
        "owner_vs_sample_difference_pct_of_owner": (sample_mass - owner_mass) / owner_mass * 100.0,
        "owner_equivalence": "UNKNOWN_SOURCE_METADATA_DOES_NOT_PROVE_CONTINUOUS_NUMERICAL_SUPPORT",
        "native_type_counts": owner.get("actual_initial_qa", {}).get("native_type_counts"),
        "native_initial_fluid_count": owner.get("actual_initial_qa", {}).get("native_fluid"),
        "source_regions": binding.get("initial_state", {}).get("source_labels"),
        "motion_control": binding.get("parameters"),
    }


def validate_label_anchor(docs: dict[str, dict[str, Any]], paths: dict[str, Path]) -> dict[str, Any]:
    proof = docs["f7_label_proof"]
    report = docs["f7_label_report"]
    receipt = docs["f7_label_receipt"]
    expect(proof.get("schema"), "ds02.stage2.f7-family-labels-root-verification.v1", "F7 label proof schema")
    expect(proof.get("status"), "PASS_ACTUAL_SAVED_FRAME_SPATIAL_COHORT_REGION_EVENT_LABEL_ACCOUNTING", "F7 label proof status")
    expect(proof.get("report"), str(paths["f7_label_report"]), "F7 label report path")
    expect(proof.get("report_sha256"), sha256_file(paths["f7_label_report"]), "F7 label report SHA")
    expect(proof.get("receipt"), str(paths["f7_label_receipt"]), "F7 label receipt path")
    expect(proof.get("receipt_sha256"), sha256_file(paths["f7_label_receipt"]), "F7 label receipt SHA")
    expect(report.get("schema"), "ds02.stage2.family-label-report.v1", "F7 label report schema")
    expect(report.get("status"), "LABELS_MATERIALIZED_SOURCE_BOUND", "F7 label report status")
    expect(report.get("family_id"), "F7", "F7 label report family")
    expect(report.get("physical_case_id"), "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1", "F7 label report case")
    expect(receipt.get("schema"), "ds02.execution-receipt.v1", "F7 label receipt schema")
    expect(receipt.get("status"), "completed", "F7 label receipt status")
    expect(receipt.get("returncode"), 0, "F7 label receipt returncode")
    if receipt.get("model_invoked") is True or receipt.get("cfd_invoked") is True:
        raise AuditError("F7 label receipt reports model/CFD invocation")
    q_unknown(receipt.get("qualification"), "F7 label receipt qualification")
    quality = proof.get("independent_new_label_quality", {})
    expect(quality.get("frames"), 601, "F7 label frame count")
    expect(quality.get("identities"), 70179, "F7 label identity count")
    expect(quality.get("fluid_count"), 40700, "F7 label fluid count")
    return {
        "source": {
            "proof": stat_ref(paths["f7_label_proof"], "F7 label proof"),
            "report": stat_ref(paths["f7_label_report"], "F7 label report"),
            "receipt": stat_ref(paths["f7_label_receipt"], "F7 label receipt"),
        },
        "frames": quality["frames"],
        "identities": quality["identities"],
        "fluid_count": quality["fluid_count"],
        "initial_mass_kg": quality.get("initial_mass_kg"),
        "source_cohort_semantics": quality.get("cohort_semantics"),
        "fixed_eulerian_saved_chord_scope": proof.get("scope"),
        "physical_fate": "UNKNOWN",
        "moving_obstacle_pose": "UNKNOWN_UNSUPPORTED_BY_FIXED_EULERIAN_LABELS",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }


def validate_mass_fit(docs: dict[str, dict[str, Any]], mass_fit_path: Path) -> dict[str, Any]:
    proof = docs["mass_fit_proof"]
    expect(proof.get("schema"), "ds02.stage2.mass-fit-independent-verification.v3", "F7 mass-fit proof schema")
    records = [row for row in proof.get("records", []) if isinstance(row, dict) and row.get("sentinel_id") == "F7-S1"]
    if len(records) < 2:
        raise AuditError("F7 mass-fit proof lacks F7-S1 candidate records")
    selected = []
    for row in records:
        expect(row.get("CURRENT_physical_case_id"), "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1", "F7 mass-fit CURRENT case")
        q_unknown(row, "F7 mass-fit row")
        selected.append({
            "case_id": row.get("case_id"),
            "requested_dp_m": row.get("case_id", "").split("DP")[-1],
            "candidate_mass_kg": row.get("candidate_initial_fluid_mass_kg"),
            "total_mass_deviation_pct": row.get("total_mass_deviation_pct"),
            "gate": row.get("initial_total_mass_gate"),
            "Def_only_dp_changed": row.get("Def_only_dp_changed"),
            "motion_dependency_bytes_unchanged": row.get("motion_dependency_bytes_unchanged"),
            "source_mapping": row.get("source_mapping"),
        })
    return {
        "source": stat_ref(mass_fit_path, "F7 mass-fit proof"),
        "records": selected,
        "interpretation": "initial mass/resolution diagnostics only; no adjacent-grid truth or solver qualification",
    }


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest, paths, docs = load_manifest(manifest_path)
    f7_status, f7_next = validate_source_status(docs)
    proof = docs["f7_label_proof"]
    current = validate_current(docs, proof, paths["source_xml"])
    initial = validate_initial_audit(docs)
    source_xml = parse_source_xml(paths["source_xml"])
    source_control = validate_source_control(docs, paths["source_xml"], paths["motion_asset"])
    owner = validate_owner(docs, paths["owner_metadata"])
    label = validate_label_anchor(docs, paths)
    mass_fit = validate_mass_fit(docs, paths["mass_fit_proof"])
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_F7_S1_SOURCE_SUPPORT_AUDIT_V1_JSON_AND_SMALL_SOURCE_ONLY",
        "sentinel_id": "F7-S1",
        "family_id": "F7",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1",
        "current_binding": current,
        "source_recipe": {
            "source_status": stat_ref(paths["source_status"], "fourteen-sentinel source status"),
            "next_request": stat_ref(paths["next_requests"], "F7-S1 next request matrix"),
            "status": f7_status.get("terminal_state", {}).get("status"),
            "next_request_id": f7_next.get("request_id"),
            "source_xml": source_xml,
            "source_xml_file": stat_ref(paths["source_xml"], "F7-S1 source XML"),
            "motion_asset": stat_ref(paths["motion_asset"], "F7-S1 motion asset"),
            "source_control": source_control,
            "owner_metadata": owner,
        },
        "initial_support_and_mass": initial,
        "existing_label_evidence": label,
        "mass_fit_diagnostics": mass_fit,
        "domain_and_boundary_scope": {
            "source_declared_domain": {
                "pointmin_m": [-0.68, -0.48, -0.08],
                "pointmax_m": [0.68, 0.48, 0.68],
            },
            "tank_boundary_box": {"point_m": [-0.6, -0.4, 0.0], "size_m": [1.2, 0.8, 0.6], "top_open": True},
            "moving_paddle_box": {"point_m": [-0.07, -0.24, 0.05], "size_m": [0.06, 0.48, 0.48]},
            "fluid_owner_envelope": owner["geometry"].get("fluid_envelope"),
            "source_fluid_mk": {"mkfluid": "1", "mk": "2", "sample_mass_kg": 325.6},
            "initial_type_counts": owner.get("native_type_counts"),
            "boundary_and_mk_semantics": "source/initial diagnostic only; no dynamic wall/contact or physical-spill claim",
        },
        "task_eligibility": {
            "exact_current_source_recipe": "ELIGIBLE_SOURCE_CLOSED_METADATA",
            "initial_mk_and_sample_mass": "ELIGIBLE_INITIAL_BOOKKEEPING_DIAGNOSTIC",
            "initial_support_envelope": "ELIGIBLE_SOURCE_DECLARATION_AND_PRIOR_INITIAL_QA_SCOPE",
            "continuous_owner_equivalence": "UNKNOWN",
            "cross_resolution_comparability": "UNKNOWN_INITIAL_MASS_ONLY",
            "boundary_contact_or_penetration": "UNKNOWN",
            "continuous_event_time": "UNKNOWN_SAVED_BRACKET_ONLY",
            "physical_fate_or_legal_flux": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "mass_semantics": {
            "discrete_source_sample_mass_kg": owner["discrete_source_sample_mass_kg"],
            "owner_metadata_continuum_mass_kg": owner["continuous_owner_mass_kg"],
            "difference_percent_of_owner": owner["owner_vs_sample_difference_pct_of_owner"],
            "interpretation": "separate source sample and continuum-owner quantities; mismatch does not establish a dynamics error or a physical missing-mass fate",
            "mass_rescale": False,
        },
        "read_policy": {
            "json_opened": True,
            "source_xml_opened": True,
            "motion_asset_hashed_only": True,
            "h5_opened": False,
            "bi4_opened": False,
            "partout_opened": False,
            "vtk_opened": False,
            "raw_solver_output_opened": False,
            "solver_started": False,
        },
        "claim_boundary": {
            "source_identity": "CLOSED_FOR_F7-S1_CURRENT_AND_SOURCE_RECIPE",
            "initial_support_or_mass": "LIMITED_DIAGNOSTIC_SCOPE_ONLY",
            "continuous_owner": "UNKNOWN",
            "boundary_contact": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "old_products_unchanged": True,
        "manifest_contract": manifest.get("contract"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, derive(args.manifest.expanduser().resolve()))
    except AuditError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
