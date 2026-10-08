#!/usr/bin/env python3
"""Forward v3 source-bound removal-time momentum/energy diagnostics for the F2 pair.

The completed fine reference (175 native rows) and expanded numerical-domain
control (111 native rows) already have official PartVTKOut CSVs.  This
forward-only audit reads those CSVs, their RunPARTs timelines, generated XML,
Run.out bounds, and completed receipts.  It computes each removed particle's
initial-mass-weighted ``m*v`` and ``0.5*m*|v|^2`` and aggregates them by saved
removal time, source MK, and the printed ``MapRealPos(final)`` face.

The aggregation is per removal time.  It never sums quantities across unlike
times and never turns a native exclusion into a physical spill, force, impulse,
or dynamics-error bound.  No H5, trajectory Part_*.bi4, decoder, solver, CFD,
or model is opened or started by this worker.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV = LAB_ROOT / ".venv/bin/python"
PAIR_RESULT = DATA_ROOT / (
    "families/F2/F2_S1_FINE_EXPANDED_NATIVE_WEIGHTED_V1/"
    "f2-s1-fine-expanded-native-weighted-v1-primary-003-v5/"
    "f2-s1-fine-expanded-native-weighted.json"
)
PAIR_EXECUTION_RECEIPT = PAIR_RESULT.parent / "execution-receipt.json"
TOOL = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
CONFIG = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
OUTPUT_SCHEMA = "ds02.stage2.native-removal-kinematics.v3"
MANIFEST_SCHEMA = "ds02.stage2.native-removal-kinematics-manifest.v3"
PHYSICAL_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
ORIGINAL_CASE = "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE"
EXPANDED_CASE = "F2_S1_FINE_DOMAIN_EXPANDED_DP00855_XYZ_V1"
FACE_ORDER = ("x_low", "x_high", "y_low", "y_high", "z_low", "z_high")
REQUIRED_CSV = {
    "Idp", "PartOut", "Motive", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]",
    "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]",
}


class RemovalKinematicsError(RuntimeError):
    """Raised when source identity, CSV semantics, or timing closure opens."""


def sha256(value: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(value).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise RemovalKinematicsError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemovalKinematicsError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RemovalKinematicsError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RemovalKinematicsError(f"refuse to overwrite existing output: {path}")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
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


def record(value: Path | str, label: str, *, allow_raw_partout: bool = True) -> dict[str, Any]:
    path = require_file(value, label)
    lower = path.suffix.lower()
    if lower in {".h5", ".hdf5"} or (path.name.startswith("Part_") and path.name.endswith(".bi4")):
        raise RemovalKinematicsError(f"trajectory input is forbidden: {path}")
    if not allow_raw_partout and path.name == "PartOut_000.obi4":
        raise RemovalKinematicsError(f"raw PartOut input is forbidden here: {path}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RemovalKinematicsError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise RemovalKinematicsError(f"{label} is not finite")
    return result


def _same(left: Any, right: Any, *, tol: float = 2e-12) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=tol, abs_tol=tol)
    except (TypeError, ValueError):
        return False


def parse_xml(path: Path, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise RemovalKinematicsError(f"{label} is invalid XML: {path}") from exc
    particle_node = root.find(".//particles")
    mass_node = root.find(".//massfluid")
    if particle_node is None or mass_node is None:
        raise RemovalKinematicsError(f"{label} lacks particles/massfluid metadata")
    try:
        count = int(next(node for node in root.iter("fluid") if "mkfluid" not in node.attrib).attrib["count"])
        mass = finite(mass_node.attrib["value"], f"{label} massfluid")
        mkfluidfirst = int(particle_node.attrib["mkfluidfirst"])
    except (StopIteration, KeyError, TypeError, ValueError) as exc:
        raise RemovalKinematicsError(f"{label} has invalid aggregate fluid metadata") from exc
    ranges: list[dict[str, Any]] = []
    for node in particle_node.findall("fluid"):
        if "mkfluid" not in node.attrib:
            continue
        try:
            mkfluid = int(node.attrib["mkfluid"])
            begin = int(node.attrib["begin"])
            n = int(node.attrib["count"])
        except (KeyError, ValueError) as exc:
            raise RemovalKinematicsError(f"{label} has invalid MK range") from exc
        if n <= 0:
            raise RemovalKinematicsError(f"{label} has an empty MK range")
        ranges.append({"mkfluid": mkfluid, "mk_absolute": mkfluidfirst + mkfluid, "begin": begin, "count": n, "end": begin + n})
    if not ranges or sum(item["count"] for item in ranges) != count:
        raise RemovalKinematicsError(f"{label} MK ranges do not sum to fluid count")
    return {"path": str(path), "sha256": sha256(path), "fluid_count": count, "massfluid_kg": mass,
            "initial_mass_kg": count * mass, "mkfluidfirst": mkfluidfirst, "ranges": ranges}


def mk_for_id(idp: int, metadata: dict[str, Any]) -> dict[str, int]:
    for item in metadata["ranges"]:
        if item["begin"] <= idp < item["end"]:
            return {"mkfluid": int(item["mkfluid"]), "mk_absolute": int(item["mk_absolute"])}
    raise RemovalKinematicsError(f"Idp {idp} is outside bound XML fluid ranges")


def normalize_xml(path: Path) -> bytes:
    root = ET.parse(path).getroot()
    for domain in list(root.iter("simulationdomain")):
        parent = next((node for node in root.iter() if domain in list(node)), None)
        if parent is not None:
            parent.remove(domain)
    return ET.tostring(root, encoding="utf-8")


def parse_runparts(path: Path, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov"}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise RemovalKinematicsError(f"{label} lacks the RunPARTs fields")
    rows: list[dict[str, Any]] = []
    totals = Counter()
    for raw in reader:
        try:
            part = int(raw["Part"].replace(",", ""))
            time_s = finite(raw["TimeStep [s]"], f"{label} time")
            counts = {key: int(raw[key].replace(",", "")) for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise RemovalKinematicsError(f"{label} has an invalid RunPARTs row") from exc
        if part != len(rows) or any(value < 0 for value in counts.values()):
            raise RemovalKinematicsError(f"{label} Part sequence/count is invalid")
        if rows and time_s <= rows[-1]["time_s"]:
            raise RemovalKinematicsError(f"{label} time is not increasing")
        if counts["NpOut"] != counts["NpOutPos"] + counts["NpOutRho"] + counts["NpOutMov"]:
            raise RemovalKinematicsError(f"{label} motive counts do not sum")
        previous_time_s = rows[-1]["time_s"] if rows else None
        row = {"part": part, "time_s": time_s, "previous_time_s": previous_time_s,
               "saved_record_bracket_s": [previous_time_s, time_s], **counts}
        rows.append(row)
        totals.update(counts)
    if not rows:
        raise RemovalKinematicsError(f"{label} is empty")
    return {"path": str(path), "sha256": sha256(path), "rows": rows, "by_part": {row["part"]: row for row in rows}, "totals": dict(totals)}


def parse_map_final(path: Path, label: str) -> dict[str, Any]:
    text = require_file(path, label).read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"MapRealPos\(final\)=\(([^)]*)\)-\(([^)]*)\)", text)
    if len(matches) != 1:
        raise RemovalKinematicsError(f"{label} must contain exactly one MapRealPos(final)")
    try:
        low = [finite(value.strip(), f"{label} lower bound") for value in matches[0][0].split(",")]
        high = [finite(value.strip(), f"{label} upper bound") for value in matches[0][1].split(",")]
    except Exception as exc:
        if isinstance(exc, RemovalKinematicsError):
            raise
        raise RemovalKinematicsError(f"{label} MapRealPos(final) is invalid") from exc
    if len(low) != 3 or len(high) != 3 or any(a >= b for a, b in zip(low, high)):
        raise RemovalKinematicsError(f"{label} MapRealPos(final) bounds are invalid")
    return {"path": str(path), "sha256": sha256(path), "low_m": low, "high_m": high,
            "predicate": "strict CSV coordinate comparison against printed Run.out bounds"}


def classify_faces(position: list[float], bounds: dict[str, Any]) -> list[str]:
    low, high = bounds["low_m"], bounds["high_m"]
    faces: list[str] = []
    for axis, index in (("x", 0), ("y", 1), ("z", 2)):
        if position[index] < low[index]:
            faces.append(f"{axis}_low")
        if position[index] > high[index]:
            faces.append(f"{axis}_high")
    return faces or ["inside"]


def parse_csv(path: Path, label: str, runparts: dict[str, Any], xml: dict[str, Any], bounds: dict[str, Any]) -> dict[str, Any]:
    path = require_file(path, label)
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream)
        fields = {str(name).strip() for name in (reader.fieldnames or [])}
        if not REQUIRED_CSV <= fields:
            raise RemovalKinematicsError(f"{label} lacks velocity/mass native columns")
        rows: list[dict[str, Any]] = []
        seen: set[int] = set()
        for raw in reader:
            item = {str(key).strip(): (value or "").strip() for key, value in raw.items() if key is not None}
            try:
                idp = int(item["Idp"])
                part = int(item["PartOut"])
                motive = int(item["Motive"])
                position = [finite(item[f"Pos.{axis} [m]"], f"{label} position") for axis in "xyz"]
                velocity = [finite(item[f"Vel.{axis} [m/s]"], f"{label} velocity") for axis in "xyz"]
                rhop = finite(item["Rhop [kg/m^3]"], f"{label} density")
            except (KeyError, TypeError, ValueError) as exc:
                raise RemovalKinematicsError(f"{label} row is invalid") from exc
            if idp in seen or idp < 0 or part < 1 or motive not in {1, 2, 3}:
                raise RemovalKinematicsError(f"{label} has duplicate Idp or invalid PartOut/Motive")
            if part not in runparts["by_part"]:
                raise RemovalKinematicsError(f"{label} PartOut is outside RunPARTs")
            runpart = runparts["by_part"][part]
            mk = mk_for_id(idp, xml)
            mass = xml["massfluid_kg"]
            momentum = [mass * component for component in velocity]
            speed2 = sum(component * component for component in velocity)
            rows.append({
                "idp": idp, "part": part, "time_s": runpart["time_s"],
                "saved_record_time_s": runpart["time_s"],
                "saved_record_bracket_s": list(runpart["saved_record_bracket_s"]),
                "motive_code": motive, "motive": {1: "position", 2: "density", 3: "movement"}[motive],
                "mkfluid": mk["mkfluid"], "mk_absolute": mk["mk_absolute"], "mass_kg": mass,
                "position_m": position, "velocity_m_s": velocity, "density_kg_m3": rhop,
                "faces": classify_faces(position, bounds),
                "momentum_kg_m_s": momentum, "momentum_norm_kg_m_s": math.sqrt(sum(value * value for value in momentum)),
                "kinetic_energy_j": 0.5 * mass * speed2,
            })
            seen.add(idp)
    if not rows:
        raise RemovalKinematicsError(f"{label} has no native rows")
    return {"path": str(path), "sha256": sha256(path), "rows": rows, "ids": sorted(seen), "motive_counts": dict(sorted(Counter(row["motive"] for row in rows).items()))}


def aggregate_time_mk_face(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, float, int, str], dict[str, Any]] = {}
    for row in rows:
        for face in row["faces"]:
            key = (row["part"], row["saved_record_time_s"], row["mk_absolute"], face)
            group = groups.setdefault(key, {"part": row["part"], "time_s": row["saved_record_time_s"],
                                             "saved_record_time_s": row["saved_record_time_s"],
                                             "saved_record_bracket_s": list(row["saved_record_bracket_s"]),
                                             "mk_absolute": row["mk_absolute"], "face": face,
                                             "native_count": 0, "mass_kg": 0.0, "momentum_kg_m_s": [0.0, 0.0, 0.0],
                                             "sum_particle_momentum_norm_kg_m_s": 0.0, "kinetic_energy_j": 0.0})
            group["native_count"] += 1
            group["mass_kg"] += row["mass_kg"]
            group["momentum_kg_m_s"] = [a + b for a, b in zip(group["momentum_kg_m_s"], row["momentum_kg_m_s"])]
            group["sum_particle_momentum_norm_kg_m_s"] += row["momentum_norm_kg_m_s"]
            group["kinetic_energy_j"] += row["kinetic_energy_j"]
    output = []
    for key in sorted(groups, key=lambda item: (item[0], item[2], FACE_ORDER.index(item[3]))):
        group = groups[key]
        group["vector_norm_kg_m_s"] = math.sqrt(sum(value * value for value in group["momentum_kg_m_s"]))
        output.append(group)
    return output


def validate_decoder_receipt(receipt_path: Path, csv_path: Path, raw_root: Path, raw_partout: Path, label: str) -> dict[str, Any]:
    _, receipt = read_json(receipt_path, label)
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise RemovalKinematicsError(f"{label} is not a completed decoder receipt")
    if Path(receipt.get("output_root", "")).resolve() != csv_path.parent.resolve():
        raise RemovalKinematicsError(f"{label} output root differs from CSV")
    command = receipt.get("command", [])
    if not isinstance(command, list):
        raise RemovalKinematicsError(f"{label} command is missing")
    try:
        tool_index = next(index for index, value in enumerate(command) if Path(str(value)).name == TOOL.name)
    except StopIteration as exc:
        raise RemovalKinematicsError(f"{label} command lacks official PartVTKOut") from exc
    actual = command[tool_index:]
    def after(option: str) -> str:
        if option not in actual or actual.index(option) + 1 >= len(actual):
            raise RemovalKinematicsError(f"{label} command lacks {option}")
        return str(actual[actual.index(option) + 1])
    if Path(after("-dirdata")).resolve() != raw_root.resolve() or Path(after("-savecsv")).resolve() != csv_path.resolve():
        raise RemovalKinematicsError(f"{label} decoder source/output path differs")
    if not Path(after("-saveresume")).resolve().is_file():
        # A receipt is allowed to use a path that the outer report materialized
        # after the native invocation; only the CSV is consumed here.
        pass
    input_launch = receipt.get("input_hashes_at_launch", {})
    input_finish = receipt.get("input_hashes_after_run", {})
    declared = receipt.get("request", {}).get("input_sha256", {})
    if input_launch and (input_launch != input_finish or declared != input_launch):
        raise RemovalKinematicsError(f"{label} input hashes are not stable")
    csv_meta = receipt.get("csv")
    if isinstance(csv_meta, dict) and (csv_meta.get("path") != str(csv_path) or csv_meta.get("sha256") != sha256(csv_path)):
        raise RemovalKinematicsError(f"{label} CSV digest/path differs")
    return {"path": str(receipt_path), "sha256": sha256(receipt_path), "schema": receipt.get("schema"), "status": receipt.get("status"),
            "raw_root": str(raw_root), "raw_partout": record(raw_partout, f"{label} raw PartOut")}


def validate_outer_report() -> dict[str, Any]:
    report_path, report = read_json(PAIR_RESULT, "expanded weighted report")
    if report.get("schema") != "ds02.stage2.f2-s1-fine-expanded-native-weighted.v1" or report.get("status") != "EXPANDED_NATIVE_WEIGHTED_RECONCILED":
        raise RemovalKinematicsError("expanded weighted report is not the completed v5 product")
    if report.get("physical_case_id") != PHYSICAL_CASE:
        raise RemovalKinematicsError("expanded weighted report physical case differs")
    manifest_ref = report.get("manifest")
    if not isinstance(manifest_ref, dict):
        raise RemovalKinematicsError("expanded weighted report lacks manifest binding")
    manifest_path = require_file(manifest_ref.get("path", ""), "expanded weighted manifest")
    if sha256(manifest_path) != manifest_ref.get("sha256"):
        raise RemovalKinematicsError("expanded weighted manifest digest differs")
    _, manifest = read_json(manifest_path, "expanded weighted manifest")
    if manifest.get("schema") != "ds02.stage2.f2-s1-fine-expanded-native-weighted-manifest.v1" or manifest.get("status") != "PREPARED_CONFIG_CLOSED_EXPANDED_NATIVE_WEIGHTED":
        raise RemovalKinematicsError("expanded weighted manifest is not config-closed")
    if manifest.get("physical_case_id") != PHYSICAL_CASE or manifest.get("original_case_id") != ORIGINAL_CASE or manifest.get("expanded_case_id") != EXPANDED_CASE:
        raise RemovalKinematicsError("expanded weighted manifest case identity differs")
    outer_path, outer = read_json(PAIR_EXECUTION_RECEIPT, "expanded weighted execution receipt")
    if outer.get("schema") != "ds02.execution-receipt.v1" or outer.get("status") != "completed" or int(outer.get("returncode", -1)) != 0:
        raise RemovalKinematicsError("expanded weighted execution receipt is not completed")
    if Path(outer.get("output_root", "")).resolve() != report_path.parent.resolve():
        raise RemovalKinematicsError("expanded weighted execution output root differs")
    selected: dict[str, Any] = {"report_path": report_path, "report": report, "manifest_path": manifest_path, "manifest": manifest,
                                "outer_receipt_path": outer_path, "outer_receipt": outer}
    original = manifest["source_cases"]["original"]
    expanded = manifest["source_cases"]["expanded"]
    decoder = report["official_expanded_decoder"]
    # The old original CSV/receipt is the completed source pair; the expanded
    # CSV/receipt are the v5 official decoder product.  Their bytes are all
    # small and are independently rehashed in prepare/run.
    selected["original"] = {"case_id": ORIGINAL_CASE, "csv_path": require_file(original["decoder_csv"]["path"], "original CSV"),
                             "decoder_receipt_path": require_file(original["decoder_receipt"]["path"], "original decoder receipt"),
                             "raw_root": Path(str(original["raw_root"])).resolve(), "raw_partout": require_file(original["raw_partout"]["path"], "original raw PartOut"),
                             "runparts_path": require_file(original["runparts"]["path"], "original RunPARTs"), "run_out_path": require_file(original["run_out"]["path"], "original Run.out"),
                             "xml_path": require_file(original["xml"]["path"], "original XML")}
    selected["expanded"] = {"case_id": EXPANDED_CASE, "csv_path": require_file(decoder["csv"]["path"], "expanded CSV"),
                             "decoder_receipt_path": require_file(decoder["receipt"]["path"], "expanded decoder receipt"),
                             "raw_root": Path(str(expanded["raw_root"])).resolve(), "raw_partout": require_file(expanded["raw_partout"]["path"], "expanded raw PartOut"),
                             "runparts_path": require_file(expanded["runparts"]["path"], "expanded RunPARTs"), "run_out_path": require_file(expanded["run_out"]["path"], "expanded Run.out"),
                             "xml_path": require_file(expanded["xml"]["path"], "expanded XML")}
    for key in ("original", "expanded"):
        row = selected[key]
        source = manifest["source_cases"][key]
        for field in ("runparts", "run_out", "raw_partout", "xml"):
            declared = source[field]
            actual = row[field + "_path"] if field in ("runparts", "run_out", "xml") else row[field]
            if str(actual) != str(Path(declared["path"]).resolve()) or sha256(actual) != declared["sha256"]:
                raise RemovalKinematicsError(f"{key} {field} differs from manifest source binding")
        csv_declared = source.get("decoder_csv")
        if csv_declared:
            if str(row["csv_path"]) != str(Path(csv_declared["path"]).resolve()) or sha256(row["csv_path"]) != csv_declared["sha256"]:
                raise RemovalKinematicsError(f"{key} CSV differs from manifest source binding")
        receipt_declared = source.get("decoder_receipt")
        if receipt_declared and sha256(row["decoder_receipt_path"]) != receipt_declared["sha256"]:
            raise RemovalKinematicsError(f"{key} decoder receipt differs from manifest source binding")
        if key == "expanded":
            if str(row["csv_path"]) != str(Path(decoder["csv"]["path"]).resolve()) or sha256(row["csv_path"]) != decoder["csv"]["sha256"]:
                raise RemovalKinematicsError("expanded decoder CSV differs from report binding")
            if sha256(row["decoder_receipt_path"]) != decoder["receipt"]["sha256"]:
                raise RemovalKinematicsError("expanded decoder receipt differs from report binding")
        for value in (row["runparts_path"], row["run_out_path"], row["xml_path"], row["raw_partout"], row["csv_path"], row["decoder_receipt_path"]):
            expected = manifest.get("input_sha256", {}).get(str(value))
            # Expanded decoder outputs are produced by the completed attempt
            # and are therefore absent from the prepared source manifest; the
            # report's decoder record supplies their binding instead.
            if expected is not None and expected != sha256(value):
                raise RemovalKinematicsError(f"manifest input digest changed: {value}")
    if normalize_xml(selected["original"]["xml_path"]) != normalize_xml(selected["expanded"]["xml_path"]):
        raise RemovalKinematicsError("original/expanded XML differs outside simulationdomain")
    # The outer receipt must have stable declared hashes for each solver/raw
    # source selected above.  This closes the source identity without reading
    # any trajectory file or recomputing the old solver receipt's H5 digest.
    outer_launch = outer.get("input_hashes_at_launch", {})
    outer_finish = outer.get("input_hashes_after_run", {})
    if outer_launch != outer_finish:
        raise RemovalKinematicsError("expanded weighted outer input hashes are unstable")
    for key in ("expanded", "original"):
        row = selected[key]
        for value in (row["raw_partout"], row["runparts_path"], row["run_out_path"], row["xml_path"]):
            declared = outer_launch.get(str(value))
            if declared is None or declared != sha256(value):
                raise RemovalKinematicsError(f"outer receipt does not bind {key} source: {value}")
    return selected


def build_case(case: dict[str, Any], *, selected: dict[str, Any]) -> dict[str, Any]:
    xml = parse_xml(case["xml_path"], f"{case['case_id']} XML")
    runparts = parse_runparts(case["runparts_path"], f"{case['case_id']} RunPARTs")
    bounds = parse_map_final(case["run_out_path"], f"{case['case_id']} Run.out")
    csv_data = parse_csv(case["csv_path"], f"{case['case_id']} native CSV", runparts, xml, bounds)
    csv_rows = csv_data["rows"]
    decoder_info = validate_decoder_receipt(case["decoder_receipt_path"], case["csv_path"], case["raw_root"], case["raw_partout"], f"{case['case_id']} decoder")
    return {
        "case_id": case["case_id"], "native_count": len(csv_rows), "native_motive_counts": dict(sorted(Counter(row["motive"] for row in csv_rows).items())),
        "first_native_time_s": min(row["saved_record_time_s"] for row in csv_rows), "last_native_time_s": max(row["saved_record_time_s"] for row in csv_rows),
        "time_semantics": {"saved_record_time": True, "event_time": "UNKNOWN_WITHIN_BRACKET",
                            "bracket_source": "previous and current RunPARTs saved records"},
        "initial_mass_basis": {"fluid_count": xml["fluid_count"], "particle_mass_kg": xml["massfluid_kg"], "whole_fluid_initial_mass_kg": xml["initial_mass_kg"], "mkfluidfirst": xml["mkfluidfirst"], "ranges": xml["ranges"]},
        "maprealpos_final": bounds,
        "face_counts": dict(sorted(Counter(face for row in csv_rows for face in row["faces"]).items())),
        "inside_count": sum(row["faces"] == ["inside"] for row in csv_rows),
        "per_mk_counts": dict(sorted(Counter(str(row["mk_absolute"]) for row in csv_rows).items())),
        "records": csv_rows,
        "time_mk_face_aggregates": aggregate_time_mk_face(csv_rows),
        "decoder_source": decoder_info,
        "interpretation": "removal-time source-visible m*v and kinetic-energy diagnostics; not a physical force/impulse/dynamics error",
    }


def audit(output_path: Path) -> dict[str, Any]:
    selected = validate_outer_report()
    original = build_case(selected["original"], selected=selected)
    expanded = build_case(selected["expanded"], selected=selected)
    if original["native_count"] != 175 or expanded["native_count"] != 111:
        raise RemovalKinematicsError("native counts differ from completed source report 175/111")
    if original["initial_mass_basis"] != expanded["initial_mass_basis"]:
        raise RemovalKinematicsError("original/expanded mass or MK basis differs")
    original_ids = {row["idp"] for row in original["records"]}
    expanded_ids = {row["idp"] for row in expanded["records"]}
    report_pair = selected["report"]["paired_weighted_impact"]
    if report_pair["original"]["native_count"] != original["native_count"] or report_pair["expanded"]["native_count"] != expanded["native_count"]:
        raise RemovalKinematicsError("source report weighted counts do not match CSV counts")
    result = {
        "schema": OUTPUT_SCHEMA,
        "status": "NATIVE_REMOVAL_KINEMATICS_SOURCE_CLOSED",
        "source_report": record(selected["report_path"], "expanded weighted report"),
        "source_manifest": record(selected["manifest_path"], "expanded weighted manifest"),
        "source_execution_receipt": record(selected["outer_receipt_path"], "expanded weighted execution receipt"),
        "physical_case_id": PHYSICAL_CASE,
        "paired_control": {"same_current_case": True, "same_initial_mass_basis": True, "only_numerical_domain_changed": True,
                            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "original": original,
        "expanded": expanded,
        "native_id_set_comparison": {"original_only_count": len(original_ids - expanded_ids), "expanded_only_count": len(expanded_ids - original_ids), "shared_count": len(original_ids & expanded_ids),
                                      "original_only_ids": sorted(original_ids - expanded_ids), "expanded_only_ids": sorted(expanded_ids - original_ids)},
        "native_visibility_difference": {"original_minus_expanded_count": original["native_count"] - expanded["native_count"],
                                          "mass_lower_bound_difference_kg": (original["native_count"] - expanded["native_count"]) * original["initial_mass_basis"]["particle_mass_kg"],
                                          "expanded_unknown_mass_fraction_lower_bound": expanded["native_count"] * original["initial_mass_basis"]["particle_mass_kg"] / original["initial_mass_basis"]["whole_fluid_initial_mass_kg"],
                                          "mass_gate_fraction": 0.003,
                                          "qualification": "mass visibility screen only; expanded value remains above 0.003 and does not bound dynamics"},
        "aggregation_semantics": {"group_keys": ["saved PartOut/RunPARTs part", "saved record time_s", "source MK", "printed MapRealPos(final) face"],
                                   "time_semantics": "saved record time with event time UNKNOWN within saved_record_bracket_s=[previous Part time,current Part time]",
                                   "cross_time_sum_forbidden": True,
                                   "face_membership_is_incidence": True,
                                   "multi_face_row_warning": "a row outside more than one printed face contributes to each face incidence; face-group mass/momentum/energy must not be summed as a disjoint partition",
                                   "meaning": "per-removal-time source-visible particle momentum and kinetic-energy contributions; not a system momentum difference, force integral, impulse, or dynamics-error bound",
                                   "face_predicate": "strict CSV coordinate comparison against printed MapRealPos(final); binary native predicate precision is not inferred"},
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
        "next_evidence": {"required": ["calibrated fluid/rigid observer comparison in the paired runs", "physical destination/fate evidence", "if force/impulse is needed, source-bound time-aligned retained-body/fluid records"],
                           "no_claim_from_removal_kinematics": True},
    }
    atomic_json(output_path, result)
    return {"status": result["status"], "output": str(output_path.resolve()), "original_native_count": original["native_count"], "expanded_native_count": expanded["native_count"], "h5_opened": False}


def prepare(output_dir: Path, variant: str = "v3") -> dict[str, Any]:
    if not re.fullmatch(r"v[0-9]+", variant):
        raise RemovalKinematicsError(f"invalid request variant: {variant}")
    # Preparation binds the already completed result and selected small source
    # files.  It does not open trajectory inventories or launch the official
    # decoder again.
    selected = validate_outer_report()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = [SCRIPT, PAIR_RESULT, PAIR_EXECUTION_RECEIPT, selected["manifest_path"], TOOL, CONFIG]
    for key in ("original", "expanded"):
        row = selected[key]
        files.extend([row["csv_path"], row["decoder_receipt_path"], row["raw_partout"], row["runparts_path"], row["run_out_path"], row["xml_path"]])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in files:
        path = require_file(path, f"kinematics request input {path.name}")
        if path.name.startswith("Part_") and path.name.endswith(".bi4") or path.suffix.lower() in {".h5", ".hdf5"}:
            raise RemovalKinematicsError(f"trajectory/H5 input entered kinematics request: {path}")
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    hashes = {str(path): sha256(path) for path in unique}
    name = f"f2-s1-fine-native-removal-kinematics-{variant}"
    manifest_path = output_dir / f"{name}-manifest.json"
    request_path = output_dir / f"{name}-request.json"
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "PREPARED_SOURCE_CLOSED_NO_H5",
        "physical_case_id": PHYSICAL_CASE, "original_case_id": ORIGINAL_CASE, "expanded_case_id": EXPANDED_CASE,
        "source_report": record(PAIR_RESULT, "expanded weighted report"), "source_execution_receipt": record(PAIR_EXECUTION_RECEIPT, "expanded weighted execution receipt"),
        "input_files": sorted(hashes), "input_sha256": dict(sorted(hashes.items())),
        "source_scope": {"original_native_csv_reused": True, "expanded_native_csv_reused": True, "official_decoder_rerun": False, "h5_opened": False, "trajectory_content_opened": False, "solver_started": False},
        "diagnostics": {"fields": ["initial-mass-weighted momentum m*v", "particle kinetic energy 0.5*m*|v|^2", "saved removal time", "source MK", "printed final MapRealPos face"], "cross_time_sum_forbidden": True, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
    }
    atomic_json(manifest_path, manifest)
    request_hashes = dict(hashes); request_hashes[str(manifest_path)] = sha256(manifest_path)
    request = {
        "schema": "ds02.request.v1", "family_id": "F2", "case_id": "F2_S1_FINE_NATIVE_REMOVAL_KINEMATICS_V3", "physical_case_id": PHYSICAL_CASE,
        "attempt_id": f"{name}-primary-001", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 900, "estimated_storage_bytes": 128 * 1024 * 1024, "cwd": str(SCRIPT.parent), "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", f"{{attempt_root}}/{name}.json"],
        "input_files": sorted(request_hashes), "input_sha256": dict(sorted(request_hashes.items())),
        "source_read_cost": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "raw_partout_bytes_read": sum(path.stat().st_size for path in unique if path.name == "PartOut_000.obi4"), "csv_runparts_xml_bytes_read": sum(path.stat().st_size for path in unique if path.suffix.lower() in {".csv", ".xml"}), "runtime_pre_post_hash_bytes": 2 * sum(path.stat().st_size for path in unique), "estimated_output_bytes": 128 * 1024 * 1024},
        "source_scope": {"completed_official_csv_only": True, "original_native_count": 175, "expanded_native_count": 111, "decoder_rerun": False, "solver_launch_forbidden": True, "h5_content_read": False},
        "launch_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "canonical_ready": True, "launch": True, "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "primary_launch_owner": "root", "shared_lease_required": True, "foreign_process_protection_required": True,
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "request_note": "Read-only source-bound removal-time m*v and 0.5*m*v^2 audit for completed original175/expanded111 official native CSVs. Aggregates remain per saved time/MK/printed boundary face; no cross-time system momentum/force interpretation. No H5, trajectory, decoder, solver, CFD, or model.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "request": str(request_path), "request_sha256": sha256(request_path), "input_count": len(unique), "h5_opened": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("--output-dir", type=Path, required=True); prep.add_argument("--variant", default="v3")
    aud = sub.add_parser("audit"); aud.add_argument("--manifest", type=Path, required=True); aud.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.output_dir, args.variant)
        else:
            manifest_path, manifest = read_json(args.manifest, "kinematics manifest")
            if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_SOURCE_CLOSED_NO_H5":
                raise RemovalKinematicsError("kinematics manifest schema/status differs")
            for path_text, expected in manifest.get("input_sha256", {}).items():
                path = require_file(path_text, "kinematics source input")
                if path.suffix.lower() in {".h5", ".hdf5"} or (path.name.startswith("Part_") and path.name.endswith(".bi4")):
                    raise RemovalKinematicsError(f"forbidden trajectory/H5 input: {path}")
                if sha256(path) != expected:
                    raise RemovalKinematicsError(f"kinematics source input changed: {path}")
            result = audit(args.output)
    except RemovalKinematicsError as exc:
        raise SystemExit(f"RemovalKinematicsError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
