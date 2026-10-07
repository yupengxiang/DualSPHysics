#!/usr/bin/env python3
"""Prepare fine F2-S1 native bounds evidence and an expanded-domain pair.

The source fine run and its PartVTKOut audit are immutable.  This preparation
reads only the completed small CSV/Run.out/RunPARTs/XML/receipt evidence,
classifies every primary002 exclusion against the actual printed
``MapRealPos(final)`` bounds, and writes a new XML whose only semantic changes
are the six numerical simulation-domain faces.  The initial BI4 and motion
file are exact read-only symlinks to the completed fine GenCase products.

No H5, trajectory frame, GenCase, solver, PartVTKOut, CFD, or model workload
is started here.  The paired request is owned by root and must be run through
the shared Stage2 guard.  Physical fate and dynamical impact remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV = LAB_ROOT / ".venv/bin/python"
SOLVER = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
RUNTIME_V4 = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2 = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4 = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4 = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"
PHYSICAL_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
FINE_CASE = "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE"
PAIR_CASE = "F2_S1_FINE_DOMAIN_EXPANDED_DP00855_XYZ_V1"
PAIR_ATTEMPT = "f2-s1-fine-domain-expanded-xyz-v1"
OUTPUT_SCHEMA = "ds02.stage2.f2-s1-fine-domain-boundary-classification.v2"
PREP_SCHEMA = "ds02.stage2.f2-s1-fine-domain-pair-preparation.v2"
REQUEST_SCHEMA = "ds02.request.v1"
PRIMARY002_ROOT = DATA_ROOT / "families/F2/F2_S1_FINE_NATIVE_IMPACT_AUDIT_V2/f2-s1-fine-partvtkout-v2-primary-002"
PRIMARY002_RECEIPT = PRIMARY002_ROOT / "execution-receipt.json"
PRIMARY002_CSV = PRIMARY002_ROOT / "PartOut.csv"
FINE_SOLVER_RECEIPT = DATA_ROOT / "families/F2/F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE/f2-s1-fine-dp00855-same-cfl-full4s-primary-001/execution-receipt.json"
EXPANDED_BOUNDS = {
    "posmin": {"x": "-1.60", "y": "-1.40", "z": "-0.70"},
    "posmax": {"x": "3.20", "y": "1.40", "z": "2.50"},
}


class PairError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise PairError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PairError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise PairError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def actual_ref(value: str | Path, expected: str | None, label: str) -> dict[str, Any]:
    path = require_file(value, label)
    actual = sha256(path)
    if expected is not None and actual != str(expected):
        raise PairError(f"{label} digest differs: {path}; expected {expected}, got {actual}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def descendant(root: ET.Element, name: str) -> ET.Element:
    for node in root.iter():
        if tag(node) == name:
            return node
    raise PairError(f"XML element {name} is missing")


def simulation_domain(root: ET.Element) -> tuple[ET.Element, dict[str, dict[str, str]]]:
    parameters = descendant(root, "parameters")
    domain = next((node for node in parameters if tag(node) == "simulationdomain"), None)
    if domain is None:
        raise PairError("XML parameters/simulationdomain is missing")
    values: dict[str, dict[str, str]] = {}
    for name in ("posmin", "posmax"):
        node = next((item for item in domain if tag(item) == name), None)
        if node is None or any(axis not in node.attrib for axis in "xyz"):
            raise PairError(f"XML simulationdomain/{name} is incomplete")
        values[name] = {axis: node.attrib[axis] for axis in "xyz"}
    return domain, values


def semantic_xml(path: Path, restore: dict[str, dict[str, str]] | None = None) -> bytes:
    root = ET.parse(path).getroot()
    if restore is not None:
        domain, _ = simulation_domain(root)
        for name in ("posmin", "posmax"):
            node = next(item for item in domain if tag(item) == name)
            node.attrib.update(restore[name])
    return ET.tostring(root, encoding="utf-8")


def xml_sources(receipt_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise PairError("fine source solver receipt is not completed code 0")
    request = receipt.get("request", {})
    if request.get("family_id") != "F2" or request.get("case_id") != FINE_CASE or request.get("physical_case_id") != PHYSICAL_CASE:
        raise PairError("fine source solver receipt identity differs")
    command = request.get("command", [])
    expected_flags = ["-tmax:4.000007783879406", "-tout:0.005000000000000"]
    if not isinstance(command, list) or len(command) < 5 or [str(value) for value in command[3:]] != expected_flags:
        raise PairError("fine source solver control flags changed")
    prefix = require_file(str(command[1]) + ".xml", "fine source generated XML")
    bi4 = require_file(str(command[1]) + ".bi4", "fine source generated BI4")
    root = ET.parse(prefix).getroot()
    _, bounds = simulation_domain(root)
    definition = descendant(root, "definition")
    if definition.get("dp") != "0.00855":
        raise PairError("fine source dp is not 0.00855")
    motion_nodes = [node for node in root.iter() if tag(node) == "file" and node.get("name")]
    if not motion_nodes:
        raise PairError("fine source XML has no motion file")
    motion = require_file(prefix.parent / motion_nodes[0].get("name", ""), "fine source motion file")
    gencase = require_file(request.get("candidate_gencase_receipt", ""), "fine source GenCase receipt")
    gencase_payload = read_json(gencase, "fine source GenCase receipt")[1]
    if gencase_payload.get("status") != "completed" or gencase_payload.get("returncode") != 0:
        raise PairError("fine source GenCase receipt is not completed code 0")
    return {
        "receipt": receipt_path,
        "receipt_payload": receipt,
        "request": request,
        "prefix": prefix,
        "bi4": bi4,
        "motion": motion,
        "gencase": gencase,
        "bounds": bounds,
    }


def csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        lines = [line for line in stream if line.strip()]
    if not lines:
        raise PairError(f"fine PartOut CSV is empty: {path}")
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    rows = list(csv.reader(lines, delimiter=delimiter))
    header = [value.strip() for value in rows[0]]
    required = ["Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "PartOut", "Motive", "Idp"]
    required += ["Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]"]
    pos = {name: header.index(name) for name in required if name in header}
    if len(pos) != len(required):
        raise PairError(f"fine PartOut CSV lacks required fields: {sorted(set(required) - set(pos))}")
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for ordinal, raw in enumerate(rows[1:]):
        if not any(value.strip() for value in raw):
            continue
        try:
            item: dict[str, Any] = {"Idp": int(raw[pos["Idp"]]), "PartOut": int(raw[pos["PartOut"]]), "Motive": int(raw[pos["Motive"]])}
            for axis in "xyz":
                item[f"x{axis}"] = float(raw[pos[f"Pos.{axis} [m]"]])
                item[f"v{axis}"] = float(raw[pos[f"Vel.{axis} [m/s]"]])
            item["rhop"] = float(raw[pos["Rhop [kg/m^3]"]])
        except (ValueError, TypeError, IndexError) as exc:
            raise PairError(f"fine PartOut row {ordinal} is invalid") from exc
        if item["Idp"] in seen:
            raise PairError(f"fine PartOut has duplicate Idp {item['Idp']}")
        seen.add(item["Idp"])
        if not all(math.isfinite(float(item[key])) for key in ("xx", "xy", "xz", "vx", "vy", "vz", "rhop")):
            raise PairError(f"fine PartOut row {ordinal} is nonfinite")
        result.append(item)
    if len(result) != 175:
        raise PairError(f"fine PartOut row count changed: {len(result)}")
    return result


def final_map_bounds(runout: Path) -> dict[str, Any]:
    pattern = re.compile(r"MapRealPos\(final\)=\(([^,]+),([^,]+),([^\)]+)\)-\(([^,]+),([^,]+),([^\)]+)\)")
    matches = pattern.findall(runout.read_text(encoding="utf-8", errors="replace"))
    if not matches:
        raise PairError(f"Run.out has no MapRealPos(final): {runout}")
    values = matches[-1]
    numbers = [float(value) for value in values]
    return {
        "text": f"MapRealPos(final)=({values[0]},{values[1]},{values[2]})-({values[3]},{values[4]},{values[5]})",
        "posmin": {axis: numbers[index] for index, axis in enumerate("xyz")},
        "posmax": {axis: numbers[index + 3] for index, axis in enumerate("xyz")},
    }


def fluid_mk_ranges(xml: Path) -> dict[str, Any]:
    root = ET.parse(xml).getroot()
    particles = descendant(root, "particles")
    mk_first = int(particles.get("mkfluidfirst", "0"))
    groups: list[dict[str, Any]] = []
    for node in particles:
        if tag(node) != "fluid" or node.get("mkfluid") is None:
            continue
        local = int(node.get("mkfluid", "0"))
        absolute = int(node.get("mk", str(mk_first + local)))
        groups.append({"mkfluid": local, "mk_absolute": absolute, "begin": int(node.get("begin", "0")), "count": int(node.get("count", "0"))})
    if len(groups) != 3:
        raise PairError(f"fine XML fluid groups changed: {groups}")
    return {"mkfluidfirst": mk_first, "ranges": groups}


def mk_for_id(idp: int, groups: list[dict[str, Any]]) -> int | None:
    for group in groups:
        if group["begin"] <= idp < group["begin"] + group["count"]:
            return int(group["mk_absolute"])
    return None


def runparts_terminal(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = [row for row in csv.DictReader(stream, delimiter=";") if (row.get("Part") or "").strip().isdigit()]
    if not rows:
        raise PairError("fine RunPARTs is empty")
    last = {str(key).strip(): (value or "").strip() for key, value in rows[-1].items() if key is not None}
    fields = ("Part", "TimeStep [s]", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
    if any(field not in last for field in fields):
        raise PairError("fine RunPARTs terminal row lacks output counters")
    counters = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
    return {
        "row_count": len(rows),
        "terminal": {"part": int(last["Part"]), "time_s": float(last["TimeStep [s]"]), **{key: int(last[key]) for key in counters}},
        "maximum_per_part": {key: max(int((row.get(key) or "0").strip()) for row in rows) for key in counters},
        "sum_across_parts": {key: sum(int((row.get(key) or "0").strip()) for row in rows) for key in counters},
    }


def classify(source: dict[str, Any], output: Path) -> dict[str, Any]:
    decoder_path, decoder = read_json(PRIMARY002_RECEIPT, "fine primary002 decoder receipt")
    if decoder.get("schema") != "ds02.execution-receipt.v1" or decoder.get("status") != "completed" or decoder.get("returncode") != 0:
        raise PairError("fine primary002 decoder receipt is not completed code 0")
    decoder_request = decoder.get("request", {})
    if decoder_request.get("family_id") != "F2" or decoder_request.get("physical_case_id") != PHYSICAL_CASE:
        raise PairError("fine primary002 decoder identity differs")
    if decoder_request.get("source_solver_receipt") != str(source["receipt"]):
        raise PairError("fine primary002 decoder is bound to a different solver receipt")
    csv_path = require_file(PRIMARY002_CSV, "fine primary002 PartOut.csv")
    runout = require_file(Path(str(source["receipt"].parent / "solver_output/Run.out")), "fine source Run.out")
    runparts = require_file(Path(str(source["receipt"].parent / "solver_output/RunPARTs.csv")), "fine source RunPARTs.csv")
    printed = final_map_bounds(runout)
    xml_ranges = fluid_mk_ranges(source["prefix"])
    rows = csv_rows(csv_path)
    direction_counts = {f"{axis}{sign}": 0 for axis in "xyz" for sign in ("-", "+")}
    direction_mk_counts = {key: {str(group["mk_absolute"]): 0 for group in xml_ranges["ranges"]} for key in direction_counts}
    records: list[dict[str, Any]] = []
    for row in rows:
        flags: list[str] = []
        for axis in "xyz":
            value = float(row[f"x{axis}"])
            if value < printed["posmin"][axis]:
                flags.append(f"{axis}-")
            if value > printed["posmax"][axis]:
                flags.append(f"{axis}+")
        mk = mk_for_id(int(row["Idp"]), xml_ranges["ranges"])
        for key in flags:
            direction_counts[key] += 1
            if mk is not None:
                direction_mk_counts[key][str(mk)] += 1
        records.append({
            "idp": int(row["Idp"]), "partout": int(row["PartOut"]), "motive": int(row["Motive"]),
            "position_m": [row["xx"], row["xy"], row["xz"]],
            "outside_axes": flags, "absolute_mk": mk,
        })
    all_outside = [row for row in records if row["outside_axes"]]
    bounds = {"posmin": printed["posmin"], "posmax": printed["posmax"]}
    report = {
        "schema": OUTPUT_SCHEMA,
        "status": "completed",
        "family_id": "F2",
        "physical_case_id": PHYSICAL_CASE,
        "fine_case_id": FINE_CASE,
        "source": {
            "solver_receipt": actual_ref(source["receipt"], None, "fine solver receipt"),
            "decoder_receipt": actual_ref(decoder_path, None, "fine primary002 decoder receipt"),
            "partout_csv": actual_ref(csv_path, None, "fine primary002 PartOut.csv"),
            "runout": actual_ref(runout, None, "fine source Run.out"),
            "runparts": actual_ref(runparts, None, "fine source RunPARTs.csv"),
            "generated_xml": actual_ref(source["prefix"], None, "fine generated XML"),
        },
        "printed_native_bounds": bounds,
        "xml_fluid_ranges": xml_ranges,
        "observed": {
            "csv_rows": len(rows), "all_rows_motive": sorted({int(row["Motive"]) for row in rows}),
            "outside_row_count": len(all_outside), "inside_row_count": len(rows) - len(all_outside),
            "direction_counts": direction_counts,
            "direction_absolute_mk_counts": direction_mk_counts,
            "position_range_m": {axis: {"min": min(row[f"x{axis}"] for row in rows), "max": max(row[f"x{axis}"] for row in rows)} for axis in "xyz"},
            "first_partout": min(int(row["PartOut"]) for row in rows), "last_partout": max(int(row["PartOut"]) for row in rows),
            "runparts_terminal": runparts_terminal(runparts),
        },
        "records": records,
        "interpretation": {
            "classification": "numeric printed-boundary exclusion only; every axis with a flagged coordinate is recorded",
            "six_direction_scope": "x-, x+, y-, y+, z-, z+ are all checked independently against Run.out MapRealPos(final)",
            "mk_policy": "XML mkfluidfirst=1 maps local mkfluid 0/1/2 to absolute MK 1/2/3",
            "physical_fate": "UNKNOWN; numerical position outside is not proof of physical spill or legal overflow",
            "dynamical_impact": "UNKNOWN; missing typed mass is a visibility lower bound only and is not a bounded velocity/impact/coupling error",
            "boundary_precision": "Run.out uses native printed MapRealPos; exact binary bound predicate remains a separate precision limitation",
            "qualification": "none",
        },
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "solver_started": False, "partvtkout_started": False, "cfd_or_model_run": False},
    }
    atomic_json(output, report)
    return report


def make_pair(source: dict[str, Any], classification_path: Path, output_dir: Path, request_path: Path) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PairError(f"fine domain pair output directory is not fresh: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_xml = source["prefix"]
    candidate_prefix = output_dir / "F2_S1_FINE_DOMAIN_EXPANDED_DP00855_XYZ_V1"
    candidate_xml = candidate_prefix.with_suffix(".xml")
    tree = ET.parse(source_xml)
    root = tree.getroot()
    domain, source_bounds = simulation_domain(root)
    for name in ("posmin", "posmax"):
        node = next(item for item in domain if tag(item) == name)
        node.attrib.update(EXPANDED_BOUNDS[name])
    ET.indent(tree, space="    ")
    tree.write(candidate_xml, encoding="utf-8", xml_declaration=True)
    candidate_bi4 = candidate_prefix.with_suffix(".bi4")
    candidate_bi4.symlink_to(source["bi4"])
    candidate_motion = output_dir / source["motion"].name
    candidate_motion.symlink_to(source["motion"])
    if semantic_xml(candidate_xml, restore=EXPANDED_BOUNDS) == semantic_xml(source_xml):
        raise PairError("candidate XML did not retain the intended six-face expansion")
    if semantic_xml(candidate_xml, restore=source_bounds) != semantic_xml(source_xml):
        raise PairError("candidate XML changed fields outside simulationdomain faces")
    changed = [f"parameters/simulationdomain/{name}/@{axis}" for name in ("posmin", "posmax") for axis in "xyz" if source_bounds[name][axis] != EXPANDED_BOUNDS[name][axis]]
    if changed != [f"parameters/simulationdomain/{name}/@{axis}" for name in ("posmin", "posmax") for axis in "xyz"]:
        raise PairError(f"expanded candidate did not change exactly six faces: {changed}")
    classification_path = require_file(classification_path, "fine boundary classification")
    source_request = source["request"]
    solver = require_file(SOLVER, "official DualSPHysics solver")
    runtime_files = [RUNTIME_V4, RUNTIME_V2, DISPATCH_V4, STRICT_V4]
    source_inputs = [source["receipt"], source_xml, source["bi4"], source["motion"], source["gencase"], PRIMARY002_RECEIPT, PRIMARY002_CSV,
                     source["receipt"].parent / "solver_output/RunPARTs.csv", source["receipt"].parent / "solver_output/Run.out"]
    input_paths = [SCRIPT, classification_path, candidate_xml, candidate_bi4, candidate_motion, solver] + runtime_files + source_inputs
    unique: list[Path] = []
    seen: set[str] = set()
    for path in input_paths:
        path = require_file(path, "fine domain pair input")
        if path.name == "trajectory.h5" or (path.name.startswith("Part_") and path.name.endswith(".bi4")):
            raise PairError(f"fine pair input unexpectedly contains trajectory content: {path}")
        key = str(path if path in (candidate_bi4, candidate_motion) else path.resolve())
        if key not in seen:
            seen.add(key); unique.append(path)
    digest_map = {str(path): sha256(path) for path in unique}
    digest_map[str(candidate_bi4)] = sha256(source["bi4"])
    digest_map[str(candidate_motion)] = sha256(source["motion"])
    output_dir_manifest = output_dir / "prepared.json"
    manifest = {
        "schema": PREP_SCHEMA,
        "status": "PREPARED_CANONICAL_READY",
        "family_id": "F2", "physical_case_id": PHYSICAL_CASE, "fine_case_id": FINE_CASE,
        "classification": {"path": str(classification_path), "sha256": sha256(classification_path)},
        "source_solver_receipt": actual_ref(source["receipt"], None, "fine source solver receipt"),
        "source_generated_xml": actual_ref(source_xml, None, "fine source generated XML"),
        "source_generated_bi4": {"path": str(source["bi4"]), "sha256": sha256(source["bi4"]), "bytes": source["bi4"].stat().st_size},
        "source_motion": actual_ref(source["motion"], None, "fine source motion"),
        "candidate_generated_xml": actual_ref(candidate_xml, None, "fine candidate XML"),
        "candidate_generated_bi4": {"path": str(candidate_bi4), "sha256": sha256(source["bi4"]), "bytes": source["bi4"].stat().st_size, "symlink_target": str(source["bi4"])},
        "candidate_motion": {"path": str(candidate_motion), "sha256": sha256(source["motion"]), "bytes": source["motion"].stat().st_size, "symlink_target": str(source["motion"])},
        "domain_control": {"source_bounds": source_bounds, "candidate_bounds": EXPANDED_BOUNDS, "changed_paths": changed, "numeric_domain_only": True, "all_six_triggered_by_primary002": True, "wetted_wall_or_geometry_changed": False},
        "invariants": {"dp_m": 0.00855, "cfl": 0.2, "initial_bi4_reused_without_rescale": True, "all_physics_xml_values_unchanged": True, "motion_reused_without_change": True, "physical_geometry_or_wetted_wall_changed": False, "solver_flags_reused": [str(value) for value in source_request["command"][3:]], "gencase_rerun": False, "solver_started": False},
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "solver_started": False, "partvtkout_started": False},
    }
    atomic_json(output_dir_manifest, manifest)
    digest_map[str(output_dir_manifest)] = sha256(output_dir_manifest)
    command = [str(solver), str(candidate_prefix), "{attempt_root}/solver_output"] + [str(value) for value in source_request["command"][3:]]
    request = {
        "schema": REQUEST_SCHEMA, "family_id": "F2", "case_id": PAIR_CASE, "physical_case_id": PHYSICAL_CASE, "attempt_id": PAIR_ATTEMPT,
        "kind": source_request.get("kind", "qualification"), "qualification_stage": "stage2_fine_expanded_numeric_domain_pair_pending_root_guard",
        "cpu_task_kind": "solver", "cpu_threads": int(source_request.get("cpu_threads", 2)), "omp_threads": int(source_request.get("omp_threads", 2)),
        "max_wall_seconds": int(source_request.get("max_wall_seconds", 7200)), "estimated_storage_bytes": int(source_request.get("estimated_storage_bytes", 36507222016)), "estimated_peak_gpu_mib": int(source_request.get("estimated_peak_gpu_mib", 4096)),
        "cwd": str(WORKTREE_ROOT), "worktree_root": str(WORKTREE_ROOT), "command": command,
        "input_files": sorted(digest_map), "input_sha256": dict(sorted(digest_map.items())),
        "source_solver_receipt": str(source["receipt"]), "source_solver_receipt_sha256": sha256(source["receipt"]), "source_generated_xml": str(source_xml), "source_generated_xml_sha256": sha256(source_xml), "source_generated_bi4": str(source["bi4"]), "source_generated_bi4_sha256": sha256(source["bi4"]), "source_motion": str(source["motion"]), "source_motion_sha256": sha256(source["motion"]), "source_gencase_receipt": str(source["gencase"]), "source_gencase_receipt_sha256": sha256(source["gencase"]),
        "prepared_manifest": str(output_dir_manifest), "prepared_manifest_sha256": sha256(output_dir_manifest), "classification": {"path": str(classification_path), "sha256": sha256(classification_path)},
        "domain_control": manifest["domain_control"], "control_closure": manifest["invariants"],
        "runtime_binding": {"runtime_v4": {"path": str(RUNTIME_V4), "sha256": sha256(RUNTIME_V4)}, "runtime_v2": {"path": str(RUNTIME_V2), "sha256": sha256(RUNTIME_V2)}, "dispatch_v4": {"path": str(DISPATCH_V4), "sha256": sha256(DISPATCH_V4)}, "strict_dispatch_v4": {"path": str(STRICT_V4), "sha256": sha256(STRICT_V4)}, "shared_lease_required": True},
        "launch_owner": "root", "primary_launch_owner": "root", "launch": True, "launch_allowed": True, "execution_allowed": True, "canonical_ready": True, "launch_disabled": False, "foreign_process_protection_required": True, "shared_lease_required": True,
        "qualification_claim": "none; numerical-domain paired diagnostic only", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "request_note": "Fine .00855 paired numerical-domain diagnostic. The same generated BI4, all non-domain XML physics/geometry values, motion file, dp, CFL, and solver flags are source-bound; only six simulationdomain xyz faces expand to x[-1.60,3.20], y[-1.40,1.40], z[-0.70,2.50]. Existing dp=.01 x-low control remains separate and is not a substitute. No preparation workload launched.",
    }
    atomic_json(request_path, request)
    return {"status": "CANONICAL_READY", "manifest": {"path": str(output_dir_manifest), "sha256": sha256(output_dir_manifest)}, "classification": {"path": str(classification_path), "sha256": sha256(classification_path)}, "request": {"path": str(request_path), "sha256": sha256(request_path), "case_id": PAIR_CASE, "attempt_id": PAIR_ATTEMPT}, "changed_paths": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver-receipt", type=Path, default=FINE_SOLVER_RECEIPT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--classification", type=Path)
    parser.add_argument("--request", type=Path)
    args = parser.parse_args()
    try:
        solver_path, receipt = read_json(args.solver_receipt, "fine source solver receipt")
        source = xml_sources(solver_path, receipt)
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        classification = (args.classification or output_dir / "fine-domain-boundary-classification.json").resolve()
        if classification.exists():
            existing = json.loads(classification.read_text(encoding="utf-8"))
            if existing.get("schema") != OUTPUT_SCHEMA:
                raise PairError(f"refusing to overwrite unrelated classification: {classification}")
        else:
            classify(source, classification)
        request = (args.request or output_dir / "fine-domain-expanded-request.json").resolve()
        result = make_pair(source, classification, output_dir / "prepared", request)
    except PairError as exc:
        raise SystemExit(f"PairError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
