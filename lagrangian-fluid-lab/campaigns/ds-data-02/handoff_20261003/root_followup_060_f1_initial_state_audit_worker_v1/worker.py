#!/usr/bin/env python3
"""Read-only initial-state mass and evidence worker for F1 ECC/DUAL.

The worker consumes the actual GenCase027/QA031 source manifests and the
official PartVTK CSV that Root's QA031 preflight reader already produced.  It
does not launch a solver, GenCase, PartVTK, or any other subprocess, and it
never writes a particle array.  It streams the bound CSV, computes the native
fluid weight/mass and continuum difference from the actual rows, and writes
five small JSON sidecars plus a case-specific audit result.

The request that invokes this module is deliberately disabled.  Root must
review the source bindings and enable a fresh CPU ``audit`` request before
running it.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


READER_SCHEMA = "ds02.root.actual-initial-native-QA.v1"
QA_RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
INPUT_CASES = {
    "F1_STAGE1_ECC_H130_DP010": {
        "audit_schema": "ds02.stage1.f1.ecc.h130-strict-cpu-audit-result.v1",
        "family_variant": "ecc",
        "expected_total": 136276,
        "expected_fluid": 34840,
    },
    "F1_STAGE1_DUAL_H260_DP020": {
        "audit_schema": "ds02.stage1.f1.dual.h260-strict-cpu-audit-result.v1",
        "family_variant": "dual",
        "expected_total": 120316,
        "expected_fluid": 32500,
    },
}
REQUIRED_COLUMNS = (
    "Pos.x [m]",
    "Pos.y [m]",
    "Pos.z [m]",
    "Zone",
    "Idp",
    "Vel.x [m/s]",
    "Vel.y [m/s]",
    "Vel.z [m/s]",
    "Rhop [kg/m^3]",
    "Mass [kg]",
    "Press [Pa]",
    "Type",
    "Mk",
)
REQUIRED_CHECK_NAMES = (
    "genuine_gencase_counts_match_qa031_and_prepared_report",
    "native_particle_weight_read_from_actual_input",
    "mass_difference_computed_by_worker",
    "no_mass_rescaling",
    "physics_finite_state",
    "geometry_finite_state",
    "motion_finite_state",
    "no_initial_fluid_solid_overlap",
)
SIDECARE_NAMES = (
    "initial_mass_discrepancy_report",
    "physics_evidence",
    "geometry_evidence",
    "motion_evidence",
    "no_overlap_finite_state_evidence",
)


class AuditError(RuntimeError):
    """Raised when an immutable source or worker invariant fails."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _binding(path: Path, expected: str | None = None) -> dict[str, str]:
    path = path.resolve()
    _require(path.is_file(), f"source file is missing: {path}")
    actual = _sha256(path)
    if expected is not None:
        _require(actual == expected, f"source hash mismatch: {path}")
    return {"path": str(path), "sha256": actual}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot load JSON source: {path}") from error


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a JSON object")
    return value


def _write_new_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as error:
        raise AuditError(f"refusing to overwrite existing worker output: {path}") from error


def _path_hashes(manifest: Mapping[str, Any]) -> dict[Path, str]:
    values = manifest.get("inputs")
    _require(isinstance(values, list) and values, "input manifest has no inputs")
    result: dict[Path, str] = {}
    for value in values:
        row = _mapping(value, "input binding")
        raw_path = row.get("path")
        expected = row.get("sha256")
        _require(isinstance(raw_path, str) and isinstance(expected, str), "input binding is incomplete")
        path = Path(raw_path).resolve()
        _require(path not in result or result[path] == expected, f"conflicting input binding: {path}")
        result[path] = expected
    for path, expected in result.items():
        _binding(path, expected)
    return result


def _find_json(
    paths: Iterable[Path],
    predicate: Any,
    label: str,
) -> tuple[Path, Mapping[str, Any]]:
    matches: list[tuple[Path, Mapping[str, Any]]] = []
    for path in paths:
        if path.suffix.lower() != ".json":
            continue
        try:
            value = _mapping(_load(path), path.name)
        except AuditError:
            continue
        if predicate(value):
            matches.append((path, value))
    _require(len(matches) == 1, f"expected exactly one {label}, found {len(matches)}")
    return matches[0]


