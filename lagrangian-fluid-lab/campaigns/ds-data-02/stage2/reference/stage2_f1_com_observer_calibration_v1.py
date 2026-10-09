#!/usr/bin/env python3
"""Validate source-bound F1 COM observations without opening native payloads.

ROOT202 consumes completed selected-observer JSON sidecars and their small
provenance files.  It deliberately does not decode BI4/H5/VTK.  The worker
checks that an observer report is still the exact producer output named by its
proof, request, and receipt, and that its fluid aggregate is kept separate
from fixed/moving groups.  It also makes the two unresolved pieces explicit:
the producer does not expose an axis-orientation record and the selected
observer reports expose a particle-sum mass rather than a native header
MassFluid/MassBound field.

The output is a diagnostic/source-closure result.  It grants no QI, QN, or QE
credit, no integration/output error bound, and no continuum-mass equivalence.
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


SCHEMA = "ds02.stage2.f1-com-observer-calibration.v1"
OBSERVER_SCHEMA = "ds02.stage2.native-physical-observer.v2"
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
TIME_TOLERANCE_S = 1.0e-12
MASS_TOLERANCE_KG = 1.0e-10
VECTOR_TOLERANCE = 1.0e-12
FORBIDDEN_PAYLOAD_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}


class ContractError(ValueError):
    """A source, identity, or observable contract is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label} is not a regular file: {path}")
    if path.suffix.lower() in FORBIDDEN_PAYLOAD_SUFFIXES:
        raise ContractError(f"{label} points to native/H5/VTK payload: {path}")
    return path


def file_record(path: Path, label: str) -> dict[str, Any]:
    path = regular_file(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "sha256": sha256_file(path),
    }


def assert_record(spec: dict[str, Any], label: str) -> Path:
    if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
        raise ContractError(f"{label} has no path record")
    path = regular_file(Path(spec["path"]), label)
    stat = path.stat()
    actual = {
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "sha256": sha256_file(path),
    }
    for key in ("bytes", "mtime_ns", "ctime_ns", "device", "inode", "sha256"):
        if key in spec and spec[key] != actual[key]:
            raise ContractError(f"{label} current {key} does not match bound record")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} is not a JSON object: {path}")
    return value


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise ContractError(f"{label} is not finite")
    return result


def vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ContractError(f"{label} is not a 3-vector")
    return [finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def determinant(matrix: list[list[float]]) -> float:
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def validate_coordinate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    coordinate = contract.get("coordinate_contract")
    if not isinstance(coordinate, dict):
        raise ContractError("manifest has no coordinate_contract")
    if coordinate.get("position_unit") != "m":
        raise ContractError("position unit must be metres")
    if coordinate.get("velocity_unit") != "m/s":
        raise ContractError("velocity unit must be metres per second")
    if coordinate.get("mass_unit") != "kg":
        raise ContractError("mass unit must be kilograms")
    if coordinate.get("time_unit") != "s":
        raise ContractError("time unit must be seconds")
    if coordinate.get("axis_labels") != ["x", "y", "z"]:
        raise ContractError("axis labels must be the registered x/y/z order")
    if coordinate.get("frame") != "world_cartesian_right_handed":
        raise ContractError("unsupported coordinate frame")
    rotation = coordinate.get("rotation_to_world", [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    if not isinstance(rotation, list) or len(rotation) != 3 or any(not isinstance(row, list) or len(row) != 3 for row in rotation):
        raise ContractError("rotation_to_world must be a 3x3 matrix")
    matrix = [[finite(item, "rotation_to_world") for item in row] for row in rotation]
    det = determinant(matrix)
    if abs(det - 1.0) > VECTOR_TOLERANCE:
        raise ContractError("rotation_to_world must preserve a right-handed frame")
    return {
        "frame": coordinate["frame"],
        "axis_labels": list(coordinate["axis_labels"]),
        "position_unit": coordinate["position_unit"],
        "velocity_unit": coordinate["velocity_unit"],
        "mass_unit": coordinate["mass_unit"],
        "time_unit": coordinate["time_unit"],
        "rotation_to_world": matrix,
        "producer_axis_metadata_required": True,
    }


def transform_vector(value: list[float], matrix: list[list[float]]) -> list[float]:
    return [sum(matrix[row][column] * value[column] for column in range(3)) for row in range(3)]


def _assert_unknown_qualification(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key in UNKNOWN_QUALIFICATION:
            if value.get(key) not in (None, "UNKNOWN"):
                raise ContractError(f"{label} grants {key} credit; ROOT202 is diagnostic-only")


def _validate_request_identity(request: dict[str, Any], case: dict[str, Any], label: str) -> None:
    for key in ("family_id", "sentinel_id", "physical_case_id"):
        expected = case.get(key)
        if expected is not None and request.get(key) != expected:
            raise ContractError(f"{label} {key} mismatch")
    if request.get("case_id") != case.get("observer_case_id"):
        raise ContractError(f"{label} case_id does not match observer producer")
    if not request.get("attempt_id"):
        raise ContractError(f"{label} has no attempt_id")


def _validate_observer_groups(row: dict[str, Any], label: str) -> dict[str, Any]:
    groups = row.get("groups")
    if not isinstance(groups, dict) or not isinstance(groups.get("fluid"), dict):
        raise ContractError(f"{label} lacks a fluid group")
    fluid = groups["fluid"]
    if fluid.get("kind") != "fluid":
        raise ContractError(f"{label} fluid group is not typed as fluid")
    total_count = 0
    group_summary: dict[str, Any] = {}
    for name, group in groups.items():
        if not isinstance(group, dict):
            raise ContractError(f"{label} group {name} is not an object")
        expected_kind = {"fluid": "fluid", "fixed": "fixed", "moving": "moving"}.get(name)
        if expected_kind is not None and group.get("kind") != expected_kind:
            raise ContractError(f"{label} group {name} has wrong kind")
        count = int(finite(group.get("count"), f"{label} group {name} count"))
        if count < 0:
            raise ContractError(f"{label} group {name} count is negative")
        total_count += count
        for field in ("position_finite", "velocity_finite", "density_finite"):
            if group.get(field) is not True:
                raise ContractError(f"{label} group {name} has non-finite {field}")
        group_summary[name] = {
            "kind": group.get("kind"),
            "count": count,
            "sample_mass_kg": group.get("sample_mass_kg"),
            "excluded_from_fluid_com": name != "fluid",
        }
    identity = row.get("identity", {})
    particle_count = int(finite(identity.get("particle_count"), f"{label} particle_count"))
    if total_count != particle_count:
        raise ContractError(f"{label} group counts do not close to particle_count")
    return {"groups": group_summary, "particle_count": particle_count}


def _validate_observation(row: dict[str, Any], index: int, contract: dict[str, Any]) -> dict[str, Any]:
    label = f"observation[{index}]"
    frame = int(finite(row.get("frame"), f"{label} frame"))
    time = row.get("time", {})
    runparts_s = finite(time.get("runparts_s"), f"{label} RunPARTs time")
    decoded_s = finite(time.get("decoded_s"), f"{label} decoded time")
    if abs(runparts_s - decoded_s) > TIME_TOLERANCE_S:
        raise ContractError(f"{label} decoded time disagrees with RunPARTs")
    if time.get("status") not in ("PASS_DECODED_TIME_MATCH", "PASS_TIME_MATCH", None):
        raise ContractError(f"{label} has an unaccepted time status")
    identity = row.get("identity", {})
    if identity.get("id_unique") is not True:
        raise ContractError(f"{label} particle IDs are not unique")
    finite_fields = row.get("finite_fields", {})
    for field in ("position", "velocity", "density"):
        if finite_fields.get(field) is not True:
            raise ContractError(f"{label} {field} is not finite")
    group_summary = _validate_observer_groups(row, label)
    fluid = row["groups"]["fluid"]
    fluid_observables = row.get("fluid_observables")
    if not isinstance(fluid_observables, dict) or fluid_observables.get("status") != "PASS":
        raise ContractError(f"{label} fluid_observables is not PASS")
    density_count = int(finite(fluid.get("density", {}).get("count"), f"{label} fluid density count"))
    fluid_count = int(finite(fluid.get("count"), f"{label} fluid count"))
    if density_count != fluid_count:
        raise ContractError(f"{label} fluid density/count mismatch")
    fluid_mass = finite(fluid.get("sample_mass_kg"), f"{label} fluid sample mass")
    observable_mass = finite(fluid_observables.get("sample_mass_kg"), f"{label} observable sample mass")
    if abs(fluid_mass - observable_mass) > MASS_TOLERANCE_KG:
        raise ContractError(f"{label} fluid group and aggregate mass disagree")
    particle_mass = finite(fluid.get("particle_mass_kg"), f"{label} particle mass")
    if particle_mass <= 0 or fluid_mass < 0:
        raise ContractError(f"{label} invalid fluid mass")
    semantics = str(fluid_observables.get("sample_mass_semantics", ""))
    if "native" not in semantics.lower() or "continuum" not in semantics.lower():
        raise ContractError(f"{label} does not identify a native particle-sum mass")
    position = vector(fluid.get("weighted_centroid_m"), f"{label} weighted centroid")
    velocity = vector(fluid.get("weighted_velocity_m_per_s"), f"{label} weighted velocity")
    kinetic_energy = finite(fluid.get("kinetic_energy_j"), f"{label} kinetic energy")
    if kinetic_energy < 0:
        raise ContractError(f"{label} kinetic energy is negative")
    return {
        "frame": frame,
        "time_s": runparts_s,
        "fluid_count": fluid_count,
        "fluid_sample_mass_kg": fluid_mass,
        "fluid_particle_mass_kg": particle_mass,
        "weighted_centroid_m": position,
        "weighted_velocity_m_per_s": velocity,
        "kinetic_energy_j": kinetic_energy,
        "group_summary": group_summary,
        "coordinate_metadata_present": any(key in row for key in ("coordinate_frame", "axis_contract", "coordinate_system")),
        "native_header_mass_present": any(key in row for key in ("native_header", "mass_header", "MassFluid", "MassBound")),
    }


def validate_observer_report(report: dict[str, Any], case: dict[str, Any], coordinate: dict[str, Any]) -> dict[str, Any]:
    label = str(case.get("label", "case"))
    if report.get("schema") != OBSERVER_SCHEMA or report.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ContractError(f"{label} is not a completed observer v2 sidecar")
    _assert_unknown_qualification(report.get("scope", {}).get("scientific_qualification"), f"{label} observer scope")
    scope = report.get("scope", {})
    if scope.get("selected_frames_only") is not True or scope.get("full_native_tree_scanned") is not False or scope.get("hdf5_read") is not False:
        raise ContractError(f"{label} observer scope opens more than selected native rows")
    if report.get("manufactured_semantic_selftests", {}).get("status") != "PASS":
        raise ContractError(f"{label} observer manufactured self-tests are not PASS")
    source_integrity = report.get("source_integrity", {})
    if not str(source_integrity.get("status", "")).startswith("PASS"):
        raise ContractError(f"{label} observer source integrity is not PASS")
    rows = report.get("observations")
    if not isinstance(rows, list) or not rows:
        raise ContractError(f"{label} observer has no observations")
    summaries = [_validate_observation(row, index, case) for index, row in enumerate(rows)]
    if any(right["time_s"] <= left["time_s"] for left, right in zip(summaries, summaries[1:])):
        raise ContractError(f"{label} selected observer times are not strictly increasing")
    source = report.get("source", {})
    runparts = source.get("runparts", {})
    generated_xml = source.get("generated_xml", {})
    if not isinstance(runparts, dict) or not isinstance(generated_xml, dict):
        raise ContractError(f"{label} observer source lacks RunPARTs/XML records")
    current_source: dict[str, Any] = {}
    for key, item in (("runparts", runparts), ("generated_xml", generated_xml)):
        path = assert_record(item, f"{label} source {key}")
        current_source[key] = file_record(path, f"{label} source {key} current")
    report_axis_metadata = any(key in report for key in ("coordinate_frame", "axis_contract", "coordinate_system"))
    native_header_metadata = any(key in report for key in ("native_header", "mass_header", "MassFluid", "MassBound"))
    return {
        "label": label,
        "physical_case_id": case.get("physical_case_id"),
        "observer_case_id": case.get("observer_case_id"),
        "selected_frame_count": len(summaries),
        "first_time_s": summaries[0]["time_s"],
        "last_time_s": summaries[-1]["time_s"],
        "selected_frames": [item["frame"] for item in summaries],
        "observations": summaries,
        "source_current": current_source,
        "producer_coordinate_metadata": "PRESENT" if report_axis_metadata else "MISSING_FROM_PRODUCER",
        "producer_native_header_mass": "PRESENT" if native_header_metadata else "NOT_EXPOSED_BY_PRODUCER",
        "coordinate_contract_used": coordinate,
        "mass_semantics": "native particle-sum diagnostic only; continuum and rigid-body mass remain UNKNOWN",
        "cross_case_time_alignment": "UNKNOWN_UNEQUAL_SAVED_TIMES_NO_INTERPOLATION",
        "scientific_qualification": dict(UNKNOWN_QUALIFICATION),
    }


def _record_matches_declared(path: Path, declared: dict[str, Any], label: str) -> None:
    actual = file_record(path, label)
    for key in ("bytes", "mtime_ns", "ctime_ns", "device", "inode", "sha256"):
        if key in declared and declared[key] != actual[key]:
            raise ContractError(f"{label} {key} mismatch")


def validate_provenance(case: dict[str, Any], manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    label = str(case.get("label", "case"))
    observer = case.get("observer")
    if not isinstance(observer, dict):
        raise ContractError(f"{label} missing observer provenance")
    proof_spec = observer.get("proof")
    proof_path = assert_record(proof_spec, f"{label} observer proof")
    proof = read_json(proof_path, f"{label} observer proof")
    if not str(proof.get("status", "")).startswith(("PASS", "VERIFIED")):
        raise ContractError(f"{label} observer proof is not a successful proof")
    _assert_unknown_qualification(proof.get("scientific_qualification", proof.get("qualification")), f"{label} observer proof")
    report_spec = observer.get("report")
    report_path = assert_record(report_spec, f"{label} observer report")
    _record_matches_declared(report_path, report_spec, f"{label} observer report")
    report = read_json(report_path, f"{label} observer report")
    declared_report = proof.get("report")
    if isinstance(declared_report, str) and str(report_path) != str(Path(declared_report).resolve()):
        raise ContractError(f"{label} proof/report path mismatch")
    declared_report_sha = proof.get("report_sha256")
    if declared_report_sha and declared_report_sha != report_spec.get("sha256"):
        raise ContractError(f"{label} proof/report SHA mismatch")
    receipt_spec = observer.get("receipt")
    receipt_path = assert_record(receipt_spec, f"{label} observer receipt")
    _record_matches_declared(receipt_path, receipt_spec, f"{label} observer receipt")
    receipt = read_json(receipt_path, f"{label} observer receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") not in (0, None):
        raise ContractError(f"{label} observer receipt is not completed successfully")
    declared_receipt_sha = proof.get("receipt_sha256")
    if declared_receipt_sha and declared_receipt_sha != receipt_spec.get("sha256"):
        raise ContractError(f"{label} proof/receipt SHA mismatch")
    embedded_request = receipt.get("request")
    if not isinstance(embedded_request, dict):
        raise ContractError(f"{label} observer receipt has no embedded request")
    _validate_request_identity(embedded_request, case, f"{label} observer request")
    case["observer_case_id"] = embedded_request.get("case_id")
    if observer.get("request", {}).get("kind") == "file":
        request_spec = observer["request"]["record"]
        request_path = assert_record(request_spec, f"{label} observer request")
        request = read_json(request_path, f"{label} observer request")
        _validate_request_identity(request, case, f"{label} observer request file")
        if request.get("case_id") != embedded_request.get("case_id"):
            raise ContractError(f"{label} request/receipt case mismatch")
        declared_request = proof.get("request")
        if isinstance(declared_request, str) and str(request_path) != str(Path(declared_request).resolve()):
            raise ContractError(f"{label} proof/request path mismatch")
        if isinstance(proof.get("request_sha256"), str) and proof["request_sha256"] != request_spec.get("sha256"):
            raise ContractError(f"{label} proof/request SHA mismatch")
    else:
        request = embedded_request
    proof_identity = proof.get("physical_case_id") or proof.get("case", {}).get("physical_case_id")
    if proof_identity and proof_identity != case.get("physical_case_id"):
        raise ContractError(f"{label} proof physical_case_id mismatch")
    solver = case.get("solver_evidence", {})
    solver_result: dict[str, Any]
    if solver.get("status") == "BOUND":
        solver_proof_path = assert_record(solver["proof"], f"{label} solver proof")
        solver_proof = read_json(solver_proof_path, f"{label} solver proof")
        if not str(solver_proof.get("status", "")).startswith(("PASS", "VERIFIED", "ACTUAL")):
            raise ContractError(f"{label} solver proof is not successful")
        solver_detail = solver_proof
        proof_pair = solver.get("proof_pair")
        if proof_pair is not None:
            solver_detail = solver_proof.get("pairs", {}).get(proof_pair)
            if not isinstance(solver_detail, dict):
                raise ContractError(f"{label} solver proof has no pair {proof_pair}")
        solver_request_spec = solver.get("request")
        solver_receipt_spec = solver.get("receipt")
        solver_request_path = assert_record(solver_request_spec, f"{label} solver request")
        solver_receipt_path = assert_record(solver_receipt_spec, f"{label} solver receipt")
        solver_request = read_json(solver_request_path, f"{label} solver request")
        solver_receipt = read_json(solver_receipt_path, f"{label} solver receipt")
        declared_solver_request = solver_detail.get("request")
        declared_solver_receipt = solver_detail.get("receipt")
        if isinstance(declared_solver_request, str) and str(solver_request_path) != str(Path(declared_solver_request).resolve()):
            raise ContractError(f"{label} solver proof/request path mismatch")
        if isinstance(declared_solver_receipt, str) and str(solver_receipt_path) != str(Path(declared_solver_receipt).resolve()):
            raise ContractError(f"{label} solver proof/receipt path mismatch")
        if isinstance(declared_solver_request, dict) and str(solver_request_path) != str(Path(declared_solver_request["path"]).resolve()):
            raise ContractError(f"{label} solver proof/request path mismatch")
        if isinstance(declared_solver_receipt, dict) and str(solver_receipt_path) != str(Path(declared_solver_receipt["path"]).resolve()):
            raise ContractError(f"{label} solver proof/receipt path mismatch")
        if solver_receipt.get("status") not in ("completed", "COMPLETED", "completed0", "COMPLETED_DEVELOPMENT_UNKNOWN") or solver_receipt.get("returncode") not in (0, None):
            raise ContractError(f"{label} solver receipt is not completed successfully")
        embedded_solver_request = solver_receipt.get("request")
        if isinstance(embedded_solver_request, dict):
            if embedded_solver_request.get("physical_case_id") not in (None, case.get("physical_case_id")):
                raise ContractError(f"{label} solver request/physical identity mismatch")
            if embedded_solver_request.get("case_id") and solver_request.get("case_id") and embedded_solver_request.get("case_id") != solver_request.get("case_id"):
                raise ContractError(f"{label} solver request/receipt case mismatch")
        solver_result = {
            "status": "BOUND_SUCCESS",
            "proof": file_record(solver_proof_path, f"{label} solver proof current"),
            "request": file_record(solver_request_path, f"{label} solver request current"),
            "receipt": file_record(solver_receipt_path, f"{label} solver receipt current"),
        }
    else:
        solver_result = {
            "status": "UNKNOWN_MISSING_INDEPENDENT_SOLVER_PROOF",
            "reason": solver.get("reason", "no independent terminal solver proof was supplied"),
        }
    return {
        "observer_proof": file_record(proof_path, f"{label} observer proof current"),
        "observer_report": file_record(report_path, f"{label} observer report current"),
        "observer_receipt": file_record(receipt_path, f"{label} observer receipt current"),
        "observer_request": {"kind": "embedded_in_receipt", "request_sha256": receipt.get("request_sha256"), "case_id": embedded_request.get("case_id")},
        "solver": solver_result,
    }, report


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != "ds02.stage2.f1-com-observer-calibration-manifest.v1":
        raise ContractError("unsupported ROOT202 manifest schema")
    coordinate = validate_coordinate_contract(manifest)
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ContractError("manifest has no small input records")
    for index, item in enumerate(inputs):
        assert_record(item, f"manifest input[{index}]")
    contract_record = manifest.get("contract")
    if contract_record is not None:
        contract_path = assert_record(contract_record, "ROOT202 calibration contract")
        contract_document = read_json(contract_path, "ROOT202 calibration contract")
        if contract_document.get("coordinate_contract") != manifest.get("coordinate_contract"):
            raise ContractError("manifest coordinate contract differs from bound contract file")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ContractError("manifest has no cases")
    validated: list[dict[str, Any]] = []
    for original_case in cases:
        if not isinstance(original_case, dict):
            raise ContractError("case is not an object")
        case = dict(original_case)
        provenance, report = validate_provenance(case, manifest)
        identity = case.get("identity", {})
        case.update({
            "family_id": identity.get("family_id", case.get("family_id")),
            "sentinel_id": identity.get("sentinel_id", case.get("sentinel_id")),
            "physical_case_id": identity.get("physical_case_id", case.get("physical_case_id")),
        })
        summary = validate_observer_report(report, case, coordinate)
        summary["provenance"] = provenance
        summary["grid"] = case.get("grid", {})
        summary["source_case_id"] = case.get("observer_case_id")
        validated.append(summary)
    missing_axis = sum(item["producer_coordinate_metadata"] != "PRESENT" for item in validated)
    missing_header = sum(item["producer_native_header_mass"] != "PRESENT" for item in validated)
    missing_solver = sum(item["provenance"]["solver"]["status"] != "BOUND_SUCCESS" for item in validated)
    return {
        "schema": SCHEMA,
        "status": "PASS_SOURCE_BOUND_F1_COM_DIAGNOSTICS_WITH_DECLARED_GAPS",
        "scope": {
            "native_payload_read_by_worker": False,
            "hdf5_read": False,
            "bi4_read": False,
            "vtk_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "interpolation": "NOT_PERFORMED",
            "cases": len(validated),
        },
        "cases": validated,
        "gaps": {
            "producer_axis_orientation_metadata_missing_cases": missing_axis,
            "producer_native_header_mass_missing_cases": missing_header,
            "independent_solver_proof_missing_cases": missing_solver,
            "rigid_body_physical_mass": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SUM",
            "continuum_mass": "UNKNOWN_NOT_DERIVED_FROM_NATIVE_PARTICLE_SUM",
            "cross_case_time_alignment": "UNKNOWN_UNEQUAL_SAVED_TIMES_NO_INTERPOLATION",
            "integration_and_output_error": "UNKNOWN_NO_INDEPENDENT_TIME_OR_FIELD_TRUTH",
        },
        "interpretation": {
            "fluid_com": "weighted_centroid_m and weighted_velocity_m_per_s from groups.fluid only",
            "wall_separation": "groups.fixed and groups.moving are counted and excluded from fluid aggregates; mixed kind is rejected",
            "mass": "native particle-sum diagnostic only; native header MassFluid/MassBound was not exposed by existing producer sidecars",
            "coordinates": "x/y/z metres in the registered right-handed world convention; existing producer reports do not emit orientation metadata, so this remains an external contract",
            "time": "actual observer RunPARTs timestamps; no cross-case interpolation or frame-index pairing",
        },
        "scientific_qualification": dict(UNKNOWN_QUALIFICATION),
    }


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fixture_report() -> dict[str, Any]:
    def group(kind: str, count: int, mass: float, centroid: list[float], velocity: list[float]) -> dict[str, Any]:
        return {
            "kind": kind,
            "count": count,
            "position_finite": True,
            "velocity_finite": True,
            "density_finite": True,
            "density": {"count": count},
            "sample_mass_kg": mass,
            "particle_mass_kg": mass / count,
            "weighted_centroid_m": centroid,
            "weighted_velocity_m_per_s": velocity,
            "kinetic_energy_j": 0.5 * mass * sum(x * x for x in velocity),
        }
    rows = []
    for frame, time in enumerate((0.0, 1.0)):
        fluid = group("fluid", 2, 2.0, [1.0 + time + 0.5 * time * time, 2.0, 3.0], [1.0 + time, 0.0, 0.0])
        fixed = group("fixed", 2, 200.0, [100.0, 100.0, 100.0], [0.0, 0.0, 0.0])
        rows.append({
            "frame": frame,
            "time": {"runparts_s": time, "decoded_s": time, "status": "PASS_DECODED_TIME_MATCH"},
            "identity": {"particle_count": 4, "id_unique": True},
            "finite_fields": {"position": True, "velocity": True, "density": True},
            "groups": {"fluid": fluid, "fixed": fixed},
            "fluid_observables": {"status": "PASS", "sample_mass_kg": 2.0, "sample_mass_semantics": "sum(native fluid particle mass) only; not continuum mass or rigid body mass"},
        })
    return {
        "schema": OBSERVER_SCHEMA,
        "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
        "scope": {"selected_frames_only": True, "full_native_tree_scanned": False, "hdf5_read": False, "scientific_qualification": dict(UNKNOWN_QUALIFICATION)},
        "manufactured_semantic_selftests": {"status": "PASS"},
        "source_integrity": {"status": "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT"},
        "source": {"runparts": {}, "generated_xml": {}},
        "observations": rows,
    }


def self_test() -> dict[str, Any]:
    contract = {"coordinate_contract": {"frame": "world_cartesian_right_handed", "axis_labels": ["x", "y", "z"], "position_unit": "m", "velocity_unit": "m/s", "mass_unit": "kg", "time_unit": "s", "rotation_to_world": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}
    coordinate = validate_coordinate_contract(contract)
    report = _fixture_report()
    case = {"label": "fixture", "physical_case_id": "fixture", "observer_case_id": "fixture"}
    with tempfile.TemporaryDirectory(prefix="root202-com-fixture-") as temporary:
        fixture_root = Path(temporary)
        runparts = fixture_root / "RunPARTs.csv"
        generated_xml = fixture_root / "generated.xml"
        runparts.write_text("Part;TimeStep [s]\n0;0.0\n1;1.0\n", encoding="utf-8")
        generated_xml.write_text("<case />\n", encoding="utf-8")
        report["source"] = {
            "runparts": file_record(runparts, "fixture RunPARTs"),
            "generated_xml": file_record(generated_xml, "fixture XML"),
            "raw_root": str(fixture_root / "data"),
        }
        summary = validate_observer_report(report, case, coordinate)
    if summary["observations"][0]["weighted_centroid_m"] != [1.0, 2.0, 3.0] or summary["observations"][1]["weighted_centroid_m"] != [2.5, 2.0, 3.0]:
        raise AssertionError("trajectory fixture failed")
    rotated = transform_vector([1.0, 2.0, 3.0], [[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    if any(abs(a - b) > VECTOR_TOLERANCE for a, b in zip(rotated, [-2.0, 1.0, 3.0])):
        raise AssertionError("coordinate rotation fixture failed")
    try:
        validate_coordinate_contract({"coordinate_contract": {**contract["coordinate_contract"], "position_unit": "mm"}})
    except ContractError:
        pass
    else:
        raise AssertionError("unit error fixture was accepted")
    try:
        validate_coordinate_contract({"coordinate_contract": {**contract["coordinate_contract"], "rotation_to_world": [[1, 0, 0], [0, 1, 0], [0, 0, -1]]}})
    except ContractError:
        pass
    else:
        raise AssertionError("left-handed rotation fixture was accepted")
    contaminated = summary["observations"][0]
    if contaminated["weighted_centroid_m"] != [1.0, 2.0, 3.0] or contaminated["group_summary"]["groups"]["fixed"]["excluded_from_fluid_com"] is not True:
        raise AssertionError("solid contamination fixture was not excluded")
    return {"status": "PASS", "cases": ["quadratic/linear trajectory", "right-handed coordinate rotation", "fixed-wall contamination", "mass/position unit rejection", "left-handed axis rejection"], "scope": "manufactured semantics only; no native payload read"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    if args.manifest is None or args.output is None:
        parser.error("--manifest and --output are required unless --self-test is used")
    manifest = read_json(args.manifest.resolve(), "ROOT202 manifest")
    result = validate_manifest(manifest)
    atomic_json(args.output.resolve(), result)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "cases": len(result["cases"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
