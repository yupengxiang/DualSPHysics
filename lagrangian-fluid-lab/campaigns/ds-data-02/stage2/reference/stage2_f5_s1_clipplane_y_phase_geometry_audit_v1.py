#!/usr/bin/env python3
"""Audit the F5 fluid-box Y lattice phase without running GenCase.

The source and candidate Def files are small XML inputs.  This audit derives
the inclusive Cartesian lattice population implied by each ``pointref`` and
the initial fluid drawbox.  It is a geometry arithmetic diagnostic only: the
bundled GenCase parser may apply additional shape/clip rules, so the report
never calls these counts an actual generated population or a mass pass.

The legacy Y=0 candidates are kept as immutable comparison inputs.  The
forward Y-half candidates move only ``pointref.y`` relative to those legacy
candidate Def files: +0.005 m at dp=.010 and +0.0025 m at dp=.005.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE_REL = "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
SOURCE_DEF_DEFAULT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/"
    "handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/"
    "candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml"
)
LEGACY_ROOT_DEFAULT = PRIMARY_REPO / REFERENCE_REL / "stage2_f5_s1_clipplane_repair_v2_inputs/F5_S1"
YHALF_ROOT_DEFAULT = PRIMARY_REPO / REFERENCE_REL / "stage2_f5_s1_clipplane_repair_v5_inputs/F5_S1"
CHANGES_DEFAULT = PRIMARY_REPO / "CHANGES.txt"
TEMPLATE_DEFAULT = PRIMARY_REPO / "doc/xml_format/GenCase_CaseTemplate.xml"
SCHEMA = "ds02.stage2.f5-s1.clipplane-y-phase-geometry-audit.v1"

GRIDS = {
    "dp010": {
        "dp_m": 0.010,
        "legacy_def": "F5_S1_CLIPPLANE_CENTER_LATTICE_DP010_Def.xml",
        "yhalf_def": "F5_S1_CLIPPLANE_YHALF_LATTICE_DP010_Def.xml",
        "legacy_y_m": 0.0,
        "yhalf_m": 0.005,
    },
    "dp005": {
        "dp_m": 0.005,
        "legacy_def": "F5_S1_CLIPPLANE_CENTER_LATTICE_DP005_Def.xml",
        "yhalf_def": "F5_S1_CLIPPLANE_YHALF_LATTICE_DP005_Def.xml",
        "legacy_y_m": 0.0,
        "yhalf_m": 0.0025,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_xml_or_document_hashed_by_audit",
    }


def local_name(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def finite_number(value: str | None, label: str) -> float:
    if value is None:
        raise ValueError(f"missing {label}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite {label}")
    return number


def parse_definition(path: Path) -> dict[str, Any]:
    root = ET.fromstring(path.read_bytes())
    definition = next((node for node in root.iter() if local_name(node) == "definition"), None)
    if definition is None:
        raise ValueError(f"missing definition: {path}")
    pointref = next((node for node in definition if local_name(node) == "pointref"), None)
    if pointref is None:
        raise ValueError(f"missing pointref: {path}")
    point = tuple(finite_number(pointref.get(axis), f"pointref.{axis}") for axis in "xyz")
    dp = finite_number(definition.get("dp"), "definition.dp")
    target = next(
        (node for node in root.iter() if local_name(node) == "drawbox" and "initial_fluid_equilibrium" in (node.get("cmt") or "")),
        None,
    )
    if target is None:
        raise ValueError(f"missing initial fluid drawbox: {path}")
    point_node = next((node for node in target if local_name(node) == "point"), None)
    size_node = next((node for node in target if local_name(node) == "size"), None)
    if point_node is None or size_node is None:
        raise ValueError(f"initial fluid drawbox lacks point/size: {path}")
    low = tuple(finite_number(point_node.get(axis), f"fluid.low.{axis}") for axis in "xyz")
    size = tuple(finite_number(size_node.get(axis), f"fluid.size.{axis}") for axis in "xyz")
    if any(value <= 0.0 for value in size):
        raise ValueError(f"initial fluid drawbox has non-positive size: {path}")
    return {"path": str(path), "dp_m": dp, "pointref_m": point, "fluid_low_m": low, "fluid_size_m": size, "fluid_high_m": tuple(low[i] + size[i] for i in range(3))}


def normalize_except_phase(data: bytes) -> bytes:
    """Mask dp and all pointref coordinates for representation comparison."""

    import re

    data, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb"\1<DP>\2", data, count=1)
    if count != 1:
        raise ValueError("expected one definition@dp")
    data, count = re.subn(rb'<pointref\s+x="[^"]+"\s+y="[^"]+"\s+z="[^"]+"\s*/>', b'<pointref x="<X>" y="<Y>" z="<Z>" />', data, count=1)
    if count != 1:
        raise ValueError("expected one pointref")
    return data


def lattice_axis(low: float, high: float, phase: float, dp: float) -> dict[str, Any]:
    """Count points in an inclusive endpoint lattice model."""

    tolerance = max(1e-12, abs(dp) * 1e-10)
    first = math.ceil((low - phase) / dp - 1e-10)
    last = math.floor((high - phase) / dp + 1e-10)
    count = max(0, last - first + 1)
    first_value = phase + first * dp if count else None
    last_value = phase + last * dp if count else None
    return {
        "model": "inclusive_cartesian_endpoint_lattice",
        "count": count,
        "first_m": first_value,
        "last_m": last_value,
        "includes_low_endpoint": bool(count and abs(first_value - low) <= tolerance),
        "includes_high_endpoint": bool(count and abs(last_value - high) <= tolerance),
        "low_m": low,
        "high_m": high,
        "phase_m": phase,
        "dp_m": dp,
    }


def grid_audit(grid: str, source_def: Path, legacy_root: Path, yhalf_root: Path) -> dict[str, Any]:
    spec = GRIDS[grid]
    legacy = regular(legacy_root / grid / spec["legacy_def"], f"{grid} legacy Y=0 Def")
    yhalf = regular(yhalf_root / grid / spec["yhalf_def"], f"{grid} Y-half Def")
    source = parse_definition(source_def)
    legacy_facts = parse_definition(legacy)
    yhalf_facts = parse_definition(yhalf)
    if abs(legacy_facts["dp_m"] - spec["dp_m"]) > 1e-12 or abs(yhalf_facts["dp_m"] - spec["dp_m"]) > 1e-12:
        raise ValueError(f"{grid}: candidate dp mismatch")
    if legacy_facts["fluid_low_m"] != yhalf_facts["fluid_low_m"] or legacy_facts["fluid_size_m"] != yhalf_facts["fluid_size_m"]:
        raise ValueError(f"{grid}: Y phase candidate changed fluid drawbox")
    if normalize_except_phase(legacy.read_bytes()) != normalize_except_phase(yhalf.read_bytes()):
        raise ValueError(f"{grid}: Y phase candidate changed Def outside dp/pointref")
    expected_y = round(legacy_facts["fluid_size_m"][1] / spec["dp_m"])
    legacy_axes = [lattice_axis(legacy_facts["fluid_low_m"][i], legacy_facts["fluid_high_m"][i], legacy_facts["pointref_m"][i], spec["dp_m"]) for i in range(3)]
    yhalf_axes = [lattice_axis(yhalf_facts["fluid_low_m"][i], yhalf_facts["fluid_high_m"][i], yhalf_facts["pointref_m"][i], spec["dp_m"]) for i in range(3)]
    legacy_y = legacy_axes[1]["count"]
    yhalf_y = yhalf_axes[1]["count"]
    if legacy_y != expected_y + 1 or yhalf_y != expected_y:
        raise ValueError(f"{grid}: registered Y phase does not produce expected arithmetic counts")
    return {
        "grid": grid,
        "dp_m": spec["dp_m"],
        "source_pointref_m": list(source["pointref_m"]),
        "fluid_low_m": list(legacy_facts["fluid_low_m"]),
        "fluid_high_m": list(legacy_facts["fluid_high_m"]),
        "fluid_size_m": list(legacy_facts["fluid_size_m"]),
        "legacy_y0": {"pointref_m": list(legacy_facts["pointref_m"]), "axes": legacy_axes, "fluid_count_model": math.prod(axis["count"] for axis in legacy_axes)},
        "yhalf": {"pointref_m": list(yhalf_facts["pointref_m"]), "axes": yhalf_axes, "fluid_count_model": math.prod(axis["count"] for axis in yhalf_axes)},
        "expected_centered_y_count": expected_y,
        "legacy_y_excess_count": legacy_y - expected_y,
        "legacy_y_population_excess_fraction_vs_centered": legacy_y / expected_y - 1.0,
        "yhalf_vs_legacy_population_fraction": yhalf_y / legacy_y - 1.0,
        "interpretation": "GEOMETRY_ARITHMETIC_SUPPORTS_Y_HALF; NOT_AN_ACTUAL_GENCASE_RESULT",
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    source = regular(args.source_def, "F5 source Def")
    legacy_root = args.legacy_root.expanduser().resolve()
    yhalf_root = args.yhalf_root.expanduser().resolve()
    changes = regular(args.changes, "CHANGES.txt")
    template = regular(args.template, "GenCase template")
    grids = [grid_audit(grid, source, legacy_root, yhalf_root) for grid in GRIDS]
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_GEOMETRY_ARITHMETIC_Y_PHASE_AUDIT",
        "family_id": "F5",
        "sentinel_id": "F5-S1",
        "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
        "scope": {
            "source_and_candidate_xml_read": True,
            "changes_document_read": True,
            "template_read": True,
            "vtk_read": False,
            "bi4_read": False,
            "gencase_started": False,
            "solver_started": False,
            "actual_particle_counts": False,
        },
        "inputs": {
            "source_def": record(source, "F5 source Def"),
            "changes": record(changes, "CHANGES.txt"),
            "template": record(template, "GenCase template"),
        },
        "grids": grids,
        "conclusion": {
            "legacy_y0_endpoint_model": "Y=0 lies on both fluid-box y endpoints for dp=.010/.005",
            "legacy_excess_fraction_model": {"dp010": grids[0]["legacy_y_population_excess_fraction_vs_centered"], "dp005": grids[1]["legacy_y_population_excess_fraction_vs_centered"]},
            "forward_candidate": "Y-half phase removes the modeled extra endpoint while preserving fluid drawbox, clip, bed and motion inputs",
            "qualification": "UNKNOWN_UNTIL_PARENT_GENCASE_SUPPORT_AND_MASS_AUDIT",
            "not_proven": ["GenCase endpoint/tie behavior", "actual fluid population", "continuous mass agreement", "VTK support/overlap"],
        },
    }
    if args.output is not None:
        output = args.output.expanduser().resolve()
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"refuse to overwrite immutable audit report: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
            temporary.unlink(missing_ok=True)
        os.replace(temporary, output)
        report["output"] = str(output)
    return report


def self_test() -> dict[str, Any]:
    assert lattice_axis(-0.14, 0.14, 0.0, 0.01)["count"] == 29
    assert lattice_axis(-0.14, 0.14, 0.005, 0.01)["count"] == 28
    assert lattice_axis(-0.14, 0.14, 0.0, 0.005)["count"] == 57
    assert lattice_axis(-0.14, 0.14, 0.0025, 0.005)["count"] == 56
    return {"status": "PASS", "schema": SCHEMA, "vtk_or_bi4_read": False, "gencase_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--audit", action="store_true")
    parser.add_argument("--source-def", type=Path, default=SOURCE_DEF_DEFAULT)
    parser.add_argument("--legacy-root", type=Path, default=LEGACY_ROOT_DEFAULT)
    parser.add_argument("--yhalf-root", type=Path, default=YHALF_ROOT_DEFAULT)
    parser.add_argument("--changes", type=Path, default=CHANGES_DEFAULT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_DEFAULT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    report = audit(args)
    print(json.dumps({"status": report["status"], "schema": report["schema"], "grids": report["grids"], "output": report.get("output"), "gencase_started": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
