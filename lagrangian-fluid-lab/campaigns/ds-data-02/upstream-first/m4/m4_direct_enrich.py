#!/usr/bin/env python3
"""Enrich a completed direct-converter HDF5 into the M4 handoff contract.

The direct converter intentionally emits only the standard root HDF5 fields.  This
producer consumes that HDF5 plus its conversion report and the independent native
integrity/frame-scan receipts.  It creates a new HDF5 copy with the native
exclusion mask and endpoint transport datasets; the consumed direct-conversion
artifact is opened read-only and is never patched.

For a derivative child, ``--case-manifest`` and ``--semantic-diff`` are required.
They bind the generated child XML's physical depth and output recipe to a new
owner metadata record.  The official mother owner record is used as an immutable
base only; it is never reused as the child's physical-condition identity.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Mapping, Sequence

import h5py
import numpy as np

try:  # direct execution and package-style imports both work
    from m4_portable_adapter import M4Error, _sha256_array, _typed_identity_hash
except ImportError:  # pragma: no cover - package import fallback
    from .m4_portable_adapter import M4Error, _sha256_array, _typed_identity_hash


PRODUCER_SCHEMA = "ds-data-02.m4.direct-enrichment-producer.v1"
RECEIPT_SCHEMA = "ds-data-02.m4.direct-enrichment-receipt.v1"
DIRECT_REPORT_SCHEMA = "ds-data-02.bi4-direct-conversion.v1"
FRAME_SCAN_SCHEMA = "ds-data-02.upstream-first.native-frame-identity-scan.v1"
NATIVE_INTEGRITY_SCHEMA = "ds-data-02.upstream-first.f1-native-integrity.v1"
CHILD_MANIFEST_SCHEMA = "ds-data-02.upstream-first.m3.f1-fine-dp010-t025.case-manifest.v1"
SEMANTIC_DIFF_SCHEMA = "ds-data-02.upstream-first.m3.f1-fine-dp010-t025.semantic-diff.v1"
CASE_PREFIX = "UF_F1_MDBC_"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise M4Error(f"{label} is not a regular file: {path}")
    return path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M4Error(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise M4Error(f"{label} must be a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise M4Error(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, default=_json_default)
        stream.write("\n")


def _serialized_json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _binding(path: Path, *, relative: str | None = None) -> dict[str, Any]:
    path = _regular(path, "artifact")
    return {"path": relative or str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _as_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise M4Error(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise M4Error(f"{label} is not finite: {value!r}")
    return number


def _parse_xml_value(value: str | None) -> Any:
    if value is None:
        return None
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if any(token in value for token in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value


def _xml_element_payload(element: ET.Element | None) -> Any:
    if element is None:
        return None
    children = [_xml_element_payload(child) for child in element]
    result: dict[str, Any] = {"tag": element.tag, "attributes": dict(sorted(element.attrib.items()))}
    if element.text and element.text.strip():
        result["text"] = element.text.strip()
    if children:
        result["children"] = children
    return result


def _xml_evidence(path: Path) -> dict[str, Any]:
    path = _regular(path, "generated XML")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise M4Error(f"generated XML cannot be parsed: {path}") from exc
    geometry = root.find(".//geometry")
    if geometry is None:
        raise M4Error("generated XML has no geometry subtree")
    data2d = root.find(".//constants/data2d")
    if data2d is None or data2d.get("value") is None:
        raise M4Error("generated XML has no explicit constants/data2d dimension")
    dimension = 2 if data2d.get("value", "").lower() in {"1", "true", "yes"} else 3
    if dimension != 3:
        raise M4Error("M4 enrichment requires explicit three-dimensional generated XML")
    fillbox = root.find(".//geometry/commands/mainlist/fillbox")
    size = None if fillbox is None else fillbox.find("size")
    point = None if fillbox is None else fillbox.find("point")
    if fillbox is None or size is None or point is None or size.get("z") is None:
        raise M4Error("generated XML lacks the child fillbox point/size evidence")
    parameters = [
        {"key": item.get("key"), "value": item.get("value")}
        for item in root.findall(".//execution/parameters/parameter")
        if item.get("key") is not None
    ]
    parameter_map = {item["key"]: _parse_xml_value(item["value"]) for item in parameters}
    constants = {
        item.tag: {key: _parse_xml_value(value) for key, value in item.attrib.items()}
        for item in root.findall(".//constants/*")
    }
    user_vars = {
        item.get("name"): _parse_xml_value(item.get("value"))
        for item in root.findall(".//uservars/varnum")
        if item.get("name") is not None
    }
    particles = root.find(".//execution/particles")
    if particles is None:
        particles = root.find(".//particles")
    if particles is None or particles.get("np") is None:
        raise M4Error("generated XML lacks execution particle count")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "solver_dimension": dimension,
        "geometry_sha256": hashlib.sha256(ET.tostring(geometry, encoding="utf-8")).hexdigest(),
        "control_sha256": _canonical_hash(
            {
                "execution_parameters": parameters,
                "motion_xml": ET.tostring(root.find(".//motion"), encoding="unicode")
                if root.find(".//motion") is not None
                else None,
            }
        ),
        "fillbox": {
            "point": {key: _as_float(value, f"fillbox point {key}") for key, value in point.attrib.items()},
            "size": {key: _as_float(value, f"fillbox size {key}") for key, value in size.attrib.items()},
        },
        "execution_parameters": parameters,
        "parameter_map": parameter_map,
        "constants": constants,
        "user_vars": user_vars,
        "particle_count": int(particles.get("np")),
        "geometry_tree": _xml_element_payload(geometry),
    }


def _update_depth(value: Any, depth: float, mother_depth: float) -> Any:
    if isinstance(value, dict):
        result = {key: _update_depth(item, depth, mother_depth) for key, item in value.items()}
        return result
    if isinstance(value, list):
        return [_update_depth(item, depth, mother_depth) for item in value]
    return value


def _derive_child_owner(
    mother: Mapping[str, Any],
    generated_xml: Path,
    case_manifest: Mapping[str, Any],
    semantic_diff: Mapping[str, Any],
    *,
    manifest_path: Path,
    semantic_diff_path: Path,
    mother_sha256: str | None = None,
) -> dict[str, Any]:
    if case_manifest.get("schema") != CHILD_MANIFEST_SCHEMA:
        raise M4Error(f"unsupported child case manifest schema: {case_manifest.get('schema')!r}")
    if semantic_diff.get("schema") != SEMANTIC_DIFF_SCHEMA:
        raise M4Error(f"unsupported semantic diff schema: {semantic_diff.get('schema')!r}")
    case_id = case_manifest.get("case_id")
    if not isinstance(case_id, str) or not case_id.startswith(CASE_PREFIX):
        raise M4Error("child manifest case_id is outside the F1 upstream contract")
    comparisons = semantic_diff.get("comparisons")
    comparison = next(
        (item for item in comparisons if isinstance(item, Mapping) and item.get("case_id") == case_id),
        None,
    ) if isinstance(comparisons, list) else None
    if comparison is None:
        raise M4Error(f"semantic diff has no comparison for child {case_id}")
    physical = case_manifest.get("physical_axis")
    if not isinstance(physical, Mapping):
        raise M4Error("child manifest lacks physical_axis")
    depth = _as_float(physical.get("candidate_value_m"), "child physical_axis.candidate_value_m")
    allowed = physical.get("allowed_change")
    if not isinstance(allowed, Mapping) or _as_float(allowed.get("after"), "child allowed depth") != depth:
        raise M4Error("child manifest physical-axis change is incomplete")
    xml = _xml_evidence(generated_xml)
    xml_depth = _as_float(xml["fillbox"]["size"].get("z"), "generated XML fillbox depth")
    if not math.isclose(xml_depth, depth, rel_tol=0.0, abs_tol=1.0e-9):
        raise M4Error(f"generated XML depth {xml_depth} disagrees with child manifest depth {depth}")
    definition = case_manifest.get("definition")
    if not isinstance(definition, Mapping):
        raise M4Error("child manifest lacks definition binding")
    candidate_hash = comparison.get("candidate_sha256")
    definition_hash = definition.get("sha256")
    if candidate_hash and definition_hash and candidate_hash != definition_hash:
        raise M4Error("semantic diff candidate hash disagrees with child manifest definition hash")
    candidate_geometry = definition.get("geometry")
    if isinstance(candidate_geometry, Mapping) and candidate_geometry.get("fillbox_size_z_m") is not None:
        if not math.isclose(_as_float(candidate_geometry["fillbox_size_z_m"], "manifest fillbox depth"), depth, abs_tol=1.0e-9, rel_tol=0.0):
            raise M4Error("manifest definition geometry disagrees with physical-axis depth")
    owner = copy.deepcopy(dict(mother))
    params_before = owner.get("parameter_values")
    mother_depth = _as_float(
        params_before.get("initial_depth_m", physical.get("mother_value_m", depth))
        if isinstance(params_before, Mapping)
        else physical.get("mother_value_m", depth),
        "mother initial depth",
    )
    source_case_id = owner.get("case_id")
    owner["case_id"] = case_id
    owner["physical_case_id"] = case_id
    owner["condition_role"] = "m3_depth_child"
    owner["physical_condition_id"] = f"{case_id}:initial_fill_height_m={depth:.6f}"
    owner["source_mother"] = {
        "case_id": source_case_id,
        "owner_metadata_sha256": mother_sha256 or _canonical_hash(mother),
        "role": "immutable mother metadata base; not the child physical identity",
    }
    owner["definition_path"] = definition.get("path")
    owner["definition_sha256"] = definition_hash
    owner["recipe_id"] = f"m3_dp010_t025_{case_id}"
    owner["generated_xml"] = {
        "path": str(generated_xml.resolve()),
        "sha256": xml["sha256"],
        "geometry_sha256": xml["geometry_sha256"],
        "control_sha256": xml["control_sha256"],
        "fillbox": xml["fillbox"],
        "particle_count": xml["particle_count"],
    }
    owner["child_condition_binding"] = {
        "case_manifest": {"path": str(manifest_path.resolve()), "sha256": _sha256(manifest_path)},
        "semantic_diff": {"path": str(semantic_diff_path.resolve()), "sha256": _sha256(semantic_diff_path)},
        "physical_axis": {
            "name": physical.get("name"),
            "mother_value_m": physical.get("mother_value_m"),
            "candidate_value_m": depth,
            "path": physical.get("path"),
        },
        "candidate_definition_sha256": definition_hash,
        "generated_xml_sha256": xml["sha256"],
        "physical_condition_source": "M3 case manifest + semantic diff + generated child XML",
    }
    # The evaluated child XML binds the actual obstacle (0.66..0.82 in the
    # current F1 child), while the mother card carried a legacy separator range
    # (1.25..2.05). Replace those fields with XML-derived values and retain the
    # rounded GenCase fillbox as explicit evidence beside the physical reservoir.
    user = xml.get("user_vars", {})
    fill_point = xml["fillbox"]["point"]
    fill_size = xml["fillbox"]["size"]
    old_geometry = mother.get("geometry") if isinstance(mother.get("geometry"), Mapping) else {}
    geometry = {
        "tank": {
            "low_m": [user.get("DefTankpx", 0.0), user.get("DefTankpy", 0.0), user.get("DefTankpz", 0.0)],
            "size_m": [user.get("DefTanksx"), user.get("DefTanksy"), user.get("DefTanksz")],
            "label": "generated child tank envelope",
        },
        "central_obstacle": {
            "low_m": [user.get("Boxpx1"), user.get("Boxpy1"), 0.0],
            "size_m": [user.get("DefBoxsx"), user.get("DefBoxsy"), user.get("DefBoxsz")],
            "label": "generated child central obstacle envelope",
        },
        "initial_fluid_reservoir": copy.deepcopy(old_geometry.get("initial_fluid_reservoir", {})),
        "generated_fillbox": {
            "low_m": [fill_point.get("x"), fill_point.get("y"), fill_point.get("z")],
            "size_m": [fill_size.get("x"), fill_size.get("y"), fill_size.get("z")],
            "mkfluid": 0,
            "label": "evaluated GenCase fillbox; includes native rounding margin",
        },
    }
    reservoir = geometry["initial_fluid_reservoir"]
    if isinstance(reservoir, dict) and isinstance(reservoir.get("size_m"), list) and len(reservoir["size_m"]) == 3:
        reservoir["size_m"][2] = depth
    owner["geometry"] = geometry
    source_params = owner.get("parameter_values")
    params = dict(source_params) if isinstance(source_params, Mapping) else {}
    params.update(
        {
            "tank_length_m": user.get("DefTanksx"),
            "tank_width_m": user.get("DefTanksy"),
            "tank_height_m": user.get("DefTanksz"),
            "separator_start_x_m": user.get("Boxpx1"),
            "separator_end_x_m": user.get("Boxpx2"),
            "separator_y_m": user.get("Boxpy1"),
            "separator_thickness_m": user.get("DefBoxsx"),
            "separator_height_m": user.get("DefBoxsz"),
            "initial_depth_m": depth,
            "generated_fillbox_start_x_m": fill_point.get("x"),
            "generated_fillbox_length_m": fill_size.get("x"),
            "generated_fillbox_width_m": fill_size.get("y"),
            "generated_fillbox_depth_m": fill_size.get("z"),
        }
    )
    if isinstance(params.get("initial_fluid_volume_m3"), (int, float)) and mother_depth > 0:
        params["initial_fluid_volume_m3"] = float(params["initial_fluid_volume_m3"]) * depth / mother_depth
    owner["parameter_values"] = params
    binding = owner.get("physical_binding")
    if not isinstance(binding, dict):
        raise M4Error("mother owner metadata lacks explicit physical_binding.v1")
    binding["physical_case_id"] = case_id
    binding["geometry"] = copy.deepcopy(owner.get("geometry", binding.get("geometry", {})))
    binding_params = binding.get("parameters")
    if isinstance(binding_params, dict):
        binding_params.clear()
        binding_params.update(copy.deepcopy(params))
    initial_state = binding.get("initial_state")
    if isinstance(initial_state, dict):
        masses = initial_state.get("continuum_mass_by_source_kg")
        if isinstance(masses, dict) and mother_depth > 0:
            initial_state["continuum_mass_by_source_kg"] = {
                key: float(value) * depth / mother_depth if isinstance(value, (int, float)) else value
                for key, value in masses.items()
            }
        if isinstance(initial_state.get("initial_mass_total_kg"), (int, float)) and mother_depth > 0:
            initial_state["initial_mass_total_kg"] = float(initial_state["initial_mass_total_kg"]) * depth / mother_depth
    owner["physical_binding"] = binding
    owner["solver_parameters"] = dict(xml["parameter_map"])
    owner["event_window"] = copy.deepcopy(owner.get("event_window", binding.get("event_window", {})))
    owner["numerical_output_recipe"] = {
        "dp_m": _as_float(xml["constants"].get("dp", {}).get("value", 0.01), "child dp"),
        "time_max_s": xml["parameter_map"].get("TimeMax"),
        "time_out_s": xml["parameter_map"].get("TimeOut"),
        "role": "separate numerical/output-sampling recipe; not physical-axis equivalence",
    }
    return owner


def _identity_hashes(ids: np.ndarray, zones: np.ndarray) -> tuple[str, str]:
    return _sha256_array(ids, dtype="<u4"), _typed_identity_hash(zones, ids)


def prepare_child_owner(
    *,
    owner_metadata: Path,
    generated_xml: Path,
    case_manifest: Path,
    semantic_diff: Path,
    output: Path,
) -> dict[str, Any]:
    """Create the child owner record before direct conversion is launched.

    The direct converter must receive this output as its ``--owner-metadata``
    input, so the physical-condition hash is already present in the conversion
    report and HDF5 attributes.  The operation only reads the mother metadata,
    M3 evidence, and generated XML, and refuses to overwrite the output.
    """

    owner_path = _regular(owner_metadata, "owner metadata")
    xml_path = _regular(generated_xml, "generated XML")
    manifest_path = _regular(case_manifest, "child case manifest")
    diff_path = _regular(semantic_diff, "semantic diff")
    owner = _load_json(owner_path, "owner metadata")
    manifest = _load_json(manifest_path, "child case manifest")
    diff = _load_json(diff_path, "semantic diff")
    derived = _derive_child_owner(
        owner,
        xml_path,
        manifest,
        diff,
        manifest_path=manifest_path,
        semantic_diff_path=diff_path,
        mother_sha256=_sha256(owner_path),
    )
    output = output.expanduser().resolve()
    _write_json(output, derived)
    return {
        "schema": "ds-data-02.m4.child-owner-preparation.v1",
        "status": "prepared",
        "case_id": derived["case_id"],
        "output": _binding(output),
        "physical_condition_sha256": _canonical_hash(derived["physical_binding"]),
        "source_mother_sha256": _sha256(owner_path),
        "generated_xml_sha256": _sha256(xml_path),
        "case_manifest_sha256": _sha256(manifest_path),
        "semantic_diff_sha256": _sha256(diff_path),
        "direct_converter_binding": "pass this output as --owner-metadata before running ds_data02_direct_convert.py",
    }


def _validate_direct_report(
    report: Mapping[str, Any],
    source_hdf5: Path,
    source_hash: str,
    xml: Mapping[str, Any],
    owner_source_hash: str,
    owner_derived_hash: str,
    physical_condition_hash: str,
) -> tuple[int, int]:
    if report.get("schema") != DIRECT_REPORT_SCHEMA:
        raise M4Error(f"unexpected direct-converter report schema: {report.get('schema')!r}")
    if report.get("conversion_status") != "completed":
        raise M4Error("direct-converter report is not completed")
    if report.get("output_sha256") != source_hash:
        raise M4Error("direct-converter report does not bind the supplied HDF5")
    with h5py.File(source_hdf5, "r") as handle:
        if "time" not in handle or "particle_id" not in handle or "valid" not in handle:
            raise M4Error("direct HDF5 lacks standard converter axes")
        frame_count = int(handle["time"].shape[0])
        particle_count = int(handle["particle_id"].shape[0])
    if report.get("frames") is not None and int(report["frames"]) != frame_count:
        raise M4Error("direct report frame count disagrees with HDF5")
    if report.get("particles") is not None and int(report["particles"]) != particle_count:
        raise M4Error("direct report particle count disagrees with HDF5")
    dimension = report.get("solver_dimension")
    if isinstance(dimension, Mapping):
        dimension = dimension.get("solver_dimension")
    if dimension is not None and int(dimension) != 3:
        raise M4Error("direct report is not three-dimensional")
    typed_identity = report.get("typed_identity")
    if isinstance(typed_identity, Mapping) and typed_identity.get("key") != "(Zone,Idp)":
        raise M4Error("direct report does not bind the typed identity key")
    provenance = report.get("source_provenance")
    if isinstance(provenance, Mapping):
        generated = provenance.get("generated_xml")
        if isinstance(generated, Mapping) and generated.get("sha256") != xml["sha256"]:
            raise M4Error("direct report generated XML hash disagrees with supplied XML")
        for key in ("geometry_sha256", "geometry_reference_sha256"):
            if provenance.get(key) is not None and provenance[key] != xml["geometry_sha256"]:
                raise M4Error(f"direct report {key} disagrees with generated XML")
        for key in ("control_sha256", "control_reference_sha256"):
            if provenance.get(key) is not None and provenance[key] != xml["control_sha256"]:
                raise M4Error(f"direct report {key} disagrees with generated XML")
        owner = provenance.get("owner_metadata")
        if isinstance(owner, Mapping) and owner.get("sha256") not in {owner_source_hash, owner_derived_hash}:
            raise M4Error("direct report owner metadata hash is not one of the supplied/derived records")
    scopes = report.get("hash_scopes")
    if isinstance(scopes, Mapping) and scopes.get("physical_condition_sha256") is not None:
        if scopes["physical_condition_sha256"] != physical_condition_hash:
            raise M4Error("direct report physical-condition hash is not depth-specific to this handoff")
    time_evidence = report.get("time_evidence")
    if isinstance(time_evidence, Mapping):
        with h5py.File(source_hdf5, "r") as handle:
            times = np.asarray(handle["time"][:], dtype=np.float64)
        if time_evidence.get("first_s") is not None and not math.isclose(float(time_evidence["first_s"]), float(times[0]), abs_tol=1e-6, rel_tol=0.0):
            raise M4Error("direct report first time disagrees with HDF5")
        if time_evidence.get("last_s") is not None and not math.isclose(float(time_evidence["last_s"]), float(times[-1]), abs_tol=1e-6, rel_tol=0.0):
            raise M4Error("direct report last time disagrees with HDF5")
    return frame_count, particle_count


def _native_audit(
    integrity: Mapping[str, Any],
    scan: Mapping[str, Any],
    ids: np.ndarray,
    frame_count: int,
    *,
    case_id: str,
) -> dict[str, Any]:
    if integrity.get("schema") != NATIVE_INTEGRITY_SCHEMA or integrity.get("status") != "verified":
        raise M4Error("native integrity receipt is not verified")
    if scan.get("schema") != FRAME_SCAN_SCHEMA or scan.get("status") != "verified":
        raise M4Error("native full-frame scan is not verified")
    for evidence, label in ((integrity, "native integrity"), (scan, "native frame scan")):
        if evidence.get("case_id") not in {case_id, case_id.replace("_DP010_H050", "").replace("_DP010_H060", "")}:
            raise M4Error(f"{label} case_id disagrees with the enrichment case")
        if evidence.get("family_id") != "F1":
            raise M4Error(f"{label} is outside family F1")
    scan_identity = scan.get("identity_axis")
    scan_exclusions = scan.get("native_exclusions")
    if not isinstance(scan_identity, Mapping) or not isinstance(scan_exclusions, Mapping):
        raise M4Error("native frame scan lacks identity/exclusion evidence")
    if int(scan_identity.get("initial_count", -1)) != len(ids):
        raise M4Error("native scan initial count disagrees with direct HDF5")
    id_hash, _ = _identity_hashes(ids, np.zeros(len(ids), dtype=np.uint32))
    if scan_identity.get("initial_ids_sha256") != id_hash:
        raise M4Error("native scan initial Idp hash disagrees with direct HDF5")
    rows = integrity.get("native_rows")
    if not isinstance(rows, list):
        raise M4Error("native integrity lacks native_rows")
    native_ids: list[int] = []
    motives: dict[int, str] = {}
    times: dict[int, float] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise M4Error("native integrity row is not an object")
        try:
            idp = int(row["idp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise M4Error("native integrity row lacks integer idp") from exc
        if idp < 0 or idp > np.iinfo(np.uint32).max or idp in motives:
            raise M4Error("native integrity contains duplicate/negative excluded Idp")
        motive = row.get("motive")
        if not isinstance(motive, str) or not motive:
            raise M4Error("native integrity row lacks native numerical motive")
        native_ids.append(idp)
        motives[idp] = motive
        if row.get("part_out_time_s") is not None:
            times[idp] = _as_float(row["part_out_time_s"], "native exclusion time")
    native_ids_array = np.asarray(sorted(native_ids), dtype=np.uint32)
    if len(native_ids_array) != len(native_ids):
        raise M4Error("native integrity excluded Idp values are not unique")
    excluded_hash = _sha256_array(native_ids_array, dtype="<u4")
    expected_count = len(native_ids_array)
    for value, label in (
        (scan_identity.get("final_missing_count"), "scan final missing count"),
        (scan_exclusions.get("final_missing_count"), "scan exclusion count"),
        (scan_exclusions.get("record_count"), "scan exclusion record count"),
        (scan_exclusions.get("excluded_particles_runout"), "scan runout exclusion count"),
    ):
        if value is not None and int(value) != expected_count:
            raise M4Error(f"{label} disagrees with native integrity rows")
    for value, label in (
        (scan_identity.get("final_missing_ids_sha256"), "scan final missing Idp hash"),
        (scan_exclusions.get("id_set_sha256"), "scan exclusion Idp hash"),
    ):
        if value is not None and value != excluded_hash:
            raise M4Error(f"{label} disagrees with native integrity rows")
    continuity = integrity.get("count_continuity")
    if isinstance(continuity, Mapping):
        for key in ("initial_particles",):
            if continuity.get(key) is not None and int(continuity[key]) != len(ids):
                raise M4Error("native integrity initial count disagrees with direct HDF5")
        if continuity.get("excluded_particles") is not None and int(continuity["excluded_particles"]) != expected_count:
            raise M4Error("native integrity excluded count disagrees with rows")
    coverage = scan.get("coverage")
    if isinstance(coverage, Mapping) and coverage.get("frame_count") is not None and int(coverage["frame_count"]) != frame_count:
        raise M4Error("native scan frame count disagrees with direct HDF5")
    if scan.get("fatal_findings") not in (None, []):
        raise M4Error("native frame scan contains fatal findings")
    if scan_identity.get("physical_fate_inferred") is True or scan_exclusions.get("raw_native_fields_retained") is not True:
        raise M4Error("native scan does not preserve numerical censoring semantics")
    sorted_ids = np.sort(np.asarray(ids, dtype=np.uint32))
    if not np.all(np.isin(native_ids_array, sorted_ids)):
        raise M4Error("native exclusions contain Idp values outside the direct initial axis")
    positions = np.searchsorted(sorted_ids, native_ids_array)
    if not np.array_equal(sorted_ids[positions], native_ids_array):
        raise M4Error("native exclusion Idp values are not present in direct HDF5")
    return {
        "ids": native_ids_array,
        "motives": motives,
        "times": times,
        "ids_sha256": excluded_hash,
        "count": expected_count,
        "scan_identity": dict(scan_identity),
    }


def _copy_and_enrich_hdf5(
    source_path: Path,
    destination_path: Path,
    *,
    case_id: str,
    source_hash: str,
    report_hash: str,
    integrity_hash: str,
    scan_hash: str,
    physical_hash: str,
    native: Mapping[str, Any],
) -> dict[str, Any]:
    with h5py.File(source_path, "r") as source:
        if "native" in source or "transport" in source:
            raise M4Error("direct-converter HDF5 already contains M4 producer groups; refusing re-enrichment")
        required = {"time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk", "initial_type", "initial_mk", "initial_mass"}
        if not required.issubset(source.keys()):
            raise M4Error(f"direct HDF5 lacks standard converter fields: {sorted(required.difference(source.keys()))}")
        time_values = np.asarray(source["time"][:], dtype=np.float64)
        ids = np.asarray(source["particle_id"][:])
        zones = np.asarray(source["particle_zone"][:])
        valid_shape = (len(time_values), len(ids))
        if source["valid"].shape != valid_shape or ids.ndim != 1 or zones.shape != ids.shape:
            raise M4Error("direct HDF5 axes have incompatible shapes")
        if not np.isfinite(time_values).all() or not np.all(np.diff(time_values) > 0):
            raise M4Error("direct HDF5 time axis is not finite and increasing")
        if ids.dtype.kind not in "iu" or zones.dtype.kind not in "iu" or np.any(ids < 0) or np.any(zones < 0) or np.any(ids > np.iinfo(np.uint32).max) or np.any(zones > np.iinfo(np.uint32).max):
            raise M4Error("direct HDF5 identity fields are invalid")
        if len(np.unique(np.stack((zones.astype(np.int64), ids.astype(np.int64)), axis=1), axis=0)) != len(ids):
            raise M4Error("direct HDF5 typed identity axis contains duplicates")
        final_valid = np.asarray(source["valid"][-1, :], dtype=bool)
        if int((~final_valid).sum()) != int(native["count"]):
            raise M4Error("native exclusion count does not equal direct final validity mask")
        source_valid = np.asarray(source["valid"][0, :], dtype=bool)
        observed = np.ones(len(ids), dtype=bool)
        for frame in range(len(time_values)):
            observed &= np.asarray(source["valid"][frame, :], dtype=bool)
        order = np.argsort(ids.astype(np.uint64), kind="mergesort")
        sorted_ids = ids[order].astype(np.uint64, copy=False)
        excluded_ids = np.asarray(native["ids"], dtype=np.uint64)
        positions = np.searchsorted(sorted_ids, excluded_ids)
        if np.any(positions >= len(sorted_ids)) or not np.array_equal(sorted_ids[positions], excluded_ids):
            raise M4Error("native excluded Idp is absent from the direct HDF5 identity axis")
        exclusion = np.zeros(len(ids), dtype=bool)
        exclusion[order[positions]] = True
        if not np.array_equal(exclusion, ~final_valid):
            raise M4Error("native exclusion Idp set disagrees with direct final validity mask")
        source_position = np.asarray(source["position"][0, :, :], dtype=np.float32).copy()
        destination_position = np.asarray(source["position"][-1, :, :], dtype=np.float32).copy()
        if source_position.shape != (len(ids), 3) or destination_position.shape != (len(ids), 3):
            raise M4Error("direct HDF5 endpoint positions have the wrong shape")
        if np.any(source_valid & ~np.isfinite(source_position).all(axis=1)) or np.any(final_valid & ~np.isfinite(destination_position).all(axis=1)):
            raise M4Error("direct HDF5 valid endpoint position is non-finite")
        source_position[~source_valid] = np.nan
        destination_position[~final_valid] = np.nan
        displacement = np.full((len(ids), 3), np.nan, dtype=np.float32)
        pair_valid = source_valid & final_valid
        displacement[pair_valid] = destination_position[pair_valid] - source_position[pair_valid]
        source_labels = np.where(source_valid, "valid_source", "unknown").astype(object)
        destination_labels = np.where(final_valid, "valid_destination", "unknown").astype(object)
        reasons = np.full(len(ids), "not_excluded", dtype=object)
        exclusion_times = np.full(len(ids), np.nan, dtype=np.float64)
        for identity, motive in native["motives"].items():
            identity_position = np.searchsorted(sorted_ids, np.uint64(identity))
            if identity_position >= len(sorted_ids) or int(sorted_ids[identity_position]) != int(identity):
                raise M4Error("native motive identity is absent from direct HDF5")
            index = int(order[identity_position])
            reasons[index] = str(motive)
            if identity in native["times"]:
                exclusion_times[index] = float(native["times"][identity])
        string_dtype = h5py.string_dtype(encoding="utf-8")
        with h5py.File(destination_path, "w") as target:
            for key, value in source.attrs.items():
                target.attrs[key] = value
            for name in source.keys():
                source.copy(name, target)
            target.attrs["m4_enrichment_schema"] = PRODUCER_SCHEMA
            target.attrs["m4_enrichment_case_id"] = case_id
            target.attrs["m4_source_hdf5_sha256"] = source_hash
            target.attrs["m4_direct_report_sha256"] = report_hash
            target.attrs["m4_native_integrity_sha256"] = integrity_hash
            target.attrs["m4_native_frame_scan_sha256"] = scan_hash
            target.attrs["m4_physical_condition_sha256"] = physical_hash
            target.attrs["m4_source_mutated"] = False
            native_group = target.create_group("native")
            native_group.attrs["exclusion_semantics"] = "native numerical PartOut motive; physical fate remains UNKNOWN"
            native_group.attrs["physical_fate_inferred"] = False
            native_group.create_dataset("exclusion_mask", data=exclusion, compression="lzf")
            native_group.create_dataset("observed_all_frames", data=observed, compression="lzf")
            native_group.create_dataset("exclusion_reason", data=np.asarray(reasons, dtype=object), dtype=string_dtype)
            native_group.create_dataset("exclusion_time_s", data=exclusion_times)
            transport = target.create_group("transport")
            transport.attrs["semantics"] = "keyed numerical endpoint transport; no material trajectory or physical fate claim"
            transport.attrs["physical_fate_inferred"] = False
            transport.create_dataset("particle_id", data=ids)
            transport.create_dataset("particle_zone", data=zones)
            transport.create_dataset("source_valid", data=source_valid, compression="lzf")
            transport.create_dataset("destination_valid", data=final_valid, compression="lzf")
            transport.create_dataset("source_label", data=source_labels, dtype=string_dtype)
            transport.create_dataset("destination_label", data=destination_labels, dtype=string_dtype)
            transport.create_dataset("source_position", data=source_position, compression="lzf")
            transport.create_dataset("destination_position", data=destination_position, compression="lzf")
            transport.create_dataset("displacement", data=displacement, compression="lzf")
        return {
            "frames": len(time_values),
            "particles": len(ids),
            "source_valid_count": int(source_valid.sum()),
            "destination_valid_count": int(final_valid.sum()),
            "observed_all_frames_count": int(observed.sum()),
            "native_exclusion_count": int(exclusion.sum()),
        }


def _geometry_sidecar(owner: Mapping[str, Any], xml: Mapping[str, Any], case_id: str, physical_hash: str) -> dict[str, Any]:
    binding = owner.get("physical_binding") if isinstance(owner.get("physical_binding"), Mapping) else owner
    geometry = binding.get("geometry", owner.get("geometry"))
    if not isinstance(geometry, Mapping) or not geometry:
        raise M4Error("derived owner metadata has no geometry evidence")
    return {
        "schema": "ds-data-02.m4.geometry.v1",
        "case_id": case_id,
        "family_id": "F1",
        "solver_dimension": 3,
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "geometry_family_id": owner.get("geometry_family_id"),
        "geometry": geometry,
        "parameter_values": owner.get("parameter_values", binding.get("parameters", {})),
        "generated_xml_evidence": {
            "sha256": xml["sha256"],
            "geometry_sha256": xml["geometry_sha256"],
            "fillbox": xml["fillbox"],
            "geometry_tree": xml["geometry_tree"],
        },
        "physical_condition_sha256": physical_hash,
        "physical_fate_inferred": False,
    }


def _control_sidecar(owner: Mapping[str, Any], xml: Mapping[str, Any], case_id: str, physical_hash: str, semantic_diff: Mapping[str, Any] | None) -> dict[str, Any]:
    binding = owner.get("physical_binding") if isinstance(owner.get("physical_binding"), Mapping) else owner
    event_window = owner.get("event_window", binding.get("event_window"))
    if not isinstance(event_window, Mapping) or not event_window:
        raise M4Error("derived owner metadata has no event-window evidence")
    return {
        "schema": "ds-data-02.m4.control.v1",
        "case_id": case_id,
        "family_id": "F1",
        "control_family_id": owner.get("control_family_id"),
        "event_window": event_window,
        "solver_parameters": owner.get("solver_parameters", {}),
        "generated_execution_parameters": xml["execution_parameters"],
        "generated_constants": xml["constants"],
        "generated_xml_sha256": xml["sha256"],
        "control_sha256": xml["control_sha256"],
        "physical_condition_sha256": physical_hash,
        "semantic_diff": {
            "schema": semantic_diff.get("schema"),
            "status": semantic_diff.get("status"),
            "fixed_controls_excluding_output_schedule_sha256": semantic_diff.get("fixed_controls_excluding_output_schedule_sha256"),
        } if semantic_diff is not None else None,
        "physical_fate_inferred": False,
    }


def _source_receipt(role: str, path: Path) -> dict[str, Any]:
    item = _binding(path)
    return {"role": role, **item}


def enrich_direct(
    *,
    trajectory: Path,
    report: Path,
    generated_xml: Path,
    owner_metadata: Path,
    native_integrity: Path,
    frame_scan: Path,
    output_dir: Path,
    case_manifest: Path | None = None,
    semantic_diff: Path | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    trajectory = _regular(trajectory, "direct-converter HDF5")
    report = _regular(report, "direct-converter report")
    generated_xml = _regular(generated_xml, "generated XML")
    owner_metadata = _regular(owner_metadata, "owner metadata")
    native_integrity = _regular(native_integrity, "native integrity receipt")
    frame_scan = _regular(frame_scan, "native full-frame scan")
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() or output_dir.is_symlink():
        raise M4Error(f"refusing to overwrite enrichment output directory: {output_dir}")
    if case_manifest is not None and semantic_diff is None or case_manifest is None and semantic_diff is not None:
        raise M4Error("case_manifest and semantic_diff must be supplied together for a child")
    case_manifest_value = _load_json(case_manifest, "child case manifest") if case_manifest is not None else None
    semantic_diff_value = _load_json(semantic_diff, "semantic diff") if semantic_diff is not None else None
    owner_source = _load_json(owner_metadata, "owner metadata")
    owner_source_hash = _sha256(owner_metadata)
    xml = _xml_evidence(generated_xml)
    if case_manifest_value is not None:
        owner = _derive_child_owner(
            owner_source,
            generated_xml,
            case_manifest_value,
            semantic_diff_value or {},
            manifest_path=case_manifest,
            semantic_diff_path=semantic_diff,
            mother_sha256=owner_source_hash,
        )
        case_id = str(owner["case_id"])
        if owner_source.get("case_id") == case_id and owner_source.get("condition_role") == "m3_depth_child":
            # A prepared child owner is the direct converter's provenance input.
            # Re-derive only as a semantic check; preserve its original mother
            # lineage and exact file hash in the enrichment output.
            if _canonical_hash(owner_source.get("physical_binding")) != _canonical_hash(owner.get("physical_binding")):
                raise M4Error("prepared child owner physical binding disagrees with generated XML/M3 evidence")
            if owner_source.get("generated_xml", {}).get("sha256") != xml["sha256"]:
                raise M4Error("prepared child owner generated XML hash disagrees with supplied XML")
            owner = copy.deepcopy(owner_source)
    else:
        case_id = str(owner_source.get("case_id", ""))
        if not case_id.startswith(CASE_PREFIX):
            raise M4Error("owner metadata case_id is outside the F1 upstream contract")
        owner = copy.deepcopy(owner_source)
        owner["condition_role"] = owner.get("condition_role", "official_mother")
        owner["generated_xml"] = {"path": str(generated_xml), "sha256": xml["sha256"], "geometry_sha256": xml["geometry_sha256"], "control_sha256": xml["control_sha256"]}
    owner["case_id"] = case_id
    physical_binding = owner.get("physical_binding")
    if not isinstance(physical_binding, Mapping):
        raise M4Error("owner metadata must contain explicit physical_binding evidence")
    physical_condition_hash = _canonical_hash(physical_binding)
    report_value = _load_json(report, "direct-converter report")
    source_hash_before = _sha256(trajectory)
    with h5py.File(trajectory, "r") as source:
        ids = np.asarray(source["particle_id"][:])
        zones = np.asarray(source["particle_zone"][:])
        frame_count = int(source["time"].shape[0])
        particle_count = int(ids.shape[0])
    frame_count_report, particle_count_report = _validate_direct_report(
        report_value,
        trajectory,
        source_hash_before,
        xml,
        owner_source_hash,
        _serialized_json_hash(owner),
        physical_condition_hash,
    )
    if (frame_count_report, particle_count_report) != (frame_count, particle_count):
        raise M4Error("direct report and direct HDF5 dimensions disagree")
    integrity_value = _load_json(native_integrity, "native integrity receipt")
    scan_value = _load_json(frame_scan, "native frame scan")
    native = _native_audit(integrity_value, scan_value, ids, frame_count, case_id=case_id)
    temporary = output_dir.with_name(output_dir.name + f".partial-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise M4Error(f"stale partial enrichment output exists: {temporary}")
    temporary.mkdir(parents=True)
    try:
        enriched_path = temporary / "enriched.h5"
        owner_path = temporary / "owner-metadata.json"
        geometry_path = temporary / "geometry.json"
        control_path = temporary / "control.json"
        interface_path = temporary / "interface.json"
        receipt_path = temporary / "enrichment-receipt.json"
        owner["producer_record"] = {
            "schema": PRODUCER_SCHEMA,
            "source_direct_hdf5_sha256": source_hash_before,
            "source_direct_report_sha256": _sha256(report),
            "native_integrity_sha256": _sha256(native_integrity),
            "native_frame_scan_sha256": _sha256(frame_scan),
            "physical_condition_sha256": physical_condition_hash,
        }
        _write_json(owner_path, owner)
        geometry_value = _geometry_sidecar(owner, xml, case_id, physical_condition_hash)
        control_value = _control_sidecar(owner, xml, case_id, physical_condition_hash, semantic_diff_value)
        _write_json(geometry_path, geometry_value)
        _write_json(control_path, control_value)
        hdf_summary = _copy_and_enrich_hdf5(
            trajectory,
            enriched_path,
            case_id=case_id,
            source_hash=source_hash_before,
            report_hash=_sha256(report),
            integrity_hash=_sha256(native_integrity),
            scan_hash=_sha256(frame_scan),
            physical_hash=physical_condition_hash,
            native=native,
        )
        source_hash_after = _sha256(trajectory)
        if source_hash_after != source_hash_before:
            raise M4Error("direct-converter HDF5 changed during read-only enrichment")
        ids_hash, typed_hash = _identity_hashes(ids, zones)
        exclusion_mask = np.zeros(len(ids), dtype=bool)
        id_order = np.argsort(ids.astype(np.uint64), kind="mergesort")
        sorted_ids = ids[id_order].astype(np.uint64, copy=False)
        exclusion_mask[id_order[np.searchsorted(sorted_ids, native["ids"].astype(np.uint64))]] = True
        exclusion_typed_hash = _typed_identity_hash(zones[exclusion_mask], ids[exclusion_mask])
        source_receipts = [
            _source_receipt("direct_conversion_hdf5", trajectory),
            _source_receipt("direct_conversion_report", report),
            _source_receipt("generated_xml", generated_xml),
            _source_receipt("owner_metadata_input", owner_metadata),
            _source_receipt("native_integrity", native_integrity),
            _source_receipt("native_frame_scan", frame_scan),
            {"role": "derived_owner_metadata", **_binding(owner_path, relative="owner-metadata.json")},
        ]
        if case_manifest is not None and semantic_diff is not None:
            source_receipts.extend(
                (
                    _source_receipt("m3_child_case_manifest", case_manifest),
                    _source_receipt("m3_semantic_diff", semantic_diff),
                )
            )
        interface = {
            "schema": "ds-data-02.m4.native-conversion-interface.v1",
            "status": "normalized_verified",
            "family_id": "F1",
            "case_id": case_id,
            "source_mother": owner.get("source_mother", owner_source.get("case_id")),
            "condition_role": owner.get("condition_role"),
            "credit_status": "not_credited",
            "physical_fate_inferred": False,
            "normalized_hdf5": _binding(enriched_path, relative="enriched.h5"),
            "geometry": _binding(geometry_path, relative="geometry.json"),
            "control": _binding(control_path, relative="control.json"),
            "owner_metadata": _binding(owner_path, relative="owner-metadata.json"),
            "identity_axis": {
                "key": "(Zone,Idp)",
                "full_initial_identity": True,
                "all_frames_fixed_axis": True,
                "initial_particle_count": particle_count,
                "frame_count": frame_count,
                "initial_ids_sha256": ids_hash,
                "initial_typed_ids_sha256": typed_hash,
                "source": "direct-converter fixed initial identity axis plus native full-frame scan",
            },
            "exclusion_mask": {
                "status": "verified",
                "count": native["count"],
                "ids_sha256": native["ids_sha256"],
                "typed_ids_sha256": exclusion_typed_hash,
                "mask_dataset": "/native/exclusion_mask",
                "observed_all_frames_dataset": "/native/observed_all_frames",
                "reason_dataset": "/native/exclusion_reason",
                "time_dataset": "/native/exclusion_time_s",
                "native_scan_schema": FRAME_SCAN_SCHEMA,
                "native_integrity_schema": NATIVE_INTEGRITY_SCHEMA,
                "native_scan_path": str(frame_scan),
                "native_integrity_path": str(native_integrity),
                "motive_semantics": "native numerical PartOut motive; physical fate remains UNKNOWN",
                "physical_fate_inferred": False,
            },
            "native_exclusion": {
                "schema": "ds-data-02.m4.native-exclusion-evidence.v1",
                "status": "verified",
                "count": native["count"],
                "ids_sha256": native["ids_sha256"],
                "physical_fate": "UNKNOWN",
                "native_motive_values": sorted(set(native["motives"].values())),
                "scan_identity": native["scan_identity"],
                "physical_fate_inferred": False,
            },
            "endpoint_transport": {
                "schema": "ds-data-02.m4.endpoint-transport.v1",
                "source_frame": 0,
                "destination_frame": "last",
                "source_valid_label": "valid_source",
                "destination_valid_label": "valid_destination",
                "missing_endpoint_labels": ["unknown", "censored"],
                "physical_fate_inferred": False,
                "particle_id_dataset": "/transport/particle_id",
                "particle_zone_dataset": "/transport/particle_zone",
                "source_valid_dataset": "/transport/source_valid",
                "destination_valid_dataset": "/transport/destination_valid",
                "source_label_dataset": "/transport/source_label",
                "destination_label_dataset": "/transport/destination_label",
                "source_position_dataset": "/transport/source_position",
                "destination_position_dataset": "/transport/destination_position",
                "displacement_dataset": "/transport/displacement",
                "fate_label_policy": "invalid endpoints remain unknown or censored; no physical fate is assigned",
            },
            "conversion_report": _binding(report),
            "native_integrity": _binding(native_integrity),
            "native_frame_scan": _binding(frame_scan),
            "physical_condition": {
                "physical_condition_sha256": physical_condition_hash,
                "geometry_sha256": xml["geometry_sha256"],
                "control_sha256": xml["control_sha256"],
                "child_manifest_sha256": _sha256(case_manifest) if case_manifest is not None else None,
                "semantic_diff_sha256": _sha256(semantic_diff) if semantic_diff is not None else None,
                "generated_xml_sha256": xml["sha256"],
                "depth_m": owner.get("child_condition_binding", {}).get("physical_axis", {}).get("candidate_value_m") if isinstance(owner.get("child_condition_binding"), Mapping) else None,
            },
            "source_receipts": source_receipts,
            "producer": {
                "schema": PRODUCER_SCHEMA,
                "source_is_standard_direct_hdf5": True,
                "source_mutation": False,
                "scratch_policy": "destination-side partial directory only; no independent scientific scratch copy",
            },
        }
        _write_json(interface_path, interface)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "producer_schema": PRODUCER_SCHEMA,
            "status": "completed",
            "case_id": case_id,
            "condition_role": owner.get("condition_role"),
            "source": {
                "direct_hdf5": _binding(trajectory),
                "direct_report": _binding(report),
                "generated_xml": _binding(generated_xml),
                "owner_metadata_input": _binding(owner_metadata),
                "native_integrity": _binding(native_integrity),
                "native_frame_scan": _binding(frame_scan),
                "sha256_before": source_hash_before,
                "sha256_after": source_hash_after,
                "unchanged": True,
            },
            "outputs": {
                "enriched_hdf5": _binding(enriched_path, relative="enriched.h5"),
                "geometry": _binding(geometry_path, relative="geometry.json"),
                "control": _binding(control_path, relative="control.json"),
                "owner_metadata": _binding(owner_path, relative="owner-metadata.json"),
                "interface": _binding(interface_path, relative="interface.json"),
            },
            "native_exclusion": {
                "count": native["count"],
                "ids_sha256": native["ids_sha256"],
                "physical_fate": "UNKNOWN",
                "motive_semantics": "native numerical exclusion cause only",
            },
            "hdf5_summary": hdf_summary,
            "storage": {
                "source_bytes": trajectory.stat().st_size,
                "enriched_bytes": enriched_path.stat().st_size,
                "destination_copy_bytes": enriched_path.stat().st_size,
                "scratch_bytes_outside_destination": 0,
                "copy_policy": "one new HDF5 copy; source opened read-only",
            },
            "physical_condition": {
                "sha256": physical_condition_hash,
                "generated_xml_sha256": xml["sha256"],
                "child_manifest_sha256": _sha256(case_manifest) if case_manifest is not None else None,
                "semantic_diff_sha256": _sha256(semantic_diff) if semantic_diff is not None else None,
            },
            "elapsed_seconds": time.monotonic() - started,
            "credit_status": "not_credited",
            "physical_fate_inferred": False,
        }
        _write_json(receipt_path, receipt)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, output_dir)
        return receipt
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    enrich = commands.add_parser("enrich", help="enrich a completed direct-converter HDF5")
    enrich.add_argument("--trajectory", type=Path, required=True, help="completed standard direct-converter HDF5")
    enrich.add_argument("--report", type=Path, required=True)
    enrich.add_argument("--generated-xml", type=Path, required=True)
    enrich.add_argument("--owner-metadata", type=Path, required=True)
    enrich.add_argument("--native-integrity", type=Path, required=True)
    enrich.add_argument("--frame-scan", type=Path, required=True)
    enrich.add_argument("--case-manifest", type=Path, help="M3 child case manifest; required for H050/H060")
    enrich.add_argument("--semantic-diff", type=Path, help="M3 semantic diff; required with --case-manifest")
    enrich.add_argument("--output-dir", type=Path, required=True)
    prepare = commands.add_parser("prepare-owner", help="derive a child owner record before direct conversion")
    prepare.add_argument("--owner-metadata", type=Path, required=True)
    prepare.add_argument("--generated-xml", type=Path, required=True)
    prepare.add_argument("--case-manifest", type=Path, required=True)
    prepare.add_argument("--semantic-diff", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare-owner":
            receipt = prepare_child_owner(
                owner_metadata=args.owner_metadata,
                generated_xml=args.generated_xml,
                case_manifest=args.case_manifest,
                semantic_diff=args.semantic_diff,
                output=args.output,
            )
            print(json.dumps(receipt, sort_keys=True))
            return 0
        receipt = enrich_direct(
                trajectory=args.trajectory,
                report=args.report,
                generated_xml=args.generated_xml,
                owner_metadata=args.owner_metadata,
                native_integrity=args.native_integrity,
                frame_scan=args.frame_scan,
                output_dir=args.output_dir,
                case_manifest=args.case_manifest,
                semantic_diff=args.semantic_diff,
            )
    except (M4Error, OSError, ValueError, KeyError) as exc:
        print(f"M4 direct enrichment rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": receipt["status"], "case_id": receipt["case_id"], "output_dir": str(args.output_dir.resolve()), "native_exclusion_count": receipt["native_exclusion"]["count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
