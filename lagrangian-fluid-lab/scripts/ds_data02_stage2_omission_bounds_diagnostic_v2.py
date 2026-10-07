#!/usr/bin/env python3
"""Diagnose native omission gates from immutable Stage2 sidecars.

This module consumes an already completed omission-forensics sidecar.  It
does not open the trajectory HDF5 and it never changes the sidecar or native
solver output.  A numerical cause receives credit only when the corresponding
Run.out/XML/PartOut/RunPARTs evidence is present and source-bound.  Native
numerical exclusion remains separate from physical fate and dynamics.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ds_data02_runtime_v2 import atomic_json


AXES = ("x", "y", "z")
PARTOUT_FIELDS = {
    "Idp", "PartOut", "Motive", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]",
    "Rhop [kg/m^3]",
}
RUNPART_FIELDS = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
FLOAT_RE = r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?"
MAP_RE = re.compile(
    rf"MapRealPos\((border|final)\)=\(([^)]*)\)-\(([^)]*)\)"
)
CASE_RE = re.compile(r'CaseName="([^"]+)"')
RHOP_RE = {
    key: re.compile(rf"\b{key}=({FLOAT_RE}|True|False)\b")
    for key in ("RhopOutMin", "RhopOutMax")
}


class EvidenceError(ValueError):
    """Raised when a diagnostic cannot establish a source-bound observation."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict:
    path = Path(path)
    stat = path.stat()
    return {"path": str(path), "sha256": sha256(path), "bytes": stat.st_size}


