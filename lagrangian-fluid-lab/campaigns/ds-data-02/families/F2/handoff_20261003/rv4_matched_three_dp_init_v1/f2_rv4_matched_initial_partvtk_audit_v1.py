#!/usr/bin/env python3
"""Run a bounded initial-frame PartVTK audit for one matched RV4 GenCase.

This script is intended to run as a CPU ``audit`` request through the shared
runtime after a terminal GenCase receipt exists.  It calls the official
``PartVTK_linux64`` binary for frame zero, then checks actual typed rows,
source-band counts and positions, native XML MassFluid/BI4-facing population,
finite cup/receiver/tray coverage, initial fluid/solid separation, 3D
coordinates, and copied motion/control hashes.  It reports evidence only; it
does not launch a solver or assign Q-I/Q-N.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping
import xml.etree.ElementTree as ET


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_RV4_MATCHED_THREE_DP_INIT_20261003"
SCHEMA = "ds-data-02.f2.rv4-matched-initial-partvtk-audit.v1"
RUNTIME_V2 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
WORKTREE_ROOT = Path(__file__).resolve().parents[4]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def require_dir(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    return json.loads(require(path, label).read_text(encoding="utf-8"))


def row_float(row: Mapping[str, str], key: str) -> float:
    return float(row[key])


def row_int(row: Mapping[str, str], key: str) -> int:
    return int(float(row[key]))


def parse_partvtk_csv(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Pos.x [m]")), None)
    if header_index is None:
        raise ValueError(f"PartVTK data header missing: {path}")
    header = [item.strip() for item in lines[header_index].split(",") if item.strip()]
    required = {"Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk", "Mass [kg]"}
    missing = required.difference(header)
    if missing:
        raise ValueError(f"PartVTK fields missing {sorted(missing)}: {path}")
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 1 :]:
        if not line.strip():
            continue
        fields = [item.strip() for item in line.split(",")]
        if len(fields) >= len(header):
            rows.append(dict(zip(header, fields)))
    if not rows:
        raise ValueError(f"PartVTK CSV has no particle rows: {path}")
    return rows


def parse_generated_xml(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    definition = root.find(".//casedef/geometry/definition")
    particles = root.find(".//particles")
    constants = root.find(".//constants")
    if definition is None or particles is None or constants is None:
        raise ValueError(f"generated XML incomplete: {xml_path}")
    massfluid = constants.find("massfluid")
    if massfluid is None:
        raise ValueError(f"generated XML MassFluid missing: {xml_path}")
    fluid = particles.find("fluid")
    fluid_rows = particles.findall("fluid")
    if fluid is None or len(fluid_rows) != 3:
        raise ValueError(f"generated XML must have three fluid blocks: {xml_path}")
    sim = root.find(".//execution/parameters/simulationdomain")
    posmin = sim.find("posmin") if sim is not None else None
    posmax = sim.find("posmax") if sim is not None else None
    bounds = []
    mainlist = root.find(".//casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError("generated XML bound mainlist missing")
    current_mk: int | None = None
    for node in mainlist:
        if node.tag == "setmkbound":
            current_mk = int(node.attrib["mk"])
        elif node.tag == "setmkfluid":
            current_mk = None
        elif node.tag == "drawbox" and current_mk is not None:
            point = node.find("point")
            size = node.find("size")
            if point is not None and size is not None:
                bounds.append({
                    "mkbound": current_mk,
                    "boxfill": node.findtext("boxfill", default="").strip(),
                    "low_m": [float(point.attrib[axis]) for axis in "xyz"],
                    "size_m": [float(size.attrib[axis]) for axis in "xyz"],
                })
    return {
        "dp_m": float(definition.attrib["dp"]),
        "massfluid_kg": float(massfluid.attrib["value"]),
        "particle_count": int(particles.attrib["np"]),
        "fluid_count": int(particles.find("_summary/fluid").attrib["count"]),
        "fluid_blocks": [{"mk": int(row.attrib["mk"]), "count": int(row.attrib["count"]), "begin": int(row.attrib["begin"])} for row in fluid_rows],
        "bound_blocks": [{"mk": int(row.attrib["mk"]), "count": int(row.attrib["count"])} for row in particles.findall("fixed") + particles.findall("moving")],
        "simulationdomain": {
            "posmin": [float(posmin.attrib[axis]) for axis in "xyz"] if posmin is not None else None,
            "posmax": [float(posmax.attrib[axis]) for axis in "xyz"] if posmax is not None else None,
        },
        "bounds": bounds,
    }


def run_partvtk(generated_dir: Path, case_id: str, output_dir: Path) -> tuple[Path, dict[str, Any]]:
    generated_dir = require_dir(generated_dir, "GenCase output directory")
    xml = require(generated_dir / f"{case_id}.xml", "generated XML")
    bi4 = require(generated_dir / f"{case_id}.bi4", "generated BI4")
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "initial"
    command = [str(PARTVTK), "-filedata", str(bi4), "-filexml", str(xml), "-first:0", "-last:0", "-threads:4", "-savecsv", str(prefix), "-onlytype:+all", "-vars:-all,+idp,+vel,+rhop,+type,+mk,+mass,+zone", "-csvsep:1"]
    result = subprocess.run(command, cwd=output_dir, capture_output=True, text=True, check=False, timeout=600)
    log = output_dir / "partvtk.stdout.log"
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    csvs = [path for path in sorted(output_dir.glob("initial_*.csv")) if not path.name.endswith("_stats.csv")]
    if not csvs and (output_dir / "initial.csv").is_file():
        csvs = [output_dir / "initial.csv"]
    if result.returncode != 0 or not csvs:
        raise RuntimeError(f"official PartVTK failed; returncode={result.returncode}; see {log}")
    return csvs[0], {
        "command": command,
        "returncode": result.returncode,
        "binary": {"path": str(PARTVTK.resolve()), "sha256": sha256(PARTVTK)},
        "csv": {"path": str(csvs[0].resolve()), "sha256": sha256(csvs[0]), "bytes": csvs[0].stat().st_size},
        "log": {"path": str(log.resolve()), "sha256": sha256(log), "bytes": log.stat().st_size},
    }


def finite_face_coverage(rows: list[dict[str, str]], boxes: list[dict[str, Any]], dp: float) -> dict[str, Any]:
    # Type 1/0 are boundary classes in native PartVTK output; moving and fixed
    # boxes are distinguished by generated native Mk 17/18/19 below.
    by_mk: dict[int, list[tuple[float, float, float]]] = {}
    for row in rows:
        if row_int(row, "Type") not in (0, 1):
            continue
        by_mk.setdefault(row_int(row, "Mk"), []).append(tuple(row_float(row, f"Pos.{axis} [m]") for axis in "xyz"))
    mk_by_bound_index = {0: 17, 1: 18, 2: 19}
    axis_index = {"x": 0, "y": 1, "z": 2}
    tolerance = max(2.25 * dp, 1.0e-6)
    result: dict[str, Any] = {}
    all_pass = True
    for index, box in enumerate(boxes):
        native_mk = mk_by_bound_index[index]
        points = by_mk.get(native_mk, [])
        low = box["low_m"]
        high = [low[axis] + box["size_m"][axis] for axis in range(3)]
        faces: dict[str, Any] = {}
        for face in (part.strip() for part in box["boxfill"].split("|") if part.strip()):
            if face not in {"bottom", "top", "left", "right", "front", "back"}:
                continue
            axis = axis_index[{"bottom": "z", "top": "z", "left": "x", "right": "x", "front": "y", "back": "y"}[face]]
            target = low[axis] if face in {"bottom", "left", "front"} else high[axis]
            selected = [point for point in points if abs(point[axis] - target) <= tolerance]
            tangential = [item for item in range(3) if item != axis]
            spans = [
                None if not selected else {"min_m": min(point[item] for point in selected), "max_m": max(point[item] for point in selected), "target_low_m": low[item], "target_high_m": high[item]}
                for item in tangential
            ]
            covered = bool(selected) and all(span is not None and span["min_m"] <= span["target_low_m"] + tolerance and span["max_m"] >= span["target_high_m"] - tolerance for span in spans)
            faces[face] = {"row_count": len(selected), "tolerance_m": tolerance, "tangential_spans": spans, "covered": covered}
            all_pass = all_pass and covered
        result[str(index)] = {"native_mk": native_mk, "boxfill": box["boxfill"], "row_count": len(points), "faces": faces, "pass": all(item["covered"] for item in faces.values())}
    return {"boxes": result, "all_finite_faces_covered": all_pass}


def source_fluid_audit(rows: list[dict[str, str]], metadata: Mapping[str, Any], xml_info: Mapping[str, Any]) -> dict[str, Any]:
    expected = metadata["expected_population"]
    dp = float(metadata["dp_m"])
    low = [float(item) for item in metadata["physical_geometry"]["continuous_fluid_low_m"]]
    size = [float(item) for item in metadata["physical_geometry"]["continuous_fluid_size_m"]]
    band_width = float(metadata["physical_geometry"]["source_band_width_m"])
    fluid = [row for row in rows if row_int(row, "Type") == 3 and row_int(row, "Mk") in (1, 2, 3)]
    by_mk = {mk: [row for row in fluid if row_int(row, "Mk") == mk] for mk in (1, 2, 3)}
    expected_per_band = int(expected["source_band_particle_count"])
    positions: dict[str, Any] = {}
    positions_pass = True
    for index, mk in enumerate((1, 2, 3)):
        group = by_mk[mk]
        target_low = [low[0], low[1] + index * band_width, low[2]]
        target_high = [target_low[axis] + (size[axis] if axis != 1 else band_width) for axis in range(3)]
        actual_min = [min((row_float(row, f"Pos.{axis} [m]") for row in group), default=None) for axis in "xyz"]
        actual_max = [max((row_float(row, f"Pos.{axis} [m]") for row in group), default=None) for axis in "xyz"]
        expected_min = [target_low[axis] + dp / 2 for axis in range(3)]
        expected_max = [target_high[axis] - dp / 2 for axis in range(3)]
        group_pass = len(group) == expected_per_band and all(actual_min[axis] is not None and abs(actual_min[axis] - expected_min[axis]) <= max(dp * 1.1, 2e-6) and abs(actual_max[axis] - expected_max[axis]) <= max(dp * 1.1, 2e-6) for axis in range(3))
        positions[str(mk)] = {"count": len(group), "expected_count": expected_per_band, "actual_min_m": actual_min, "actual_max_m": actual_max, "expected_min_m": expected_min, "expected_max_m": expected_max, "pass": group_pass}
        positions_pass = positions_pass and group_pass
    ids = [row_int(row, "Idp") for row in fluid]
    masses = [row_float(row, "Mass [kg]") for row in fluid]
    expected_particle_mass = float(expected["expected_particle_mass_kg"])
    native_mass = float(xml_info["massfluid_kg"]) * len(fluid)
    csv_mass = sum(masses)
    fluid_x = [row_float(row, "Pos.x [m]") for row in fluid]
    fluid_y = [row_float(row, "Pos.y [m]") for row in fluid]
    fluid_z = [row_float(row, "Pos.z [m]") for row in fluid]
    # A positive margin means every initial fluid point is away from the cup
    # finite faces; receiver/tray are also tested as boxes below.
    solids = metadata["finite_solids"]
    overlap: dict[str, Any] = {}
    overlap_pass = True
    for name, box in zip(("cup", "receiver", "tray"), solids):
        box_low = [float(value) for value in box["low_m"]]
        box_high = [box_low[axis] + float(box["size_m"][axis]) for axis in range(3)]
        inside = [all(box_low[axis] <= point[axis] <= box_high[axis] for axis in range(3)) for point in zip(fluid_x, fluid_y, fluid_z)]
        # The fluid is expected to be in the cup interior, while receiver/tray
        # are disjoint initial solids.  Finite-wall particle thickness is
        # checked by comparing to the declared box envelope, not by declaring
        # a point inside a wall to be fluid spill.
        if name == "cup":
            margin = min(min(point[axis] - box_low[axis] for point in zip(fluid_x, fluid_y, fluid_z)) for axis in range(3))
            overlap[name] = {"fluid_points_inside_declared_envelope": sum(inside), "fluid_count": len(fluid), "interior_margin_lower_bound_m": margin, "pass": sum(inside) == len(fluid) and margin > 0.0}
        else:
            overlap[name] = {"fluid_points_inside_declared_envelope": sum(inside), "fluid_count": len(fluid), "pass": sum(inside) == 0}
        overlap_pass = overlap_pass and overlap[name]["pass"]
    return {
        "fluid_row_count": len(fluid),
        "expected_fluid_row_count": int(expected["total_particle_count"]),
        "fluid_type_mk_counts": {str(mk): len(by_mk[mk]) for mk in (1, 2, 3)},
        "unique_id_count": len(set(ids)),
        "id_span": [min(ids), max(ids)] if ids else None,
        "source_band_positions": positions,
        "csv_particle_mass_min_kg": min(masses) if masses else None,
        "csv_particle_mass_max_kg": max(masses) if masses else None,
        "expected_particle_mass_kg": expected_particle_mass,
        "native_xml_massfluid_kg": float(xml_info["massfluid_kg"]),
        "native_xml_mass_total_kg": native_mass,
        "csv_mass_total_kg": csv_mass,
        "continuous_mass_kg": float(expected["continuous_mass_kg"]),
        "mass_relative_error_native_to_continuum": native_mass / float(expected["continuous_mass_kg"]) - 1.0,
        "mass_relative_error_csv_to_continuum": csv_mass / float(expected["continuous_mass_kg"]) - 1.0,
        "checks": {
            "fluid_count_matches_expected": len(fluid) == int(expected["total_particle_count"]),
            "fluid_ids_unique": len(set(ids)) == len(ids),
            "fluid_mk_counts_match_expected": all(len(by_mk[mk]) == expected_per_band for mk in (1, 2, 3)),
            "fluid_is_3d": len({row_int(row, "Zone") for row in fluid}) >= 1 and all(len({row_float(row, f"Pos.{axis} [m]") for row in fluid}) > 1 for axis in "xyz"),
            "source_band_centres_and_bounds_match": positions_pass,
            "native_xml_mass_matches_continuum": abs(native_mass / float(expected["continuous_mass_kg"]) - 1.0) <= 1e-12,
            "csv_mass_matches_native_within_display_tolerance": abs(csv_mass - native_mass) <= max(abs(native_mass) * 2e-6, 1e-9),
            "initial_fluid_solid_separation": overlap_pass,
        },
        "initial_overlap": overlap,
    }


def audit(generated_dir: Path, case_id: str, metadata_path: Path, receipt_path: Path, output: Path) -> dict[str, Any]:
    metadata = load_json(metadata_path, "case metadata")
    receipt = load_json(receipt_path, "GenCase receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("PartVTK audit requires a terminal successful GenCase receipt")
    xml = require(generated_dir / f"{case_id}.xml", "generated XML")
    bi4 = require(generated_dir / f"{case_id}.bi4", "generated BI4")
    xml_info = parse_generated_xml(xml)
    csv_path, partvtk = run_partvtk(generated_dir, case_id, output.parent / "partvtk")
    rows = parse_partvtk_csv(csv_path)
    finite = finite_face_coverage(rows, xml_info["bounds"], xml_info["dp_m"])
    fluid = source_fluid_audit(rows, metadata, xml_info)
    checks = {
        **fluid["checks"],
        "gencase_receipt_completed": receipt.get("returncode") == 0,
        "generated_xml_hash_matches_receipt_output": receipt.get("output_root") is not None,
        "generated_xml_particle_count_matches_partvtk_summary": xml_info["particle_count"] == len(rows),
        "generated_xml_dimension_is_3d": receipt.get("solver_dimension_from_gencase") == 3,
        "finite_faces_covered": finite["all_finite_faces_covered"],
    }
    result = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": FAMILY_ID,
        "scope_id": SCOPE_ID,
        "case_id": case_id,
        "status": "initial_native_partvtk_audit_complete" if all(checks.values()) else "initial_native_partvtk_audit_incomplete",
        "qualification_claim": "none",
        "q_i_status": "initial geometry/population/finite-face evidence only; full lifecycle and solver trajectory not audited",
        "q_n_status": "not_assessed",
        "production_status": "not_evaluated",
        "source_binding": {
            "metadata": {"path": str(metadata_path.resolve()), "sha256": sha256(metadata_path)},
            "gencase_receipt": {"path": str(receipt_path.resolve()), "sha256": sha256(receipt_path)},
            "generated_xml": {"path": str(xml.resolve()), "sha256": sha256(xml)},
            "generated_bi4": {"path": str(bi4.resolve()), "sha256": sha256(bi4)},
            "physical_condition_hash": metadata["rv4_binding"]["physical_condition_hash"],
            "numerical_recipe_hash": metadata["numerical_recipe_hash"],
        },
        "generated_xml": xml_info,
        "partvtk": partvtk,
        "partvtk_row_count": len(rows),
        "finite_face_coverage": finite,
        "source_fluid": fluid,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "claim_boundary": "Initial native evidence does not infer physical spill from absence/presence, does not close full Q-I lifecycle, and does not grant Q-N or production eligibility.",
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["output"] = {"path": str(output), "sha256": sha256(output)}
    return result


def make_request(case_id: str, generated_dir: Path, metadata_path: Path, receipt_path: Path, attempt_id: str, request_path: Path) -> dict[str, Any]:
    """Create a terminal-GenCase-bound PartVTK audit request without running it."""
    generated_dir = generated_dir.resolve()
    metadata_path = metadata_path.resolve()
    receipt_path = receipt_path.resolve()
    xml = require(generated_dir / f"{case_id}.xml", "generated XML")
    bi4 = require(generated_dir / f"{case_id}.bi4", "generated BI4")
    inputs = [Path(__file__).resolve(), PYTHON.resolve(), RUNTIME_V2.resolve(), PARTVTK.resolve(), xml, bi4, receipt_path, metadata_path]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "command": [str(PYTHON.resolve()), str(Path(__file__).resolve()), "--generated-dir", str(generated_dir), "--case-id", case_id, "--metadata", str(metadata_path), "--gencase-receipt", str(receipt_path), "--output", "{attempt_root}/initial-partvtk-audit.json"],
        "cwd": str(Path(__file__).resolve().parent),
        "raw_output_root": str((DATA_ROOT / "families/F2" / case_id / attempt_id).resolve()),
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "solver_launch_forbidden": True,
        "scope_id": SCOPE_ID,
        "physical_condition_hash": load_json(metadata_path, "case metadata")["rv4_binding"]["physical_condition_hash"],
        "numerical_recipe_hash": load_json(metadata_path, "case metadata")["numerical_recipe_hash"],
        "input_files": [str(path) for path in inputs],
        "input_sha256": {str(path): sha256(path) for path in inputs},
        "gencase_terminal_binding": {
            "receipt_path": str(receipt_path),
            "receipt_sha256": sha256(receipt_path),
            "generated_xml_path": str(xml),
            "generated_xml_sha256": sha256(xml),
            "generated_bi4_path": str(bi4),
            "generated_bi4_sha256": sha256(bi4),
        },
        "qualification_claim": "none; initial native geometry/population/finite-face evidence only",
        "q_n_status": "not_assessed",
        "request_note": "Official PartVTK_linux64 frame-zero audit only. No solver/GPU/converter/labels launch; unknown native fate remains outside this initial-state check.",
    }
    request_path = request_path.resolve()
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-dir", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--gencase-receipt", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--make-request", type=Path)
    parser.add_argument("--request-case-id")
    parser.add_argument("--request-generated-dir", type=Path)
    parser.add_argument("--request-metadata", type=Path)
    parser.add_argument("--request-gencase-receipt", type=Path)
    parser.add_argument("--request-attempt-id")
    args = parser.parse_args()
    if args.make_request:
        required = (args.request_case_id, args.request_generated_dir, args.request_metadata, args.request_gencase_receipt, args.request_attempt_id)
        if any(item is None for item in required):
            parser.error("--make-request requires --request-case-id, --request-generated-dir, --request-metadata, --request-gencase-receipt, and --request-attempt-id")
        request = make_request(args.request_case_id, args.request_generated_dir, args.request_metadata, args.request_gencase_receipt, args.request_attempt_id, args.make_request)
        print(json.dumps({"status": "written", "request": str(args.make_request.resolve()), "input_count": len(request["input_files"])}, sort_keys=True))
        return 0
    if args.generated_dir is None or args.case_id is None or args.metadata is None or args.gencase_receipt is None or args.output is None:
        parser.error("audit mode requires --generated-dir, --case-id, --metadata, --gencase-receipt, and --output")
    result = audit(args.generated_dir, args.case_id, args.metadata, args.gencase_receipt, args.output)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "all_checks_pass": result["all_checks_pass"], "q_n_status": result["q_n_status"]}, sort_keys=True))
    return 0 if result["all_checks_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
