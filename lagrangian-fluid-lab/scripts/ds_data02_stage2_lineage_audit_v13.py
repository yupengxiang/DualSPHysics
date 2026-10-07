#!/usr/bin/env python3
"""Build a source-bound CURRENT336 effective-condition audit.

This audit reads the CURRENT catalog and the small source closure named by
each row.  It parses XML control/geometry declarations, execution parameters,
owner condition hashes, receipts, resolution tokens, and saved-window headers.
It deliberately does not open or hash trajectory HDF5 payloads.  The output
is evidence for development review: observed support is finite and exact,
while interpolation, recovery equivalence, and split safety remain explicit
unknowns until their sources prove them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


AUDIT_SCHEMA = "ds02.stage2.current336-effective-lineage-audit.v13"
CARD_SCHEMA = "ds02.stage2.family-card.v13"
DEFAULT_CURRENT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
    "STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
)
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/lineage/v13"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
RESOLUTION_RE = re.compile(r"(?:^|[_-])DP(?P<token>[0-9]{3})(?:[_-]|$)", re.IGNORECASE)


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def json_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list) and len(value) <= 24 and all(
            isinstance(item, (str, int, float, bool)) or item is None for item in value):
        return value
    if isinstance(value, dict) and len(value) <= 16 and all(
            isinstance(key, str) and (isinstance(item, (str, int, float, bool)) or item is None)
            for key, item in value.items()):
        return {str(key): item for key, item in value.items()}
    return None


def _attrs(element: ET.Element) -> dict[str, str]:
    return {str(key): str(value) for key, value in sorted(element.attrib.items())}


def _nodes(root: ET.Element, names: set[str]) -> list[dict[str, Any]]:
    result = []
    for element in root.iter():
        if element.tag.lower() not in names:
            continue
        item: dict[str, Any] = {"tag": element.tag, "attrs": _attrs(element)}
        text = (element.text or "").strip()
        if text:
            item["text"] = text
        result.append(item)
    return result


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    tag_counts = Counter(element.tag.lower() for element in root.iter())
    parameters = [
        {"key": element.attrib.get("key"), "value": element.attrib.get("value"),
         "attrs": _attrs(element)}
        for element in root.iter()
        if element.tag.lower() == "parameter"
    ]
    parameter_map: dict[str, list[str | None]] = defaultdict(list)
    for item in parameters:
        parameter_map[str(item["key"])].append(item["value"])
    control_nodes = _nodes(root, {
        "begin", "mvrotfile", "mvlinfile", "mvpredef", "mvrectfile", "file",
        "move", "rotateaxis", "angularvelini", "acccentre", "accinput",
        "floating", "moving", "translationdof", "rotationdof", "massbody",
        "inertia", "center", "pointref",
    })
    geometry_nodes = _nodes(root, {
        "definition", "pointmin", "pointmax", "drawbox", "boxfill", "size",
        "point", "setmkbound", "setmkfluid", "layers", "setdrawmode",
        "setshapemode", "geometryfile", "extrude", "clipplane",
    })
    motion_tags = {item["tag"].lower() for item in control_nodes}
    if {"mvrotfile", "rotateaxis"} & motion_tags:
        control_class = "PRESCRIBED_ROTATION"
    elif {"mvpredef", "mvrectfile", "mvlinfile"} & motion_tags:
        control_class = "PRESCRIBED_FILE_MOTION"
    elif {"acccentre", "accinput"} & motion_tags:
        control_class = "ACCELERATION_DECLARATION"
    elif {"floating", "massbody", "angularvelini", "rotationdof"} & motion_tags:
        control_class = "RIGID_BODY_INITIAL_STATE"
    else:
        control_class = "STATIC_OR_UNFORCED_DECLARATION"
    motion_nodes = [item for item in control_nodes if item["tag"].lower() in {
        "begin", "mvrotfile", "mvlinfile", "mvpredef", "mvrectfile", "file",
        "move", "rotateaxis", "angularvelini", "acccentre", "accinput",
    }]
    definition_nodes = [item for item in geometry_nodes if item["tag"].lower() == "definition"]
    bounds = [item for item in geometry_nodes if item["tag"].lower() in {"pointmin", "pointmax"}]
    boxfills = [item for item in geometry_nodes if item["tag"].lower() == "boxfill"]
    control_payload = {
        "class": control_class,
        "parameters": parameters,
        "motion_nodes": motion_nodes,
        "tag_counts": dict(sorted(tag_counts.items())),
    }
    geometry_payload = {
        "definitions": definition_nodes,
        "bounds": bounds,
        "boxfills": boxfills,
        "nodes": geometry_nodes,
        "tag_counts": dict(sorted(tag_counts.items())),
    }
    dp_values = [item["attrs"].get("dp") for item in definition_nodes
                 if item["attrs"].get("dp") is not None]
    boxfill_modes = [item.get("text", "") for item in boxfills]
    return {
        "root_tag": root.tag,
        "tag_counts": dict(sorted(tag_counts.items())),
        "execution_parameter_count": len(parameters),
        "execution_parameter_keys": sorted(parameter_map),
        "execution_parameter_values": {key: values for key, values in sorted(parameter_map.items())},
        "control_class": control_class,
        "control_nodes": control_nodes,
        "control_signature_sha256": digest(control_payload),
        "motion_signature_sha256": digest(motion_nodes),
        "geometry_signature_sha256": digest(geometry_payload),
        "geometry_nodes": geometry_nodes,
        "definition_dp_values": dp_values,
        "bounds": bounds,
        "boxfill_modes": boxfill_modes,
        "boxfill_closed_boundary_candidate": bool({"bottom", "left", "right", "front", "back"} <= {
            token.strip() for mode in boxfill_modes for token in mode.split("|") if token.strip()
        }),
    }


def _walk_named(value: Any, names: set[str], path: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            current = f"{path}.{key}" if path else str(key)
            if str(key) in names:
                scalar = json_scalar(item)
                if scalar is not None:
                    found.append((current, scalar))
            found.extend(_walk_named(item, names, current))
    elif isinstance(value, list):
        for index, item in enumerate(value[:32]):
            found.extend(_walk_named(item, names, f"{path}[{index}]"))
    return found


OWNER_KEYS = {
    "physical_condition_sha256", "source_physical_condition_sha256",
    "source_plan_physical_condition_sha256", "canonical_physical_binding_sha256",
    "source_plan_sha256", "source_definition_sha256", "base_asset_sha256",
    "condition_id", "mechanism_id", "geometry_family_id", "control_family_id",
    "scope_id", "schema", "status", "condition_hash_semantics", "resolution",
    "motion_reader", "production_approval", "source_only", "metadata_closure_complete",
}
RECOVERY_KEYS = {
    "recovery", "recovery_provenance", "restart", "restart_provenance", "resume",
    "continuation", "checkpoint", "handoff", "restore", "recovery_status",
}


def owner_summary(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    matches = _walk_named(value, OWNER_KEYS)
    selected: dict[str, list[Any]] = defaultdict(list)
    paths: dict[str, list[str]] = defaultdict(list)
    for location, item in matches:
        key = location.rsplit(".", 1)[-1]
        if item not in selected[key]:
            selected[key].append(item)
        paths[key].append(location)
    recovery_matches = _walk_named(value, RECOVERY_KEYS)
    return {
        "schema": value.get("schema"),
        "selected_values": {key: values[:12] for key, values in sorted(selected.items())},
        "selected_paths": {key: values[:12] for key, values in sorted(paths.items())},
        "recovery_paths": [location for location, _ in recovery_matches[:24]],
        "recovery_values": [item for _, item in recovery_matches[:24]],
        "top_level_keys": sorted(value)[:80],
    }


def manifest_summary(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    names = {
        "schema", "case_id", "physical_case_id", "family_id", "physical_condition_sha256",
        "source_h5_sha256", "expected_frames", "expected_particles", "frames", "particles",
        "physical_window_s", "actual_time_s", "metadata_closure_complete",
        "actual_converter_physical_condition_sha256", "canonical_physical_binding_sha256",
        "canonical_source_scope_is_separate_from_actual_converter_scope", "relative_or_absolute_paths",
        "source_h5_read_only", "source_only", "production_status",
    }
    return {key: json_scalar(value.get(key)) for key in sorted(names) if key in value}


def receipt_summary(path: Path, expected_hashes: Iterable[str]) -> dict[str, Any]:
    value = json.loads(path.read_text())
    expected = {item for item in expected_hashes if isinstance(item, str)}
    launch = value.get("input_hashes_at_launch", {})
    finish = value.get("input_hashes_after_run", {})
    launch_values = set(launch.values()) if isinstance(launch, Mapping) else set()
    finish_values = set(finish.values()) if isinstance(finish, Mapping) else set()
    return {
        "schema": value.get("schema"),
        "status": value.get("status"),
        "returncode": value.get("returncode"),
        "runner_sha256": value.get("runner_sha256"),
        "input_hash_count_launch": len(launch) if isinstance(launch, Mapping) else None,
        "input_hash_count_finish": len(finish) if isinstance(finish, Mapping) else None,
        "expected_small_source_hashes_supported_at_launch": sorted(expected & launch_values),
        "expected_small_source_hashes_supported_at_finish": sorted(expected & finish_values),
        "source_hash_support_complete": bool(expected) and expected <= launch_values and expected <= finish_values,
    }


def source_item(role: str, item: Mapping[str, Any] | None, *, hash_h5: bool = False) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        return {"role": role, "status": "MISSING_BINDING"}
    path_value = item.get("path")
    if not isinstance(path_value, str):
        return {"role": role, "status": "MISSING_PATH", "declared_sha256": item.get("sha256")}
    path = Path(path_value).expanduser()
    expected = item.get("sha256") or item.get("recomputed_sha256") or item.get("producer_declared_sha256")
    record: dict[str, Any] = {"role": role, "path": str(path), "declared_sha256": expected}
    if not path.is_file():
        record["status"] = "MISSING_FILE"
        return record
    stat = path.stat()
    record.update({"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    if path.suffix.lower() in {".h5", ".hdf5"} and not hash_h5:
        record["status"] = "H5_STAT_ONLY_CONTENT_NOT_READ"
        return record
    actual = sha256(path)
    record.update({"recomputed_sha256": actual,
                   "status": "HASH_MATCH" if actual == expected else "HASH_MISMATCH"})
    return record


def _header_summary(case: Mapping[str, Any]) -> dict[str, Any]:
    header = case.get("header", {})
    fields = header.get("fields", {}) if isinstance(header, Mapping) else {}
    return {
        "identity_key": header.get("identity_key"),
        "coordinate_frame": header.get("coordinate_frame"),
        "units": header.get("units"),
        "conversion_complete": header.get("conversion_complete"),
        "fields": {
            key: {name: value for name, value in item.items()
                  if name in {"shape", "dtype", "chunks"}}
            for key, item in fields.items() if isinstance(item, Mapping)
        },
    }


def _numeric_parameters(case: Mapping[str, Any]) -> dict[str, Any]:
    value = case.get("known_numeric_physical_parameters", {})
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in sorted(value.items())
            if isinstance(item, (int, float)) and not isinstance(item, bool)}


def _resolution_tokens(case: Mapping[str, Any], xml: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for text in (case.get("runtime_case_alias"), case.get("physical_case_id"), case.get("manifest_physical_case_id")):
        if isinstance(text, str):
            match = RESOLUTION_RE.search(text)
            if match:
                values.append(match.group("token"))
    values.extend(str(item) for item in case.get("resolution_token_evidence", []) if item is not None)
    return sorted(set(values))


def _manifest_identity_match(
    case: Mapping[str, Any], manifest: Mapping[str, Any]
) -> tuple[bool, dict[str, list[str]]]:
    """Match either explicit manifest identity axis without flattening aliases."""
    catalog_ids = {
        str(value) for value in (
            case.get("runtime_case_alias"), case.get("physical_case_id"),
            case.get("manifest_physical_case_id"),
        ) if isinstance(value, str)
    }
    manifest_ids = {
        str(value) for value in (manifest.get("case_id"), manifest.get("physical_case_id"))
        if isinstance(value, str)
    }
    manifest_family = manifest.get("family_id")
    if manifest_family is None:
        family_status = "UNDECLARED_MANIFEST_FAMILY; ID_MATCH_ONLY"
    elif manifest_family == case.get("family_id"):
        family_status = "MATCH"
    else:
        family_status = "MISMATCH"
    return bool(catalog_ids & manifest_ids) and family_status != "MISMATCH", {
        "catalog_declared_ids": sorted(catalog_ids),
        "manifest_declared_ids": sorted(manifest_ids),
        "matched_ids": sorted(catalog_ids & manifest_ids),
        "family_status": family_status,
    }


def _selected_owner_hashes(owner: Mapping[str, Any]) -> dict[str, list[str]]:
    selected = owner.get("selected_values", {})
    result: dict[str, list[str]] = {}
    for key in ("physical_condition_sha256", "source_physical_condition_sha256",
                "source_plan_physical_condition_sha256", "canonical_physical_binding_sha256",
                "source_plan_sha256", "source_definition_sha256", "base_asset_sha256"):
        values = selected.get(key, []) if isinstance(selected, Mapping) else []
        result[key] = [str(item) for item in values if isinstance(item, str) and HASH_RE.fullmatch(item)]
    return result


def audit_case(index: int, case: Mapping[str, Any]) -> dict[str, Any]:
    source = case.get("source_bindings", {})
    manifest_binding = case.get("manifest", {})
    xml_binding = source.get("generated_xml", {})
    xml_path = Path(xml_binding.get("path", "")).expanduser()
    xml = parse_xml(xml_path)
    manifest_path = Path(manifest_binding.get("path", "")).expanduser()
    owner_binding = source.get("owner_metadata", {})
    owner_path = Path(owner_binding.get("path", "")).expanduser()
    manifest = manifest_summary(manifest_path)
    owner = owner_summary(owner_path)
    expected_receipt_hashes = [xml_binding.get("sha256")]
    gencase_binding = source.get("gencase_receipt", {})
    solver_binding = source.get("solver_receipt", {})
    gencase_path = Path(gencase_binding.get("path", "")).expanduser()
    solver_path = Path(solver_binding.get("path", "")).expanduser()
    source_hashes = {
        role: source_item(role, item)
        for role, item in {
            "manifest": manifest_binding,
            "xmf": case.get("xmf"),
            "conversion_report": case.get("conversion_report"),
            **{str(role): value for role, value in source.items()},
        }.items()
    }
    small_source_hashes = {
        role: record for role, record in source_hashes.items()
        if role not in {"trajectory", "trajectory_h5", "output_h5"}
    }
    receipt_hashes = {
        "gencase": receipt_summary(gencase_path, expected_receipt_hashes),
        "solver": receipt_summary(solver_path, expected_receipt_hashes),
    }
    small_hash_complete = bool(small_source_hashes) and all(
        item.get("status") == "HASH_MATCH" for item in small_source_hashes.values())
    solver_receipt_support = bool(receipt_hashes["solver"].get("source_hash_support_complete"))
    all_receipt_support = all(item.get("source_hash_support_complete") for item in receipt_hashes.values())
    receipt_support = solver_receipt_support
    owner_hashes = _selected_owner_hashes(owner)
    manifest_condition_hashes = [str(manifest[key]) for key in (
        "physical_condition_sha256", "actual_converter_physical_condition_sha256",
        "canonical_physical_binding_sha256")
        if isinstance(manifest.get(key), str) and HASH_RE.fullmatch(manifest[key])]
    explicit_link_values = {
        key: values for key, values in owner_hashes.items() if values
    }
    for key in ("condition_id", "mechanism_id", "geometry_family_id", "control_family_id", "scope_id"):
        values = owner.get("selected_values", {}).get(key, []) if isinstance(owner.get("selected_values"), Mapping) else []
        if values:
            explicit_link_values[key] = values[:12]
    owner_condition_hashes = owner_hashes.get("physical_condition_sha256", [])
    condition_status = "EXPLICIT_OWNER_OR_MANIFEST_CONDITION_HASH" if (owner_condition_hashes or manifest_condition_hashes) else "CATALOG_NUMERIC_ONLY"
    recovery_paths = owner.get("recovery_paths", [])
    manifest_identity_match, manifest_identity_evidence = _manifest_identity_match(case, manifest)
    manifest_trajectory_sha_match = (
        manifest.get("source_h5_sha256") == case.get("trajectory", {}).get("producer_declared_sha256")
    )
    recovery_status = "EXPLICIT_RECOVERY_OR_RESTART_KEY_PRESENT" if recovery_paths else "UNKNOWN_NO_EXPLICIT_RECOVERY_PROVENANCE"
    source_status = "SMALL_SOURCE_HASH_CLOSURE_COMPLETE" if small_hash_complete else "SMALL_SOURCE_HASH_CLOSURE_INCOMPLETE"
    if not all_receipt_support:
        source_status += "; gencase receipt input hash support incomplete"
    if not solver_receipt_support:
        source_status += "; solver receipt input hash support incomplete"
    if not manifest_identity_match:
        source_status += "; manifest identity mismatch"
    if not manifest_trajectory_sha_match:
        source_status += "; manifest H5 producer hash mismatch"
    physical_alias = case.get("accepted_alias_evidence")
    resolution = {
        "tokens": _resolution_tokens(case, xml),
        "xml_dp_values": xml.get("definition_dp_values", []),
        "header_particles": case.get("particles"),
        "header_frame_count": case.get("frames"),
        "status": "OBSERVED_XML_DP_HEADER_SHAPE; CROSS_RESOLUTION_SUPPORT_UNKNOWN",
    }
    control = {
        "class": xml["control_class"],
        "signature_sha256": xml["control_signature_sha256"],
        "motion_signature_sha256": xml["motion_signature_sha256"],
        "execution_parameter_count": xml["execution_parameter_count"],
        "execution_parameter_keys": xml["execution_parameter_keys"],
        "motion_nodes": xml["control_nodes"],
        "source_hash_bound": bool(small_hash_complete and receipt_support),
        "status": "SOURCE_HASH_BOUND_XML_CONTROL_PARSED; PHYSICAL_TEMPLATE_EQUIVALENCE_REVIEWED_SEPARATELY",
    }
    geometry = {
        "signature_sha256": xml["geometry_signature_sha256"],
        "definition_dp_values": xml["definition_dp_values"],
        "bounds": xml["bounds"],
        "boxfill_modes": xml["boxfill_modes"],
        "closed_boundary_candidate": xml["boxfill_closed_boundary_candidate"],
        "source_hash_bound": small_hash_complete,
        "status": "SOURCE_HASH_BOUND_XML_GEOMETRY_PARSED; CLOSED_OPEN_AND_DESTINATION_SEMANTICS_REQUIRE_PHYSICAL_REVIEW",
    }
    condition_payload = {
        "family_id": case.get("family_id"),
        "physical_case_id": case.get("physical_case_id"),
        "catalog_numeric": _numeric_parameters(case),
        "owner_condition_hashes": owner_condition_hashes,
        "manifest_condition_hashes": manifest_condition_hashes,
        "accepted_alias_evidence": physical_alias,
    }
    return {
        "case_index": index,
        "family_id": case.get("family_id"),
        "physical_case_id": case.get("physical_case_id"),
        "runtime_case_alias": case.get("runtime_case_alias"),
        "manifest_physical_case_id": case.get("manifest_physical_case_id"),
        "frames": case.get("frames"),
        "particles": case.get("particles"),
        "actual_time_window_s": case.get("actual_time_window_s"),
        "known_numeric_physical_parameters": _numeric_parameters(case),
        "header": _header_summary(case),
        "source_hash_evidence": source_hashes,
        "source_closure": {
            "status": source_status,
            "manifest_identity_match": manifest_identity_match,
            "manifest_identity_evidence": manifest_identity_evidence,
            "manifest_trajectory_sha_match": manifest_trajectory_sha_match,
            "trajectory": source_item("trajectory_h5", case.get("trajectory")),
            "receipt_support": receipt_hashes,
            "solver_receipt_source_hash_support": solver_receipt_support,
            "all_receipt_source_hash_support": all_receipt_support,
        },
        "identity": {
            "key": case.get("header", {}).get("identity_key"),
            "coordinate_frame": case.get("header", {}).get("coordinate_frame"),
            "accepted_alias_evidence": physical_alias,
            "status": "CURRENT_IDENTITY_AND_ALIAS_SCOPES_PRESERVED_SEPARATELY",
        },
        "effective_condition": {
            "condition_signature_sha256": digest(condition_payload),
            "catalog_numeric_parameters": _numeric_parameters(case),
            "owner_condition_hashes": owner_condition_hashes,
            "manifest_condition_hashes": manifest_condition_hashes,
            "owner_selected_values": owner.get("selected_values", {}),
            "condition_status": condition_status,
            "status": "SOURCE_BOUND_OBSERVED_CONDITION; VALIDITY_OUTSIDE_EXACT_SOURCE_UNPROVEN",
        },
        "control": control,
        "geometry": geometry,
        "resolution": resolution,
        "window": {
            "frames": case.get("frames"),
            "actual_time_window_s": case.get("actual_time_window_s"),
            "manifest_window": manifest.get("physical_window_s", manifest.get("actual_time_s")),
            "status": "CURRENT_SAVED_WINDOW_BOUND; CROSS_CASE_TIME_COMPATIBILITY_UNKNOWN",
        },
        "recovery": {
            "status": recovery_status,
            "evidence_paths": recovery_paths,
            "evidence_values": owner.get("recovery_values", []),
        },
        "parameter_support": {
            "catalog_values": _numeric_parameters(case),
            "owner_values": owner.get("selected_values", {}),
            "status": "FINITE_OBSERVED_SUPPORT_ONLY; NO_INTERPOLATION_OR_EXTRAPOLATION_CLAIM",
        },
        "lineage": {
            "explicit_link_values": explicit_link_values,
            "conservative_family_group": f"family:{case.get('family_id')}",
            "status": "PROVISIONAL_CONSERVATIVE_FAMILY_GROUP; PHYSICAL/CONTROL CONNECTIVITY NOT SPLIT_SAFE",
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "development_only": True,
    }


def _unique(values: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def family_card(family: str, cases: list[dict[str, Any]], *, audit_path: str) -> dict[str, Any]:
    def counts(path: str) -> dict[str, int]:
        counter = Counter()
        for case in cases:
            item: Any = case
            for part in path.split("."):
                item = item.get(part, {}) if isinstance(item, Mapping) else {}
            counter[str(item)] += 1
        return dict(sorted(counter.items(), key=lambda pair: (-pair[1], pair[0])))

    numeric_keys = sorted({key for case in cases for key in case["known_numeric_physical_parameters"]})
    numeric_values = {
        key: sorted(_unique(case["known_numeric_physical_parameters"].get(key)
                          for case in cases if key in case["known_numeric_physical_parameters"]))
        for key in numeric_keys
    }
    dp_values = sorted(_unique(value for case in cases for value in case["resolution"]["xml_dp_values"]))
    token_values = sorted(_unique(value for case in cases for value in case["resolution"]["tokens"]))
    condition_hash_count = sum(bool(case["effective_condition"]["owner_condition_hashes"] or
                                   case["effective_condition"]["manifest_condition_hashes"])
                               for case in cases)
    source_complete = sum(case["source_closure"]["status"].startswith("SMALL_SOURCE_HASH_CLOSURE_COMPLETE")
                          for case in cases)
    explicit_recovery = sum(case["recovery"]["status"].startswith("EXPLICIT") for case in cases)
    shared_tokens = Counter()
    for case in cases:
        for key, values in case["lineage"]["explicit_link_values"].items():
            for value in values:
                shared_tokens[f"{key}:{value}"] += 1
    return {
        "schema": CARD_SCHEMA,
        "family_id": family,
        "case_count": len(cases),
        "status": "DEVELOPMENT_ONLY_EFFECTIVE_EVIDENCE; QUALIFICATION_UNKNOWN",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "evidence_index": audit_path,
        "effective_evidence": {
            "small_source_hash_closure_complete_count": source_complete,
            "xml_control_parsed_count": len(cases),
            "xml_geometry_parsed_count": len(cases),
            "explicit_condition_hash_count": condition_hash_count,
            "explicit_recovery_provenance_count": explicit_recovery,
            "control_class_counts": counts("control.class"),
            "control_signature_counts": counts("control.signature_sha256"),
            "geometry_signature_counts": counts("geometry.signature_sha256"),
            "resolution_dp_counts": counts("resolution.xml_dp_values"),
            "lineage_shared_explicit_tokens": {key: value for key, value in sorted(shared_tokens.items()) if value > 1},
        },
        "observed_support": {
            "numeric_parameter_values": numeric_values,
            "resolution_dp_values": dp_values,
            "resolution_tokens": token_values,
            "frame_counts": sorted(_unique(case["frames"] for case in cases)),
            "particle_count_range": [min(case["particles"] for case in cases), max(case["particles"] for case in cases)],
            "time_window_range_s": [
                min(case["actual_time_window_s"][0] for case in cases),
                max(case["actual_time_window_s"][1] for case in cases),
            ],
            "support_claim": "observed finite values only; no interpolation/extrapolation or cross-resolution equivalence",
        },
        "lineage": {
            "conservative_group": f"family:{family}",
            "explicit_shared_token_count": sum(value > 1 for value in shared_tokens.values()),
            "split_status": "PROVISIONAL_ONLY; unknown physical/control/template links remain in one conservative family group",
        },
        "closure": {
            "identity_and_source": "SMALL_SOURCE_HASH_CLOSURE_RECORDED; H5 CONTENT HASH/PRIMARY REPLAY SEPARATE",
            "control": "XML CONTROL AND EXECUTION PARAMETERS PARSED PER CASE; SEMANTIC SUPPORT DOMAIN STILL DEVELOPMENT",
            "geometry": "XML BOUNDS/DEFINITION/BOXFILL PARSED PER CASE; RECEIVER/OPENING/DESTINATION EQUIVALENCE NOT INFERRED",
            "physical_condition": "CATALOG NUMERIC VALUES AND OWNER/MANIFEST HASHES RETAINED; VALIDITY DOMAIN NOT CLAIMED",
            "parameter_support": "FINITE OBSERVED SUPPORT ONLY",
            "resolution": "XML DP AND HEADER SHAPE OBSERVED; RESOLUTION/RECOVERY SUPPORT EQUIVALENCE UNKNOWN",
            "recovery": "EXPLICIT PROVENANCE COUNTED; ABSENCE REMAINS UNKNOWN",
            "window": "CURRENT FRAME/TIME WINDOW BOUND; CROSS-CASE COMPARABILITY UNKNOWN",
            "split": "CONSERVATIVE FAMILY GROUP ONLY; NOT SPLIT-SAFE",
        },
        "unknown_scope": [
            "interpolation/extrapolation outside observed numeric support",
            "recovery/restart equivalence and missing-frame semantics",
            "closed/open/receiver destination equivalence unless separately geometry-bound",
            "cross-resolution support and particle-level transfer",
            "prospective split leakage safety across common controls, templates, and physical conditions",
            "QI/QN/QE qualification and reference-result validity",
        ],
        "failure_or_rejection_conditions": [
            "CURRENT/source SHA, identity, or header shape mismatch",
            "missing or mismatched XML/manifest/receipt/owner source closure",
            "using latest glob, arbitrary Run.out, or fixed legacy case list",
            "claiming support beyond listed finite observed values",
            "using conservative family group as split-safe evidence",
            "granting QI/QN/QE or hidden-test status",
        ],
        "physical_case_ids": [case["physical_case_id"] for case in cases],
    }


def build_audit(current_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current = json.loads(current_path.read_text())
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise ValueError("CURRENT catalog must contain exactly 336 cases")
    audited = [audit_case(index, row) for index, row in enumerate(rows)]
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in audited:
        by_family[str(row["family_id"])].append(row)
    cards: dict[str, dict[str, Any]] = {}
    audit_name = "../CURRENT336-effective-lineage-audit-v13.json"
    for family, cases in sorted(by_family.items()):
        cards[family] = family_card(family, cases, audit_path=audit_name)
    family_summary = {
        family: {
            "family_id": family,
            "case_count": len(cases),
            "case_indices": [case["case_index"] for case in cases],
            "control_classes": dict(Counter(case["control"]["class"] for case in cases)),
            "geometry_signatures": dict(Counter(case["geometry"]["signature_sha256"] for case in cases)),
            "small_source_status": dict(Counter(case["source_closure"]["status"] for case in cases)),
            "condition_status": dict(Counter(case["effective_condition"]["condition_status"] for case in cases)),
            "recovery_status": dict(Counter(case["recovery"]["status"] for case in cases)),
            "split_status": "PROVISIONAL_CONSERVATIVE_FAMILY_GROUP",
        }
        for family, cases in sorted(by_family.items())
    }
    audit = {
        "schema": AUDIT_SCHEMA,
        "catalog_path": str(current_path.resolve()),
        "catalog_sha256": sha256(current_path),
        "catalog_schema": current.get("schema"),
        "case_count": len(audited),
        "family_count": len(by_family),
        "review_status": "EFFECTIVE_SOURCE_EVIDENCE_RECORDED; SEMANTIC SUPPORT/RECOVERY/SPLIT CLOSURE DEVELOPMENT_PENDING",
        "source_scope": "CURRENT336 plus per-case small XML/manifest/XMF/conversion/receipt/owner inputs; HDF5 stat only, no trajectory content read",
        "rules": {
            "identity": "CURRENT (Zone,Idp) header identity and accepted alias provenance remain separate; alias evidence is never flattened",
            "control": "XML control nodes and execution parameter values are parsed per case; F2/F7 prescribed motion, F3 acceleration, F5 file motion, F6 rigid initial state are distinct classes",
            "geometry": "XML definition/bounds/boxfill signatures are source-hash bound; boxfill presence does not by itself grant receiver/destination semantics",
            "condition": "catalog numeric values and owner/manifest physical-condition hashes are retained as separate evidence scopes",
            "support": "only finite observed values are enumerated; no interpolation, extrapolation, or cross-resolution equivalence is claimed",
            "recovery": "explicit recovery/restart/checkpoint keys are counted; absent evidence stays UNKNOWN",
            "source": "no latest glob, arbitrary Run.out, fixed legacy list, or H5 content read is used",
            "split": "explicit shared tokens are reported, but all unknown links stay in conservative family groups; no split-safe claim",
            "qualification": "all QI/QN/QE remain UNKNOWN and all rows are DEVELOPMENT",
        },
        "families": family_summary,
        "cases": audited,
        "family_cards": {family: f"F{family[1:]}-family-card-v13.json" for family in sorted(by_family)},
        "unresolved_catalog": current.get("unresolved"),
    }
    audit["sha256"] = digest(audit)
    return audit, cards


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    audit, cards = build_audit(args.current.expanduser())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = args.output_dir / "CURRENT336-effective-lineage-audit-v13.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    for family, card in cards.items():
        path = args.output_dir / f"{family}-family-card-v13.json"
        path.write_text(json.dumps(card, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"audit": str(audit_path), "case_count": audit["case_count"],
                      "families": sorted(cards), "audit_sha256": audit["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