def require_file(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_file():
        raise EvidenceError(f"{label} is missing: {path}")
    return path


def require_binding(row: dict, path: Path, label: str) -> str:
    path = require_file(path, label)
    expected = row.get("sha256")
    actual = sha256(path)
    if expected != actual:
        raise EvidenceError(f"{label} digest changed: {path}")
    return actual


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def descendants(root: ET.Element, tag: str):
    return (element for element in root.iter() if local_tag(element) == tag)


def vector_attributes(element: ET.Element, label: str) -> list[float]:
    try:
        values = [float(element.attrib[axis]) for axis in AXES]
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError(f"XML {label} vector is not numeric") from error
    if not all(math.isfinite(value) for value in values):
        raise EvidenceError(f"XML {label} vector is nonfinite")
    return values


def parse_run_out(path: Path) -> dict:
    text = require_file(path, "Run.out").read_text(errors="replace")
    maps = {}
    for match in MAP_RE.finditer(text):
        if match.group(1) in maps:
            raise EvidenceError(f"Run.out repeats MapRealPos({match.group(1)})")
        try:
            low = [float(value) for value in match.group(2).split(",")]
            high = [float(value) for value in match.group(3).split(",")]
        except ValueError as error:
            raise EvidenceError("Run.out MapRealPos is not numeric") from error
        if len(low) != 3 or len(high) != 3 or not all(
            math.isfinite(value) for value in (*low, *high)
        ) or any(a >= b for a, b in zip(low, high)):
            raise EvidenceError("Run.out MapRealPos bounds are invalid")
        maps[match.group(1)] = [low, high]
    if set(maps) != {"border", "final"}:
        raise EvidenceError("Run.out does not contain exactly border and final MapRealPos")

    case_matches = CASE_RE.findall(text)
    if len(case_matches) != 1:
        raise EvidenceError("Run.out CaseName evidence is missing or ambiguous")
    rhop = {}
    for key, pattern in RHOP_RE.items():
        matches = pattern.findall(text)
        if len(matches) != 1:
            raise EvidenceError(f"Run.out {key} evidence is missing or ambiguous")
        try:
            rhop[key] = float(matches[0])
        except ValueError as error:
            raise EvidenceError(f"Run.out {key} is not numeric") from error
    if rhop["RhopOutMin"] >= rhop["RhopOutMax"]:
        raise EvidenceError("Run.out density bounds are invalid")
    enabled = re.findall(r"\bRhopOut=(True|False)\b", text)
    if enabled != ["True"]:
        raise EvidenceError("Run.out RhopOut is not uniquely enabled")
    return {"case_name": case_matches[0], "map_real_pos": maps, "rhop_out": rhop}


def _first_descendant(root: ET.Element, tag: str) -> ET.Element:
    try:
        return next(descendants(root, tag))
    except StopIteration as error:
        raise EvidenceError(f"XML element {tag} is missing") from error


def parse_xml(path: Path) -> dict:
    path = require_file(path, "generated XML")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise EvidenceError(f"generated XML is invalid: {path}") from error

    definition = _first_descendant(root, "definition")
    pointmin = _first_descendant(definition, "pointmin")
    pointmax = _first_descendant(definition, "pointmax")
    definition_bounds = [vector_attributes(pointmin, "definition pointmin"),
                         vector_attributes(pointmax, "definition pointmax")]

    parameters = _first_descendant(root, "parameters")
    rhop_xml = {}
    for parameter in descendants(parameters, "parameter"):
        key = parameter.attrib.get("key")
        if key in ("RhopOutMin", "RhopOutMax"):
            try:
                rhop_xml[key] = float(parameter.attrib["value"])
            except (KeyError, TypeError, ValueError) as error:
                raise EvidenceError(f"XML {key} is invalid") from error
    if set(rhop_xml) != {"RhopOutMin", "RhopOutMax"}:
        raise EvidenceError("XML RhopOut threshold evidence is incomplete")

    domain = _first_descendant(parameters, "simulationdomain")
    domain_raw = {}
    domain_numeric = {}
    for name in ("posmin", "posmax"):
        element = next((x for x in domain if local_tag(x) == name), None)
        if element is None:
            raise EvidenceError(f"XML simulationdomain {name} is missing")
        raw = {axis: element.attrib.get(axis) for axis in AXES}
        domain_raw[name] = raw
        try:
            values = [float(raw[axis]) for axis in AXES]
        except (TypeError, ValueError):
            values = None
        domain_numeric[name] = values

    bottom_boxes = []
    for drawbox in descendants(root, "drawbox"):
        boxfill = next((x for x in drawbox if local_tag(x) == "boxfill"), None)
        if boxfill is None or "bottom" not in (boxfill.text or ""):
            continue
        point = next((x for x in drawbox if local_tag(x) == "point"), None)
        size = next((x for x in drawbox if local_tag(x) == "size"), None)
        if point is None or size is None:
            raise EvidenceError("XML bottom drawbox lacks point or size")
        low = vector_attributes(point, "bottom point")
        extent = vector_attributes(size, "bottom size")
        if any(value <= 0 for value in extent):
            raise EvidenceError("XML bottom drawbox size is not positive")
        high = [low[index] + extent[index] for index in range(3)]
        bottom_boxes.append({
            "comment": drawbox.attrib.get("cmt"),
            "boxfill": (boxfill.text or "").strip(),
            "low": low,
            "high": high,
        })
    if not bottom_boxes:
        raise EvidenceError("XML has no static bottom wall drawbox evidence")
    bottom_z = min(box["low"][2] for box in bottom_boxes)

    particles = _first_descendant(root, "particles")
    fluid = next((x for x in descendants(particles, "fluid")
                  if "count" in x.attrib), None)
    if fluid is None:
        raise EvidenceError("XML fluid count evidence is missing")
    try:
        fluid_count = int(fluid.attrib["count"])
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("XML fluid count is invalid") from error
    massfluid = next((x for x in descendants(root, "massfluid")
                      if "value" in x.attrib), None)
    if massfluid is None:
        raise EvidenceError("XML fluid particle mass evidence is missing")
    try:
        massfluid_kg = float(massfluid.attrib["value"])
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("XML fluid particle mass is invalid") from error
    if fluid_count <= 0 or not math.isfinite(massfluid_kg) or massfluid_kg <= 0:
        raise EvidenceError("XML fluid mass basis is invalid")
    body_masses = []
    for element in descendants(root, "massbody"):
        if "value" in element.attrib:
            try:
                body_masses.append(float(element.attrib["value"]))
            except ValueError as error:
                raise EvidenceError("XML body mass is invalid") from error
    return {
        "definition_bounds": definition_bounds,
        "simulationdomain": {"raw": domain_raw, "numeric": domain_numeric},
        "rhop_out": rhop_xml,
        "bottom_boxes": bottom_boxes,
        "static_bottom_reference_z": bottom_z,
        "fluid_count": fluid_count,
        "massfluid_kg": massfluid_kg,
        "body_masses_kg": body_masses,
        "sha256": sha256(path),
        "path": str(path),
    }


def parse_partout(path: Path) -> list[dict]:
    path = require_file(path, "PartOut CSV")
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        names = {name.strip() for name in (reader.fieldnames or [])}
        if not PARTOUT_FIELDS <= names:
            raise EvidenceError("PartOut CSV header is incomplete")
        rows = []
        for raw in reader:
            row = {key.strip(): (value or "").strip()
                   for key, value in raw.items() if key and value is not None}
            try:
                values = {
                    "idp": int(row["Idp"]),
                    "part_out": int(row["PartOut"]),
                    "motive_code": int(row["Motive"]),
                    "position_m": [float(row[f"Pos.{axis} [m]"]) for axis in AXES],
                    "density_kg_m3": float(row["Rhop [kg/m^3]"]),
                }
            except (KeyError, TypeError, ValueError) as error:
                raise EvidenceError("PartOut CSV contains an invalid row") from error
            if values["idp"] < 0 or values["part_out"] < 1 or values["motive_code"] not in (1, 2, 3):
                raise EvidenceError("PartOut CSV identity or motive is invalid")
            if not all(math.isfinite(value) for value in
                       (*values["position_m"], values["density_kg_m3"])):
                raise EvidenceError("PartOut CSV contains a nonfinite state")
            rows.append(values)
    if len({row["idp"] for row in rows}) != len(rows):
        raise EvidenceError("PartOut CSV has ambiguous duplicate Idp records")
    if not rows:
        raise EvidenceError("PartOut CSV is empty")
    return rows


def parse_runparts(path: Path) -> dict:
    path = require_file(path, "RunPARTs CSV")
    lines = [line for line in path.read_text(errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    if reader.fieldnames is None or not set(RUNPART_FIELDS) | {"Part", "TimeStep [s]"} <= set(reader.fieldnames):
        raise EvidenceError("RunPARTs header is incomplete")
    rows = []
    totals = {name: 0 for name in RUNPART_FIELDS}
    for raw in reader:
        try:
            part = int(raw["Part"].replace(",", ""))
            time_s = float(raw["TimeStep [s]"])
            counts = {name: int(raw[name].replace(",", "")) for name in RUNPART_FIELDS}
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise EvidenceError("RunPARTs contains an invalid row") from error
        if part != len(rows) or not math.isfinite(time_s):
            raise EvidenceError("RunPARTs Part sequence or time is invalid")
        if rows and time_s <= rows[-1]["time_s"]:
            raise EvidenceError("RunPARTs time is not strictly increasing")
        if any(value < 0 for value in counts.values()) or counts["NpOut"] != sum(
            counts[name] for name in RUNPART_FIELDS[1:]
        ):
            raise EvidenceError("RunPARTs exclusion counters are invalid")
        rows.append({"part": part, "time_s": time_s, **counts})
        for name, value in counts.items():
            totals[name] += value
    if not rows:
        raise EvidenceError("RunPARTs has no rows")
    return {"rows": rows, "totals": totals}


def command_value(command: list[str], flag: str) -> str:
    for index, value in enumerate(command[:-1]):
        if value == flag:
            return command[index + 1]
    raise EvidenceError(f"decoder command lacks {flag}")


def _verify_decoder(decoder: dict, sidecar: dict, scan_path: Path,
                    runparts_path: Path, conversion_path: Path,
                    xml_path: Path, solver_receipt_path: Path,
                    gencase_receipt_path: Path) -> dict:
    if decoder.get("status") != "completed" or decoder.get("returncode") != 0:
        raise EvidenceError("official decoder receipt is not completed")
    request = decoder.get("request", {})
    files = [Path(path) for path in request.get("input_files", [])]
    declared = request.get("input_sha256", {})
    launch = decoder.get("input_hashes_at_launch", {})
    after = decoder.get("input_hashes_after_run", {})
    if not files or set(declared) != {str(path) for path in files}:
        raise EvidenceError("decoder receipt input digest map is incomplete")
    for path in files:
        key = str(path)
        if declared.get(key) != launch.get(key) or declared.get(key) != after.get(key):
            raise EvidenceError(f"decoder input digest did not remain stable: {path}")

    source = sidecar["source_provenance"]
    data_root = require_file(Path(source["data_root"]) / "PartOut_000.obi4",
                              "decoder raw PartOut source").parent
    raw = [path for path in files if path.name == "PartOut_000.obi4"]
    if len(raw) != 1 or raw[0].parent != data_root:
        raise EvidenceError("decoder raw PartOut source is not the bound data_root")
    # The raw source is deliberately rehashed: a changed native input cannot
    # inherit cause credit from a historical receipt.
    if sha256(raw[0]) != declared[str(raw[0])]:
        raise EvidenceError("decoder raw PartOut digest changed")

    required = [scan_path, runparts_path, conversion_path, xml_path,
                solver_receipt_path, gencase_receipt_path]
    for path in required:
        key = str(path)
        if path not in files or sha256(path) != declared.get(key):
            raise EvidenceError(f"decoder source digest is not bound: {path}")
    command = decoder.get("command", [])
    expanded = [value.replace("{attempt_root}", decoder["output_root"])
                for value in request.get("command", [])]
    if expanded != command:
        raise EvidenceError("decoder command differs from its request")
    if Path(command_value(command, "-dirdata")) != data_root:
        raise EvidenceError("decoder -dirdata differs from conversion source data_root")
    partout_path = Path(sidecar["native_decode"]["partout"]["path"])
    if Path(command_value(command, "-savecsv")) != partout_path:
        raise EvidenceError("decoder -savecsv differs from bound PartOut")
    if Path(decoder.get("output_root", "")) != partout_path.parent:
        raise EvidenceError("decoder output root differs from PartOut parent")
    if Path(command[0]).name != "PartVTKOut_linux64":
        raise EvidenceError("decoder binary is not official PartVTKOut")
    if decoder.get("binary_sha256") != sha256(Path(command[0])):
        raise EvidenceError("decoder binary digest changed")
    if Path(runparts_path).parent != data_root.parent:
        raise EvidenceError("RunPARTs is not from the same raw solver parent")
    return {"data_root": str(data_root), "raw_partout": binding(raw[0]),
            "command": command}


def _validate_sources(sidecar: dict) -> dict:
    if sidecar.get("schema") != "ds02.stage2.omission-forensics.v2":
        raise EvidenceError("unsupported omission sidecar schema")
    if sidecar.get("status") != "CAUSES_RECONCILED":
        raise EvidenceError("omission sidecar does not have reconciled causes")
    scan_info = sidecar.get("scan", {})
    scan_path = require_file(Path(scan_info.get("path", "")), "scientific scan")
    require_binding(scan_info, scan_path, "scientific scan")
    scan = json.loads(scan_path.read_text())
    if scan.get("scan_status") != "SCANNED" or scan.get("failures"):
        raise EvidenceError("scientific scan is not a clean completed scan")
    if (scan.get("family_id") != sidecar.get("family_id") or
            scan.get("physical_case_id") != sidecar.get("physical_case_id")):
        raise EvidenceError("sidecar and scientific scan case identity differ")
    completion = sidecar.get("scan_completion", {}).get("receipt", {})
    scan_receipt_path = require_file(Path(completion.get("path", "")),
                                     "scientific scan receipt")
    require_binding(completion, scan_receipt_path, "scientific scan receipt")
    scan_receipt = json.loads(scan_receipt_path.read_text())
    if scan_receipt.get("status") != "completed" or scan_receipt.get("returncode") != 0:
        raise EvidenceError("scientific scan receipt is not completed")

    conversion_info = sidecar.get("trajectory", {}).get("conversion_report", {})
    conversion_path = require_file(Path(conversion_info.get("path", "")),
                                   "conversion report")
    require_binding(conversion_info, conversion_path, "conversion report")
    conversion = json.loads(conversion_path.read_text())
    trajectory = Path(scan["trajectory"])
    if (conversion.get("output_hdf5") != str(trajectory) or
            conversion.get("output_sha256") != sidecar["trajectory"].get("sha256")):
        raise EvidenceError("conversion output does not match bound scan trajectory")

    source = sidecar.get("source_provenance", {})
    paths = {}
    for field in ("generated_xml", "solver_receipt", "gencase_receipt"):
        info = source.get(field, {})
        path = require_file(Path(info.get("path", "")), field)
        if info.get("sha256") != sha256(path):
            raise EvidenceError(f"{field} digest changed")
        paths[field] = path

    native = sidecar.get("native_decode", {})
    receipt_info = native.get("receipt", {})
    decoder_path = require_file(Path(receipt_info.get("path", "")),
                                "PartVTKOut receipt")
    require_binding(receipt_info, decoder_path, "PartVTKOut receipt")
    decoder = json.loads(decoder_path.read_text())
    partout_info = native.get("partout", {})
    partout_path = require_file(Path(partout_info.get("path", "")), "PartOut CSV")
    require_binding(partout_info, partout_path, "PartOut CSV")
    runparts_info = native.get("runparts", {})
    runparts_path = require_file(Path(runparts_info.get("path", "")), "RunPARTs CSV")
    require_binding(runparts_info, runparts_path, "RunPARTs CSV")

    solver_receipt = json.loads(paths["solver_receipt"].read_text())
    if solver_receipt.get("status") != "completed" or solver_receipt.get("returncode") != 0:
        raise EvidenceError("solver receipt is not completed")
    if solver_receipt.get("request", {}).get("physical_case_id") != sidecar.get("physical_case_id"):
        raise EvidenceError("solver receipt physical_case_id differs from exact sidecar identity")
    solver_root = Path(solver_receipt.get("output_root", ""))
    if solver_root != paths["solver_receipt"].parent:
        raise EvidenceError("solver receipt output_root is inconsistent")
    run_out = require_file(solver_root / "solver_output" / "Run.out", "Run.out")
    return {
        "scan": scan,
        "scan_path": scan_path,
        "scan_receipt": scan_receipt,
        "scan_receipt_path": scan_receipt_path,
        "conversion": conversion,
        "conversion_path": conversion_path,
        "paths": paths,
        "decoder": decoder,
        "decoder_path": decoder_path,
        "partout_path": partout_path,
        "runparts_path": runparts_path,
        "run_out": run_out,
    }


def _time_check(scan: dict, runparts: dict) -> float:
    times = scan.get("time_s")
    if not isinstance(times, list) or len(times) != len(runparts["rows"]):
        raise EvidenceError("scan and RunPARTs timeline lengths differ")
    delta = max(abs(float(a) - b["time_s"])
                for a, b in zip(times, runparts["rows"]))
    tolerance = 1e-8 * max(1.0, float(times[-1]), runparts["rows"][-1]["time_s"])
    if delta > tolerance:
        raise EvidenceError(f"scan and RunPARTs timeline differs by {delta}")
    return delta


def _join(sidecar: dict, sources: dict, run_out: dict, xml: dict,
          partout: list[dict], runparts: dict, max_time_delta: float) -> dict:
    native = sidecar["native_decode"]
    expected_ids = sidecar["typed_identity"]["ids"]
    expected_by_id = {int(row["idp"]): row for row in expected_ids}
    if len(expected_by_id) != len(expected_ids):
        raise EvidenceError("sidecar typed omission identity is ambiguous")
    sidecar_rows = {int(row["idp"]): row for row in sidecar["excluded_particles"]}
    if set(sidecar_rows) != set(expected_by_id):
        raise EvidenceError("sidecar typed identity and particle records differ")
    if len(partout) != len(sidecar_rows):
        raise EvidenceError("PartOut count differs from typed omission count")
    if native.get("runparts_totals") != runparts["totals"]:
        raise EvidenceError("RunPARTs totals changed from omission sidecar")
    if native.get("runparts_row_count") != len(runparts["rows"]):
        raise EvidenceError("RunPARTs row count changed from omission sidecar")

    motive_names = {1: "position", 2: "density", 3: "movement"}
    part_by_id = {row["idp"]: row for row in partout}
    if set(part_by_id) != set(sidecar_rows):
        raise EvidenceError("PartOut Idp set differs from typed omissions")
    for row in partout:
        if row["part_out"] >= len(sources["scan"].get("time_s", [])):
            raise EvidenceError("PartOut frame is outside scan timeline")
    motive_counts = Counter()
    joined = []
    map_final = run_out["map_real_pos"]["final"]
    map_border = run_out["map_real_pos"]["border"]
    rhop = run_out["rhop_out"]
    bottom_z = xml["static_bottom_reference_z"]
    for idp, typed in sidecar_rows.items():
        row = part_by_id[idp]
        if row["part_out"] != int(typed["first_missing_frame"]):
            raise EvidenceError(f"PartOut frame mismatch for Idp {idp}")
        motive = motive_names.get(row["motive_code"])
        if motive != typed.get("native_motive"):
            raise EvidenceError(f"PartOut motive mismatch for Idp {idp}")
        map_violations = []
        border_violations = []
        for index, axis in enumerate(AXES):
            value = row["position_m"][index]
            if value < map_final[0][index]:
                map_violations.append({"axis": axis, "direction": "below",
                                       "amount_m": map_final[0][index] - value,
                                       "bound_m": map_final[0][index]})
            elif value > map_final[1][index]:
                map_violations.append({"axis": axis, "direction": "above",
                                       "amount_m": value - map_final[1][index],
                                       "bound_m": map_final[1][index]})
            if value < map_border[0][index]:
                border_violations.append({"axis": axis, "direction": "below",
                                          "amount_m": map_border[0][index] - value,
                                          "bound_m": map_border[0][index]})
            elif value > map_border[1][index]:
                border_violations.append({"axis": axis, "direction": "above",
                                          "amount_m": value - map_border[1][index],
                                          "bound_m": map_border[1][index]})
        density = row["density_kg_m3"]
        if density < rhop["RhopOutMin"]:
            density_state = "below_rhop_min"
        elif density > rhop["RhopOutMax"]:
            density_state = "above_rhop_max"
        else:
            density_state = "inside_rhop_window"
        if row["position_m"][2] < bottom_z:
            bottom_relation = "below_static_bottom_reference"
        else:
            bottom_relation = "at_or_above_static_bottom_reference"
        if motive == "position" and map_violations:
            category = "position_outside_map_final"
            cause_credit = True
            basis = "PartOut position motive and Run.out MapRealPos(final) violation"
        elif motive == "density" and density_state != "inside_rhop_window":
            category = "density_outside_rhop_window"
            cause_credit = True
            basis = "PartOut density motive and Run.out RhopOut threshold violation"
        elif motive == "movement":
            category = "movement_unresolved"
            cause_credit = False
            basis = "movement motive has no independent motion diagnostic in this sidecar"
        else:
            category = "native_motive_unresolved_by_available_evidence"
            cause_credit = False
            basis = "native motive is not independently established by the bound diagnostics"
        motive_counts[motive] += 1
        joined.append({
            "zone": int(typed["zone"]),
            "idp": idp,
            "native_motive": motive,
            "diagnostic_category": category,
            "numerical_cause_credit": cause_credit,
            "cause_basis": basis,
            "map_final_violations": map_violations,
            "map_border_violations": border_violations,
            "partvtkout_position_m": row["position_m"],
            "density_kg_m3": density,
            "density_threshold_state": density_state,
            "rhop_out_min_kg_m3": rhop["RhopOutMin"],
            "rhop_out_max_kg_m3": rhop["RhopOutMax"],
            "static_bottom_relation": bottom_relation,
            "static_bottom_reference_z_m": bottom_z,
            "initial_mass_kg": typed["initial_mass_kg"],
            "last_normal": {
                "frame": typed["last_known_frame"],
                "time_s": typed["last_known_time_s"],
                "position_m": typed["last_known_position_m"],
                "velocity_m_s": typed["last_known_velocity_m_s"],
                "density_kg_m3": typed["last_known_density_kg_m3"],
            },
            "first_gap": {
                "frame": typed["first_missing_frame"],
                "bracket_s": typed["first_missing_bracket_s"],
                "previous_state": typed.get("first_gap_previous_state"),
            },
            "observation_impact": {
                "native_accounting": "observed numerical exclusion gate only",
                "mass_visibility": "identified missing fluid mass contributes to an observed mass-visibility lower bound",
                "static_geometry": "coordinate relation to the XML bottom wall; not a legal-outflow test",
                "physical_fate": "UNKNOWN",
                "dynamical_impact": "NOT_ASSESSED",
            },
        })

    expected_motives = {
        "position": runparts["totals"]["NpOutPos"],
        "density": runparts["totals"]["NpOutRho"],
        "movement": runparts["totals"]["NpOutMov"],
    }
    if {name: motive_counts.get(name, 0) for name in expected_motives} != expected_motives:
        raise EvidenceError("PartOut motive count differs from RunPARTs")
    observed_mass = sum(float(row["initial_mass_kg"]) for row in joined)
    initial_mass = xml["fluid_count"] * xml["massfluid_kg"]
    categories = Counter(row["diagnostic_category"] for row in joined)
    credited = sum(1 for row in joined if row["numerical_cause_credit"])
    return {
        "particles": joined,
        "motive_counts": dict(motive_counts),
        "diagnostic_category_counts": dict(categories),
        "numerical_cause_credit_count": credited,
        "map_final_violation_count": sum(bool(row["map_final_violations"]) for row in joined),
        "below_static_bottom_count": sum(
            row["static_bottom_relation"] == "below_static_bottom_reference"
            for row in joined
        ),
        "mass_visibility": {
            "identified_missing_mass_kg": observed_mass,
            "initial_fluid_population_mass_kg": initial_mass,
            "identified_mass_fraction_lower_bound": observed_mass / initial_mass,
            "basis": "sum of source-bound initial fluid masses divided by XML fluid_count times XML massfluid; no claim about unobserved fate or dynamics",
        },
        "max_scan_runparts_time_delta_s": max_time_delta,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "NOT_ASSESSED",
        "legal_outflow_proven": False,
    }


def diagnose(sidecar_path: Path) -> dict:
    sidecar_path = require_file(sidecar_path, "omission sidecar")
    sidecar = json.loads(sidecar_path.read_text())
    sources = _validate_sources(sidecar)
    run_out = parse_run_out(sources["run_out"])
    xml = parse_xml(sources["paths"]["generated_xml"])
    if xml["rhop_out"] != run_out["rhop_out"]:
        raise EvidenceError("XML and Run.out density thresholds differ")
    runparts = parse_runparts(sources["runparts_path"])
    max_time_delta = _time_check(sources["scan"], runparts)
    partout = parse_partout(sources["partout_path"])
    decoder_info = _verify_decoder(
        sources["decoder"], sidecar, sources["scan_path"], sources["runparts_path"],
        sources["conversion_path"], sources["paths"]["generated_xml"],
        sources["paths"]["solver_receipt"], sources["paths"]["gencase_receipt"],
    )
    joined = _join(sidecar, sources, run_out, xml, partout, runparts, max_time_delta)
    return {
        "schema": "ds02.stage2.omission-bounds-diagnostic.v1",
        "status": "BOUNDS_DENSITY_DIAGNOSED",
        "family_id": sidecar["family_id"],
        "physical_case_id": sidecar["physical_case_id"],
        "input_sidecar": binding(sidecar_path),
        "evidence": {
            "scan": binding(sources["scan_path"]),
            "scan_receipt": binding(sources["scan_receipt_path"]),
            "conversion_report": binding(sources["conversion_path"]),
            "generated_xml": binding(sources["paths"]["generated_xml"]),
            "solver_receipt": binding(sources["paths"]["solver_receipt"]),
            "gencase_receipt": binding(sources["paths"]["gencase_receipt"]),
            "run_out": binding(sources["run_out"]),
            "runparts": binding(sources["runparts_path"]),
            "partout": binding(sources["partout_path"]),
            "decoder_receipt": binding(sources["decoder_path"]),
            "decoder_raw_partout": decoder_info["raw_partout"],
            "decoder_command": decoder_info["command"],
            "trajectory_h5_read": False,
        },
        "run_out": run_out,
        "xml_geometry": xml,
        "diagnostic": joined,
        "paired_control_plan": {
            "status": "PROPOSAL_ONLY_NOT_RUN",
            "domain_position_pair": {
                "hold": "same XML, geometry, controls, time window, and source cohort",
                "vary": "explicit simulationdomain margin beyond the maximum measured MapRealPos violation",
                "readout": "compare exact typed Idp survival, first-gap frame, RunPARTs motive counts, and post-gap observables",
                "interpretation": "different survival is evidence of numerical sensitivity only; it does not prove physical spill or zero dynamics impact",
            },
            "density_pair": {
                "hold": "same source and geometry",
                "vary": "one-at-a-time RhopOut threshold sensitivity control",
                "readout": "compare native density exclusions and density trajectories; do not infer physical validity from threshold bypass",
            },
            "geometry_pair": {
                "hold": "same numerical domain and thresholds",
                "vary": "static bottom/wall placement only in a bounded control",
                "readout": "compare wall relation and first-gap identity; no open-boundary claim",
            },
        },
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "NOT_ASSESSED",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Preserve existing diagnostic: {args.output}")
    result = diagnose(args.sidecar)
    atomic_json(args.output, result)
    print(json.dumps({"status": result["status"],
                      "case": result["physical_case_id"],
                      "credit": result["diagnostic"]["numerical_cause_credit_count"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