def _find_case_sources(
    manifest: Mapping[str, Any],
    input_hashes: Mapping[Path, str],
    case_id: str,
) -> dict[str, Any]:
    paths = tuple(input_hashes)
    qa_path, qa_document = _find_json(
        paths,
        lambda value: value.get("schema") == READER_SCHEMA,
        "QA031 native-initial-qa document",
    )
    qa_rows = qa_document.get("cases")
    _require(isinstance(qa_rows, list), "QA031 document has no cases")
    matching_rows = [row for row in qa_rows if isinstance(row, Mapping) and row.get("case_id") == case_id]
    _require(len(matching_rows) == 1, f"QA031 does not contain one {case_id} row")
    qa_row = matching_rows[0]

    receipt_path, receipt = _find_json(
        paths,
        lambda value: (
            value.get("schema") == QA_RECEIPT_SCHEMA
            and isinstance(value.get("request"), Mapping)
            and value["request"].get("case_id") == case_id
        ),
        f"GenCase027 receipt for {case_id}",
    )
    prepared_path, prepared = _find_json(
        paths,
        lambda value: value.get("case_id") == case_id
        and "generated_xml_particle_counts" in value
        and "actual_total_particles" in value,
        f"prepared-input report for {case_id}",
    )

    xml_candidates = [
        path for path in paths
        if path.suffix.lower() == ".xml" and path.stem == case_id
    ]
    bi4_candidates = [
        path for path in paths
        if path.suffix.lower() == ".bi4" and path.stem == case_id
    ]
    _require(len(xml_candidates) == 1, f"expected one generated XML for {case_id}")
    _require(len(bi4_candidates) == 1, f"expected one generated BI4 for {case_id}")
    xml_path, bi4_path = xml_candidates[0], bi4_candidates[0]

    csv_raw = qa_row.get("official_csv")
    csv_sha = qa_row.get("official_csv_sha256")
    _require(isinstance(csv_raw, str) and isinstance(csv_sha, str), "QA031 official CSV binding is missing")
    csv_path = Path(csv_raw).resolve()
    _require(csv_path in input_hashes, "QA031 official CSV is not in the immutable input manifest")
    _require(input_hashes[csv_path] == csv_sha, "QA031 official CSV hash differs from the input manifest")

    qa_receipt_path = qa_path.parent / "execution-receipt.json"
    _require(qa_receipt_path.is_file(), "QA031 execution receipt is missing beside the QA document")
    qa_receipt = _mapping(_load(qa_receipt_path), "QA031 execution receipt")

    return {
        "qa_path": qa_path,
        "qa_document": qa_document,
        "qa_row": qa_row,
        "qa_receipt_path": qa_receipt_path,
        "qa_receipt": qa_receipt,
        "gencase_receipt_path": receipt_path,
        "gencase_receipt": receipt,
        "prepared_report_path": prepared_path,
        "prepared_report": prepared,
        "xml_path": xml_path,
        "bi4_path": bi4_path,
        "csv_path": csv_path,
    }


