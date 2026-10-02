#!/usr/bin/env python3
"""Decode the completed DP005 native exclusion ledgers and compare mothers.

This is a read-only post-solver diagnostic.  It invokes the official
``PartVTKOut_linux64`` tool for each completed DP005 case and records every
excluded identity with its native PartOut index, RunPARTs time, position,
velocity, density, Motive, and a typed-identity lookup from the generated XML
summary.  It then compares the actual DP005 XML/motion geometry and control
against the registered RV4 reference source.  A source-side claim that a view
is a finer numerical member is kept separate from the measured comparison;
physical spill is never inferred from Motive or position alone.

The script only writes a new diagnostic attempt and never edits solver data,
source XML, BI4 files, requests, or historical reports.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping


FAMILY_ROOT = Path(__file__).resolve().parent
DIAGNOSTIC_HELPER = FAMILY_ROOT / "f2_native_resolution_diagnostic.py"
FLOAT_PAIR = re.compile(
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?);"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)"
)


class DiagnosticError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DiagnosticError(f"{label} is not an object: {path}")
    return value


def canonical_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def import_helper() -> Any:
    spec = importlib.util.spec_from_file_location("f2_native_resolution_diagnostic", DIAGNOSTIC_HELPER)
    if spec is None or spec.loader is None:
        raise DiagnosticError(f"cannot import diagnostic helper: {DIAGNOSTIC_HELPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _attrs(node: ET.Element, keys: Iterable[str]) -> dict[str, str]:
    return {key: str(node.attrib[key]) for key in keys if key in node.attrib}


def geometry_signature(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise DiagnosticError(f"generated XML lacks geometry mainlist: {xml_path}")
    current_kind: str | None = None
    current_mk: int | None = None
    boundary: list[dict[str, Any]] = []
    fluid: list[dict[str, Any]] = []
    for node in mainlist:
        tag = str(node.tag).split("}")[-1]
        if tag == "setmkbound":
            current_kind, current_mk = "bound", int(node.attrib["mk"])
        elif tag == "setmkfluid":
            current_kind, current_mk = "fluid", int(node.attrib["mk"])
        elif tag != "drawbox" or current_kind is None or current_mk is None:
            continue
        point = node.find("./point")
        size = node.find("./size")
        if point is None or size is None:
            continue
        record = {
            "kind": current_kind,
            "mk": current_mk,
            "boxfill": (node.findtext("./boxfill") or "").strip(),
            "point_m": [float(point.attrib[key]) for key in ("x", "y", "z")],
            "size_m": [float(size.attrib[key]) for key in ("x", "y", "z")],
            "layers": _attrs(node.find("./layers") or ET.Element("layers"), ("vdp",)),
        }
        (boundary if current_kind == "bound" else fluid).append(record)
    if not boundary or not fluid:
        raise DiagnosticError(f"generated XML has no bound/fluid drawboxes: {xml_path}")

    parameters = {
        str(item.attrib["key"]): str(item.attrib.get("value", ""))
        for item in root.findall(".//execution/parameters/parameter")
        if "key" in item.attrib
    }
    simulation = root.find(".//execution/parameters/simulationdomain")
    domain: dict[str, list[float]] | None = None
    if simulation is not None:
        posmin = simulation.find("./posmin")
        posmax = simulation.find("./posmax")
        if posmin is not None and posmax is not None:
            domain = {
                "low_m": [float(posmin.attrib[key]) for key in ("x", "y", "z")],
                "high_m": [float(posmax.attrib[key]) for key in ("x", "y", "z")],
            }
    motion = root.find(".//casedef/motion/objreal/mvrotfile")
    motion_structure = {
        "begin": _attrs(root.find(".//casedef/motion/objreal/begin") or ET.Element("begin"), ("mov", "start", "finish")),
        "mvrotfile": _attrs(motion or ET.Element("mvrotfile"), ("id", "duration", "anglesunits")),
        "axis_p1": _attrs(motion.find("./axisp1") if motion is not None else ET.Element("axisp1"), ("x", "y", "z")),
        "axis_p2": _attrs(motion.find("./axisp2") if motion is not None else ET.Element("axisp2"), ("x", "y", "z")),
    }
    physical_parameters = {
        key: parameters.get(key)
        for key in ("Boundary", "SlipMode", "StepAlgorithm", "Kernel", "ViscoTreatment", "Visco", "ViscoBoundFactor", "DensityDT", "DensityDTvalue", "RigidAlgorithm")
    }
    # Fluid drawboxes are a numerical population command in these mothers;
    # boundary drawboxes are the finite physical surfaces used for comparison.
    return {
        "boundary_boxes": sorted(boundary, key=lambda item: (int(item["mk"]), str(item["boxfill"]), item["point_m"], item["size_m"])),
        "fluid_boxes": sorted(fluid, key=lambda item: int(item["mk"])),
        "boundary_canonical_sha256": canonical_sha(sorted(boundary, key=lambda item: (int(item["mk"]), str(item["boxfill"]), item["point_m"], item["size_m"]))),
        "fluid_command_canonical_sha256": canonical_sha(sorted(fluid, key=lambda item: int(item["mk"]))),
        "execution_physical_parameters": physical_parameters,
        "execution_physical_parameters_sha256": canonical_sha(physical_parameters),
        "simulation_domain": domain,
        "motion_structure": motion_structure,
        "motion_structure_sha256": canonical_sha(motion_structure),
        "parameters": parameters,
    }


def motion_values(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    values = [[float(a), float(b)] for a, b in FLOAT_PAIR.findall(text)]
    if len(values) < 2:
        raise DiagnosticError(f"motion control has fewer than two time-angle points: {path}")
    times = [row[0] for row in values]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise DiagnosticError(f"motion time axis is not strictly increasing: {path}")
    return {
        "count": len(values),
        "first": values[0],
        "last": values[-1],
        "values_sha256": canonical_sha(values),
        "raw_sha256": sha256(path),
        "times_s": [times[0], times[-1]],
        "angle_range_deg": [min(row[1] for row in values), max(row[1] for row in values)],
        "values": values,
    }


def motion_difference(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    av, bv = a["values"], b["values"]
    pairs = list(zip(av, bv))
    max_time = max((abs(x[0] - y[0]) for x, y in pairs), default=None)
    max_angle = max((abs(x[1] - y[1]) for x, y in pairs), default=None)
    return {
        "same_count": len(av) == len(bv),
        "same_values_exact": av == bv,
        "paired_count": len(pairs),
        "max_time_difference_s": max_time,
        "max_angle_difference_deg": max_angle,
    }


def parse_ranges(xml_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(xml_path).getroot()
    summary = root.find(".//particles/_summary")
    if summary is None:
        raise DiagnosticError(f"generated XML has no particles summary: {xml_path}")
    ranges: list[dict[str, Any]] = []
    for tag, type_id in (("fixed", 0), ("moving", 1), ("fluid", 3)):
        for node in summary.findall(f"./{tag}"):
            raw = str(node.attrib.get("id", ""))
            try:
                low_text, high_text = raw.split("-", 1)
                low, high = int(low_text), int(high_text)
            except ValueError as error:
                raise DiagnosticError(f"invalid particle range {raw!r}: {xml_path}") from error
            mk_values = [int(value) for value in str(node.attrib.get("mkvalues", "")).split("-") if value]
            ranges.append({"low": low, "high": high, "type": type_id, "mk_values": mk_values, "source": tag})
    if not ranges:
        raise DiagnosticError(f"generated XML has no typed particle ranges: {xml_path}")
    return ranges


def typed_identity(idp: int, ranges: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [item for item in ranges if int(item["low"]) <= idp <= int(item["high"])]
    if len(matches) != 1:
        return {"status": "unknown", "matching_ranges": matches}
    item = matches[0]
    mk_values = item.get("mk_values") or []
    # A fluid range is one mk per source band.  Fixed/moving ranges can also
    # contain a single mk in these generated mothers; retain ambiguity if not.
    mk = mk_values[0] if len(mk_values) == 1 else None
    return {
        "status": "resolved",
        "type": int(item["type"]),
        "mk": mk,
        "source": item["source"],
        "range": {key: item[key] for key in ("low", "high", "type", "mk_values", "source")},
    }


def runparts(path: Path) -> list[dict[str, Any]]:
    # RunPARTs uses locale-style thousands separators once an exclusion count
    # exceeds 999.  The historical helper's ``finite_float`` path does not
    # remove those separators, which silently drops exactly the rows needed
    # for this DP005 loss diagnosis.  Parse the actual file here and preserve
    # all 401 Part indices.
    rows: list[dict[str, Any]] = []
    with require_file(path, "RunPARTs.csv").open(encoding="utf-8", errors="replace", newline="") as handle:
        header = None
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if header is None:
                header = [item.strip() for item in line.split(";")]
                continue
            values = [item.strip() for item in line.split(";")]
            if len(values) != len(header):
                continue
            record = dict(zip(header, values))
            try:
                row = {
                    "part": int(record["Part"].replace(",", "")),
                    "time_s": float(record["TimeStep [s]"].replace(",", "")),
                }
                for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov"):
                    row[key] = int(round(float(record[key].replace(",", ""))))
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(row)
    rows.sort(key=lambda row: int(row["part"]))
    if not rows or [int(row["part"]) for row in rows] != list(range(len(rows))):
        raise DiagnosticError(f"RunPARTs.csv parts are not contiguous after separator-aware parsing: {path}")
    return rows


def inside_box(position: list[float], box: Mapping[str, Any], tolerance: float) -> bool:
    low = [float(value) for value in box["point_m"]]
    high = [low[index] + float(box["size_m"][index]) for index in range(3)]
    return all(low[index] - tolerance <= position[index] <= high[index] + tolerance for index in range(3))


def box_distance(position: list[float], box: Mapping[str, Any]) -> float:
    low = [float(value) for value in box["point_m"]]
    high = [low[index] + float(box["size_m"][index]) for index in range(3)]
    squared = 0.0
    for index, value in enumerate(position):
        if value < low[index]:
            squared += (low[index] - value) ** 2
        elif value > high[index]:
            squared += (value - high[index]) ** 2
    return math.sqrt(squared)


def position_evidence(position: list[float], signature: dict[str, Any], dp_m: float) -> dict[str, Any]:
    domain = signature.get("simulation_domain")
    domain_evidence: dict[str, Any] = {"declared": domain}
    if domain is not None:
        low, high = domain["low_m"], domain["high_m"]
        distances = {f"{axis}{side}": (position[index] - low[index] if side == "-" else high[index] - position[index]) for index, axis in enumerate(("x", "y", "z")) for side in ("-", "+")}
        tolerance = max(2.0 * dp_m, 1e-6)
        domain_evidence.update({
            "inside_without_tolerance": all(low[index] <= position[index] <= high[index] for index in range(3)),
            "near_faces_within_2dp": sorted(name for name, distance in distances.items() if distance <= tolerance),
            "signed_face_distances_m": distances,
        })
    boxes = {int(item["mk"]): item for item in signature["boundary_boxes"]}
    physical = {}
    for mk, label in ((0, "moving_cup_initial_aabb"), (1, "receiver_aabb"), (2, "tray_aabb")):
        box = boxes.get(mk)
        if box is None:
            physical[label] = {"declared": False}
            continue
        tolerance = max(2.0 * dp_m, 1e-6)
        physical[label] = {
            "declared": True,
            "inside_initial_aabb_with_2dp": inside_box(position, box, tolerance),
            "distance_to_initial_aabb_m": box_distance(position, box),
            "note": "moving cup uses initial AABB only; no physical fate is inferred without interpolated moving-body pose",
        }
    return {"simulation_domain": domain_evidence, "finite_geometry": physical}


def comparison_record(case: Mapping[str, Any], dp_signature: dict[str, Any], dp_motion: dict[str, Any]) -> dict[str, Any]:
    rv4 = case["rv4"]
    rv4_xml = require_file(Path(str(rv4["generated_xml"])), "RV4 generated XML")
    rv4_motion = require_file(Path(str(rv4["motion"])), "RV4 motion control")
    rv4_owner = load_json(Path(str(rv4["owner_metadata"])), "RV4 owner metadata")
    rv4_report = load_json(Path(str(rv4["conversion_report"])), "RV4 conversion report")
    rv4_signature = geometry_signature(rv4_xml)
    rv4_motion_values = motion_values(rv4_motion)
    dp_owner = load_json(Path(str(case["owner_metadata"])), "DP005 owner metadata")
    dp_physical = dp_owner.get("physical_condition", {})
    rv4_physical = rv4_report.get("hash_scopes", {}).get("physical_condition_sha256")
    dp_boundaries = dp_signature["boundary_boxes"]
    rv4_boundaries = rv4_signature["boundary_boxes"]
    same_boundary = dp_boundaries == rv4_boundaries
    same_physical_parameters = dp_signature["execution_physical_parameters"] == rv4_signature["execution_physical_parameters"]
    same_motion = motion_difference(dp_motion, rv4_motion_values)
    continuous_dp = dp_owner.get("geometry", {}).get("continuous_fluid_size_m"), dp_owner.get("geometry", {}).get("continuous_fluid_low_m")
    continuous_rv4 = rv4_owner.get("geometry", {}).get("continuous_fluid_size_m"), rv4_owner.get("geometry", {}).get("continuous_fluid_low_m")
    measured_same_mother = bool(same_boundary and same_physical_parameters and same_motion["same_values_exact"] and continuous_dp == continuous_rv4)
    return {
        "registered_claim": {
            "physical_case_id": dp_owner.get("physical_case_id"),
            "physical_mother_id": dp_physical.get("physical_mother_id"),
            "same_physical_mother": dp_owner.get("repair", {}).get("same_physical_mother"),
            "physical_geometry_control_unchanged": dp_owner.get("repair", {}).get("physical_geometry_control_unchanged"),
            "physical_condition_hash": dp_owner.get("physical_condition_hash"),
            "source_geometry_control_hash": dp_physical.get("source_geometry_control_hash"),
            "motion_raw_sha256": dp_motion["raw_sha256"],
        },
        "rv4_actual": {
            "case_id": rv4.get("case_id"),
            "physical_condition_hash": rv4_owner.get("physical_condition_hash_declared", rv4_physical),
            "physical_condition_hash_from_conversion_report": rv4_physical,
            "source_geometry_sha256": rv4_report.get("source_provenance", {}).get("geometry_sha256"),
            "source_control_sha256": rv4_report.get("source_provenance", {}).get("control_sha256"),
            "motion_raw_sha256": rv4_motion_values["raw_sha256"],
            "generated_xml_sha256": sha256(rv4_xml),
        },
        "measured_signatures": {
            "dp005_boundary_geometry_sha256": dp_signature["boundary_canonical_sha256"],
            "rv4_boundary_geometry_sha256": rv4_signature["boundary_canonical_sha256"],
            "dp005_motion_values_sha256": dp_motion["values_sha256"],
            "rv4_motion_values_sha256": rv4_motion_values["values_sha256"],
            "dp005_motion_structure_sha256": dp_signature["motion_structure_sha256"],
            "rv4_motion_structure_sha256": rv4_signature["motion_structure_sha256"],
            "dp005_execution_physical_parameters_sha256": dp_signature["execution_physical_parameters_sha256"],
            "rv4_execution_physical_parameters_sha256": rv4_signature["execution_physical_parameters_sha256"],
        },
        "comparisons": {
            "continuous_fluid_reference_equal": continuous_dp == continuous_rv4,
            "boundary_geometry_equal": same_boundary,
            "execution_physical_parameters_equal": same_physical_parameters,
            "motion_values": same_motion,
            "motion_raw_bytes_equal": dp_motion["raw_sha256"] == rv4_motion_values["raw_sha256"],
            "rv4_physical_condition_hash_equal": dp_owner.get("physical_condition_hash") == rv4_physical,
            "measured_strict_mother_equivalence": measured_same_mother,
            "classification": "finer_numerical_view_of_same_mother" if measured_same_mother else "non_equivalent_geometry_or_control_requires_new_scope",
        },
        "differences": {
            "dp005_boundary_boxes": dp_boundaries,
            "rv4_boundary_boxes": rv4_boundaries,
            "continuous_fluid_dp005": {"low_m": continuous_dp[1], "size_m": continuous_dp[0]},
            "continuous_fluid_rv4": {"low_m": continuous_rv4[1], "size_m": continuous_rv4[0]},
        },
    }


def audit_case(case: Mapping[str, Any], *, helper: Any, partvtkout: Path, output_root: Path) -> dict[str, Any]:
    case_id = str(case["case_id"])
    xml_path = require_file(Path(str(case["generated_xml"])), f"{case_id} generated XML")
    motion_path = require_file(Path(str(case["motion"])), f"{case_id} motion control")
    runparts_path = require_file(Path(str(case["runparts"])), f"{case_id} RunPARTs.csv")
    data_dir = require_file(Path(str(case["data_dir"])) / "PartOut_000.obi4", f"{case_id} PartOut_000.obi4").parent
    ranges = parse_ranges(xml_path)
    signature = geometry_signature(xml_path)
    motion = motion_values(motion_path)
    steps = runparts(runparts_path)
    artifact_dir = output_root / "artifacts" / "partvtkout" / case_id
    exclusion = helper.decode_exclusions(binary=partvtkout, data_dir=data_dir, output_dir=artifact_dir, prefix="excluded_particles")
    enriched_path = output_root / "artifacts" / "records" / f"{case_id}.jsonl"
    enriched_path.parent.mkdir(parents=True, exist_ok=True)
    motive_totals: Counter[str] = Counter()
    type_totals: Counter[str] = Counter()
    near_domain_totals: Counter[str] = Counter()
    unresolved_parts: list[int] = []
    records: list[dict[str, Any]] = []
    with enriched_path.open("w", encoding="utf-8") as handle:
        for raw in exclusion["rows"]:
            part = int(raw["part_out"])
            time_s = steps[part]["time_s"] if 0 <= part < len(steps) else None
            if time_s is None:
                unresolved_parts.append(part)
            identity = typed_identity(int(raw["idp"]), ranges)
            location = position_evidence(list(raw["position_m"]), signature, float(case["dp_m"]))
            near_domain = location["simulation_domain"].get("near_faces_within_2dp", [])
            for face in near_domain:
                near_domain_totals[str(face)] += 1
            motive_totals[str(raw["motive"])] += 1
            type_totals[str(identity.get("type", "unknown"))] += 1
            record = {
                "idp": int(raw["idp"]),
                "typed_identity": identity,
                "part_out": part,
                "first_missing_frame": part,
                "first_missing_time_s": time_s,
                "motive": int(raw["motive"]),
                "motive_class": "native_solver_excluded_numerical_unknown",
                "position_m": list(raw["position_m"]),
                "velocity_m_s": list(raw["velocity_m_s"]),
                "density_kg_m3": float(raw["density_kg_m3"]),
                "location_evidence": location,
            }
            handle.write(json.dumps(jsonable(record), ensure_ascii=False, sort_keys=True) + "\n")
            records.append(record)
    comparison = comparison_record(case, signature, motion)
    source_paths = [
        Path(__file__), DIAGNOSTIC_HELPER, xml_path, motion_path, runparts_path,
        data_dir / "PartOut_000.obi4", Path(str(case["solver_receipt"])), Path(str(case["gencase_receipt"])),
        Path(str(case["owner_metadata"])), require_file(Path(str(case["rv4"]["generated_xml"])), "RV4 generated XML"),
        require_file(Path(str(case["rv4"]["motion"])), "RV4 motion"), require_file(Path(str(case["rv4"]["owner_metadata"])), "RV4 owner"),
        require_file(Path(str(case["rv4"]["conversion_report"])), "RV4 conversion report"), enriched_path,
    ]
    source_bindings = {str(path.resolve()): {"path": str(path.resolve()), "sha256": sha256(path)} for path in source_paths if path.is_file()}
    source_bindings.update({item["path"]: item for item in exclusion.get("outputs", [])})
    return {
        "case_id": case_id,
        "background": case.get("background"),
        "dp_m": float(case["dp_m"]),
        "physical_case_id": case.get("physical_case_id"),
        "source_bindings": source_bindings,
        "typed_identity_ranges": ranges,
        "generated_xml_signature": signature,
        "motion_signature": {key: value for key, value in motion.items() if key != "values"},
        "runparts": {
            "path": str(runparts_path),
            "sha256": sha256(runparts_path),
            "rows": len(steps),
            "first_time_s": steps[0]["time_s"],
            "last_time_s": steps[-1]["time_s"],
            "NpOut_sum": int(sum(row["NpOut"] for row in steps)),
            "NpOutPos_sum": int(sum(row["NpOutPos"] for row in steps)),
            "NpOutRho_sum": int(sum(row["NpOutRho"] for row in steps)),
            "NpOutMov_sum": int(sum(row["NpOutMov"] for row in steps)),
        },
        "partvtkout_exclusions": {
            "binary": exclusion["binary"],
            "command": exclusion["command"],
            "returncode": exclusion["returncode"],
            "row_count": len(records),
            "motive_totals": dict(sorted(motive_totals.items())),
            "typed_type_totals": dict(sorted(type_totals.items())),
            "near_domain_face_totals": dict(sorted(near_domain_totals.items())),
            "unresolved_first_missing_parts": sorted(set(unresolved_parts)),
            "raw_outputs": exclusion.get("outputs", []),
            "enriched_records": {"path": str(enriched_path), "sha256": sha256(enriched_path), "rows": len(records)},
            "all_rows_are_unknown_until_event_audit": True,
        },
        "strict_mother_equivalence": comparison,
        "interpretation": {
            "motive_is_not_physical_spill": True,
            "position_near_domain_face_is_not_physical_spill": True,
            "moving_cup_classification_uses_initial_aabb_only": True,
            "finite_receiver_tray_membership_is_geometric_side_evidence_only": True,
            "qualification_claim": "none",
            "production_claim": "none",
            "scientific_status": "native_exclusions_decoded_and_mother_equivalence_pending_root_review",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--partvtkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = require_file(args.manifest, "DP005 diagnostic manifest")
    manifest = load_json(manifest_path, "DP005 diagnostic manifest")
    if manifest.get("schema") != "ds-data-02.f2.dp005-native-diagnostic-input.v1":
        raise DiagnosticError(f"unexpected manifest schema: {manifest.get('schema')!r}")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 2:
        raise DiagnosticError("DP005 diagnostic manifest must contain exactly CENTER and OFFSET cases")
    partvtkout = require_file(args.partvtkout, "official PartVTKOut binary")
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    helper = import_helper()
    report = {
        "schema": "ds-data-02.f2.dp005-native-diagnostic.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "source_bindings": {
            str(DIAGNOSTIC_HELPER.resolve()): {"path": str(DIAGNOSTIC_HELPER.resolve()), "sha256": sha256(DIAGNOSTIC_HELPER)},
            str(partvtkout): {"path": str(partvtkout), "sha256": sha256(partvtkout)},
        },
        "cases": [audit_case(case, helper=helper, partvtkout=partvtkout, output_root=output.parent) for case in cases],
        "status": "diagnostic_complete_pending_scientific_review",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    output.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "path": str(output), "sha256": sha256(output), "case_count": len(report["cases"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
