#!/usr/bin/env python3
"""Prepare the five fresh F7 first8 internal target-angle source assets.

The worker is deliberately disabled in this handoff.  If Root later launches
it, it creates one endpoint-specific motion table and one Definition clone per
endpoint, changing only the declared motion subtree and the scalar amplitude
used to generate the motion table.  It never changes the explicit-wet
geometry, dp, execution recipe, pivot, moving type, or mass policy.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "ds02.f7.target-angle-source-preparation.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_motion_module(path: Path):
    spec = importlib.util.spec_from_file_location("f7_target_angle_owner_motion", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import motion module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_without_motion(root: ET.Element) -> bytes:
    clone = copy.deepcopy(root)
    motion = clone.find("casedef/motion")
    if motion is None:
        raise ValueError("source Definition lacks casedef/motion")
    motion.clear()
    return ET.tostring(clone, encoding="utf-8")


def validate_source_definition(path: Path, expected_sha: str, plan: dict[str, Any]) -> dict[str, Any]:
    if sha256(path) != expected_sha:
        raise RuntimeError(f"source Definition hash mismatch: {path}")
    root = ET.parse(path).getroot()
    definition = root.find("casedef/geometry/definition")
    if definition is None or definition.attrib.get("dp") != "0.02":
        raise ValueError("F7 endpoint source must remain the native dp=0.02 Definition")
    params = {
        str(node.attrib.get("key")): str(node.attrib.get("value"))
        for node in root.findall("execution/parameters/parameter")
    }
    if params.get("TimeMax") != "12" or params.get("TimeOut") != "0.02":
        raise ValueError("F7 source window/save cadence differs from the bound source")
    motion = root.find("casedef/motion/objreal[@ref='2']")
    if motion is None:
        raise ValueError("F7 source lacks the ref=2 moving-body motion object")
    rot = motion.find("mvrotfile")
    if rot is None or rot.find("file") is None or rot.find("file").attrib.get("name") != "motion_obstacle_quintic.dat":
        raise ValueError("F7 source motion filename is not the bound native filename")
    p1 = rot.find("axisp1")
    p2 = rot.find("axisp2")
    if p1 is None or p2 is None or [p1.attrib.get(k) for k in "xyz"] != ["-0.04", "0", "0.05"] or [p2.attrib.get(k) for k in "xyz"] != ["-0.04", "0", "1.05"]:
        raise ValueError("F7 source pivot differs from the bound native pivot")
    expected = plan["fixed_physical_and_numerical_source"]["source_native_particle_counts"]
    return {
        "source_definition_sha256": expected_sha,
        "dp_m": float(definition.attrib["dp"]),
        "time_max_s": float(params["TimeMax"]),
        "time_out_s": float(params["TimeOut"]),
        "pivot_p1_m": [-0.04, 0.0, 0.05],
        "pivot_p2_m": [-0.04, 0.0, 1.05],
        "native_source_particle_counts": {
            "fixed": int(expected["fixed"]),
            "moving": int(expected["moving"]),
            "fluid": int(expected["fluid"]),
        },
        "geometry_without_motion_sha256": hashlib.sha256(canonical_without_motion(root)).hexdigest(),
    }


def prepare(plan_path: Path, output_root: Path, execute: bool) -> int:
    plan = load_json(plan_path)
    if plan.get("stage_contract", {}).get("launch_allowed") is not False:
        raise RuntimeError("source plan must remain launch_allowed=false")
    if not execute:
        raise RuntimeError("source builder requires the explicit Root-only --execute switch")
    module_path = Path(plan["selected_motion_module"])
    if sha256(module_path) != plan["selected_motion_module_sha256"]:
        raise RuntimeError("selected motion module hash differs from the registered source")
    source_motion = Path(plan["source_motion_template"])
    if sha256(source_motion) != plan["source_motion_template_sha256"]:
        raise RuntimeError("source motion template hash differs from the registered source")
    source_definition_external = Path(plan["source_definition"])
    if sha256(source_definition_external) != plan["source_definition_sha256"]:
        raise RuntimeError("external source Definition hash differs from the registered source")
    motion = load_motion_module(module_path)
    output_root.mkdir(parents=True, exist_ok=False)
    endpoint_receipts: list[dict[str, Any]] = []
    for endpoint in plan["endpoints"]:
        endpoint_id = str(endpoint["endpoint_id"])
        source_clone = plan_path.parent / str(endpoint["source_definition_clone"])
        source_meta = validate_source_definition(
            source_clone,
            str(endpoint["source_definition_clone_sha256"]),
            plan,
        )
        endpoint_root = output_root / endpoint_id
        endpoint_root.mkdir(parents=False, exist_ok=False)
        motion_path = endpoint_root / str(Path(endpoint["prepared_motion_relative"]).name)
        definition_path = endpoint_root / str(Path(endpoint["prepared_definition_relative"]).name)
        amplitude = float(endpoint["amplitude_deg"])
        motion_content = motion.generate_motion_dat_content(amplitude, 12.0, 0.001)
        motion_rows = [
            line.split()
            for line in motion_content.splitlines()
            if line and not line.startswith("#")
        ]
        if len(motion_rows) != 12001 or motion_rows[0] != ["0", "0"] or float(motion_rows[-1][0]) != 12.0 or float(motion_rows[-1][1]) != 0.0:
            raise RuntimeError(f"endpoint motion source does not cover the exact 0..12 s window: {endpoint_id}")
        motion_sha = motion.write_motion_file_exclusive(motion_path, motion_content)
        definition_text = motion.generate_smooth_c2_definition_xml(source_clone, motion_path.name)
        definition_path.write_text(definition_text, encoding="utf-8")
        undo = motion.verify_xml_declared_subtree_undo(source_clone, definition_path)
        if not undo.get("whole_tree_identical_upon_undo") or not undo.get("declared_motion_subtree_isolated"):
            raise RuntimeError(f"motion-only XML verification failed: {endpoint_id}")
        generated = ET.parse(definition_path).getroot()
        generated_motion = generated.find("casedef/motion/objreal[@ref='2']/mvrotfile")
        if generated_motion is None or generated_motion.find("file").attrib.get("name") != motion_path.name:
            raise RuntimeError(f"prepared Definition does not bind its endpoint motion file: {endpoint_id}")
        endpoint_receipts.append(
            {
                "endpoint_id": endpoint_id,
                "physical_case_id": endpoint["physical_case_id"],
                "physical_condition_sha256": endpoint["physical_condition_sha256"],
                "amplitude_deg": amplitude,
                "source_definition": str(source_clone),
                "source_definition_sha256": sha256(source_clone),
                "prepared_definition": str(definition_path),
                "prepared_definition_sha256": sha256(definition_path),
                "motion_file": str(motion_path),
                "motion_file_sha256": motion_sha,
                "motion_rows": len(motion_rows),
                "native_reader": plan["fixed_physical_and_numerical_source"]["native_motion_reader"],
                "native_sampled_regular": plan["fixed_physical_and_numerical_source"]["native_sampled_regular"],
                "source_recipe": source_meta,
                "motion_only_undo": undo,
                "geometry_policy": "source Definition geometry and execution fields retained; motion subtree only",
                "mass_policy": "native wet-fluid mass 325.60001628000003 kg distinct from continuum envelope 320.1984 kg; no rescale",
            }
        )
    report = {
        "schema": SCHEMA,
        "scope_id": plan["scope_id"],
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "endpoint_count": len(endpoint_receipts),
        "endpoints": endpoint_receipts,
        "sampled_motion_tables_written": [row["motion_file"] for row in endpoint_receipts],
        "binary_or_particle_outputs": [],
        "gencase": "not performed by this builder",
        "native_qa": "not performed by this builder",
        "solver": "forbidden",
        "conversion": "forbidden",
        "rendering": "forbidden",
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "launch_allowed": False,
    }
    write_json(output_root / "motion-source-preparation.json", report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", help="Root-only explicit launch switch")
    args = parser.parse_args()
    return prepare(args.plan, args.output_root, args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