def _check_manifest_identity(manifest: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    _require(case_id in INPUT_CASES, f"unsupported F1 audit case: {case_id}")
    schema = manifest.get("schema")
    _require(isinstance(schema, str) and schema.endswith("strict-cpu-audit-inputs.v1"), "unexpected strict audit input schema")
    _require(manifest.get("source_only") is True, "input manifest is not source-only")
    _require(manifest.get("execution_allowed") is False, "input manifest enables execution")
    _require(manifest.get("case_id") == case_id, "input manifest case identity mismatch")
    expected = INPUT_CASES[case_id]
    identity = _mapping(manifest.get("expected_identity"), "expected identity")
    _require(identity.get("genuine_gencase_total_particles") == expected["expected_total"], "GenCase total differs from frozen identity")
    _require(identity.get("genuine_gencase_fluid_particles") == expected["expected_fluid"], "GenCase fluid count differs from frozen identity")
    _require(identity.get("qa_native_particles") == expected["expected_total"], "QA total differs from frozen identity")
    _require(identity.get("qa_native_fluid") == expected["expected_fluid"], "QA fluid count differs from frozen identity")
    _require(identity.get("actual_3d") is True, "actual 3-D identity is missing")
    _require(identity.get("mass_rescaling") is False, "mass rescaling is not allowed")
    continuum = identity.get("continuum_reference_mass_kg")
    _require(isinstance(continuum, (int, float)) and not isinstance(continuum, bool) and math.isfinite(float(continuum)) and float(continuum) > 0, "continuum mass is invalid")
    return identity


def _check_source_metadata(
    manifest: Mapping[str, Any],
    sources: Mapping[str, Any],
    input_hashes: Mapping[Path, str],
    reader_path: Path,
    reader_sha256: str,
    case_id: str,
) -> dict[str, Any]:
    expected = INPUT_CASES[case_id]
    identity = _check_manifest_identity(manifest, case_id)
    qa_row = sources["qa_row"]
    _require(qa_row.get("passed") is True, "QA031 case did not pass")
    _require(qa_row.get("actual_3d") is True, "QA031 case is not actual 3-D")
    _require(qa_row.get("native_particles") == expected["expected_total"], "QA031 native total differs")
    _require(qa_row.get("native_fluid") == expected["expected_fluid"], "QA031 native fluid differs")
    _require(qa_row.get("generated_xml_sha256") == input_hashes[sources["xml_path"]], "QA031 XML hash differs")
    _require(qa_row.get("initial_bi4_sha256") == input_hashes[sources["bi4_path"]], "QA031 BI4 hash differs")

    receipt = _mapping(sources["gencase_receipt"], "GenCase027 receipt")
    _require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, "GenCase027 receipt is not completed")
    _require(receipt.get("solver_dimension_from_gencase") == 3, "GenCase027 receipt is not 3-D")
    _require(receipt.get("total_particles") == expected["expected_total"], "GenCase027 total differs")
    _require(receipt.get("fluid_particles") == expected["expected_fluid"], "GenCase027 fluid differs")
    _require(receipt.get("input_hashes_at_launch") == receipt.get("input_hashes_after_run"), "GenCase027 inputs changed")

    prepared = _mapping(sources["prepared_report"], "prepared-input report")
    _require(prepared.get("actual_total_particles") == expected["expected_total"], "prepared total differs")
    generated_counts = _mapping(prepared.get("generated_xml_particle_counts"), "prepared XML counts")
    _require(generated_counts.get("fluid") == expected["expected_fluid"], "prepared fluid differs")
    predictions = _mapping(prepared.get("predictions"), "prepared predictions")
    _require(isinstance(predictions.get("native_weight_float32_kg"), (int, float)), "prepared native weight metadata is missing")

    reader = _mapping(sources["qa_receipt"], "QA031 execution receipt")
    _require(reader.get("schema") == QA_RECEIPT_SCHEMA, "QA031 execution receipt schema differs")
    _require(reader.get("status") == "completed" and reader.get("returncode") == 0, "QA031 reader did not complete")
    reader_request = _mapping(reader.get("request"), "QA031 reader request")
    _require(reader_request.get("cpu_task_kind") == "audit", "QA031 reader was not an audit")
    reader_command = reader_request.get("command")
    _require(isinstance(reader_command, list) and len(reader_command) >= 2, "QA031 reader command is missing")
    _require(Path(str(reader_command[1])).resolve() == reader_path, "QA031 reader source differs from the request binding")
    _require(_sha256(reader_path) == reader_sha256, "Root preflight reader hash differs")

    partvtk = [
        Path(str(path)).resolve()
        for path in reader_request.get("input_files", [])
        if "PartVTK_linux64" in str(path)
    ]
    _require(len(partvtk) == 1, "QA031 receipt lacks one PartVTK binary binding")
    partvtk_expected_sha = _mapping(reader.get("input_sha256"), "QA031 input hashes").get(str(partvtk[0]))
    _require(isinstance(partvtk_expected_sha, str), "QA031 PartVTK binary hash is missing")
    _require(_sha256(partvtk[0]) == partvtk_expected_sha, "QA031 PartVTK binary hash differs")

    xml_root = ET.parse(sources["xml_path"]).getroot()
    constants_node = xml_root.find("./execution/constants")
    _require(constants_node is not None, "generated XML constants are missing")
    constants = {child.tag.lower(): dict(child.attrib) for child in constants_node}
    _require(constants.get("data2d", {}).get("value", "").lower() == "false", "generated XML is not actual 3-D")
    dp_value = float(constants.get("dp", {}).get("value", "nan"))
    xml_massfluid = float(constants.get("massfluid", {}).get("value", "nan"))
    _require(math.isfinite(dp_value) and dp_value > 0, "generated XML dp is invalid")
    _require(math.isfinite(xml_massfluid) and xml_massfluid > 0, "generated XML massfluid is invalid")

    return {
        "identity": identity,
        "expected": expected,
        "continuum_reference_mass_kg": float(identity["continuum_reference_mass_kg"]),
        "dp_m": dp_value,
        "xml_massfluid_kg": xml_massfluid,
        "xml_massfluid_float32_kg": struct.unpack("<f", struct.pack("<f", xml_massfluid))[0],
        "partvtk_path": partvtk[0],
        "source_bindings": {
            "input_manifest": None,
            "root_preflight_reader": _binding(reader_path, reader_sha256),
            "qa031": _binding(sources["qa_path"], input_hashes[sources["qa_path"]]),
            "qa031_execution_receipt": _binding(sources["qa_receipt_path"]),
            "gencase_receipt": _binding(sources["gencase_receipt_path"], input_hashes[sources["gencase_receipt_path"]]),
            "prepared_report": _binding(sources["prepared_report_path"], input_hashes[sources["prepared_report_path"]]),
            "generated_xml": _binding(sources["xml_path"], input_hashes[sources["xml_path"]]),
            "initial_bi4": _binding(sources["bi4_path"], input_hashes[sources["bi4_path"]]),
            "official_csv": _binding(sources["csv_path"], input_hashes[sources["csv_path"]]),
            "partvtk": _binding(partvtk[0], partvtk_expected_sha),
        },
    }


