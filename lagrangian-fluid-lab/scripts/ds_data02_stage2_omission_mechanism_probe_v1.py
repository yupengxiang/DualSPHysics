#!/usr/bin/env python3
"""Source-closed mechanism probe for F2/scan048 and F4 density exclusions.

This forward-only audit consumes the completed all-118 mechanism ledger and
its already-produced small native sidecars.  It compares the previous known
state and the PartVTKOut saved endpoint with the printed final MapRealPos and
RhopOut bounds, then reports per-saved-record ``m*v`` and ``0.5*m*|v|^2``.

The comparisons identify numerical gate consistency only.  They do not assign
physical destination, legal outflow, re-entry, force, impulse, or a dynamics
error.  RunPARTs supplies a saved-record time and the adjacent saved-record
bracket; the exact particle event time remains UNKNOWN.  H5, Part_*.bi4,
raw PartOut binaries, decoder, solver, CFD, and model execution are forbidden.
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
from collections import Counter, defaultdict
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SOURCE_REPORT_DEFAULT = DATA_ROOT / (
    "families/infra/STAGE2_OMISSION_MECHANISM_BOUNDS_118_V1/"
    "omission-mechanism-bounds-v2-primary-001-v5/omission-mechanism-bounds-v2.json"
)
RUNTIME_V6 = SCRIPT.parent / "ds_data02_runtime_v6.py"
DISPATCH_V6 = SCRIPT.parent / "ds_data02_stage2_dispatch_v6.py"
STRICT_V6 = SCRIPT.parent / "ds_data02_strict_dispatch_v6.py"
OUTPUT_SCHEMA = "ds02.stage2.omission-mechanism-probe.v1"
MANIFEST_SCHEMA = "ds02.stage2.omission-mechanism-probe-manifest.v1"
SOURCE_REPORT_SCHEMA = "ds02.stage2.omission-mechanism-bounds.v1"
MASS_GATE = 0.003
F2_CASE_KEY = "F2/scan-F2-048-001"
FAMILY_COUNTS = {"F2": 1, "F4": 22}
REQUIRED_CSV = {
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "PartOut", "Motive", "Idp",
    "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]",
}
MAP_RE = re.compile(r"MapRealPos\(final\)=\(([^)]*)\)-\(([^)]*)\)")


class MechanismProbeError(RuntimeError):
    """Raised when the selected source closure or diagnostic contract opens."""


def sha256(value: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(value).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise MechanismProbeError(f"{label} is missing: {path}")
    return path


def require_dir(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise MechanismProbeError(f"{label} is missing or not a directory: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MechanismProbeError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise MechanismProbeError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise MechanismProbeError(f"refuse to overwrite existing output: {path}")
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


def small_binding(value: Path | str, label: str, *, expected_sha256: str | None = None) -> dict[str, Any]:
    path = require_file(value, label)
    lower = path.suffix.lower()
    if lower in {".h5", ".hdf5", ".obi4"} or (path.name.startswith("Part_") and path.name.endswith(".bi4")):
        raise MechanismProbeError(f"trajectory/raw PartOut input is forbidden: {path}")
    digest = sha256(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise MechanismProbeError(f"{label} digest differs: {path}")
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MechanismProbeError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise MechanismProbeError(f"{label} is not finite")
    return result


def vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise MechanismProbeError(f"{label} is not a 3-vector")
    return [finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def interval(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise MechanismProbeError(f"{label} is not a two-point interval")
    left, right = finite(value[0], f"{label}[0]"), finite(value[1], f"{label}[1]")
    if left > right:
        raise MechanismProbeError(f"{label} is reversed")
    return [left, right]


def close(left: Any, right: Any, *, abs_tol: float = 2e-6, rel_tol: float = 2e-12) -> bool:
    try:
        return math.isclose(float(left), float(right), abs_tol=abs_tol, rel_tol=rel_tol)
    except (TypeError, ValueError):
        return False


def parse_run_out(path: Path) -> dict[str, Any]:
    path = require_file(path, "solver Run.out")
    text = path.read_text(encoding="utf-8", errors="replace")
    match = MAP_RE.search(text)
    if match is None:
        raise MechanismProbeError(f"Run.out lacks MapRealPos(final): {path}")
    low = vector([item.strip() for item in match.group(1).split(",")], "MapRealPos(final) low")
    high = vector([item.strip() for item in match.group(2).split(",")], "MapRealPos(final) high")
    if any(a >= b for a, b in zip(low, high)):
        raise MechanismProbeError(f"Run.out MapRealPos(final) bounds are invalid: {path}")
    if not re.search(r"RhopOut\s*=\s*True", text, flags=re.IGNORECASE):
        raise MechanismProbeError(f"Run.out does not declare RhopOut=True: {path}")
    rhop_min = re.search(r"RhopOutMin\s*=\s*([-+0-9.eE]+)", text)
    rhop_max = re.search(r"RhopOutMax\s*=\s*([-+0-9.eE]+)", text)
    if rhop_min is None or rhop_max is None:
        raise MechanismProbeError(f"Run.out lacks RhopOut thresholds: {path}")
    minimum, maximum = finite(rhop_min.group(1), "RhopOutMin"), finite(rhop_max.group(1), "RhopOutMax")
    if minimum >= maximum:
        raise MechanismProbeError(f"Run.out RhopOut thresholds are invalid: {path}")
    return {
        "source": small_binding(path, "Run.out"),
        "maprealpos_final_m": {"low": low, "high": high, "predicate": "printed decimal endpoint comparison only"},
        "rhop_out_kg_m3": {"enabled": True, "min": minimum, "max": maximum, "predicate": "strict endpoint density comparison"},
    }


def parse_runparts(path: Path) -> dict[str, Any]:
    path = require_file(path, "RunPARTs.csv")
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov"}
    fields = {str(name).strip() for name in (reader.fieldnames or [])}
    if not required <= fields:
        raise MechanismProbeError(f"RunPARTs lacks required fields: {path}")
    rows: list[dict[str, Any]] = []
    totals = Counter()
    for raw in reader:
        item = {str(key).strip(): (value or "").strip() for key, value in raw.items() if key is not None}
        try:
            part = int(item["Part"].replace(",", ""))
            time_s = finite(item["TimeStep [s]"], "RunPARTs time")
            counts = {key: int(item[key].replace(",", "")) for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
        except (KeyError, TypeError, ValueError) as exc:
            raise MechanismProbeError(f"RunPARTs row is invalid: {path}") from exc
        if part != len(rows) or any(value < 0 for value in counts.values()):
            raise MechanismProbeError(f"RunPARTs part sequence/count is invalid: {path}")
        if rows and time_s <= rows[-1]["time_s"]:
            raise MechanismProbeError(f"RunPARTs time is not increasing: {path}")
        if counts["NpOut"] != counts["NpOutPos"] + counts["NpOutRho"] + counts["NpOutMov"]:
            raise MechanismProbeError(f"RunPARTs motive counts do not sum: {path}")
        previous = rows[-1]["time_s"] if rows else None
        row = {"part": part, "time_s": time_s, "previous_time_s": previous,
               "saved_record_bracket_s": [previous, time_s], **counts}
        rows.append(row)
        totals.update(counts)
    if not rows:
        raise MechanismProbeError(f"RunPARTs is empty: {path}")
    return {"source": small_binding(path, "RunPARTs"), "rows": rows,
            "by_part": {row["part"]: row for row in rows}, "totals": dict(totals)}


def parse_native_csv(path: Path) -> dict[str, Any]:
    path = require_file(path, "PartVTKOut CSV")
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream)
        fields = {str(name).strip() for name in (reader.fieldnames or [])}
        if not REQUIRED_CSV <= fields:
            raise MechanismProbeError(f"native CSV lacks required fields: {path}")
        rows: list[dict[str, Any]] = []
        by_id: dict[int, dict[str, Any]] = {}
        for raw in reader:
            item = {str(key).strip(): (value or "").strip() for key, value in raw.items() if key is not None}
            try:
                idp = int(item["Idp"])
                part = int(item["PartOut"])
                motive = int(item["Motive"])
                position = [finite(item[f"Pos.{axis} [m]"], f"native CSV position {axis}") for axis in "xyz"]
                velocity = [finite(item[f"Vel.{axis} [m/s]"], f"native CSV velocity {axis}") for axis in "xyz"]
                density = finite(item["Rhop [kg/m^3]"], "native CSV density")
            except (KeyError, TypeError, ValueError) as exc:
                raise MechanismProbeError(f"native CSV row is invalid: {path}") from exc
            if idp in by_id or part < 1 or motive not in {1, 2, 3}:
                raise MechanismProbeError(f"native CSV duplicate/invalid identity: {path}")
            row = {"idp": idp, "part": part, "motive_code": motive, "position_m": position,
                   "velocity_m_s": velocity, "density_kg_m3": density}
            rows.append(row)
            by_id[idp] = row
    return {"source": small_binding(path, "PartVTKOut CSV"), "rows": rows, "by_id": by_id}


def validate_decoder_receipt(receipt_path: Path, csv_path: Path, data_root: Path, tool_path: Path) -> dict[str, Any]:
    path, receipt = read_json(receipt_path, "PartVTKOut execution receipt")
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise MechanismProbeError(f"native decoder receipt is not completed: {path}")
    command = receipt.get("command", [])
    if not isinstance(command, list):
        raise MechanismProbeError(f"native decoder command is absent: {path}")
    try:
        index = next(i for i, value in enumerate(command) if Path(str(value)).name == tool_path.name)
    except StopIteration as exc:
        raise MechanismProbeError(f"native decoder tool is absent from command: {path}") from exc
    actual = command[index:]
    def option(name: str) -> str:
        try:
            return str(actual[actual.index(name) + 1])
        except (ValueError, IndexError) as exc:
            raise MechanismProbeError(f"native decoder command lacks {name}: {path}") from exc
    if Path(option("-dirdata")).resolve() != data_root.resolve() or Path(option("-savecsv")).resolve() != csv_path.resolve():
        raise MechanismProbeError(f"native decoder source/output differs: {path}")
    output_root = receipt.get("output_root")
    if output_root is not None and Path(str(output_root)).resolve() != csv_path.parent.resolve():
        raise MechanismProbeError(f"native decoder output root differs: {path}")
    return {"source": small_binding(path, "PartVTKOut receipt"), "status": receipt.get("status"), "command": command}


def classify_position(position: list[float], bounds: dict[str, Any]) -> list[str]:
    low, high = bounds["low"], bounds["high"]
    labels: list[str] = []
    for axis, index in zip("xyz", range(3)):
        if position[index] < low[index]:
            labels.append(f"{axis}_low")
        if position[index] > high[index]:
            labels.append(f"{axis}_high")
    return labels or ["inside"]


def classify_density(density: float, rhop: dict[str, Any]) -> str:
    if density < rhop["min"]:
        return "below_min"
    if density > rhop["max"]:
        return "above_max"
    return "inside_gate"


def summarize_case(case: dict[str, Any], forensic: dict[str, Any], scan: dict[str, Any],
                   runparts: dict[str, Any], native: dict[str, Any], runout: dict[str, Any]) -> dict[str, Any]:
    family = str(case["family_id"])
    if family not in FAMILY_COUNTS or forensic.get("family_id") != family:
        raise MechanismProbeError(f"case family differs: {case.get('case_key')}")
    if forensic.get("physical_case_id") != case.get("physical_case_id") or scan.get("physical_case_id") != case.get("physical_case_id"):
        raise MechanismProbeError(f"case identity differs: {case.get('case_key')}")
    rows = forensic.get("excluded_particles", [])
    if not isinstance(rows, list) or not rows:
        raise MechanismProbeError(f"forensic rows are absent: {case.get('case_key')}")
    report_rows = {int(row["idp"]): row for row in case.get("particles", [])}
    if set(report_rows) != {int(row["idp"]) for row in rows}:
        raise MechanismProbeError(f"mechanism/forensic identity differs: {case.get('case_key')}")
    if len(native["rows"]) != len(rows):
        raise MechanismProbeError(f"native CSV count differs: {case.get('case_key')}")
    motive_name = {1: "position", 2: "density", 3: "movement"}
    endpoint_pairs: list[dict[str, Any]] = []
    previous_position_counts = Counter()
    endpoint_position_counts = Counter()
    density_counts = Counter()
    saved: dict[int, dict[str, Any]] = {}
    masses = {idp: finite(row.get("initial_mass_kg"), "initial particle mass") for idp, row in report_rows.items()}
    for source_row in rows:
        idp = int(source_row["idp"])
        csv_row = native["by_id"].get(idp)
        if csv_row is None:
            raise MechanismProbeError(f"native CSV omits forensic Idp {idp}: {case.get('case_key')}")
        motive = int(source_row["native_motive_code"])
        if csv_row["motive_code"] != motive or motive_name[motive] != source_row.get("native_motive"):
            raise MechanismProbeError(f"native CSV motive differs for Idp {idp}")
        if csv_row["part"] != int(source_row["first_missing_frame"]):
            raise MechanismProbeError(f"native CSV PartOut differs from first missing frame for Idp {idp}")
        if csv_row["part"] not in runparts["by_part"]:
            raise MechanismProbeError(f"native CSV PartOut is outside RunPARTs for Idp {idp}")
        endpoint = vector(source_row["partvtkout_position_m"], "forensic endpoint position")
        if any(not close(a, b) for a, b in zip(endpoint, csv_row["position_m"])):
            raise MechanismProbeError(f"native CSV position differs for Idp {idp}")
        endpoint_density = finite(source_row["partvtkout_density_kg_m3"], "forensic endpoint density")
        if not close(endpoint_density, csv_row["density_kg_m3"], abs_tol=2e-3):
            raise MechanismProbeError(f"native CSV density differs for Idp {idp}")
        previous = source_row.get("first_gap_previous_state")
        if not isinstance(previous, dict):
            raise MechanismProbeError(f"first gap previous state is absent for Idp {idp}")
        previous_position = vector(previous.get("position_m"), "first gap previous position")
        previous_labels = classify_position(previous_position, runout["maprealpos_final_m"])
        endpoint_labels = classify_position(endpoint, runout["maprealpos_final_m"])
        previous_position_counts.update(previous_labels)
        endpoint_position_counts.update(endpoint_labels)
        density_class = classify_density(endpoint_density, runout["rhop_out_kg_m3"])
        density_counts[density_class] += 1
        record = runparts["by_part"][csv_row["part"]]
        mass = masses[idp]
        momentum = [mass * component for component in csv_row["velocity_m_s"]]
        speed2 = sum(component * component for component in csv_row["velocity_m_s"])
        group = saved.setdefault(csv_row["part"], {
            "part": csv_row["part"], "saved_record_time_s": record["time_s"],
            "saved_record_bracket_s": list(record["saved_record_bracket_s"]),
            "motive": motive_name[motive], "native_count": 0, "mass_kg": 0.0,
            "momentum_kg_m_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0,
        })
        if group["motive"] != motive_name[motive]:
            raise MechanismProbeError(f"RunPARTs PartOut mixes motives unexpectedly: {case.get('case_key')}")
        group["native_count"] += 1
        group["mass_kg"] += mass
        group["momentum_kg_m_s"] = [a + b for a, b in zip(group["momentum_kg_m_s"], momentum)]
        group["kinetic_energy_j"] += 0.5 * mass * speed2
        endpoint_pairs.append({
            "zone": int(source_row.get("zone", 0)), "idp": idp,
            "first_missing_bracket_s": source_row["first_missing_bracket_s"],
            "saved_record_time_s": record["time_s"],
            "saved_record_bracket_s": list(record["saved_record_bracket_s"]),
            "native_motive": motive_name[motive], "native_motive_code": motive,
            "previous_position_class": previous_labels, "endpoint_position_class": endpoint_labels,
            "endpoint_density_class": density_class,
            "endpoint_position_m": endpoint, "endpoint_density_kg_m3": endpoint_density,
            "mass_kg": mass, "momentum_kg_m_s": momentum,
            "kinetic_energy_j": 0.5 * mass * speed2,
        })
    totals = runparts["totals"]
    expected_motive_key = {"position": "NpOutPos", "density": "NpOutRho", "movement": "NpOutMov"}[motive_name[int(rows[0]["native_motive_code"])] ]
    if totals.get("NpOut", -1) != len(rows) or totals.get(expected_motive_key, -1) != len(rows):
        raise MechanismProbeError(f"RunPARTs totals do not close native rows: {case.get('case_key')}")
    first_windows = [interval(row["first_missing_bracket_s"], "first missing bracket") for row in rows]
    return {
        "case_key": case["case_key"], "family_id": family, "physical_case_id": case["physical_case_id"],
        "native_gate": {
            "motive": motive_name[int(rows[0]["native_motive_code"])], "native_count": len(rows),
            "runparts_totals": totals, "cause": case["native_cause"],
            "credit": "native PartVTKOut/RunPARTs gate only; legal outflow and physical destination are UNKNOWN",
        },
        "mass_visibility": case["mass_visibility"],
        "first_missing_window_s": [min(item[0] for item in first_windows), max(item[1] for item in first_windows)],
        "printed_final_bounds_observation": {
            **runout,
            "previous_state_position_classes": dict(sorted(previous_position_counts.items())),
            "native_endpoint_position_classes": dict(sorted(endpoint_position_counts.items())),
            "temporal_scope": "Run.out final printed bounds; deletion-time dynamic bounds UNKNOWN",
            "endpoint_predicate_precision": "decimal CSV/Run.out comparison only; exact native binary predicate UNKNOWN",
        },
        "density_gate_observation": {
            "counts": dict(sorted(density_counts.items())),
            "temporal_scope": "saved native endpoint density; exact physical event time UNKNOWN",
            "threshold_source": "Run.out RhopOutMin/RhopOutMax",
        },
        "saved_record_impacts": [saved[key] for key in sorted(saved)],
        "impact_units": {
            "mass": "kg", "momentum": "kg*m/s", "kinetic_energy": "J",
            "aggregation": "per saved PartOut/RunPARTs record; cross-time system sums forbidden",
        },
        "particle_observations": endpoint_pairs,
        "physical_fate": "UNKNOWN", "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
        "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
    }


def source_cases(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("schema") != SOURCE_REPORT_SCHEMA or report.get("status") != "MECHANISM_BOUNDS_AUDITED_TYPED_NATIVE_SOURCE_CLOSED":
        raise MechanismProbeError("all-118 source report is not the completed mechanism ledger")
    cases = report.get("cases", [])
    by_key = {case.get("case_key"): case for case in cases}
    if F2_CASE_KEY not in by_key:
        raise MechanismProbeError("F2/scan-F2-048-001 is absent from all-118 report")
    selected = [by_key[F2_CASE_KEY]]
    f4 = [case for case in cases if case.get("family_id") == "F4" and case.get("native_cause", {}).get("motive_counts", {}) == {"density": int(case.get("native_cause", {}).get("exit_cause_counts", {}).get("NUMERICAL_DENSITY_EXCLUSION", -1))}]
    if len(f4) != FAMILY_COUNTS["F4"]:
        raise MechanismProbeError(f"expected 22 F4 density cases, found {len(f4)}")
    selected.extend(sorted(f4, key=lambda case: str(case["case_key"])))
    return selected


def load_case(case: dict[str, Any]) -> tuple[dict[str, Any], list[Path]]:
    bindings = case.get("source_bindings", {})
    forensic_decl = bindings.get("forensic", {})
    scan_decl = bindings.get("scan", {})
    receipt_decl = bindings.get("scan_receipt", {})
    forensic_path, forensic = read_json(forensic_decl.get("path", ""), f"{case['case_key']} forensic")
    if sha256(forensic_path) != forensic_decl.get("sha256"):
        raise MechanismProbeError(f"forensic binding differs: {case['case_key']}")
    scan_path, scan = read_json(scan_decl.get("path", ""), f"{case['case_key']} scan")
    if sha256(scan_path) != scan_decl.get("sha256") or scan.get("physical_case_id") != case.get("physical_case_id"):
        raise MechanismProbeError(f"scan binding/identity differs: {case['case_key']}")
    receipt_path, receipt = read_json(receipt_decl.get("path", ""), f"{case['case_key']} scan receipt")
    if sha256(receipt_path) != receipt_decl.get("sha256") or receipt.get("status") != "completed":
        raise MechanismProbeError(f"scan receipt is not completed/bound: {case['case_key']}")
    provenance = forensic.get("source_provenance", {})
    native_decl = forensic.get("native_decode", {})
    if not isinstance(provenance, dict) or not isinstance(native_decl, dict):
        raise MechanismProbeError(f"native/source provenance is absent: {case['case_key']}")
    data_root = require_dir(provenance.get("data_root", ""), f"{case['case_key']} solver data root")
    xml_decl = provenance.get("generated_xml", {})
    solver_decl = provenance.get("solver_receipt", {})
    gencase_decl = provenance.get("gencase_receipt", {})
    conversion_decl = forensic.get("trajectory", {}).get("conversion_report", {})
    xml_path = require_file(xml_decl.get("path", ""), f"{case['case_key']} generated XML")
    solver_path = require_file(solver_decl.get("path", ""), f"{case['case_key']} solver receipt")
    gencase_path = require_file(gencase_decl.get("path", ""), f"{case['case_key']} GenCase receipt")
    conversion_path = require_file(conversion_decl.get("path", ""), f"{case['case_key']} conversion report")
    small_binding(xml_path, "generated XML", expected_sha256=xml_decl.get("sha256"))
    small_binding(solver_path, "solver receipt", expected_sha256=solver_decl.get("sha256"))
    small_binding(gencase_path, "GenCase receipt", expected_sha256=gencase_decl.get("sha256"))
    conversion_binding = small_binding(conversion_path, "conversion report", expected_sha256=conversion_decl.get("sha256"))
    _, solver_receipt = read_json(solver_path, f"{case['case_key']} solver receipt")
    _, gencase_receipt = read_json(gencase_path, f"{case['case_key']} GenCase receipt")
    for label, receipt in (("solver", solver_receipt), ("GenCase", gencase_receipt)):
        if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
            raise MechanismProbeError(f"{label} receipt is not completed: {case['case_key']}")
    _, conversion = read_json(conversion_path, f"{case['case_key']} conversion report")
    trajectory = forensic.get("trajectory", {})
    if conversion.get("conversion_status") != "completed" or conversion.get("output_hdf5") != trajectory.get("path") or conversion.get("output_sha256") != trajectory.get("sha256"):
        raise MechanismProbeError(f"conversion/H5 metadata is not source-closed: {case['case_key']}")
    native_csv_decl = native_decl.get("partout", {})
    runparts_decl = native_decl.get("runparts", {})
    decoder_receipt_decl = native_decl.get("receipt", {})
    tool_decl = native_decl.get("binary", {})
    csv_path = require_file(native_csv_decl.get("path", ""), f"{case['case_key']} PartVTKOut CSV")
    runparts_path = require_file(runparts_decl.get("path", ""), f"{case['case_key']} RunPARTs")
    decoder_receipt_path = require_file(decoder_receipt_decl.get("path", ""), f"{case['case_key']} PartVTKOut receipt")
    tool_path = require_file(tool_decl.get("path", ""), f"{case['case_key']} PartVTKOut binary")
    native_binding = small_binding(csv_path, "PartVTKOut CSV", expected_sha256=native_csv_decl.get("sha256"))
    runparts = parse_runparts(runparts_path)
    if runparts["source"]["sha256"] != runparts_decl.get("sha256"):
        raise MechanismProbeError(f"RunPARTs binding differs: {case['case_key']}")
    if int(native_decl.get("runparts_row_count", -1)) != len(runparts["rows"]):
        raise MechanismProbeError(f"RunPARTs row count differs from decoder receipt: {case['case_key']}")
    if native_decl.get("runparts_totals") != runparts["totals"]:
        raise MechanismProbeError(f"RunPARTs totals differ from decoder receipt: {case['case_key']}")
    validate_decoder_receipt(decoder_receipt_path, csv_path, data_root, tool_path)
    small_binding(decoder_receipt_path, "PartVTKOut receipt", expected_sha256=decoder_receipt_decl.get("sha256"))
    tool_binding = small_binding(tool_path, "PartVTKOut binary", expected_sha256=tool_decl.get("sha256"))
    native = parse_native_csv(csv_path)
    runout = parse_run_out(data_root.parent / "Run.out")
    output = summarize_case(case, forensic, scan, runparts, native, runout)
    output["source_files"] = {
        "forensic": small_binding(forensic_path, "forensic sidecar"),
        "scan": small_binding(scan_path, "scientific scan"),
        "scan_receipt": small_binding(receipt_path, "scan receipt"),
        "xml": small_binding(xml_path, "generated XML", expected_sha256=xml_decl.get("sha256")),
        "solver_receipt": small_binding(solver_path, "solver receipt", expected_sha256=solver_decl.get("sha256")),
        "gencase_receipt": small_binding(gencase_path, "GenCase receipt", expected_sha256=gencase_decl.get("sha256")),
        "conversion_report": conversion_binding,
        "run_out": runout["source"],
        "runparts": runparts["source"],
        "native_csv": native_binding,
        "decoder_receipt": small_binding(decoder_receipt_path, "PartVTKOut receipt", expected_sha256=decoder_receipt_decl.get("sha256")),
        "partvtk_binary": tool_binding,
    }
    return output, [Path(item["path"]) for item in output["source_files"].values()]


def control_plan(cases: list[dict[str, Any]]) -> dict[str, Any]:
    f2 = next((case for case in cases if case["case_key"] == F2_CASE_KEY),
              next(case for case in cases if case.get("family_id") == "F2"))
    return {
        "F2": {
            "status": "PLANNED_NOT_EXECUTED",
            "control_id": "F2_SCAN048_NUMERICAL_DOMAIN_ONLY_PAIRED_V1",
            "factor": "numerical MapRealPos/domain bounds only",
            "preserve": ["exact CURRENT physical case/XML/BI4", "mass and dp/CFL", "wetted geometry and moving source", "solver physics and save cadence"],
            "observed_endpoint_cover_bounds_m": {
                "low": [min(row["endpoint_position_m"][axis] for row in f2["particle_observations"]) for axis in range(3)],
                "high": [max(row["endpoint_position_m"][axis] for row in f2["particle_observations"]) for axis in range(3)],
            },
            "comparison": "native count/motive, first-gap brackets, endpoint positions and saved-record observers",
            "qualification": "changed position count is numerical-gate sensitivity only; legal flux and physical fate remain UNKNOWN",
            "required_margin_rule": "freeze a source-precision margin before launch; do not infer exact native binary predicate from printed decimal bounds",
        },
        "F4": {
            "status": "PLANNED_NOT_EXECUTED",
            "control_id": "F4_DENSITY_GATE_SOURCE_MATCHED_SENSITIVITY_V1",
            "factor": "RhopOut gate parameter only, if its source semantics are separately closed",
            "preserve": ["exact CURRENT XML/BI4 and wetted geometry", "mass and dp/CFL", "MapRealPos/domain", "motion and physics"],
            "comparison": "native density motive, Run.out RhopOut thresholds, endpoint position-inside status, first-gap brackets and saved-record m*v/KE",
            "forbidden": "do not widen thresholds by inference and do not call density endpoint loss legal outflow",
            "qualification": "density-gate sensitivity is numerical evidence only; physical fate and dynamics remain UNKNOWN",
        },
        "physical_fate_evidence_missing": [
            "retained post-gap particle or fluid records with a source-bound boundary-crossing predicate",
            "time-aligned fluid/rigid observer response after each first-missing bracket",
            "source code/metadata proving the exact deletion-time moving-bound predicate",
        ],
    }


def discover(source_report: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    report_path, report = read_json(source_report, "all-118 mechanism report")
    selected = source_cases(report)
    return report_path, report, selected


def validate_manifest(path: Path) -> tuple[Path, dict[str, Any]]:
    manifest_path, manifest = read_json(path, "mechanism probe manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_F2_SCAN048_F4_DENSITY_NO_H5":
        raise MechanismProbeError("mechanism probe manifest schema/status differs")
    if manifest.get("selected_case_keys", [None])[0] != F2_CASE_KEY or manifest.get("selected_case_counts") != {"F2": 1, "F4": 22}:
        raise MechanismProbeError("mechanism probe selected membership differs")
    for path_text, expected in manifest.get("input_sha256", {}).items():
        path = require_file(path_text, "mechanism probe source")
        if path.suffix.lower() in {".h5", ".hdf5", ".obi4"} or (path.name.startswith("Part_") and path.name.endswith(".bi4")):
            raise MechanismProbeError(f"forbidden trajectory/raw input in manifest: {path}")
        if sha256(path) != expected:
            raise MechanismProbeError(f"mechanism probe source changed: {path}")
    return manifest_path, manifest


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    _, manifest = validate_manifest(manifest_path)
    report_path, report = read_json(manifest["source_report"]["path"], "all-118 mechanism report")
    if sha256(report_path) != manifest["source_report"]["sha256"]:
        raise MechanismProbeError("all-118 mechanism report digest differs")
    _, _, selected = discover(report_path)
    selected_by_key = {case["case_key"]: case for case in selected}
    if set(selected_by_key) != set(manifest["selected_case_keys"]):
        raise MechanismProbeError("selected case keys changed")
    cases: list[dict[str, Any]] = []
    for case in selected:
        result, _ = load_case(case)
        cases.append(result)
    native_counts = Counter(case["native_gate"]["motive"] for case in cases)
    result = {
        "schema": OUTPUT_SCHEMA,
        "status": "MECHANISM_PROBE_SOURCE_CLOSED_NO_H5",
        "source_report": small_binding(report_path, "all-118 mechanism report", expected_sha256=manifest["source_report"]["sha256"]),
        "coverage": {"selected_case_counts": {"F2": 1, "F4": 22}, "native_motive_case_counts": dict(sorted(native_counts.items())), "selected_case_count": len(cases)},
        "cases": cases,
        "control_plan": control_plan(cases),
        "interpretation": {
            "position_or_density_gate": "source-bound native motive plus endpoint/bound comparison only",
            "legal_flux": "UNKNOWN_NOT_PROVEN",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "mass_gate_fraction": MASS_GATE,
            "cross_time_impact_sum_forbidden": True,
        },
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "raw_partout_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
    }
    atomic_json(output_path, result)
    return {"status": result["status"], "output": str(output_path.resolve()), "selected_case_count": len(cases), "h5_opened": False}


def prepare(output_dir: Path, source_report: Path = SOURCE_REPORT_DEFAULT, variant: str = "v1") -> dict[str, Any]:
    if not re.fullmatch(r"v[0-9]+", variant):
        raise MechanismProbeError(f"invalid request variant: {variant}")
    report_path, report, selected = discover(source_report)
    loaded: list[dict[str, Any]] = []
    all_paths: list[Path] = [SCRIPT, report_path, RUNTIME_V6, DISPATCH_V6, STRICT_V6, VENV]
    for case in selected:
        result, paths = load_case(case)
        loaded.append(result)
        all_paths.extend(paths)
    unique: list[Path] = []
    seen: set[str] = set()
    for value in all_paths:
        path = require_file(value, f"mechanism probe input {Path(value).name}")
        if path.suffix.lower() in {".h5", ".hdf5", ".obi4"} or (path.name.startswith("Part_") and path.name.endswith(".bi4")):
            raise MechanismProbeError(f"forbidden trajectory/raw input: {path}")
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    hashes = {str(path): sha256(path) for path in unique}
    output_dir = output_dir.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    name = f"omission-mechanism-probe-{variant}"
    manifest_path = output_dir / f"{name}-manifest.json"
    request_path = output_dir / f"{name}-request.json"
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "PREPARED_F2_SCAN048_F4_DENSITY_NO_H5",
        "selected_case_keys": [case["case_key"] for case in selected], "selected_case_counts": {"F2": 1, "F4": 22},
        "selected_native_id_count": sum(case["native_gate"]["native_count"] for case in loaded),
        "source_report": small_binding(report_path, "all-118 mechanism report"),
        "input_files": sorted(hashes), "input_sha256": dict(sorted(hashes.items())),
        "source_scope": {"mechanism_report_reused": True, "native_csv_reused": True, "runparts_reused": True, "h5_opened": False, "trajectory_content_opened": False, "decoder_started": False, "solver_started": False},
        "control_plan": control_plan(loaded),
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "raw_partout_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
    }
    atomic_json(manifest_path, manifest)
    request_hashes = dict(hashes); request_hashes[str(manifest_path)] = sha256(manifest_path)
    request = {
        "schema": "ds02.request.v1", "family_id": "infra", "case_id": "STAGE2_OMISSION_MECHANISM_PROBE_F2_SCAN048_F4_DENSITY_V1",
        "physical_case_id": "F2_SCAN048_F4_DENSITY_SELECTED_23", "attempt_id": f"{name}-primary-001", "kind": "cpu", "cpu_task_kind": "audit",
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900, "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(SCRIPT.parent), "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", f"{{attempt_root}}/{name}.json"],
        "input_files": sorted(request_hashes), "input_sha256": dict(sorted(request_hashes.items())),
        "shared_runtime_version": "v6", "runtime_binding": {"path": str(RUNTIME_V6.resolve()), "sha256": sha256(RUNTIME_V6)},
        "dispatch_binding": {"path": str(DISPATCH_V6.resolve()), "sha256": sha256(DISPATCH_V6)},
        "strict_dispatch_binding": {"path": str(STRICT_V6.resolve()), "sha256": sha256(STRICT_V6)},
        "source_read_cost": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "raw_partout_bytes_read": 0, "native_csv_runparts_xml_json_bytes_read": sum(path.stat().st_size for path in unique), "runtime_pre_post_hash_bytes": 2 * sum(path.stat().st_size for path in unique), "estimated_output_bytes": 64 * 1024 * 1024},
        "source_scope": {"selected_cases": {"F2": 1, "F4": 22}, "native_ids": manifest["selected_native_id_count"], "h5_content_read": False, "trajectory_content_read": False, "decoder_started": False, "solver_started": False, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "canonical_ready": True, "launch": True, "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "primary_launch_owner": "root", "shared_lease_required": True, "foreign_process_protection_required": True,
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "launch_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "request_note": "Small source-closed F2/scan048 position-gate and all-22-F4 density-gate mechanism probe. Reads only completed JSON, Run.out/XML, RunPARTs, and official PartVTKOut CSV/receipts; reports saved-record mass/momentum/KE with event time UNKNOWN and legal flux/physical fate/dynamics UNKNOWN. No H5, raw PartOut, decoder, solver, CFD, or model.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "request": str(request_path), "request_sha256": sha256(request_path), "selected_case_count": len(selected), "selected_native_id_count": manifest["selected_native_id_count"], "h5_opened": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("--output-dir", type=Path, required=True); prep.add_argument("--source-report", type=Path, default=SOURCE_REPORT_DEFAULT); prep.add_argument("--variant", default="v1")
    aud = sub.add_parser("audit"); aud.add_argument("--manifest", type=Path, required=True); aud.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.output_dir, args.source_report, args.variant) if args.action == "prepare" else audit(args.manifest, args.output)
    except MechanismProbeError as exc:
        raise SystemExit(f"MechanismProbeError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
