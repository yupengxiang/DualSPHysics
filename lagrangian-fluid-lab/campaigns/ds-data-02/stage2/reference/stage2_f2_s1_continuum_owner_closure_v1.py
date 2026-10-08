#!/usr/bin/env python3
"""Close the F2-S1 continuous-fluid versus native-sample mass question.

This is a small source/XML audit.  It reads the exact F2-S1 source Def,
source metadata, and generated XML, but no BI4, H5, VTK payload, or solver
output.  The three solid fluid ``drawbox`` layers define a continuous source
volume of ``.325*.22*.264`` m^3 (18.876 kg at ``rhop0=1000``).  The generated
native blocks contain 21,114 particles at 0.001 kg each (21.114 kg).  The
11.86% difference is a finite source-closure result: native sample-mass
agreement among F2 grids is a discrete diagnostic and cannot be promoted to
continuum equivalence or repaired by rescaling.

The report intentionally ends this branch with a bounded failure for the
continuum-equivalent qualification.  A future matched recipe must explicitly
change and re-register the continuous representation; it must not mutate this
CURRENT source or widen the mass gate.
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
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.continuum-owner-closure.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE_ROOT = DATA_ROOT / (
    "families/F2/F2_FIRST48_REMAINING24_SOURCE_ROOT801/"
    "root-stage1-f2-first48-remaining24-registered-source-generation-root801"
)
SOURCE_DEF = SOURCE_ROOT / "source/source/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml"
SOURCE_METADATA = SOURCE_ROOT / "source/source/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010.metadata.json"
SOURCE_OWNER = SOURCE_ROOT / "source/owners/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010.owner.json"
SOURCE_MOTION = SOURCE_ROOT / "source/source/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_motion.dat"
GENERATED_XML = DATA_ROOT / (
    "families/F2/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/"
    "root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-gencase-source801-root804/"
    "prepared/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010.xml"
)
OUTPUT = REFERENCE / "stage2_f2_s1_continuum_owner_closure_v1.json"
RHO0 = 1000.0
CONTINUUM_MASS_TARGET_KG = 18.876
NATIVE_SAMPLE_MASS_KG = 21.114
MASS_GATE_FRACTION = 0.01


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def finite_float(node: ET.Element, key: str) -> float:
    raw = node.get(key)
    if raw is None:
        raise ValueError(f"missing {key} on {tag(node)}")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"nonfinite {key} on {tag(node)}")
    return value


def parameter(root: ET.Element, key: str) -> float | None:
    for node in root.iter():
        if tag(node) == "parameter" and node.get("key") == key:
            return finite_float(node, "value")
    return None


def node_value(root: ET.Element, name: str) -> float | None:
    for node in root.iter():
        if tag(node) == name.lower() and node.get("value") is not None:
            return finite_float(node, "value")
    return None


def fluid_drawboxes(root: ET.Element) -> list[dict[str, Any]]:
    current_mk: str | None = None
    result: list[dict[str, Any]] = []
    for node in root.iter():
        if tag(node) == "setmkfluid":
            current_mk = node.get("mk")
        elif tag(node) == "drawbox" and current_mk is not None:
            fill = next((child for child in node if tag(child) == "boxfill"), None)
            point = next((child for child in node if tag(child) == "point"), None)
            size = next((child for child in node if tag(child) == "size"), None)
            if fill is None or point is None or size is None or (fill.text or "").strip().lower() != "solid":
                continue
            dims = [finite_float(size, axis) for axis in ("x", "y", "z")]
            origin = [finite_float(point, axis) for axis in ("x", "y", "z")]
            result.append({"mkfluid": int(current_mk), "origin_m": origin, "size_m": dims, "volume_m3": math.prod(dims)})
    return result


def generated_fluid_blocks(root: ET.Element) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in root.iter():
        if tag(node) == "fluid" and node.get("mkfluid") is not None and node.get("count") is not None:
            rows.append({"mkfluid": int(node.get("mkfluid")), "mk": int(node.get("mk")), "begin": int(node.get("begin")), "count": int(node.get("count"))})
    return rows


def audit() -> dict[str, Any]:
    for path in (SOURCE_DEF, SOURCE_METADATA, SOURCE_OWNER, SOURCE_MOTION, GENERATED_XML):
        if not path.is_file():
            raise FileNotFoundError(path)
    source_root = ET.parse(SOURCE_DEF).getroot()
    generated_root = ET.parse(GENERATED_XML).getroot()
    metadata = json.loads(SOURCE_METADATA.read_text(encoding="utf-8"))
    owner = json.loads(SOURCE_OWNER.read_text(encoding="utf-8"))
    boxes = fluid_drawboxes(source_root)
    blocks = generated_fluid_blocks(generated_root)
    if len(boxes) != 3 or len(blocks) != 3:
        raise ValueError(f"expected three fluid layers: boxes={len(boxes)}, blocks={len(blocks)}")
    rho0 = node_value(generated_root, "rhop0") or node_value(source_root, "rhop0")
    if rho0 != RHO0:
        raise ValueError(f"unexpected rhop0={rho0}")
    massfluid_nodes = [node for node in generated_root.iter() if tag(node) == "massfluid"]
    if len(massfluid_nodes) != 1:
        raise ValueError(f"expected one generated massfluid node, found {len(massfluid_nodes)}")
    massfluid = finite_float(massfluid_nodes[0], "value")
    continuum_volume = sum(row["volume_m3"] for row in boxes)
    continuum_mass = continuum_volume * rho0
    sample_count = sum(row["count"] for row in blocks)
    sample_mass = sample_count * massfluid
    layers_match = [
        {"mkfluid": box["mkfluid"], "source_volume_m3": box["volume_m3"], "generated_mkfluid": block["mkfluid"], "generated_mk": block["mk"], "generated_count": block["count"]}
        for box, block in zip(boxes, blocks)
    ]
    delta_continuum = (sample_mass - continuum_mass) / continuum_mass
    delta_owner = (sample_mass - CONTINUUM_MASS_TARGET_KG) / CONTINUUM_MASS_TARGET_KG
    source_size = metadata["geometry"]["fluid_source_size_m"]
    metadata_mass = RHO0 * math.prod(source_size)
    checks = {
        "source_def_has_three_solid_fluid_drawboxes": len(boxes) == 3,
        "source_metadata_size_matches_drawbox_sum": all(abs(a - b) <= 1e-15 for a, b in zip(source_size, [0.325, 0.22, 0.264])),
        "source_metadata_continuum_mass_kg": abs(metadata_mass - continuum_mass) <= 1e-12,
        "generated_fluid_block_count_is_three": len(blocks) == 3,
        "generated_mkfluid_mapping_is_0_1_2_to_mk_1_2_3": [(row["mkfluid"], row["mk"]) for row in blocks] == [(0, 1), (1, 2), (2, 3)],
        "sample_mass_matches_generated_blocks": abs(sample_mass - NATIVE_SAMPLE_MASS_KG) <= 1e-12,
        "continuous_and_sample_mass_within_one_percent": abs(delta_continuum) <= MASS_GATE_FRACTION,
    }
    if not all(checks[key] for key in ("source_def_has_three_solid_fluid_drawboxes", "source_metadata_size_matches_drawbox_sum", "source_metadata_continuum_mass_kg", "generated_fluid_block_count_is_three", "generated_mkfluid_mapping_is_0_1_2_to_mk_1_2_3", "sample_mass_matches_generated_blocks")):
        raise AssertionError(checks)
    return {
        "schema": SCHEMA,
        "status": "FINITE_CONTINUUM_OWNER_CLOSURE_SOURCE_PASS_NATIVE_EQUIVALENCE_BLOCKED",
        "identity": {
            "sentinel_id": "F2-S1",
            "family_id": "F2",
            "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
            "case_id": metadata["case_id"],
            "physical_condition_sha256": metadata["physical_condition_sha256"],
        },
        "scope": {
            "solver_started": False,
            "native_bi4_read": False,
            "h5_read": False,
            "vtk_payload_read": False,
            "source_only_xml_metadata_audit": True,
        },
        "sources": {
            "source_def": record(SOURCE_DEF),
            "source_metadata": record(SOURCE_METADATA),
            "source_owner": record(SOURCE_OWNER),
            "source_motion": record(SOURCE_MOTION),
            "generated_xml": record(GENERATED_XML),
        },
        "continuous_owner": {
            "basis": "three exact solid fluid drawboxes from frozen source Def; no inferred box enlargement",
            "fluid_low_m": metadata["geometry"]["fluid_low_m"],
            "fluid_source_size_m": source_size,
            "source_layer_count": metadata["geometry"]["source_layer_count"],
            "layer_boxes": boxes,
            "volume_m3": continuum_volume,
            "density_kg_per_m3": rho0,
            "mass_kg": continuum_mass,
            "authority": "CURRENT F2 source metadata + Def, not native particle sum",
        },
        "native_initial_sample": {
            "generated_fluid_blocks": blocks,
            "layer_mapping": layers_match,
            "massfluid_kg": massfluid,
            "fluid_particles": sample_count,
            "sample_mass_kg": sample_mass,
            "role": "discrete generated-particle diagnostic; no mass rescaling",
        },
        "mass_comparison": {
            "sample_minus_continuum_kg": sample_mass - continuum_mass,
            "sample_relative_to_continuum_fraction": delta_continuum,
            "sample_relative_to_continuum_percent": 100.0 * delta_continuum,
            "sample_relative_to_registered_continuum_target_fraction": delta_owner,
            "preferred_whole_initial_mass_gate_fraction": MASS_GATE_FRACTION,
            "gate": "HARD_FAIL_CONTINUUM_EQUIVALENCE_ABOVE_1PCT_AND_2PCT",
        },
        "source_semantics": {
            "mkfluid_to_native_mk": "0->1, 1->2, 2->3; do not identify native MK1 as source MK0 without this mapping",
            "continuous_region": "finite three-layer source boxes, total z depth .264 m; generated block counts do not redefine it",
            "initial_velocity_m_per_s": metadata["initial_state"]["velocity_m_per_s"],
            "motion_sha256": metadata["motion"]["sha256"],
            "control_window_s": [0.0, 4.0],
        },
        "qualification": {
            "continuous_geometry_equivalence": "FAIL_FINITE_MASS_MISMATCH",
            "discrete_source_relative_spatial_diagnostic": "AVAILABLE_ONLY_WITHIN_CURRENT_SAMPLE_MASS_SCOPE",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "native sample mass is 11.86% above the exact source continuum volume; no rescale or threshold widening is permitted",
        },
        "next_action": {
            "status": "BLOCKED_FOR_CONTINUUM_MATCHED_CFD_UNDER_CURRENT_SOURCE",
            "allowed": "retain existing CURRENT as discrete-source diagnostic or prepare a separately registered owner-consistent Def/GenCase recipe",
            "forbidden": "using 21.114 kg as continuum mass, backfilling H5 mass, rescaling particles, or silently changing drawbox geometry",
            "required_new_branch": "new source-bound geometry contract, actual GenCase count/mass/support QA, then solver request",
        },
        "checks": checks,
        "preparation_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    value = audit()
    if args.self_test:
        print(json.dumps({"status": "PASS_F2_SOURCE_CONTINUUM_AUDIT_SELF_TEST", "mass_comparison": value["mass_comparison"], "qualification": value["qualification"]}, ensure_ascii=False, indent=2))
        return 0
    output = args.output.expanduser().resolve()
    if output.exists():
        if output.read_text(encoding="utf-8") == json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n":
            print(json.dumps({"status": value["status"], "output": str(output), "sha256": sha256(output)}, ensure_ascii=False))
            return 0
        raise FileExistsError(f"refuse overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "output": str(output), "sha256": sha256(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