def _float(value: str, label: str) -> float:
    try:
        result = float(value.strip())
    except (TypeError, ValueError) as error:
        raise AuditError(f"invalid numeric {label}: {value!r}") from error
    _require(math.isfinite(result), f"non-finite numeric {label}")
    return result


def _integer(value: str, label: str) -> int:
    try:
        result = int(value.strip())
    except (TypeError, ValueError) as error:
        raise AuditError(f"invalid integer {label}: {value!r}") from error
    return result


def _cell(point: tuple[float, float, float], cell_size: float) -> tuple[int, int, int]:
    return tuple(math.floor(value / cell_size) for value in point)


def _scan_csv(
    csv_path: Path,
    expected_total: int,
    expected_fluid: int,
    expected_envelope: Any,
    dp_m: float,
) -> dict[str, Any]:
    _require(csv_path.is_file(), f"official QA CSV is missing: {csv_path}")
    header: list[str] | None = None
    rows_seen = 0
    fluid_count = 0
    type_counts: Counter[int] = Counter()
    id_seen: set[int] = set()
    fluid_masses: list[float] = []
    fluid_points: list[tuple[float, float, float]] = []
    fixed_grid: dict[tuple[int, int, int], list[tuple[float, float, float]]] = {}
    fluid_min = [math.inf, math.inf, math.inf]
    fluid_max = [-math.inf, -math.inf, -math.inf]
    max_velocity_abs = 0.0
    all_physics_finite = True
    all_geometry_finite = True
    all_motion_finite = True
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for raw_row in reader:
            row = [value.strip() for value in raw_row]
            if not row or not any(row):
                continue
            if header is None:
                if all(name in row for name in REQUIRED_COLUMNS):
                    header = row
                continue
            if len(row) < len(header):
                raise AuditError(f"CSV row {rows_seen + 1} is shorter than its header")
            values = {name: row[header.index(name)].strip() for name in REQUIRED_COLUMNS}
            rows_seen += 1
            point = tuple(_float(values[f"Pos.{axis} [m]"], f"position.{axis}") for axis in "xyz")
            velocity = tuple(_float(values[f"Vel.{axis} [m/s]"], f"velocity.{axis}") for axis in "xyz")
            rhop = _float(values["Rhop [kg/m^3]"], "density")
            mass = _float(values["Mass [kg]"], "mass")
            pressure = _float(values["Press [Pa]"], "pressure")
            particle_id = _integer(values["Idp"], "particle id")
            particle_type = _integer(values["Type"], "particle type")
            _integer(values["Zone"], "particle zone")
            _integer(values["Mk"], "particle marker")
            _require(0 <= particle_id < expected_total, f"particle id outside native range: {particle_id}")
            _require(particle_id not in id_seen, f"duplicate native particle id: {particle_id}")
            id_seen.add(particle_id)
            _require(particle_type in (0, 3), f"unexpected initial particle type: {particle_type}")
            type_counts[particle_type] += 1
            all_geometry_finite &= all(math.isfinite(value) for value in point)
            all_motion_finite &= all(math.isfinite(value) for value in velocity)
            all_physics_finite &= all(math.isfinite(value) for value in (*velocity, rhop, mass, pressure))
            _require(rhop > 0 and mass > 0, "native density and mass must be positive")
            max_velocity_abs = max(max_velocity_abs, *(abs(value) for value in velocity))
            if particle_type == 3:
                fluid_count += 1
                fluid_masses.append(mass)
                fluid_points.append(point)
                for axis, value in enumerate(point):
                    fluid_min[axis] = min(fluid_min[axis], value)
                    fluid_max[axis] = max(fluid_max[axis], value)
            else:
                fixed_grid.setdefault(_cell(point, dp_m), []).append(point)
    _require(header is not None, "official QA CSV header is missing")
    _require(rows_seen == expected_total, f"native row count differs: {rows_seen} != {expected_total}")
    _require(fluid_count == expected_fluid, f"native fluid count differs: {fluid_count} != {expected_fluid}")
    _require(len(id_seen) == expected_total and id_seen == set(range(expected_total)), "native particle ids are not a complete range")
    _require(type_counts == Counter({0: expected_total - expected_fluid, 3: expected_fluid}), f"native type counts differ: {type_counts}")
    _require(all_geometry_finite and all_motion_finite and all_physics_finite, "initial CSV contains a non-finite state")

    observed_envelope = [list(fluid_min), list(fluid_max)]
    envelope_tolerance = max(dp_m * 1e-4, 1e-7)
    envelope_match = True
    if isinstance(expected_envelope, list) and len(expected_envelope) == 2:
        for actual, expected in zip(observed_envelope, expected_envelope):
            if not isinstance(expected, list) or len(expected) != 3:
                envelope_match = False
                break
            envelope_match &= all(abs(float(a) - float(e)) <= envelope_tolerance for a, e in zip(actual, expected))
    else:
        envelope_match = False
    _require(envelope_match, "native fluid envelope differs from QA031")

    threshold = dp_m * (1.0 - 1e-6)
    threshold_sq = threshold * threshold
    min_distance_sq = math.inf
    overlap_count = 0
    for point in fluid_points:
        cx, cy, cz = _cell(point, dp_m)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for fixed in fixed_grid.get((cx + dx, cy + dy, cz + dz), ()):
                        distance_sq = sum((point[axis] - fixed[axis]) ** 2 for axis in range(3))
                        min_distance_sq = min(min_distance_sq, distance_sq)
                        if distance_sq < threshold_sq:
                            overlap_count += 1
    no_overlap = overlap_count == 0 and math.isfinite(min_distance_sq)
    return {
        "rows": rows_seen,
        "fluid_rows": fluid_count,
        "type_counts": {str(key): int(value) for key, value in sorted(type_counts.items())},
        "unique_particle_ids": len(id_seen),
        "fluid_envelope_m": observed_envelope,
        "qa_envelope_match": envelope_match,
        "envelope_tolerance_m": envelope_tolerance,
        "max_initial_velocity_abs_m_per_s": max_velocity_abs,
        "fluid_mass_values_kg": fluid_masses,
        "native_particle_weight_kg": fluid_masses[0],
        "native_fluid_mass_kg": math.fsum(fluid_masses),
        "fixed_particle_count": expected_total - expected_fluid,
        "minimum_fluid_solid_center_distance_m": math.sqrt(min_distance_sq),
        "fluid_solid_overlap_threshold_m": threshold,
        "fluid_solid_overlap_pair_count": overlap_count,
        "checks": {
            "physics_finite_state": bool(all_physics_finite),
            "geometry_finite_state": bool(all_geometry_finite and envelope_match),
            "motion_finite_state": bool(all_motion_finite and max_velocity_abs <= 1e-8),
            "no_initial_fluid_solid_overlap": bool(no_overlap),
        },
    }


