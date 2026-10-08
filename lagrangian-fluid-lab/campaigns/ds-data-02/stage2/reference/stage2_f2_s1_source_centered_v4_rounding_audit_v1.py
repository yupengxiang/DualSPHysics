#!/usr/bin/env python3
"""Audit the observed F2 full-box rasterisation and write a forward sidecar.

This is a bounded metadata/VTK audit of the existing root044 and original
dp=.01 GenCase products.  It does not run GenCase, read BI4/HDF5, or alter
either product.  The output deliberately labels the ``inner`` candidate as a
forecast until a parent-guarded GenCase receipt exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
V4_MANIFEST = REFERENCE / "stage2_f2_s1_source_centered_v4_inner_manifest_v1.json"
CURRENT_DEF = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010/root-stage1-f2-f2_stage1_first48_expansion_"
    "rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-"
    "gencase-source801-root804/prepared/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010_Def.xml"
)
ORIGINAL_ROOT = CURRENT_DEF.parent
ORIGINAL_XML = ORIGINAL_ROOT / CURRENT_DEF.name.replace("_Def.xml", ".xml")
ORIGINAL_VTK = ORIGINAL_ROOT / CURRENT_DEF.name.replace("_Def.xml", "_Fluid.vtk")
ROOT044 = DATA / "families/F2/F2_S1_SOURCE_CENTERED_V5_BOUND_DP0088_ROOT_044/f2-s1-source-centered-v5-dp0088-gencase-root-044-001-root-forward-030-001"
ROOT044_XML = ROOT044 / "generated.xml"
ROOT044_VTK = ROOT044 / "generated_Fluid.vtk"
ROOT044_LOG = ROOT044 / "stdout.log"
TEMPLATE = REPO / "doc/xml_format/GenCase_CaseTemplate.xml"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def parse_xml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    definition = re.search(r'<definition\b[^>]*\bdp="([^"]+)"[^>]*>', text)
    pointref = re.search(r'<pointref\b[^>]*x="([^"]+)"[^>]*y="([^"]+)"[^>]*z="([^"]+)"', text)
    mass = re.search(r'<massfluid\s+value="([^"]+)"', text)
    blocks = [
        {"mkfluid": int(m.group(1)), "mk": int(m.group(2)), "begin": int(m.group(3)), "count": int(m.group(4))}
        for m in re.finditer(r'<fluid\s+mkfluid="(\d+)"\s+mk="(\d+)"\s+begin="(\d+)"\s+count="(\d+)"', text)
    ]
    return {
        "record": record(path),
        "dp_m": float(definition.group(1)) if definition else None,
        "pointref_m": [float(pointref.group(i)) for i in range(1, 4)] if pointref else None,
        "massfluid_kg": float(mass.group(1)) if mass else None,
        "fluid_blocks": blocks,
        "fluid_count": sum(x["count"] for x in blocks),
    }


def read_vtk(path: Path, count: int) -> tuple[np.ndarray, np.ndarray]:
    data = path.read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\n", data)
    if not match or int(match.group(1)) != count:
        raise ValueError(f"unexpected VTK point count: {path}")
    points = np.frombuffer(data, dtype=">f4", count=count * 3, offset=match.end()).reshape(-1, 3)
    lookup = data.index(b"LOOKUP_TABLE default\n", match.end()) + len(b"LOOKUP_TABLE default\n")
    ids = np.frombuffer(data, dtype=">u4", count=count, offset=lookup)
    return points, ids


def axis_summary(points: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for axis, index in zip("xyz", range(3)):
        values = np.unique(points[:, index])
        result[axis] = {
            "count": int(values.size),
            "min_m": float(values[0]),
            "max_m": float(values[-1]),
            "step_values_m": sorted({round(float(v), 10) for v in np.diff(values)})[:8],
        }
    return result


def block_summary(points: np.ndarray, ids: np.ndarray, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for block in blocks:
        selection = (ids >= block["begin"]) & (ids < block["begin"] + block["count"])
        values = points[selection]
        result.append({
            **block,
            "observed_count": int(values.shape[0]),
            "axis_counts": [int(np.unique(values[:, i]).size) for i in range(3)],
            "axis_min_m": [float(values[:, i].min()) for i in range(3)],
            "axis_max_m": [float(values[:, i].max()) for i in range(3)],
        })
    return result


def template_evidence() -> dict[str, Any]:
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines()
    matches = []
    for number, line in enumerate(lines, 1):
        if "setboxlimitmode" in line or "setshapemode" in line:
            matches.append({"line": number, "text": line.strip()})
    return {"record": record(TEMPLATE), "matching_lines": matches}


def build_report() -> dict[str, Any]:
    current = parse_xml(ORIGINAL_XML)
    root = parse_xml(ROOT044_XML)
    current_points, current_ids = read_vtk(ORIGINAL_VTK, current["fluid_count"])
    root_points, root_ids = read_vtk(ROOT044_VTK, root["fluid_count"])
    owner_volume = 0.325 * 0.22 * 0.088 * 3
    owner_mass = owner_volume * 1000.0
    root_mass = root["fluid_count"] * float(root["massfluid_kg"])
    root_blocks = block_summary(root_points, root_ids, root["fluid_blocks"])
    current_blocks = block_summary(current_points, current_ids, current["fluid_blocks"])
    forecast_mass = 27750 * 1000.0 * 0.0088**3
    return {
        "schema": "ds02.stage2.f2-s1.source-centered-v4.rounding-audit.v1",
        "status": "OBSERVED_FULL_BOX_ROUNDING_AND_INNER_CANDIDATE_FORECAST",
        "scope": {
            "solver_started": False,
            "gencase_started_by_worker": False,
            "hdf5_read": False,
            "bi4_read": False,
            "vtk_read": True,
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "inputs": {
            "current_source_def": record(CURRENT_DEF),
            "current_generated_xml": current,
            "current_generated_fluid_vtk": record(ORIGINAL_VTK),
            "root044_generated_xml": root,
            "root044_stdout": record(ROOT044_LOG),
            "root044_generated_fluid_vtk": record(ROOT044_VTK),
            "official_gencase_binary": record(GENCASE),
        },
        "continuous_owner": {
            "layer_size_m": [0.325, 0.22, 0.088],
            "layer_count": 3,
            "volume_m3": owner_volume,
            "mass_kg": owner_mass,
        },
        "observed_current_dp010": {
            **current,
            "axis_summary": axis_summary(current_points),
            "block_summary": current_blocks,
            "interpretation": "Without pointref, output lattice is anchored to the GenCase case minimum; this is an observed source product fact.",
        },
        "observed_root044_dp0088_full": {
            **root,
            "axis_summary": axis_summary(root_points),
            "block_summary": root_blocks,
            "fluid_mass_kg": root_mass,
            "relative_to_owner_percent": 100.0 * (root_mass / owner_mass - 1.0),
            "interpretation": "Explicit pointref=(.0013,0,.0004) yields x=37, y=27 and z=10/10/11 under the existing full box rasterisation; endpoint ties are retained in the observed VTK.",
        },
        "inferred_rule_with_scope": {
            "rule": "For the observed solid drawboxes, GenCase places a pointref+integer*dp lattice and the existing full box limit admits the cell-envelope boundary points. This is an empirical inference from the two immutable VTK products, not a source-level proof.",
            "endpoint_ties": "At half-dp box boundaries, floating representation can decide whether a layer receives the endpoint; do not use an arithmetic count as actual evidence.",
            "official_template": template_evidence(),
            "implementation_source": "GenCase implementation source is not present in this checkout; binary SHA and template SHA are recorded.",
        },
        "forward_candidate": {
            "candidate_manifest": str(V4_MANIFEST),
            "box_limit_scope": "inner only for the three fluid solid drawboxes; full restored before mainlist close",
            "dp_m": 0.0088,
            "pointref_m": [0.0013, 0.0, 0.0004],
            "forecast_axis_counts": [37, 25, 10],
            "forecast_fluid_count": 27750,
            "forecast_mass_kg": forecast_mass,
            "forecast_relative_to_owner_percent": 100.0 * (forecast_mass / owner_mass - 1.0),
            "status": "PREDICTED_NOT_ACTUAL; parent GenCase receipt and generated XML/VTK decide",
            "scientific_use": "No CFD or initial-state qualification until generated XML, per-MK mass, positions, support/overlap and native QA pass.",
        },
        "preservation": {
            "root044_immutable": True,
            "current_dp010_immutable": True,
            "mass_rescale": False,
            "continuous_boxes_changed": False,
            "control_or_motion_changed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REFERENCE / "stage2_f2_s1_source_centered_v4_rounding_audit_v1.json")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    report = build_report()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "root044_count": report["observed_root044_dp0088_full"]["fluid_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
