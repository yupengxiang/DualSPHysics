#!/usr/bin/env python3
"""Build a bounded source-matching queue for ten remaining sentinels.

The queue is an exact-path preparation index.  It reads the frozen status
matrix, the two existing spatial-preflight request families, their small
generated XML/receipt files, and the already materialized SaveDt request
metadata.  It does not search Home, read BI4/HDF5 payloads, start GenCase or a
solver, or turn a source-bound diagnostic into QI/QN/QE credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
STATUS_PATH = REFERENCE / "stage2_fourteen_reference_status_v2.json"
SPATIAL_REQUEST_DIRS = (
    STAGE2 / "requests/stage2-sentinel-spatial-preflight-v1",
    STAGE2 / "requests/stage2-remaining-sentinel-spatial-preflight-v1",
)
OUTPUT = REFERENCE / "stage2_ten_sentinel_source_match_queue_v1.json"
WRAPPER = Path(__file__).resolve()
SCHEMA = "ds02.stage2.ten-sentinel-source-match-queue.v1"
EXCLUDED = {"F1-S2", "F4-S1", "F6-S1", "F7-S1"}
TARGET = {"F1-S1", "F2-S1", "F2-S2", "F3-S1", "F3-S2", "F4-S2", "F5-S1", "F5-S2", "F6-S2", "F7-S2"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, hash_file: bool = True) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    result: dict[str, Any] = {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if hash_file:
        result["sha256"] = sha256_file(path)
    return result


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def unique_floats(values: list[str]) -> list[float]:
    out: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and not any(abs(number - old) <= 1.0e-14 * max(1.0, abs(number), abs(old)) for old in out):
            out.append(number)
    return out


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definitions = unique_floats([element.attrib["dp"] for element in root.iter() if local_tag(element) == "definition" and "dp" in element.attrib])
    h_values = unique_floats([element.attrib["value"] for element in root.iter() if local_tag(element) == "h" and "value" in element.attrib])
    mass_values = unique_floats([element.attrib["value"] for element in root.iter() if local_tag(element) == "massfluid" and "value" in element.attrib])
    if len(mass_values) != 1:
        massfluid = None
    else:
        massfluid = mass_values[0]
    blocks = []
    for element in root.iter():
        if local_tag(element) != "fluid" or "mkfluid" not in element.attrib or "count" not in element.attrib:
            continue
        try:
            count = int(element.attrib["count"])
        except ValueError:
            count = None
        blocks.append({"mkfluid": element.attrib["mkfluid"], "count": count})
    by_mk = {row["mkfluid"]: {"count": row["count"], "sample_mass_kg": row["count"] * massfluid if row["count"] is not None and massfluid is not None else None} for row in blocks}
    parameters: dict[str, list[str]] = {}
    for element in root.iter():
        if local_tag(element) == "parameter" and "key" in element.attrib and "value" in element.attrib:
            parameters.setdefault(element.attrib["key"], []).append(element.attrib["value"])
    gravity = []
    for node in root.iter():
        if local_tag(node) == "gravity" and all(axis in node.attrib for axis in ("x", "y", "z")):
            gravity = [node.attrib[axis] for axis in ("x", "y", "z")]
            break
    cfl = [node.attrib["value"] for node in root.iter() if local_tag(node) == "cflnumber" and "value" in node.attrib]
    motion_files = [node.attrib["name"] for node in root.iter() if local_tag(node) == "file" and "name" in node.attrib]
    floating = next((node for node in root.iter() if local_tag(node) == "floating" and node.find("massbody") is not None), None)
    rigid: dict[str, Any] = {"present": False}
    if floating is not None:
        massbody = floating.find("massbody")
        center = floating.find("center")
        inertia = floating.find("inertia")
        rigid = {
            "present": True,
            "massbody_kg": float(massbody.attrib["value"]) if massbody is not None and "value" in massbody.attrib else None,
            "center_m": [float(center.attrib[axis]) for axis in ("x", "y", "z")] if center is not None and all(axis in center.attrib for axis in ("x", "y", "z")) else None,
            "inertia_diag_kg_m2": [float(inertia.attrib[axis]) for axis in ("x", "y", "z")] if inertia is not None and all(axis in inertia.attrib for axis in ("x", "y", "z")) else None,
        }
    return {
        "file": record(path),
        "definition_dp_m": definitions[0] if len(definitions) == 1 else None,
        "h_m": h_values[0] if len(h_values) == 1 else None,
        "massfluid_kg": massfluid,
        "fluid_blocks": blocks,
        "fluid_by_mk": by_mk,
        "total_fluid_particles": sum(row["count"] for row in blocks if row["count"] is not None),
        "sample_mass_kg": sum(row["sample_mass_kg"] for row in by_mk.values() if row["sample_mass_kg"] is not None),
        "gravity": gravity,
        "cfl_values": cfl,
        "parameters": parameters,
        "motion_files": motion_files,
        "rigid_body": rigid,
    }


def normalize_def(path: Path) -> str:
    raw = path.read_bytes()
    normalized, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', raw, count=1)
    if count != 1:
        raise ValueError(f"definition@dp not found exactly once: {path}")
    return hashlib.sha256(normalized).hexdigest()


def request_index() -> dict[str, tuple[Path, dict[str, Any]]]:
    index: dict[str, tuple[Path, dict[str, Any]]] = {}
    for directory in SPATIAL_REQUEST_DIRS:
        for path in sorted(directory.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            case = value.get("case_id")
            if case:
                index[str(case)] = (path, value)
    return index


def receipt_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_dir():
        path = path / "execution-receipt.json"
    return path


def gate_from_error(error: float | None) -> str:
    if error is None:
        return "UNKNOWN"
    if abs(error) <= 0.01:
        return "PASS_TARGET_1PCT_DIAGNOSTIC"
    if abs(error) <= 0.02:
        return "MARGINAL_1_TO_2PCT"
    return "HARD_FAIL_GT2PCT"


def candidate_record(sentinel: dict[str, Any], candidate: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    xml_text = candidate.get("generated_xml")
    xml = Path(xml_text) if xml_text else None
    receipt = receipt_path(candidate.get("receipt"))
    actual = None
    if xml is not None and xml.is_file():
        actual = parse_xml(xml)
    receipt_data = None
    if receipt is not None and receipt.is_file():
        receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
    request = None
    request_path = None
    # The status stores generated.xml below <case>/<attempt>/generated.xml;
    # request case_id is the case directory, not the attempt directory.
    case_id = xml.parent.parent.name if xml is not None and xml.parent.parent != xml.parent else (receipt.parent.parent.name if receipt is not None and receipt.parent.parent != receipt.parent else None)
    for key, value in index.items():
        if key.lower() == str(case_id).lower():
            request_path, request = value
            break
    geometry = {"status": "UNKNOWN_NO_EXACT_DERIVED_DEF_REQUEST"}
    if request is not None:
        defs = [Path(path) for path in request.get("input_hashes", {}) if str(path).endswith("_Def.xml")]
        derived_defs = [path for path in defs if "stage2/reference" in str(path)]
        source_defs = [path for path in defs if "stage2/reference" not in str(path)]
        if len(derived_defs) == 1 and len(source_defs) == 1 and derived_defs[0].is_file() and source_defs[0].is_file():
            source_hash = normalize_def(source_defs[0])
            derived_hash = normalize_def(derived_defs[0])
            geometry = {"status": "PASS_NORMALIZED_DEF_EQUAL" if source_hash == derived_hash else "FAIL_NORMALIZED_DEF_DIFFERENCE", "source_def": record(source_defs[0]), "derived_def": record(derived_defs[0]), "source_normalized_hash": source_hash, "derived_normalized_hash": derived_hash, "request": record(request_path), "request_input_hashes_stable_declared": request.get("input_hashes") is not None}
        else:
            geometry = {"status": "UNKNOWN_AMBIGUOUS_DERIVED_DEF_PATHS", "request": record(request_path)}
    result: dict[str, Any] = {
        "grid": candidate.get("grid"),
        "requested_dp_m": candidate.get("requested_dp_m"),
        "declared_mass_gate": candidate.get("whole_initial_mass_gate"),
        "declared_mass_error_pct": candidate.get("whole_initial_mass_error_pct"),
        "declared_candidate_sample_mass_kg": candidate.get("candidate_sample_mass_kg"),
        "generated_xml": record(xml) if xml is not None and xml.is_file() else None,
        "producer_receipt": record(receipt) if receipt is not None and receipt.is_file() else None,
        "actual_xml_semantics": actual,
        "producer_terminal": {key: receipt_data.get(key) for key in ("status", "returncode", "termination_reason", "total_particles", "fluid_particles", "elapsed_seconds", "cpu_core_seconds", "bytes", "terminal_storage_guard")} if receipt_data is not None else None,
        "normalized_geometry_control": geometry,
        "read_scope": {"generated_xml_read": actual is not None, "receipt_read": receipt_data is not None, "native_bi4_read": False, "hdf5_read": False},
    }
    if actual is None:
        result["status"] = "UNKNOWN_GENERATED_XML_MISSING"
    elif receipt_data is None or receipt_data.get("status") != "completed" or receipt_data.get("returncode") != 0:
        result["status"] = "FAIL_OR_UNKNOWN_PRODUCER_RECEIPT"
    elif geometry["status"] == "FAIL_NORMALIZED_DEF_DIFFERENCE":
        result["status"] = "FAIL_CONTINUOUS_DEF_DIFFERENCE"
    else:
        source_mass = float(sentinel["initial_state"]["source_sample_mass_kg"])
        error = (actual["sample_mass_kg"] - source_mass) / source_mass if source_mass else None
        result["recomputed_mass"] = {"source_target_kg": source_mass, "candidate_kg": actual["sample_mass_kg"], "error_pct": error * 100.0 if error is not None else None, "gate": gate_from_error(error), "per_mk": actual["fluid_by_mk"]}
        result["status"] = "SOURCE_BOUND_DIAGNOSTIC_READY" if geometry["status"] == "PASS_NORMALIZED_DEF_EQUAL" else "SOURCE_BOUND_WITH_GEOMETRY_UNKNOWN"
        if result["recomputed_mass"]["gate"] == "HARD_FAIL_GT2PCT":
            result["status"] = "BLOCKED_MASS_GT2PCT"
    return result


def temporal_plan(sentinel: dict[str, Any], mode: str) -> dict[str, Any]:
    item = sentinel.get("integration", {}).get(f"savedt_{mode}")
    if not isinstance(item, dict):
        return {"mode": mode, "status": "UNKNOWN_NO_SAVEDT_REQUEST"}
    request = item.get("request", {})
    request_path = Path(request["path"]) if request.get("path") else None
    return {
        "mode": mode,
        "status": item.get("execution_state", "UNKNOWN"),
        "request": record(request_path) if request_path is not None and request_path.is_file() else {"path": str(request_path) if request_path else None, "status": "MISSING"},
        "case_id": item.get("case_id"),
        "attempt_id": item.get("attempt_id"),
        "physical_window_s": item.get("physical_window_s"),
        "requested_tout_s": item.get("requested_tout_s"),
        "planned_frames": item.get("planned_frames"),
        "dt_trace_status": item.get("dt_trace_status", "UNKNOWN"),
        "clamp_status": item.get("clamp_status", "UNKNOWN"),
        "scope": "source original grid only; does not qualify any coarse/fine candidate",
    }


def build() -> dict[str, Any]:
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    index = request_index()
    rows = []
    for sentinel in status["sentinels"]:
        sid = sentinel["sentinel_id"]
        if sid not in TARGET:
            continue
        source_xml = Path(sentinel["identity"]["source_xml"]["path"])
        source_receipt = Path(sentinel["identity"]["source_solver_receipt"]["path"])
        source = parse_xml(source_xml)
        candidate_rows = [candidate_record(sentinel, candidate, index) for candidate in sentinel["initial_state"]["spatial_candidates"]]
        rows.append({
            "sentinel_id": sid,
            "family_id": sentinel["family_id"],
            "physical_case_id": sentinel["physical_case_id"],
            "source": {"xml": record(source_xml), "solver_receipt": record(source_receipt), "semantics": source, "identity_status": sentinel["identity"].get("current_identity_status")},
            "initial_state_policy": {"source_sample_mass_target_kg": sentinel["initial_state"]["source_sample_mass_kg"], "mass_thresholds": {"target_pct": 1.0, "marginal_upper_pct": 2.0, "hard_gt_pct": 2.0}, "no_mass_rescale": True, "continuum_geometry_not_substituted": True},
            "spatial_candidates": candidate_rows,
            "temporal_source_original_grid": {"same_cfl": temporal_plan(sentinel, "same_cfl"), "half_cfl": temporal_plan(sentinel, "half_cfl")},
            "control_window": sentinel["control_window"],
            "full_solver_candidate_policy": {"status": "NOT_LAUNCHED_PENDING_ROOT_REVIEW", "same_cfl_and_half_cfl": "only after a candidate passes source-bound geometry/control and mass review", "dense_output": "candidate-specific request required; source original-grid Savedt pair is not reused as candidate evidence", "dt_sequence": "UNKNOWN until guarded Savedt receipt", "observer": "UNKNOWN pending consumer calibration"},
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        })
    if {row["sentinel_id"] for row in rows} != TARGET:
        raise ValueError("target set does not contain exactly ten sentinels")
    return {
        "schema": SCHEMA,
        "status": "PREPARED_EXACT_SOURCE_BOUND_10_SENTINEL_QUEUE",
        "generated_at_commit": git_head(),
        "wrapper": record(WRAPPER),
        "status_input": record(STATUS_PATH),
        "scope": {"target_sentinels": sorted(TARGET), "count": len(rows), "excluded_already_active_or_bound": sorted(EXCLUDED), "native_bi4_read": False, "hdf5_read": False, "solver_started": False, "gpu_started": False},
        "matching_policy": {"source_paths": "exact CURRENT status identity XML and solver receipt", "candidate_paths": "exact generated.xml/receipt in status and exact historical request case IDs", "normalized_definition": "only dp attribute is replaced by <DP> for a byte-derived geometry/control diagnostic; this does not prove continuous fill equivalence", "motion": "dependency equality is UNKNOWN unless exact request and files are available", "rigid": "massbody/inertia/COM are independent from floating sample mass; absent or changed fields stay UNKNOWN/FAIL", "no_latest_glob": True},
        "rows": rows,
        "global_unknowns": ["continuous draw/fill equivalence beyond normalized Def", "candidate actual solver control/dt/clamp", "full-window native output and observer calibration", "scientific QI/QN/QE"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    value = build()
    atomic_json(args.output, value)
    counts: dict[str, int] = {}
    for row in value["rows"]:
        for candidate in row["spatial_candidates"]:
            counts[candidate["status"]] = counts.get(candidate["status"], 0) + 1
    print(json.dumps({"status": value["status"], "output": str(args.output), "sentinels": len(value["rows"]), "candidate_status_counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