def _source_still_bound(input_hashes: Mapping[Path, str]) -> None:
    for path, expected in input_hashes.items():
        _require(_sha256(path) == expected, f"source changed during worker: {path}")


def run(input_manifest_path: Path, reader_path: Path, reader_sha256: str, output_path: Path) -> dict[str, Any]:
    input_manifest_path = input_manifest_path.resolve()
    reader_path = reader_path.resolve()
    manifest = _mapping(_load(input_manifest_path), "strict CPU input manifest")
    case_id = manifest.get("case_id")
    _require(isinstance(case_id, str), "input manifest case_id is missing")
    input_hashes = _path_hashes(manifest)
    external_bindings = {
        "root_preflight_reader": _binding(reader_path, reader_sha256),
    }
    sources = _find_case_sources(manifest, input_hashes, case_id)
    metadata = _check_source_metadata(manifest, sources, input_hashes, reader_path, reader_sha256, case_id)
    external_bindings["qa031_execution_receipt"] = _binding(sources["qa_receipt_path"])
    external_bindings["partvtk"] = metadata["source_bindings"]["partvtk"]

    scan = _scan_csv(
        sources["csv_path"],
        metadata["expected"]["expected_total"],
        metadata["expected"]["expected_fluid"],
        sources["qa_row"].get("expected_fluid_envelope_m"),
        metadata["dp_m"],
    )
    continuum = metadata["continuum_reference_mass_kg"]
    native_mass = scan["native_fluid_mass_kg"]
    mass_difference = native_mass - continuum
    relative_difference = mass_difference / continuum
    weight = scan["native_particle_weight_kg"]
    weight_matches_xml_float32 = math.isclose(
        weight,
        metadata["xml_massfluid_float32_kg"],
        rel_tol=1e-6,
        abs_tol=1e-12,
    )
    weight_uniform = all(
        math.isclose(value, weight, rel_tol=0.0, abs_tol=1e-12)
        for value in scan["fluid_mass_values_kg"]
    )
    checks = {
        "genuine_gencase_counts_match_qa031_and_prepared_report": True,
        "native_particle_weight_read_from_actual_input": bool(weight_matches_xml_float32 and weight_uniform),
        "mass_difference_computed_by_worker": math.isfinite(mass_difference),
        "no_mass_rescaling": False if manifest.get("expected_identity", {}).get("mass_rescaling") is not False else True,
        **scan["checks"],
    }
    _require(all(checks[name] is True for name in REQUIRED_CHECK_NAMES), f"initial-state audit failed: {checks}")

    source_bindings = dict(metadata["source_bindings"])
    source_bindings["root_preflight_reader"] = external_bindings["root_preflight_reader"]
    source_bindings["qa031_execution_receipt"] = external_bindings["qa031_execution_receipt"]
    source_bindings["partvtk"] = external_bindings["partvtk"]
    source_bindings["input_manifest"] = _binding(input_manifest_path, _sha256(input_manifest_path))
    mass_document = {
        "schema": "ds02.stage1.f1.initial-mass-discrepancy.v2",
        "status": "actual_worker_computed",
        "case_id": case_id,
        "source_bindings": source_bindings,
        "checks": {
            "native_particle_weight_read_from_actual_input": True,
            "mass_difference_computed_by_worker": True,
            "no_mass_rescaling": True,
        },
        "native_particle_weight_kg": weight,
        "native_particle_weight_uniform": weight_uniform,
        "xml_massfluid_kg": metadata["xml_massfluid_kg"],
        "xml_massfluid_float32_kg": metadata["xml_massfluid_float32_kg"],
        "continuum_reference_mass_kg": continuum,
        "native_fluid_particle_count": scan["fluid_rows"],
        "native_fluid_mass_kg": native_mass,
        "mass_difference_kg": mass_difference,
        "relative_mass_difference": relative_difference,
        "mass_difference_definition": "math.fsum(actual QA031 official CSV fluid Mass [kg] values) - Root owner continuum reference mass",
        "mass_rescaling": False,
        "csv_mass_precision_note": "The official CSV is the existing QA031 Root preflight reader output; the worker computes these values from its bound rows and does not substitute a count prediction.",
    }
    physics_document = {
        "schema": "ds02.stage1.f1.physics-evidence.v2",
        "status": "actual_worker_computed",
        "case_id": case_id,
        "source_bindings": source_bindings,
        "checks": {"finite_state": checks["physics_finite_state"]},
        "summary": {
            "rows": scan["rows"],
            "fluid_rows": scan["fluid_rows"],
            "native_weight_kg": weight,
            "native_fluid_mass_kg": native_mass,
        },
    }
    geometry_document = {
        "schema": "ds02.stage1.f1.geometry-evidence.v2",
        "status": "actual_worker_computed",
        "case_id": case_id,
        "source_bindings": source_bindings,
        "checks": {"finite_state": checks["geometry_finite_state"]},
        "summary": {
            "rows": scan["rows"],
            "fluid_envelope_m": scan["fluid_envelope_m"],
            "qa_envelope_match": scan["qa_envelope_match"],
            "unique_particle_ids": scan["unique_particle_ids"],
        },
    }
    motion_document = {
        "schema": "ds02.stage1.f1.motion-evidence.v2",
        "status": "actual_worker_computed",
        "case_id": case_id,
        "source_bindings": source_bindings,
        "checks": {"finite_state": checks["motion_finite_state"]},
        "summary": {
            "max_initial_velocity_abs_m_per_s": scan["max_initial_velocity_abs_m_per_s"],
            "zero_velocity_tolerance_m_per_s": 1e-8,
        },
    }
    overlap_document = {
        "schema": "ds02.stage1.f1.no-overlap-finite-state-evidence.v2",
        "status": "actual_worker_computed",
        "case_id": case_id,
        "source_bindings": source_bindings,
        "checks": {
            "finite_state": checks["geometry_finite_state"],
            "no_initial_fluid_solid_overlap": checks["no_initial_fluid_solid_overlap"],
        },
        "summary": {
            "minimum_fluid_solid_center_distance_m": scan["minimum_fluid_solid_center_distance_m"],
            "overlap_threshold_m": scan["fluid_solid_overlap_threshold_m"],
            "overlap_pair_count": scan["fluid_solid_overlap_pair_count"],
            "definition": "A Type3 fluid center is overlapping a Type0 solid center when its center distance is below dp*(1-1e-6); no coordinates are written.",
        },
    }
    sidecar_documents = {
        "initial_mass_discrepancy_report": mass_document,
        "physics_evidence": physics_document,
        "geometry_evidence": geometry_document,
        "motion_evidence": motion_document,
        "no_overlap_finite_state_evidence": overlap_document,
    }
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_bindings: dict[str, dict[str, str]] = {}
    for name, document in sidecar_documents.items():
        sidecar_path = output_path.parent / f"{name}.json"
        _write_new_json(sidecar_path, document)
        sidecar_bindings[name] = _binding(sidecar_path)

    _source_still_bound(input_hashes)
    _require(_sha256(reader_path) == reader_sha256, "Root preflight reader changed during worker")
    _require(_sha256(sources["qa_receipt_path"]) == external_bindings["qa031_execution_receipt"]["sha256"], "QA031 execution receipt changed during worker")
    _require(_sha256(metadata["partvtk_path"]) == external_bindings["partvtk"]["sha256"], "PartVTK binary changed during worker")
    audit = {
        "schema": INPUT_CASES[case_id]["audit_schema"],
        "status": "completed",
        "returncode": 0,
        "worker": str(Path(__file__).resolve()),
        "case_id": case_id,
        "family_variant": INPUT_CASES[case_id]["family_variant"],
        "identity": {
            "case_id": case_id,
            "total_particles": metadata["expected"]["expected_total"],
            "fluid_particles": metadata["expected"]["expected_fluid"],
            "actual_3d": True,
            "continuum_reference_mass_kg": continuum,
        },
        "checks": checks,
        "mass_accounting": {
            "native_particle_weight_kg": weight,
            "native_fluid_mass_kg": native_mass,
            "continuum_reference_mass_kg": continuum,
            "mass_difference_kg": mass_difference,
            "relative_mass_difference": relative_difference,
            "mass_rescaling": False,
        },
        "reader_provenance": {
            "root_preflight_reader": metadata["source_bindings"]["root_preflight_reader"],
            "qa031_execution_receipt": metadata["source_bindings"]["qa031_execution_receipt"],
            "official_csv": metadata["source_bindings"]["official_csv"],
            "partvtk_binary": metadata["source_bindings"]["partvtk"],
            "worker_mode": "read_existing_QA031_official_CSV_streaming_no_subprocess",
        },
        "source_bindings": source_bindings,
        "sidecars": sidecar_bindings,
        "raw_arrays_written": False,
        "solver_launched": False,
        "gencase_launched": False,
        "partvtk_launched": False,
        "q_n": "not_granted",
        "production_approval": "none",
        "independent_case_count_increment": 0,
    }
    _write_new_json(output_path, audit)
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", required=True, type=Path)
    parser.add_argument("--reader-source", required=True, type=Path)
    parser.add_argument("--reader-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run(args.input_manifest, args.reader_source, args.reader_sha256, args.output)
    print(json.dumps({"status": result["status"], "case_id": result["case_id"], "output": str(args.output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as error:
        print(f"AUDIT_ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)


__all__ = ["AuditError", "run"]
