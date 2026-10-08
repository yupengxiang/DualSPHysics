#!/usr/bin/env python3
"""Audit the completed F7-S2 half-CFL GenCase before any CFD launch.

The v8 GenCase receipt completed successfully, but its stdout reports that
the prescribed motion file was not copied into the generated-case directory.
This forward audit reads only the receipt, stdout, generated XML, the small
Def XML and the prescribed motion table.  It never opens the generated BI4,
native Part/HDF5 data, or starts a solver.

The report deliberately separates:

* XML/count/mass structural checks,
* motion-file closure, and
* the unperformed BI4 initial QA.

Consequently a successful GenCase receipt cannot make the half-CFL case
CFD-ready while either the motion copy or the BI4 QA is unresolved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f7-s2.half-cfl-initial-qa-audit.v3"
REPO = Path(__file__).resolve().parents[5]
DEFAULT_OUTPUT = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f7_s2_half_cfl_initial_qa_audit_v3.json"
)
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
RECEIPT = DATA_ROOT / (
    "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/"
    "f7-half-cfl-gencase-v8-001-root-001/execution-receipt.json"
)
OUTPUT_ROOT = RECEIPT.parent
GENERATED_XML = OUTPUT_ROOT / "prepared/F7_OBSTACLE_QUINTIC_B08_A065_half_cfl01.xml"
STDOUT = OUTPUT_ROOT / "stdout.log"
HALF_DEF = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2-consumers/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "f7-half-cfl-v1/source/F7_OBSTACLE_QUINTIC_B08_A065_half_cfl01_Def.xml"
)
REFERENCE_DEF = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_TARGET_ANGLE_ENDPOINTS/root-stage1-f7-target030-065-actual-motion-preparation-074/"
    "prepared/F7_OBSTACLE_QUINTIC_B08_A065/F7_OBSTACLE_QUINTIC_B08_A065_Def.xml"
)
MOTION = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_TARGET_ANGLE_ENDPOINTS/root-stage1-f7-target030-065-actual-motion-preparation-074/"
    "prepared/F7_OBSTACLE_QUINTIC_B08_A065/motion_obstacle_quintic.dat"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256_file(path),
    }


def tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def fattr(node: ET.Element, key: str) -> float:
    raw = node.attrib.get(key)
    if raw is None:
        raise ValueError(f"{tag(node)} missing @{key}")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{tag(node)} @{key} is non-finite")
    return value


def box(node: ET.Element) -> dict[str, Any]:
    point = node.find("point")
    size = node.find("size")
    if point is None or size is None:
        raise ValueError("drawbox missing point/size")
    point_m = [fattr(point, axis) for axis in ("x", "y", "z")]
    size_m = [fattr(size, axis) for axis in ("x", "y", "z")]
    return {
        "point_m": point_m,
        "size_m": size_m,
        "end_m": [point_m[i] + size_m[i] for i in range(3)],
        "comment": node.attrib.get("cmt"),
    }


def parse_xml(path: Path, *, generated: bool) -> dict[str, Any]:
    root = ET.fromstring(path.read_bytes())
    active: tuple[str, str] | None = None
    fluid_boxes: list[dict[str, Any]] = []
    moving_boxes: list[dict[str, Any]] = []
    fixed_boxes: list[dict[str, Any]] = []
    for node in root.iter():
        name = tag(node)
        if name in {"setmkfluid", "setmkbound"}:
            active = ("fluid" if name == "setmkfluid" else "bound", str(node.attrib.get("mk", "")))
        elif name == "drawbox" and active is not None:
            parsed = box(node)
            if active == ("fluid", "1"):
                fluid_boxes.append(parsed)
            elif active == ("bound", "2"):
                moving_boxes.append(parsed)
            elif active == ("bound", "0"):
                fixed_boxes.append(parsed)

    values: dict[str, list[float]] = {}
    for name in ("dp", "massfluid", "massbound"):
        values[name] = [fattr(node, "value") for node in root.iter() if tag(node) == name and "value" in node.attrib]
        if not values[name] and generated:
            raise ValueError(f"{path}: missing {name}@value")
        if values[name] and max(values[name]) - min(values[name]) > 1e-12:
            raise ValueError(f"{path}: conflicting {name} values: {values[name]}")

    motion_nodes = [node for node in root.iter() if tag(node) == "mvrotfile"]
    motion: list[dict[str, Any]] = []
    for node in motion_nodes:
        file_node = node.find("file")
        if file_node is None or not file_node.attrib.get("name"):
            raise ValueError(f"{path}: mvrotfile missing file name")
        motion.append(
            {
                "file_name": file_node.attrib["name"],
                "duration_s": fattr(node, "duration"),
                "angles_units": node.attrib.get("anglesunits"),
            }
        )

    particles: dict[str, list[dict[str, Any]]] = {"fluid": [], "moving": []}
    if generated:
        for node in root.iter():
            name = tag(node)
            if name == "fluid" and "begin" in node.attrib and "count" in node.attrib:
                particles["fluid"].append({"mkfluid": node.attrib.get("mkfluid"), "mk": node.attrib.get("mk"), "count": int(node.attrib["count"])})
            elif name == "moving" and "begin" in node.attrib and "count" in node.attrib:
                particles["moving"].append({"mkbound": node.attrib.get("mkbound"), "mk": node.attrib.get("mk"), "count": int(node.attrib["count"])})

    result = {
        "path": str(path.resolve()),
        "fluid_boxes": fluid_boxes,
        "moving_boxes": moving_boxes,
        "fixed_boxes": fixed_boxes,
        "scalar_values": {name: (values[name][0] if values[name] else None) for name in values},
        "motion": motion,
        "particles": particles,
    }
    if generated:
        result["fluid_particle_count"] = sum(item["count"] for item in particles["fluid"])
        result["moving_particle_count"] = sum(item["count"] for item in particles["moving"])
    return result


def same_number(actual: float, expected: float, tol: float = 1e-12) -> bool:
    return (
        actual is not None
        and expected is not None
        and math.isfinite(actual)
        and math.isfinite(expected)
        and abs(actual - expected) <= tol
    )


def same_boxes(actual: list[dict[str, Any]], expected: list[dict[str, Any]]) -> bool:
    if len(actual) != len(expected):
        return False
    for a, e in zip(actual, expected):
        for key in ("point_m", "size_m"):
            if len(a[key]) != len(e[key]) or any(not same_number(x, y) for x, y in zip(a[key], e[key])):
                return False
    return True


def build() -> dict[str, Any]:
    receipt_record = record(RECEIPT, "GenCase receipt")
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("the bound GenCase receipt is not completed successfully")
    if receipt.get("cfd_invoked") is not False or receipt.get("model_invoked") is not False:
        raise ValueError("bound receipt is not GenCase-only")

    generated_record = record(GENERATED_XML, "generated half-CFL XML")
    stdout_record = record(STDOUT, "GenCase stdout")
    half_def_record = record(HALF_DEF, "half-CFL Def")
    reference_def_record = record(REFERENCE_DEF, "reference Def")
    motion_record = record(MOTION, "prescribed motion table")
    generated = parse_xml(GENERATED_XML, generated=True)
    half_def = parse_xml(HALF_DEF, generated=False)
    reference_def = parse_xml(REFERENCE_DEF, generated=False)
    stdout = STDOUT.read_text(encoding="utf-8", errors="replace")
    warning = "File 'motion_obstacle_quintic.dat' not found to copy"
    warning_count = stdout.count(warning)
    motion_name = generated["motion"][0]["file_name"] if generated["motion"] else None
    output_motion = GENERATED_XML.parent / motion_name if motion_name else None
    motion_copy_ok = bool(output_motion and output_motion.is_file() and not output_motion.is_symlink())
    xml_match = {
        "fluid_boxes_equal_to_half_def": same_boxes(generated["fluid_boxes"], half_def["fluid_boxes"]),
        "moving_boxes_equal_to_half_def": same_boxes(generated["moving_boxes"], half_def["moving_boxes"]),
        "fluid_boxes_equal_to_reference_def": same_boxes(generated["fluid_boxes"], reference_def["fluid_boxes"]),
        "moving_boxes_equal_to_reference_def": same_boxes(generated["moving_boxes"], reference_def["moving_boxes"]),
        "dp_matches_half_def": half_def["scalar_values"]["dp"] is None or same_number(generated["scalar_values"]["dp"], half_def["scalar_values"]["dp"]),
        "massfluid_matches_half_def": half_def["scalar_values"]["massfluid"] is None or same_number(generated["scalar_values"]["massfluid"], half_def["scalar_values"]["massfluid"]),
        "massbound_matches_half_def": half_def["scalar_values"]["massbound"] is None or same_number(generated["scalar_values"]["massbound"], half_def["scalar_values"]["massbound"]),
        # GenCase writes the same mvrotfile under both casedef and execution;
        # the Def source has one declaration.  Compare the effective first
        # declaration, while retaining the generated node count below.
        "motion_config_matches_half_def": bool(generated["motion"]) and bool(half_def["motion"]) and generated["motion"][0] == half_def["motion"][0],
        "motion_config_matches_reference_def": bool(generated["motion"]) and bool(reference_def["motion"]) and generated["motion"][0] == reference_def["motion"][0],
    }
    structural_pass = all(xml_match.values()) and generated["fluid_particle_count"] == 40700 and generated["moving_particle_count"] == 1984
    fluid_mass = generated["fluid_particle_count"] * generated["scalar_values"]["massfluid"]
    moving_mass = generated["moving_particle_count"] * generated["scalar_values"]["massbound"]

    if motion_copy_ok:
        motion_copy_status = "PASS"
        motion_copy_reason = "generated XML directory contains the referenced motion table"
    else:
        motion_copy_status = "FAIL_MISSING_REFERENCED_MOTION_FILE"
        motion_copy_reason = "GenCase stdout reports the source motion table was not copied; no output file exists at the generated XML directory"

    return {
        "schema": SCHEMA,
        "status": "BLOCKED_MOTION_COPY_AND_BI4_INITIAL_QA",
        "sentinel_id": "F7-S2",
        "family_id": "F7",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "read_policy": {
            "gen_case_xml_read": True,
            "source_def_read": True,
            "motion_table_read": True,
            "receipt_and_stdout_read": True,
            "bi4_read": False,
            "native_part_read": False,
            "h5_read": False,
            "solver_started": False,
        },
        "inputs": {
            "execution_receipt": receipt_record,
            "generated_xml": generated_record,
            "stdout": stdout_record,
            "half_cfl_def": half_def_record,
            "reference_def": reference_def_record,
            "motion_source": motion_record,
        },
        "gen_case_receipt": {
            "status": receipt["status"],
            "returncode": receipt["returncode"],
            "attempt_id": receipt.get("request", {}).get("attempt_id"),
            "output_root": receipt.get("output_root"),
            "bytes": receipt.get("bytes"),
            "cfd_invoked": receipt.get("cfd_invoked"),
            "model_invoked": receipt.get("model_invoked"),
            "qualification": receipt.get("qualification"),
        },
        "xml_structural_qa": {
            "status": "PASS" if structural_pass else "FAIL",
            "checks": xml_match,
            "fluid_particle_count": generated["fluid_particle_count"],
            "moving_particle_count": generated["moving_particle_count"],
            "fluid_sample_mass_kg": fluid_mass,
            "moving_sample_mass_kg_diagnostic": moving_mass,
            "mass_semantics": "particle sample only; no rigid-body mass inference",
            "expected_half_cfl_dp_m": 0.02,
            "expected_half_cfl_target_cfl": 0.1,
            "expected_reference_cfl": 0.2,
            "generated_mvrotfile_node_count": len(generated["motion"]),
            "source_def_mvrotfile_node_count": len(half_def["motion"]),
        },
        "motion_control_closure": {
            "referenced_file_name": motion_name,
            "source_motion": motion_record,
            "generated_directory_expected_path": str(output_motion) if output_motion else None,
            "generated_directory_file_present": motion_copy_ok,
            "stdout_missing_copy_warning_count": warning_count,
            "status": motion_copy_status,
            "reason": motion_copy_reason,
            "source_copy_repair_required_before_solver": True,
        },
        "bi4_initial_qa": {
            "status": "NOT_RUN_NO_BI4_OPEN_BY_THIS_AUDIT",
            "required_checks": [
                "new half-CFL BI4 source hash/stat under parent guard",
                "fluid/moving/fixed counts and native mass from the generated half-CFL BI4",
                "initial source/typed QA against this generated XML",
                "motion file content/hash closure in the solver input directory",
            ],
            "baseline_counts_must_not_be_substituted": True,
        },
        "forward_solver_gate": {
            "solver_launch_allowed": False,
            "cfd_invoked": False,
            "status": "BLOCKED_UNTIL_MOTION_COPY_REPAIRED_AND_BI4_INITIAL_QA_COMPLETES",
            "required_parent_artifacts": [
                "forward generated-case receipt with copied motion file and input SHA/stat closure",
                "BI4 initial QA receipt bound to generated XML",
                "typed QA and motion target closure",
                "parent GPU UUID lease and exact cutoff/cpu ledger reservation",
            ],
            "gpu_cutoff": {
                "status": "UNKNOWN_PENDING_PARENT_GUARD",
                "must_not_reuse_v5_same_cfl_cutoff_without_new_cost_evidence": True,
                "v5_history_preserved": True,
            },
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse overwrite of immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def self_test() -> None:
    assert same_number(0.02, 0.02)
    assert not same_number(float("nan"), 0.02)
    assert not same_boxes(
        [{"point_m": [0, 0, 0], "size_m": [1, 1, 1]}],
        [{"point_m": [0, 0, 0], "size_m": [1, 1, 1.001]}],
    )
    print("stage2 F7-S2 half-CFL initial QA audit v2 self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    atomic_json(args.output, build())
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
