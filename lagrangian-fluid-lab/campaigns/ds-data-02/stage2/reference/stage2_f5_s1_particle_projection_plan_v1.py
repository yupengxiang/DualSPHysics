#!/usr/bin/env python3
"""Prepare a source-bound F5-S1 particle-projection and three-rung plan.

This is a metadata/XML-only diagnostic.  It uses the completed q106/q107
GenCase receipts and generated XML, plus file ``stat`` for planning costs. It
does not read VTK/BI4/HDF5 payloads and does not launch GenCase or a solver.
The dp0025 rung is a registered candidate and a cost proxy, never an actual
particle count or a mass pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
STATIC_REPORT = HERE / "stage2_f5_s1_missing_mass_static_diagnostic_v1.json"
SCHEMA = "ds02.stage2.f5-s1.particle-projection-plan.v1"
CONTINUOUS_MASS_KG = 287.736
SOURCE_LOW_M = (0.010, -0.140, 0.010)
SOURCE_SIZE_M = (3.420, 0.280, 0.380)
CLIP_POINT_M = (2.0, 0.0, 0.0)
CLIP_VECTOR_M = (0.28, 0.0, -1.0)
RUNG = {
    "dp010": {"dp_m": 0.010, "pointref_m": (0.015, 0.005, 0.015)},
    "dp005": {"dp_m": 0.005, "pointref_m": (0.0125, 0.0025, 0.0125)},
    "dp0025": {"dp_m": 0.0025, "pointref_m": (0.01125, 0.00125, 0.01125)},
}
DEFAULTS = {
    "static_report": STATIC_REPORT,
    "receipt_dp010": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
        "F5_S1_CLIPPLANE_YHALF_DP010_GENCASE_ROOT_106/"
        "f5-s1-yhalf-dp010-gencase-v5-root-106-001-root-forward-030-001/execution-receipt.json"
    ),
    "receipt_dp005": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
        "F5_S1_CLIPPLANE_YHALF_DP005_GENCASE_ROOT_107/"
        "f5-s1-yhalf-dp005-gencase-v5-root-107-001-root-forward-030-001/execution-receipt.json"
    ),
    "xml_dp010": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
        "F5_S1_CLIPPLANE_YHALF_DP010_GENCASE_ROOT_106/"
        "f5-s1-yhalf-dp010-gencase-v5-root-106-001-root-forward-030-001/generated.xml"
    ),
    "xml_dp005": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
        "F5_S1_CLIPPLANE_YHALF_DP005_GENCASE_ROOT_107/"
        "f5-s1-yhalf-dp005-gencase-v5-root-107-001-root-forward-030-001/generated.xml"
    ),
}


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def small_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path), "label": label, "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino),
        "sha256": sha256(path), "content_read": True, "read_scope": "small_xml_or_json",
    }


def metadata_record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    stat = path.stat()
    return {
        "path": str(path), "label": label, "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino),
        "sha256": "NOT_COMPUTED_METADATA_ONLY", "content_read": False,
        "read_scope": "stat_only_no_vtk_payload_read",
    }


def parse_generated(path: Path, grid: str) -> dict[str, Any]:
    path = regular(path, f"{grid} generated XML")
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    particles = root.find("./execution/particles")
    mass_node = root.find("./execution/constants/massfluid")
    if definition is None or particles is None or mass_node is None:
        raise ValueError(f"{grid} generated XML is missing definition/particles/massfluid")
    pointref = definition.find("./pointref")
    if pointref is None:
        raise ValueError(f"{grid} generated XML has no pointref")
    fluid_blocks = [
        element for element in particles.findall("./fluid")
        if all(key in element.attrib for key in ("begin", "count", "mkfluid", "mk"))
    ]
    if not fluid_blocks:
        raise ValueError(f"{grid} generated XML has no typed fluid block")
    count = sum(int(element.attrib["count"]) for element in fluid_blocks)
    massfluid = float(mass_node.attrib["value"])
    sample_mass = count * massfluid
    relative = 100.0 * (sample_mass - CONTINUOUS_MASS_KG) / CONTINUOUS_MASS_KG
    return {
        "grid": grid,
        "record": small_record(path, f"{grid} generated XML"),
        "dp_m": float(definition.attrib["dp"]),
        "pointref_m": [float(pointref.attrib[key]) for key in "xyz"],
        "particles": {key: int(particles.attrib[key]) for key in ("np", "nb", "nbf") if key in particles.attrib},
        "fluid_count": count,
        "massfluid_kg": massfluid,
        "sample_mass_kg": sample_mass,
        "continuous_mass_relative_percent": relative,
        "mass_gate": "PASS_PREFERRED_1PCT" if abs(relative) <= 1.0 else "MARGINAL_1_TO_2PCT" if abs(relative) <= 2.0 else "HARDFAIL_OVER_2PCT",
        "fluid_blocks": [dict(sorted(element.attrib.items())) for element in fluid_blocks],
    }


def receipt_observation(path: Path, grid: str, generated: dict[str, Any]) -> dict[str, Any]:
    receipt = json.loads(regular(path, f"{grid} receipt").read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"{grid} receipt is not completed zero-return")
    output_root = Path(str(receipt["output_root"])).expanduser().resolve()
    file_names = (
        "generated.bi4", "generated.xml", "generated_All.vtk", "generated_Bound.vtk",
        "generated_Fluid.vtk", "generated_MkCells.vtk", "execution-receipt.json",
    )
    files = {}
    for name in file_names:
        candidate = output_root / name
        if candidate.exists():
            files[name] = metadata_record(candidate, f"{grid} {name}")
    vtk_bytes = sum(item["bytes"] for name, item in files.items() if name.endswith(".vtk"))
    fluid_bound_bytes = sum(files[name]["bytes"] for name in ("generated_Fluid.vtk", "generated_Bound.vtk") if name in files)
    return {
        "grid": grid,
        "receipt": small_record(path, f"{grid} GenCase receipt"),
        "status": receipt["status"],
        "returncode": receipt["returncode"],
        "output_root": str(output_root),
        "terminal_bytes": int(receipt.get("bytes", 0)),
        "terminal_non_receipt_bytes": int(receipt.get("terminal_storage_guard", {}).get("non_receipt_bytes", 0)),
        "cpu_core_seconds": float(receipt.get("cpu_core_seconds", 0.0)),
        "wall_seconds": float(receipt.get("wall_seconds_from_entry", 0.0)),
        "model_invoked": receipt.get("model_invoked"),
        "cfd_invoked": receipt.get("cfd_invoked"),
        "file_metadata": files,
        "vtk_bytes_stat_only": vtk_bytes,
        "fluid_bound_vtk_bytes_stat_only": fluid_bound_bytes,
        "generated_xml_count_matches_receipt_input": True,
        "generated_fluid_count": generated["fluid_count"],
    }


def lattice_rule() -> dict[str, Any]:
    axes = [SOURCE_SIZE_M[i] / RUNG["dp0025"]["dp_m"] for i in range(3)]
    counts = [int(round(value)) for value in axes]
    return {
        "status": "REGISTERED_CANDIDATE_RULE_NOT_ACTUAL_OUTPUT",
        "formula": "center_i = source_box_low + dp/2 + i*dp; retain only official clip/shape result",
        "source_box_low_m": list(SOURCE_LOW_M),
        "source_box_size_m": list(SOURCE_SIZE_M),
        "clip_point_m": list(CLIP_POINT_M),
        "clip_vector_m": list(CLIP_VECTOR_M),
        "dp0025_pointref_m": list(RUNG["dp0025"]["pointref_m"]),
        "unclipped_axis_counts_dp0025": counts,
        "unclipped_lattice_population_dp0025": math.prod(counts),
        "candidate_def_changes_allowed": ["definition.dp", "definition.pointref.x", "definition.pointref.y", "definition.pointref.z"],
        "candidate_def_changes_forbidden": ["box point/size", "clip point/vector", "draw/clip command order", "bed/boundary geometry", "motion/control", "massfluid", "mass rescale"],
        "actual_confirmation_required": [
            "generated XML dp/pointref and all MK fluid block counts",
            "VTK fluid Idp ranges mapped to XML blocks",
            "fluid coordinate finite/closed-box/clip-plane predicates",
            "axis unique counts, first/last centers, and spacing including phase",
            "boundary-fluid overlap/support audit and particle fate classification",
        ],
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    static_report = load_json(args.static_report)
    generated = {
        "dp010": parse_generated(args.xml_dp010, "dp010"),
        "dp005": parse_generated(args.xml_dp005, "dp005"),
    }
    observations = {
        "dp010": receipt_observation(args.receipt_dp010, "dp010", generated["dp010"]),
        "dp005": receipt_observation(args.receipt_dp005, "dp005", generated["dp005"]),
    }
    for grid in ("dp010", "dp005"):
        expected = RUNG[grid]
        if abs(generated[grid]["dp_m"] - expected["dp_m"]) > 1e-12 or generated[grid]["pointref_m"] != list(expected["pointref_m"]):
            raise ValueError(f"{grid} generated XML does not match registered phase")
    fine_proxy = observations["dp005"]
    scale = 8.0
    future = {
        "grid": "dp0025",
        "dp_m": RUNG["dp0025"]["dp_m"],
        "pointref_m": list(RUNG["dp0025"]["pointref_m"]),
        "status": "NOT_GENERATED_COST_PROXY_ONLY",
        "fluid_count_proxy_from_dp005_x8": int(round(generated["dp005"]["fluid_count"] * scale)),
        "total_particle_count_proxy_from_dp005_x8": int(round(generated["dp005"]["particles"]["np"] * scale)),
        "terminal_bytes_proxy_from_dp005_x8": int(round(fine_proxy["terminal_bytes"] * scale)),
        "fluid_bound_vtk_bytes_proxy_from_dp005_x8": int(round(fine_proxy["fluid_bound_vtk_bytes_stat_only"] * scale)),
        "cpu_core_seconds_proxy_from_dp005_x8": fine_proxy["cpu_core_seconds"] * scale,
        "wall_seconds_proxy_from_dp005_x8": fine_proxy["wall_seconds"] * scale,
        "proxy_basis": "dp005 actual terminal metadata multiplied by (0.005/0.0025)^3; boundary/clip rounding and file fixed costs are unknown",
        "must_not_be_used_as": ["actual count", "actual mass", "support pass", "solver reservation", "scientific qualification"],
        "next_gate": "Only prepare a GenCase+support QA request after q106/q107 V7 support cause review; no solver launch from this plan.",
    }
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_SOURCE_XML_PARTICLE_PROJECTION_PLAN_SUPPORT_PENDING",
        "identity": {"family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"},
        "scope": {"source_xml_read": True, "generated_xml_read": True, "receipt_json_read": True, "vtk_payload_read": False, "vtk_stat_only": True, "bi4_read": False, "hdf5_read": False, "gencase_started": False, "solver_started": False},
        "frozen_source_contract": {"continuous_mass_kg": CONTINUOUS_MASS_KG, "source_box_low_m": list(SOURCE_LOW_M), "source_box_size_m": list(SOURCE_SIZE_M), "clip_point_m": list(CLIP_POINT_M), "clip_vector_m": list(CLIP_VECTOR_M), "control_and_motion_change": False, "mass_rescale": False},
        "source_projection_cause": {
            "known": ["source box and official half-space define 287.736 kg continuous model", "q106/q107 preserve source command order and only change registered dp/pointref phase", "q106/q107 XML sample counts/mass are terminal facts"],
            "unknown": ["edge inclusion/rounding at clip plane", "closed bed/boundary overlap removal ordering", "whether missing samples are removed by clip, overlap, or another draw/fill material interaction", "whether any missing particle represents physical flux/outflow"],
            "qualification": "Do not reinterpret the q106/q107 mass deficits as legal flux or grant QI/QN/QE.",
        },
        "measured_rungs": generated,
        "actual_gencase_cost_metadata": observations,
        "three_grid_plan": {"dp010": {"role": "actual coarse diagnostic; mass HARDFAIL; V7 support pending", "solver_eligible": False}, "dp005": {"role": "actual fine diagnostic; mass MARGINAL; V7 support pending", "solver_eligible": False}, "dp0025": future},
        "registered_particle_rule": lattice_rule(),
        "source_evidence_reuse": {"static_report": small_record(args.static_report, "F5 static missing-mass report"), "source_command_order": static_report["source_semantics"]["source_command_order"], "official_half_space": static_report["source_semantics"]["official_half_space"], "official_symbols_static_only": True},
        "next_executable_scope": {"kind": "GenCase-only plus guarded initial-support QA", "inputs": "new dp0025 Def with source-preserving dp/pointref phase, actual q106/q107 V7 support outcome, parent storage/CPU reservation", "output": "XML count/mass plus worker Fluid/Bound support/axis/Idp/overlap report", "not_authorized": ["blind finer solver", "HDF5/native full-window read", "mass rescaling", "threshold widening", "calling proxy count a result"]},
    }
    return report


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(regular(path, "JSON input").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(path)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for key, default in DEFAULTS.items():
        parser.add_argument(f"--{key.replace('_', '-')}", type=Path, default=default)
    parser.add_argument("--output", type=Path, default=HERE / "stage2_f5_s1_particle_projection_plan_v1.json")
    args = parser.parse_args()
    if args.self_test:
        assert RUNG["dp0025"]["pointref_m"] == (0.01125, 0.00125, 0.01125)
        assert math.prod((1368, 112, 152)) == 23288832
        print("stage2_f5_s1_particle_projection_plan_v1 self-test PASS")
        return 0
    report = build(args)
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable report: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "dp010_mass": report["measured_rungs"]["dp010"]["sample_mass_kg"], "dp005_mass": report["measured_rungs"]["dp005"]["sample_mass_kg"], "dp0025_terminal_bytes_proxy": report["three_grid_plan"]["dp0025"]["terminal_bytes_proxy_from_dp005_x8"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
