#!/usr/bin/env python3
"""F6 fixed-geometry resolution and native rigid-state evidence tools.

This module deliberately imports the frozen F6 parent generator instead of
editing it.  The repaired parent definitions are the physical mother
geometry.  The three registered candidates use the same wall, fluid fill,
floating body and (for the wave parent) paddle dimensions; only the native
particle spacing and its exclusive GenCase pointmax margin vary.

The module only prepares bounded shared-runner requests and audits completed
outputs.  It never launches a solver or selects a GPU.  A post-processing
request can convert the native BI4 frames into a transparent HDF5 bundle with
all fixed, moving, floating and fluid particles, then run the official
FloatingInfo and ComputeForces tools.  HDF5 conversion is a representation of
the native files, not a numerical qualification claim.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.util
import json
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F6"
FROZEN_PARENT_SOURCE = REPO_ROOT / "scripts/ds_data02_f6.py"
RUNTIME_SOURCE = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime.py")
OFFICIAL_ROOT = REPO_ROOT / "vendor/official/DualSPHysics_v5.4"
BIN_ROOT = OFFICIAL_ROOT / "bin/linux"
GENCASE_BINARY = BIN_ROOT / "GenCase_linux64"
FLOATING_INFO_BINARY = BIN_ROOT / "FloatingInfo_linux64"
COMPUTE_FORCES_BINARY = BIN_ROOT / "ComputeForces_linux64"
PARTVTK_BINARY = BIN_ROOT / "PartVTK_linux64"
_ROOT_BI4_DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
BI4_DECODER = _ROOT_BI4_DECODER if _ROOT_BI4_DECODER.is_file() else REPO_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
PYTHON_EXECUTABLE = (REPO_ROOT / ".venv/bin/python") if (REPO_ROOT / ".venv/bin/python").is_file() else Path(sys.executable)
REPAIR_ID = "F6_HIGH_WALL_GRID_ALIGNMENT_REPAIR_02"
REPAIR_ROOT = FAMILY_ROOT / "parent_inputs/repairs" / REPAIR_ID
RESOLUTION_ROOT = FAMILY_ROOT / "parameterized_resolution"
RAW_F6_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
# The shared runtime places F6 attempts directly under families/F6/<case>,
# regardless of the source JSON's parameterized_resolution directory.
RAW_RESOLUTION_ROOT = RAW_F6_ROOT

SCHEMA = "ds-data-02.f6.fixed-geometry-resolution.v1"
POSTPROCESS_SCHEMA = "ds-data-02.f6.native-rigid-state-audit.v1"
RESOLUTION_DPS: dict[str, float] = {"coarse": 0.060, "medium": 0.030, "fine": 0.020}
EVENT_WINDOW_S = [0.0, 12.0]
CONTROL_DT_S = 0.01
SAVE_DT_S = 0.05
MECHANISMS = ("simple_free_response", "wave_no_contact")
PARENT_CASES = {
    "simple_free_response": "F6_SIMPLE_FREE_RESPONSE_PARENT",
    "wave_no_contact": "F6_WAVE_NO_CONTACT_PARENT",
}
PARENT_OUTPUT_ATTEMPT = {
    "simple_free_response": "F6_SIMPLE_FREE_RESPONSE_PARENT_F6_HIGH_WALL_GRID_ALIGNMENT_REPAIR_02_SOLVER_QUAL_01",
    "wave_no_contact": "F6_WAVE_NO_CONTACT_PARENT_F6_HIGH_WALL_GRID_ALIGNMENT_REPAIR_02_SOLVER_QUAL_01",
}
PARENT_SOLVER_RAW = {
    mechanism: RAW_F6_ROOT / f"{PARENT_CASES[mechanism]}_{REPAIR_ID}" / PARENT_OUTPUT_ATTEMPT[mechanism]
    for mechanism in MECHANISMS
}


def _load_frozen_parent_source():
    """Load the parent source under a private name without generating files."""
    spec = importlib.util.spec_from_file_location("_ds_data02_f6_frozen_parent", FROZEN_PARENT_SOURCE)
    if spec is None or spec.loader is None:
        raise ImportError(FROZEN_PARENT_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fmt(value: float) -> str:
    return f"{float(value):.12g}"


def _float_attr(node: ET.Element, name: str) -> float:
    value = node.get(name)
    if value is None:
        raise ValueError(f"missing {name} on <{node.tag}>")
    return float(value)


def _vec(node: ET.Element, names: str = "xyz") -> list[float]:
    return [_float_attr(node, axis) for axis in names]


def _drawbox(root: ET.Element, comment: str) -> ET.Element:
    node = root.find(f".//drawbox[@cmt='{comment}']")
    if node is None:
        raise ValueError(f"missing drawbox cmt={comment!r}")
    return node


def parse_physical_definition(definition: Path) -> dict[str, Any]:
    """Extract continuous physical geometry from a repaired Definition.

    `pointmax` is intentionally stored separately as a numerical bound.  The
    wall size, body, fill and paddle values are the continuous mother geometry
    and must be identical across all three resolution candidates.
    """
    root = ET.parse(definition).getroot()
    definition_node = root.find("./casedef/geometry/definition")
    if definition_node is None:
        raise ValueError(f"missing geometry definition: {definition}")
    pointmax = definition_node.find("pointmax")
    if pointmax is None:
        raise ValueError(f"missing pointmax: {definition}")
    wall = _drawbox(root, "Finite tank walls")
    wall_point = wall.find("point")
    wall_size = wall.find("size")
    if wall_point is None or wall_size is None:
        raise ValueError("finite wall lacks point/size")
    body = _drawbox(root, "Free rigid body")
    body_point = body.find("point")
    body_size = body.find("size")
    if body_point is None or body_size is None:
        raise ValueError("floating body lacks point/size")
    fill = root.find(".//fillbox")
    if fill is None:
        raise ValueError("missing fluid fillbox")
    fill_point = fill.find("point")
    fill_size = fill.find("size")
    if fill_point is None or fill_size is None:
        raise ValueError("fluid fillbox lacks point/size")
    floating = root.find("./casedef/floatings/floating")
    if floating is None:
        raise ValueError("missing casedef floating block")
    massbody = floating.find("massbody")
    if massbody is None:
        raise ValueError("missing casedef massbody")
    floating_mkbound = int(floating.get("mkbound", "50"))
    paddle_node = root.find(".//drawbox[@cmt='Wave piston']")
    paddle: dict[str, Any] | None = None
    if paddle_node is not None:
        paddle_point = paddle_node.find("point")
        paddle_size = paddle_node.find("size")
        if paddle_point is None or paddle_size is None:
            raise ValueError("wave paddle lacks point/size")
        paddle_marker = root.find(".//wavepaddles/piston/mkbound")
        paddle = {
            "point_m": _vec(paddle_point),
            "size_m": _vec(paddle_size),
            "mkbound": int(paddle_marker.get("value", "10")) if paddle_marker is not None else 10,
        }
    seed = [_float_attr(fill, axis) for axis in "xyz"]
    return {
        "definition_path": str(definition.resolve()),
        "definition_sha256": sha256_file(definition),
        "physical_wall_point_m": _vec(wall_point),
        "physical_wall_size_m": _vec(wall_size),
        "gencase_pointmax_m": _vec(pointmax),
        "body": {
            "point_m": _vec(body_point),
            "size_m": _vec(body_size),
            "mkbound": floating_mkbound,
            "mass_kg": float(massbody.get("value", "nan")),
        },
        "fluid_fill": {"seed_m": seed, "point_m": _vec(fill_point), "size_m": _vec(fill_size)},
        "paddle": paddle,
        "solver_dimension_declared": 3,
        "continuous_geometry_hash": "",
    }


def _canonical_geometry(geometry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "physical_wall_point_m": geometry["physical_wall_point_m"],
        "physical_wall_size_m": geometry["physical_wall_size_m"],
        "body": geometry["body"],
        "fluid_fill": geometry["fluid_fill"],
        "paddle": geometry.get("paddle"),
    }


def _geometry_hash(geometry: Mapping[str, Any]) -> str:
    text = json.dumps(_canonical_geometry(geometry), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_inertia(body: Mapping[str, Any]) -> list[list[float]]:
    mass = float(body["mass_kg"])
    sx, sy, sz = (float(x) for x in body["size_m"])
    return [[mass * (sy * sy + sz * sz) / 12.0, 0.0, 0.0],
            [0.0, mass * (sx * sx + sz * sz) / 12.0, 0.0],
            [0.0, 0.0, mass * (sx * sx + sy * sy) / 12.0]]


def _find_repaired_inputs(mechanism: str) -> dict[str, Path]:
    parent = PARENT_CASES[mechanism]
    directory = REPAIR_ROOT / mechanism
    return {
        "definition": directory / f"{parent}_{REPAIR_ID}_Def.xml",
        "control": directory / f"{parent}_{REPAIR_ID}_Control.csv",
        "native": directory / f"{parent}_{REPAIR_ID}_Native.json",
        "normal": directory / f"{parent}_{REPAIR_ID}_Normal.json",
    }


def _lineage_comparison() -> dict[str, Any]:
    """Bind the final mother geometry to old parent/repair evidence bounds."""
    rows: dict[str, Any] = {}
    for mechanism in MECHANISMS:
        parent = PARENT_CASES[mechanism]
        old_definition = FAMILY_ROOT / "parent_inputs" / mechanism / f"{parent}_Def.xml"
        final_definition = _find_repaired_inputs(mechanism)["definition"]
        old_geometry = parse_physical_definition(old_definition) if old_definition.is_file() else None
        final_geometry = parse_physical_definition(final_definition) if final_definition.is_file() else None
        candidate_dirs = sorted(RAW_F6_ROOT.glob(f"{parent}_*/"))
        repair_evidence = []
        for directory in candidate_dirs:
            for receipt in sorted(directory.glob("*/execution-receipt.json")):
                item = read_json(receipt)
                repair_evidence.append({"attempt": str(receipt.parent.name), "case_root": str(directory.name), "status": item.get("status"), "returncode": item.get("returncode"), "total_particles": item.get("total_particles"), "fluid_particles": item.get("fluid_particles"), "solver_dimension": item.get("solver_dimension_from_gencase"), "receipt_sha256": sha256_file(receipt)})
        base_root = RAW_F6_ROOT / parent
        old_solver = []
        for attempt in (f"{parent}_SOLVER_QUAL_01", f"{parent}_SOLVER_QUAL_02"):
            receipt = base_root / attempt / "execution-receipt.json"
            if receipt.is_file():
                item = read_json(receipt)
                old_solver.append({"attempt": attempt, "status": item.get("status"), "returncode": item.get("returncode"), "receipt_sha256": sha256_file(receipt)})
        final_root = RAW_F6_ROOT / f"{parent}_{REPAIR_ID}"
        final_gencase = final_root / f"{parent}_{REPAIR_ID}_GENCASE_02" / "execution-receipt.json"
        final_solver = final_root / f"{parent}_{REPAIR_ID}_SOLVER_QUAL_01" / "execution-receipt.json"
        rows[mechanism] = {
            "old_parent_definition": {"path": str(old_definition.resolve()), "sha256": sha256_file(old_definition) if old_definition.is_file() else None, "physical_wall_size_m": old_geometry.get("physical_wall_size_m") if old_geometry else None, "fluid_fill": old_geometry.get("fluid_fill") if old_geometry else None},
            "final_grid_repair_definition": {"path": str(final_definition.resolve()), "sha256": sha256_file(final_definition) if final_definition.is_file() else None, "repair_id": REPAIR_ID, "physical_wall_size_m": final_geometry.get("physical_wall_size_m") if final_geometry else None, "fluid_fill": final_geometry.get("fluid_fill") if final_geometry else None},
            "old_parent_solver_attempts": old_solver,
            "repair_and_final_attempts": repair_evidence,
            "final_gencase_receipt": {"path": str(final_gencase), "sha256": sha256_file(final_gencase) if final_gencase.is_file() else None, "status": read_json(final_gencase).get("status") if final_gencase.is_file() else "missing"},
            "final_solver_receipt": {"path": str(final_solver), "sha256": sha256_file(final_solver) if final_solver.is_file() else None, "status": read_json(final_solver).get("status") if final_solver.is_file() else "missing"},
            "comparison_semantics": "old parent/QUAL01/QUAL02 receipts remain failed or non-equivalent evidence; final grid repair is a new physical mother geometry and successful 12 s run, not automatic Q-N",
        }
    return rows


def _base_spec(mechanism: str, geometry: Mapping[str, Any], case_id: str, dp: float) -> dict[str, Any]:
    frozen = _load_frozen_parent_source()
    specs = frozen._parent_specs()
    spec = copy.deepcopy(specs[mechanism])
    spec["case_id"] = case_id
    spec["dp_m"] = float(dp)
    wall = [float(x) for x in geometry["physical_wall_size_m"]]
    spec["tank"] = {"length_m": wall[0], "width_m": wall[1], "height_m": wall[2]}
    spec["body"]["point_m"] = list(geometry["body"]["point_m"])
    spec["body"]["size_m"] = list(geometry["body"]["size_m"])
    spec["body"]["mkbound"] = int(geometry["body"]["mkbound"])
    spec["body"]["mass_kg"] = float(geometry["body"]["mass_kg"])
    spec["fluid_fill"] = copy.deepcopy(geometry["fluid_fill"])
    if geometry.get("paddle") is None:
        spec.pop("paddle", None)
    else:
        spec["paddle"] = copy.deepcopy(geometry["paddle"])
    return spec


def _definition_for_resolution(frozen: Any, spec: Mapping[str, Any], geometry: Mapping[str, Any], resolution_id: str) -> str:
    text = frozen._definition_xml(spec)
    wall = [float(x) for x in geometry["physical_wall_size_m"]]
    dp = float(spec["dp_m"])
    replacement = f'<pointmax x="{_fmt(wall[0] + dp)}" y="{_fmt(wall[1] + dp)}" z="{_fmt(wall[2] + dp)}" />'
    text, count = re.subn(r"<pointmax\b[^>]*/>", replacement, text, count=1)
    if count != 1:
        raise ValueError("parent definition has no pointmax")
    banner = (
        f"<!-- F6 fixed-geometry resolution {resolution_id}; physical wall/body/fluid/paddle values are copied "
        f"from {REPAIR_ID}; pointmax is computational wall+dp margin only. -->"
    )
    declaration_end = text.find("?>")
    if declaration_end < 0:
        return banner + "\n" + text
    declaration_end += 2
    return text[:declaration_end] + "\n" + banner + text[declaration_end:]


def _copy_input(source: Path, target: Path) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return {"path": str(target.resolve()), "sha256": sha256_file(target), "source_path": str(source.resolve()), "source_sha256": sha256_file(source), "byte_identical": sha256_file(source) == sha256_file(target)}


def _expected_counts(geometry: Mapping[str, Any], dp: float) -> dict[str, int]:
    # This is a cost estimate only.  GenCase remains the source of actual
    # counts, including face overlap and floating-body representation.
    fluid_volume = math.prod(float(x) for x in geometry["fluid_fill"]["size_m"])
    body_volume = math.prod(float(x) for x in geometry["body"]["size_m"])
    wall = geometry["physical_wall_size_m"]
    wall_area = 2.0 * (wall[0] * wall[1] + wall[0] * wall[2] + wall[1] * wall[2])
    fluid = max(1, round(fluid_volume / dp**3))
    floating = max(1, round(body_volume / dp**3))
    fixed = max(1, round(wall_area * max(dp, 1e-9) / dp**3))
    moving = 0
    if geometry.get("paddle"):
        moving = max(1, round(math.prod(float(x) for x in geometry["paddle"]["size_m"]) / dp**3))
    return {"fluid": fluid, "floating": floating, "fixed": fixed, "moving": moving, "total": fluid + floating + fixed + moving}


def _gencase_request(case: Mapping[str, Any], request_file: str) -> dict[str, Any]:
    paths = case["paths"]
    input_files = [
        Path(__file__).resolve(), FROZEN_PARENT_SOURCE.resolve(), RUNTIME_SOURCE.resolve(), GENCASE_BINARY.resolve(),
        Path(paths["definition"]["path"]).resolve(), Path(paths["control"]["path"]).resolve(),
        Path(paths["native"]["path"]).resolve(), Path(paths["normal"]["path"]).resolve(),
    ]
    # GenCase uses the basename without _Def as its prefix.  Runtime replaces
    # the external attempt root, making every output attempt immutable.
    prefix_name = Path(paths["definition"]["path"]).stem.removesuffix("_Def")
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6",
        "case_id": case["case_id"],
        "attempt_id": f"{case['case_id']}_GENCASE_01",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "command": [str(GENCASE_BINARY.resolve()), str(Path(paths["definition"]["path"]).with_suffix("")), f"{{attempt_root}}/{prefix_name}", "-save:all"],
        "cwd": str(Path(paths["definition"]["path"]).parent.resolve()),
        "max_wall_seconds": 300,
        "cpu_threads": 4,
        "estimated_storage_bytes": 268435456,
        "input_files": [str(path) for path in input_files],
        "worktree_root": str(REPO_ROOT.resolve()),
        "request_file": request_file,
        "mechanism_id": case["mechanism_id"],
        "resolution_id": case["resolution_id"],
        "solver_dimension_required": 3,
        "purpose": "bounded F6 fixed-continuous-geometry GenCase; actual counts and wall/floating ledgers are required before any solver request",
        "expected": {
            "dp_m": case["dp_m"],
            "physical_geometry_hash": case["physical_geometry_hash"],
            "floating_type": 2,
            "fluid_type": 3,
            "moving_particles": 1 if case["paddle"] else 0,
            "estimated_counts": case["estimated_counts"],
            "max_wall_seconds": 300,
            "max_storage_bytes": 268435456,
        },
    }


def prepare_resolution_study(output_root: Path = RESOLUTION_ROOT) -> dict[str, Any]:
    """Write six fixed-geometry Definitions and shared-runner CPU requests."""
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    frozen = _load_frozen_parent_source()
    rows: list[dict[str, Any]] = []
    geometry_records: dict[str, Any] = {}
    for mechanism in MECHANISMS:
        sources = _find_repaired_inputs(mechanism)
        if not all(path.is_file() for path in sources.values()):
            missing = [str(path) for path in sources.values() if not path.is_file()]
            raise FileNotFoundError("missing repaired F6 input(s): " + ", ".join(missing))
        geometry = parse_physical_definition(sources["definition"])
        geometry["continuous_geometry_hash"] = _geometry_hash(geometry)
        geometry_records[mechanism] = geometry
        for resolution_id, dp in RESOLUTION_DPS.items():
            case_id = f"F6_{mechanism.upper()}_RES_{resolution_id.upper()}"
            case_dir = output_root / "cases" / mechanism / resolution_id
            spec = _base_spec(mechanism, geometry, case_id, dp)
            definition = case_dir / f"{case_id}_Def.xml"
            definition.parent.mkdir(parents=True, exist_ok=True)
            definition.write_text(_definition_for_resolution(frozen, spec, geometry, resolution_id), encoding="utf-8")
            ET.parse(definition)
            copied = {
                "definition": {"path": str(definition.resolve()), "sha256": sha256_file(definition), "source_path": str(sources["definition"].resolve()), "source_sha256": sha256_file(sources["definition"]), "byte_identical": False},
                "control": _copy_input(sources["control"], case_dir / f"{case_id}_Control.csv"),
                "native": _copy_input(sources["native"], case_dir / f"{case_id}_Native.json"),
                "normal": _copy_input(sources["normal"], case_dir / f"{case_id}_Normal.json"),
            }
            estimates = _expected_counts(geometry, dp)
            body = geometry["body"]
            body_volume = math.prod(float(x) for x in body["size_m"])
            fluid_volume = math.prod(float(x) for x in geometry["fluid_fill"]["size_m"])
            row = {
                "schema": SCHEMA,
                "family_id": "F6",
                "mechanism_id": mechanism,
                "parent_case_id": PARENT_CASES[mechanism],
                "repair_id": REPAIR_ID,
                "case_id": case_id,
                "resolution_id": resolution_id,
                "dp_m": dp,
                "continuous_geometry_hash": geometry["continuous_geometry_hash"],
                "physical_geometry_hash": geometry["continuous_geometry_hash"],
                "physical_wall_size_m": geometry["physical_wall_size_m"],
                "pointmax_m": [float(x) + dp for x in geometry["physical_wall_size_m"]],
                "body": {**body, "volume_m3": body_volume, "source_inertia_kg_m2": _source_inertia(body)},
                "fluid_fill": {**geometry["fluid_fill"], "volume_m3": fluid_volume, "continuous_mass_kg": fluid_volume * 1000.0},
                "paddle": geometry.get("paddle"),
                "paths": copied,
                "estimated_counts": estimates,
                "estimated_storage_bytes": 268435456,
                "status": "gencase_pending",
            }
            request_file = f"execution_requests/{mechanism}_{resolution_id}_gencase.json"
            request = _gencase_request(row, request_file)
            request_path = output_root / request_file
            write_json(request_path, request)
            row["request"] = {"path": str(request_path.resolve()), "sha256": sha256_file(request_path), "attempt_id": request["attempt_id"]}
            write_json(case_dir / "case.json", row)
            rows.append(row)

    plan = {
        "schema": SCHEMA,
        "family_id": "F6",
        "status": "registered_gencase_pending",
        "generator": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__))},
        "frozen_parent_source": {"path": str(FROZEN_PARENT_SOURCE.resolve()), "sha256": sha256_file(FROZEN_PARENT_SOURCE)},
        "repair_parent": REPAIR_ID,
        "historical_reuse": {
            "old_f6_1357m_identity_reused": False,
            "old_parent_qual01_qual02_reused_for_solver": False,
            "repaired_parent_12s_terminal_reused_for_native_postprocessing": True,
            "semantics": "the native audit reads the terminal grid-repair raw BI4/Run files; it does not relaunch or mutate the old failed attempts or the historical 13.57M-particle identity",
        },
        "resolution_ids": list(RESOLUTION_DPS),
        "dp_m": RESOLUTION_DPS,
        "same_continuous_geometry": True,
        "geometry_contract": "wall, fluid fill, floating body, paddle, mass and source inertia are byte/number-bound from the repaired parent; pointmax=physical wall+dp is computational margin only",
        "actual_final_dimensions": {mechanism: geometry_records[mechanism]["physical_wall_size_m"] for mechanism in MECHANISMS},
        "requested_reference_dimension_note": {
            "note": "The current repaired F6 Definitions contain wall dimensions 5.46x1.56x1.26 m (simple) and 6.00x1.56x1.26 m (wave). The strings 2.76 and 0.90 do not occur as physical wall dimensions in these inputs; 2.76 is a control/log time value. No .12 candidate or .90-to-.84 snap is substituted.",
            "decision": "use parsed repaired physical dimensions and preserve them at every resolution",
        },
        "source_mass_inertia_volume": {
            mechanism: {
                "mass_kg": geometry_records[mechanism]["body"]["mass_kg"],
                "volume_m3": math.prod(geometry_records[mechanism]["body"]["size_m"]),
                "source_inertia_kg_m2": _source_inertia(geometry_records[mechanism]["body"]),
                "density_ratio_to_water": geometry_records[mechanism]["body"]["mass_kg"] / (math.prod(geometry_records[mechanism]["body"]["size_m"]) * 1000.0),
            }
            for mechanism in MECHANISMS
        },
        "event_time_sampling": {
            "complete_event_window_s": EVENT_WINDOW_S,
            "control_dt_s": CONTROL_DT_S,
            "native_save_dt_s": SAVE_DT_S,
            "events": {
                "simple_free_response": ["initial_still_water", "release_at_zero", "successive_heave_roll_pitch_extrema", "decay_tail", "final_mass_momentum_audit"],
                "wave_no_contact": ["initial_still_water", "wave_ramp", "first_wave_arrival", "steady_wave_cycles", "last_cycle_decay", "final_mass_momentum_audit"],
            },
            "coordinate_frames": {"simple_free_response": "tank_attached_inertial", "wave_no_contact": "world_tank_and_tank_attached_observations"},
        },
        "geometry_boundary_mass_audit": {
            "finite_wall_faces": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top"],
            "high_low_face_rule": "actual generated fixed particle low/high x/y planes plus bottom plane; ratio and counts recorded per candidate",
            "ghost_policy": "fixed particles are a finite boundary representation; numerical ghost fluid is not counted as fluid",
            "representmass_policy": "report native MassFluid*type3 count, MassPart/MassBound Type=2 per-particle mass, aggregate massbody and source analytic inertia separately; never rescale",
            "volume_error_policy": "record fluid continuous-volume mass error, floating discrete-volume error, aggregate mass error and generated inertia versus source analytic box inertia; all QI/QN gates remain pending",
        },
        "integrator_save_registration": {
            "status": "registered_pending_measured_baseline",
            "variants": ["native_adaptive_baseline", "fixed_half_measured_stable_baseline_min"],
            "fixed_rule": "materialize numeric DtFixed only after complete-window baseline RunPARTs.csv/Run.out; DtFixed <= 0.5*measured stable minimum dt",
            "same_geometry_control_window": True,
            "save_variants_s": [0.025, 0.05, 0.10],
            "save_study_is_not_integrator_evidence": True,
        },
        "matrix": rows,
        "resolution_study_status": "registered_pending_actual_gencase_and_solver",
        "q_status": "QI/QN pending; this plan and GenCase receipts do not qualify a solver recipe",
    }
    write_json(output_root / "resolution_plan.json", plan)
    write_json(output_root / "resolution_manifest.json", {"schema": SCHEMA, "rows": rows, "status": "registered_gencase_pending"})
    return plan


def _generated_prefix(receipt: Mapping[str, Any]) -> Path | None:
    command = receipt.get("command")
    if isinstance(command, list) and len(command) >= 3:
        return Path(str(command[2])).resolve()
    output = receipt.get("output_root")
    if isinstance(output, str):
        matches = sorted(Path(output).glob("*.xml"))
        if matches:
            return matches[0].with_suffix("")
    return None


def _receipt_hash_binding(receipt: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    """Report immutable runner hashes separately from the current worktree.

    A completed receipt records the bytes used at launch.  This module may
    later gain read-only audit code, so the current source hash can differ
    without making the already completed GenCase run disappear.  The copied
    Definition/Control/Native/Normal companions are expected to remain byte
    identical and are checked against the receipt's after-run hashes.
    """
    at_launch = receipt.get("input_hashes_at_launch", {})
    after_run = receipt.get("input_hashes_after_run", {})
    if not isinstance(at_launch, Mapping):
        at_launch = {}
    if not isinstance(after_run, Mapping):
        after_run = {}
    paths = {
        "resolution_source": Path(__file__).resolve(),
        "frozen_parent_source": FROZEN_PARENT_SOURCE.resolve(),
        "runtime_source": RUNTIME_SOURCE.resolve(),
        "gencase_binary": GENCASE_BINARY.resolve(),
        "definition": Path(case["paths"]["definition"]["path"]).resolve(),
        "control": Path(case["paths"]["control"]["path"]).resolve(),
        "native": Path(case["paths"]["native"]["path"]).resolve(),
        "normal": Path(case["paths"]["normal"]["path"]).resolve(),
    }
    rows: dict[str, Any] = {}
    for label, path in paths.items():
        key = str(path)
        current = sha256_file(path) if path.is_file() else None
        launch = at_launch.get(key)
        after = after_run.get(key)
        rows[label] = {
            "path": key,
            "hash_at_launch": launch,
            "hash_after_run": after,
            "current_hash": current,
            "recorded_at_launch": isinstance(launch, str),
            "recorded_after_run": isinstance(after, str),
            "after_run_matches_current": isinstance(after, str) and after == current,
            "launch_matches_after_run": isinstance(launch, str) and launch == after,
        }
    companion_labels = ("definition", "control", "native", "normal")
    return {
        "inputs": rows,
        "all_requested_inputs_recorded": all(item["recorded_after_run"] for item in rows.values()),
        "companions_match_current_bytes": all(rows[label]["after_run_matches_current"] for label in companion_labels),
        "source_hash_is_historical_when_changed": rows["resolution_source"]["recorded_after_run"] and not rows["resolution_source"]["after_run_matches_current"],
        "interpretation": "runner hashes at launch/after-run bind the completed attempt; current source may include later read-only audit code, while copied case companions must still match exactly",
    }


def _vtk_points(path: Path) -> list[tuple[float, float, float]]:
    # GenCase writes legacy binary VTK with big-endian float32 points.
    import struct
    data = Path(path).read_bytes()
    marker = data.find(b"POINTS ")
    if marker < 0:
        raise ValueError(f"VTK POINTS block not found: {path}")
    end = data.find(b"\n", marker)
    header = data[marker:end].split()
    if len(header) < 3 or header[2].lower() != b"float":
        raise ValueError(f"unsupported VTK point representation: {path}")
    count = int(header[1])
    values = struct.unpack_from(">" + "f" * count * 3, data, end + 1)
    return [(float(values[i]), float(values[i + 1]), float(values[i + 2])) for i in range(0, len(values), 3)]


def _generated_wall_planes(points: Sequence[tuple[float, float, float]], fixed_begin: int, fixed_count: int) -> dict[str, Any]:
    fixed = list(points[fixed_begin:fixed_begin + fixed_count])
    if not fixed:
        return {"available": False, "pass": False, "error": "empty fixed particle range"}
    planes: dict[str, Any] = {}
    passed = True
    for axis, name in ((0, "x"), (1, "y")):
        low = min(point[axis] for point in fixed)
        high = max(point[axis] for point in fixed)
        low_count = sum(abs(point[axis] - low) < 1e-6 for point in fixed)
        high_count = sum(abs(point[axis] - high) < 1e-6 for point in fixed)
        ratio = high_count / low_count if low_count else 0.0
        current = low_count > 0 and high_count > 0 and ratio >= 0.75
        passed = passed and current
        planes[name] = {"low_m": low, "high_m": high, "low_count": low_count, "high_count": high_count, "high_to_low_ratio": ratio, "pass": current}
    zlow = min(point[2] for point in fixed)
    zlow_count = sum(abs(point[2] - zlow) < 1e-6 for point in fixed)
    planes["bottom"] = {"low_m": zlow, "low_count": zlow_count, "pass": zlow_count > 0}
    passed = passed and zlow_count > 0
    return {"available": True, "planes": planes, "pass": passed, "ghost_semantics": "fixed finite-wall particles are a boundary representation; no numerical ghost fluid is counted"}


def _inertia_from_generated(node: ET.Element | None) -> list[list[float]]:
    if node is None:
        return []
    inertia = node.find("inertia")
    if inertia is None:
        return []
    result: list[list[float]] = []
    for row in (1, 2, 3):
        values = inertia.find(f"values[@v{row}1]")
        if values is None:
            return []
        result.append([float(values.get(f"v{row}{col}", "nan")) for col in (1, 2, 3)])
    return result


def audit_gencase(case_path: Path, receipt_path: Path | None = None) -> dict[str, Any]:
    case = read_json(Path(case_path) / "case.json")
    if receipt_path is None:
        request = read_json(Path(case["request"]["path"]))
        receipt_path = RAW_RESOLUTION_ROOT / case["case_id"] / request["attempt_id"] / "execution-receipt.json"
    receipt_path = Path(receipt_path).resolve()
    result: dict[str, Any] = {"schema": f"{SCHEMA}.gencase-audit", "case_id": case["case_id"], "receipt_path": str(receipt_path), "errors": []}
    if not receipt_path.is_file():
        result.update(status="pending", errors=["receipt not present"])
        return result
    receipt = read_json(receipt_path)
    result["receipt_sha256"] = sha256_file(receipt_path)
    if receipt.get("status") != "completed" or int(receipt.get("returncode", 1)) != 0:
        result.update(status="fail", errors=["GenCase receipt is not successful"])
        return result
    prefix = _generated_prefix(receipt)
    if prefix is None:
        result.update(status="fail", errors=["receipt has no generated prefix"])
        return result
    xml_path = prefix.with_suffix(".xml")
    vtk_path = prefix.with_name(prefix.name + "_All.vtk")
    normal_path = prefix.with_name(prefix.name + "__Actual.vtk")
    try:
        root = ET.parse(xml_path).getroot()
        particles = root.find("./execution/particles")
        constants = root.find("./execution/constants")
        if particles is None or constants is None:
            raise ValueError("generated XML lacks particles/constants")
        fluid = particles.find("fluid")
        floating = particles.find("floating")
        fixed = particles.find("fixed")
        if fluid is None or floating is None or fixed is None:
            raise ValueError("generated XML lacks fixed/fluid/floating block")
        moving = [node for node in particles if node.tag == "moving"]
        counts = {"fluid": int(fluid.get("count", "0")), "floating": int(floating.get("count", "0")), "fixed": int(fixed.get("count", "0")), "moving": sum(int(node.get("count", "0")) for node in moving)}
        dp = float(constants.find("dp").get("value"))
        density = float(constants.find("rhop0").get("value"))
        massfluid = float(constants.find("massfluid").get("value"))
        massbound = float(constants.find("massbound").get("value", str(massfluid)))
        massbody_node = floating.find("massbody")
        massbody = float(massbody_node.get("value", "nan")) if massbody_node is not None else float("nan")
        inertia = _inertia_from_generated(floating)
        data2d = (constants.find("data2d").get("value", "true") if constants.find("data2d") is not None else "true").lower()
        points = _vtk_points(vtk_path)
        fluid_points = points[int(fluid.get("begin", "0")):int(fluid.get("begin", "0")) + counts["fluid"]]
        floating_points = points[int(floating.get("begin", "0")):int(floating.get("begin", "0")) + counts["floating"]]
        layers = sorted({round(point[1], 9) for point in fluid_points})
        wall = _generated_wall_planes(points, int(fixed.get("begin", "0")), counts["fixed"])
        body_volume = float(case["body"]["volume_m3"])
        fluid_volume = float(case["fluid_fill"]["volume_m3"])
        fluid_mass = massfluid * counts["fluid"]
        expected_fluid_particle_mass = density * dp**3
        body_discrete_volume = counts["floating"] * dp**3
        body_mass_source = float(case["body"]["mass_kg"])
        floating_inertia = inertia
        wave_moving = counts["moving"] > 0 if case["paddle"] else True
        hash_binding = _receipt_hash_binding(receipt, case)
        hash_inputs = hash_binding["inputs"]
        checks = {
            "actual_3d": receipt.get("solver_dimension_from_gencase") == 3 and data2d in {"false", "0", "no"},
            "positive_fluid_type3": counts["fluid"] > 0 and int(receipt.get("fluid_particles", 0)) == counts["fluid"],
            "positive_floating_type2": counts["floating"] > 0,
            "effective_transverse_layers": len(layers) >= 10,
            "finite_wall_faces_and_bottom": bool(wall.get("pass")),
            "all_requested_input_hashes_recorded": hash_binding["all_requested_inputs_recorded"],
            "definition_companion_hash_bound": hash_inputs["definition"]["after_run_matches_current"],
            "control_companion_hash_bound": hash_inputs["control"]["after_run_matches_current"],
            "native_companion_hash_bound": hash_inputs["native"]["after_run_matches_current"],
            "normal_companion_hash_bound": hash_inputs["normal"]["after_run_matches_current"],
            "source_hash_recorded": hash_inputs["resolution_source"]["recorded_after_run"],
            "fluid_mass_per_particle_native": expected_fluid_particle_mass > 0 and abs(massfluid - expected_fluid_particle_mass) / expected_fluid_particle_mass < 1e-9,
            "source_mass_positive": math.isfinite(body_mass_source) and body_mass_source > 0,
            "generated_mass_positive": math.isfinite(massbody) and massbody > 0,
            "generated_inertia_defined": len(floating_inertia) == 3 and all(math.isfinite(v) for row in floating_inertia for v in row) and all(floating_inertia[i][i] > 0 for i in range(3)),
            "wave_actual_moving_particles": wave_moving,
            "normal_geometry_present": normal_path.is_file(),
        }
        body_bounds = [[min(point[axis] for point in floating_points), max(point[axis] for point in floating_points)] for axis in range(3)] if floating_points else None
        result.update({
            "status": "pass" if all(checks.values()) else "fail",
            "checks": checks,
            "generated": {
                "xml": str(xml_path), "xml_sha256": sha256_file(xml_path), "all_vtk": str(vtk_path), "normal_vtk": str(normal_path),
                "total_particles": int(receipt.get("total_particles", sum(counts.values()))), "counts": counts,
                "dp_m": dp, "data2d": data2d, "transverse_layers": len(layers), "transverse_layer_coordinates_m": layers,
                "body_bounds_m": body_bounds, "fluid_bounds_m": [[min(p[a] for p in fluid_points), max(p[a] for p in fluid_points)] for a in range(3)] if fluid_points else None,
                "mass_per_particle_kg": {"fluid": massfluid, "fixed": massbound, "floating": float(floating.find("masspart").get("value", str(massbound))) if floating.find("masspart") is not None else massbound},
                "fluid_mass_kg": fluid_mass, "floating_mass_kg": massbody, "floating_inertia_kg_m2": floating_inertia,
                "source_body_mass_kg": body_mass_source, "source_body_volume_m3": body_volume, "source_body_inertia_kg_m2": case["body"]["source_inertia_kg_m2"],
                "fluid_continuous_volume_m3": fluid_volume, "fluid_continuous_mass_kg": fluid_volume * density,
                "fluid_representation_mass_relative_error": fluid_mass / (fluid_volume * density) - 1.0,
                "body_representation_volume_relative_error": body_discrete_volume / body_volume - 1.0,
                "body_mass_relative_error_to_source": massbody / body_mass_source - 1.0,
                "type_mass_ledger": {"type_3_fluid": {"count": counts["fluid"], "mass_kg": fluid_mass}, "type_2_floating": {"count": counts["floating"], "mass_kg": massbody}, "fixed_boundary_count": counts["fixed"], "moving_count": counts["moving"]},
            },
            "wall_planes": wall,
            "hash_binding": hash_binding,
            "semantic_limits": {"fixed_particles_are_boundary_representation": True, "ghost_fluid_counted": False, "mass_inertia_source": "generated XML floating massbody/inertia; source analytic box inertia recorded separately"},
        })
        result["errors"].extend(name for name, passed in checks.items() if not passed)
    except (OSError, ValueError, TypeError, ET.ParseError, struct.error, IndexError) as exc:  # type: ignore[name-defined]
        result.update(status="fail", errors=[f"GenCase audit error: {type(exc).__name__}: {exc}"])
    return result


def _parent_generated_prefix(mechanism: str) -> Path:
    receipt = PARENT_SOLVER_RAW[mechanism] / "execution-receipt.json"
    data = read_json(receipt)
    prefix = _generated_prefix(data)
    if prefix is None:
        raise ValueError(f"no parent generated prefix in {receipt}")
    return prefix


def _postprocess_request(mechanism: str, output_root: Path = RESOLUTION_ROOT) -> dict[str, Any]:
    case_id = f"F6_{mechanism.upper()}_NATIVE_AUDIT"
    attempt_id = f"{case_id}_POST_01"
    solver_attempt = PARENT_SOLVER_RAW[mechanism]
    solver_data = solver_attempt / "solver_output/data"
    generated_prefix = _parent_generated_prefix(mechanism)
    input_files = [
        Path(__file__).resolve(), RUNTIME_SOURCE.resolve(), FLOATING_INFO_BINARY.resolve(), COMPUTE_FORCES_BINARY.resolve(), PARTVTK_BINARY.resolve(),
        BI4_DECODER.resolve(), generated_prefix.with_suffix(".xml"), solver_attempt / "execution-receipt.json",
        solver_attempt / "solver_output/Run.out", solver_attempt / "solver_output/RunPARTs.csv", solver_data / "PartFloatInfo.ibi4",
        solver_data / "PartMotionRef.ibi4",
    ]
    # Estimate HDF5 storage from the actual parent particle count and the
    # saved frame count.  The request is deliberately bounded below 2 GiB and
    # remains CPU-only; a five-million-particle input needs a separate review.
    solver_run = solver_attempt / "solver_output/Run.csv"
    total = 0
    frames = len(list(solver_data.glob("Part_[0-9][0-9][0-9][0-9].bi4")))
    if solver_run.is_file():
        try:
            row = solver_run.read_text(encoding="utf-8", errors="replace").splitlines()[-1].split(";")
            total = int(row[3].replace(",", ""))
        except (IndexError, ValueError):
            total = 0
    estimated_h5 = max(128 * 1024**2, int(max(total, 1) * max(frames, 1) * (3 * 8 * 2 + 4 * 4 + 1)))
    return {
        "schema": "ds-data-02.runner.request.v1", "family_id": "F6", "case_id": case_id, "attempt_id": attempt_id,
        "kind": "cpu", "cpu_task_kind": "audit", "command": [str(PYTHON_EXECUTABLE), str(Path(__file__).resolve()), "run-postprocessors", "--mechanism", mechanism, "--data-dir", str(solver_data.resolve()), "--generated-prefix", str(generated_prefix.resolve()), "--output-dir", "{attempt_root}/native", "--decoder", str(BI4_DECODER.resolve()), "--threads", "4"],
        "cwd": str(REPO_ROOT.resolve()), "max_wall_seconds": 600, "cpu_threads": 4, "estimated_storage_bytes": min(max(estimated_h5, 256 * 1024**2), 2 * 1024**3),
        "input_files": [str(path.resolve()) for path in input_files if path.is_file()] + [str(PYTHON_EXECUTABLE)], "worktree_root": str(REPO_ROOT.resolve()),
        "mechanism_id": mechanism, "purpose": "post-terminal native full-type HDF5 representation plus official FloatingInfo and ComputeForces rigid state/force/torque audit; no solver/GPU",
        "solver_parent_attempt": str(solver_attempt.resolve()), "generated_prefix": str(generated_prefix.resolve()), "estimated_hdf5_bytes": estimated_h5,
        "unsupported_policy": "orientation is audited as native Euler roll/pitch/yaw; quaternion is explicitly unsupported unless a native source provides it",
    }


def prepare_postprocess_requests(output_root: Path = RESOLUTION_ROOT) -> dict[str, Any]:
    requests = []
    for mechanism in MECHANISMS:
        request = _postprocess_request(mechanism, output_root)
        base_relative = f"postprocess_requests/{mechanism}_native_audit.json"
        relative = base_relative
        # A terminal postprocessor attempt is immutable.  If it exists, use a
        # new request filename and attempt id; an unconsumed request may be
        # refreshed after a local tool/runtime correction.
        for number in range(1, 100):
            candidate_relative = base_relative if number == 1 else f"postprocess_requests/{mechanism}_native_audit_{number:02d}.json"
            candidate_path = output_root / candidate_relative
            candidate_request = read_json(candidate_path) if candidate_path.is_file() else None
            candidate_attempt = str(candidate_request.get("attempt_id")) if candidate_request else f"F6_{mechanism.upper()}_NATIVE_AUDIT_POST_{number:02d}"
            candidate_receipt = RAW_F6_ROOT / f"F6_{mechanism.upper()}_NATIVE_AUDIT" / candidate_attempt / "execution-receipt.json"
            if candidate_receipt.is_file():
                continue
            relative = candidate_relative
            request["attempt_id"] = candidate_attempt
            break
        request["request_file"] = relative
        path = output_root / relative
        write_json(path, request)
        request["request_sha256"] = sha256_file(path)
        requests.append(request)
    plan_path = output_root / "native_audit_plan.json"
    plan = {
        "schema": POSTPROCESS_SCHEMA, "family_id": "F6", "status": "ready_for_shared_cpu_postprocessing", "requests": requests,
        "postprocessors": {"FloatingInfo": str(FLOATING_INFO_BINARY.resolve()), "ComputeForces": str(COMPUTE_FORCES_BINARY.resolve()), "PartVTK": str(PARTVTK_BINARY.resolve()), "bi4_decoder": str(BI4_DECODER.resolve())},
        "required_rigid_state": ["pose_center", "orientation_euler", "linear_velocity", "angular_velocity", "mass", "inertia", "force", "torque"],
        "native_h5_contract": {"particle_roles": {"1": "fixed boundary", "2": "floating rigid body", "3": "fluid", "4": "moving paddle"}, "datasets": ["time", "particle_id", "particle_type", "mk", "position", "velocity", "density", "mass", "pressure", "valid"], "all_native_frames": True},
        "unsupported": ["native quaternion orientation is not emitted by FloatingInfo v5.4; Euler roll/pitch/yaw is retained as the exact native orientation representation"],
        "qualification_claim": "none; postprocessing and HDF5 packaging do not grant Q-I/Q-N",
    }
    write_json(plan_path, plan)
    return plan


def _runparts_summary(path: Path) -> dict[str, Any]:
    """Measure the actual adaptive integration schedule from RunPARTs.csv."""
    if not Path(path).is_file():
        return {"path": str(path), "status": "missing"}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    def numbers(name: str) -> list[float]:
        values = []
        for row in rows:
            try:
                value = float(str(row.get(name, "0")).replace(",", ""))
            except ValueError:
                continue
            if math.isfinite(value) and value > 0:
                values.append(value)
        return values
    dt_min = numbers("DtMin [s]")
    dt_max = numbers("DtMax [s]")
    steps: list[int] = []
    for row in rows:
        try:
            value = int(str(row.get("Steps", "0")).replace(",", ""))
        except ValueError:
            continue
        if value >= 0:
            steps.append(value)
    import statistics
    return {"path": str(Path(path).resolve()), "sha256": sha256_file(Path(path)), "rows": len(rows), "dt_min_s": min(dt_min) if dt_min else None, "dt_max_s": max(dt_max) if dt_max else None, "dt_median_s": statistics.median(dt_min) if dt_min else None, "native_steps_sum": sum(steps), "positive_dt_rows": len(dt_min), "fixed_half_rule_numeric_pending": min(dt_min) * 0.5 if dt_min else None, "scope": "observed adaptive parent baseline; no fixed-half solver dispatched"}


def refresh_evidence(output_root: Path = RESOLUTION_ROOT) -> dict[str, Any]:
    """Bind completed CPU receipts and native audits into the F6 plan.

    This function only reads terminal shared-runner outputs and writes new F6
    evidence metadata.  It never changes a request, raw solver input, or
    solver output.
    """
    output_root = Path(output_root)
    manifest_path = output_root / "resolution_manifest.json"
    plan_path = output_root / "resolution_plan.json"
    if not manifest_path.is_file() or not plan_path.is_file():
        raise FileNotFoundError("prepare the fixed-geometry resolution study first")
    manifest = read_json(manifest_path)
    plan = read_json(plan_path)
    gencase_rows: list[dict[str, Any]] = []
    for row in manifest.get("rows", []):
        case_dir = output_root / "cases" / str(row["mechanism_id"]) / str(row["resolution_id"])
        request = read_json(Path(row["request"]["path"]))
        receipt_path = RAW_RESOLUTION_ROOT / str(row["case_id"]) / str(request["attempt_id"]) / "execution-receipt.json"
        audit = audit_gencase(case_dir, receipt_path)
        audit_path = case_dir / "gencase-audit.json"
        write_json(audit_path, audit)
        row["status"] = f"gencase_{audit.get('status')}"
        row["gencase_receipt"] = {"path": str(receipt_path), "sha256": sha256_file(receipt_path) if receipt_path.is_file() else None, "status": audit.get("status")}
        row["gencase_audit"] = {"path": str(audit_path.resolve()), "sha256": sha256_file(audit_path), "status": audit.get("status"), "checks": audit.get("checks", {})}
        if isinstance(audit.get("generated"), Mapping):
            row["actual_counts"] = audit["generated"].get("counts")
            row["representation_errors"] = {"fluid_mass_relative": audit["generated"].get("fluid_representation_mass_relative_error"), "body_volume_relative": audit["generated"].get("body_representation_volume_relative_error"), "body_mass_relative": audit["generated"].get("body_mass_relative_error_to_source")}
        gencase_rows.append(row)
    manifest["rows"] = gencase_rows
    manifest["status"] = "gencase_audited_pending_solver" if all(row["status"] == "gencase_pass" for row in gencase_rows) else "gencase_audit_mixed_or_pending"
    write_json(manifest_path, manifest)
    plan["matrix"] = gencase_rows
    plan["status"] = manifest["status"]
    plan["historical_reuse"] = {
        "old_f6_1357m_identity_reused": False,
        "old_parent_qual01_qual02_reused_for_solver": False,
        "repaired_parent_12s_terminal_reused_for_native_postprocessing": True,
        "semantics": "the native audit reads the terminal grid-repair raw BI4/Run files; it does not relaunch or mutate the old failed attempts or the historical 13.57M-particle identity",
    }
    plan["generator"]["sha256"] = sha256_file(Path(__file__))
    plan["lineage_comparison"] = _lineage_comparison()
    plan["event_time_sampling"] = {
        "complete_event_window_s": EVENT_WINDOW_S,
        "control_dt_s": CONTROL_DT_S,
        "native_save_dt_s": SAVE_DT_S,
        "events": {
            "simple_free_response": ["initial_still_water", "release_at_zero", "successive_heave_roll_pitch_extrema", "decay_tail", "final_mass_momentum_audit"],
            "wave_no_contact": ["initial_still_water", "wave_ramp", "first_wave_arrival", "steady_wave_cycles", "last_cycle_decay", "final_mass_momentum_audit"],
        },
        "coordinate_frames": {"simple_free_response": "tank_attached_inertial", "wave_no_contact": "world_tank_and_tank_attached_observations"},
    }
    plan["geometry_boundary_mass_audit"] = {
        "finite_wall_faces": ["bottom", "left", "right", "front", "back"], "open_faces": ["top"],
        "high_low_face_rule": "actual generated fixed particle low/high x/y planes plus bottom plane; ratio and counts recorded per candidate",
        "ghost_policy": "fixed particles are a finite boundary representation; numerical ghost fluid is not counted as fluid",
        "representmass_policy": "report native MassFluid*type3 count, MassPart/MassBound Type=2 per-particle mass, aggregate massbody and source analytic inertia separately; never rescale",
        "volume_error_policy": "record fluid continuous-volume mass error, floating discrete-volume error, aggregate mass error and generated inertia versus source analytic box inertia; all QI/QN gates remain pending",
    }
    plan["integrator_save_registration"] = {
        "status": "registered_pending_measured_baseline", "variants": ["native_adaptive_baseline", "fixed_half_measured_stable_baseline_min"],
        "fixed_rule": "materialize numeric DtFixed only after complete-window baseline RunPARTs.csv/Run.out; DtFixed <= 0.5*measured stable minimum dt",
        "same_geometry_control_window": True, "save_variants_s": [0.025, 0.05, 0.10], "save_study_is_not_integrator_evidence": True,
    }
    plan["resolution_study_status"] = "gencase_audited_pending_solver"
    write_json(plan_path, plan)

    native_plan_path = output_root / "native_audit_plan.json"
    native_plan = read_json(native_plan_path) if native_plan_path.is_file() else prepare_postprocess_requests(output_root)
    native_evidence: list[dict[str, Any]] = []
    for request in native_plan.get("requests", []):
        request_path = output_root / str(request.get("request_file", ""))
        if not request_path.is_file():
            continue
        registered = read_json(request_path)
        receipt_path = RAW_F6_ROOT / str(registered["case_id"]) / str(registered["attempt_id"]) / "execution-receipt.json"
        evidence: dict[str, Any] = {"mechanism_id": registered.get("mechanism_id"), "case_id": registered.get("case_id"), "attempt_id": registered.get("attempt_id"), "request": {"path": str(request_path.resolve()), "sha256": sha256_file(request_path)}, "receipt": {"path": str(receipt_path), "sha256": sha256_file(receipt_path) if receipt_path.is_file() else None, "status": "pending"}}
        evidence["adaptive_baseline_runparts"] = _runparts_summary(Path(str(registered.get("solver_parent_attempt", ""))) / "solver_output/RunPARTs.csv")
        if receipt_path.is_file():
            receipt = read_json(receipt_path)
            evidence["receipt"].update({"status": receipt.get("status"), "returncode": receipt.get("returncode"), "bytes": receipt.get("bytes")})
            output_root_raw = Path(str(receipt.get("output_root", "")))
            audit_path = output_root_raw / "native/native_rigid_state_audit.json"
            if audit_path.is_file():
                audit = read_json(audit_path)
                # Earlier successful audit attempts predate the richer
                # Type=2 mass ledger.  Re-audit the immutable terminal files
                # in place without rerunning PartVTK/FloatingInfo/
                # ComputeForces, then store the derived summary in this new
                # worktree evidence file.  The raw attempt and its receipt
                # remain untouched.
                recomputed = audit
                recomputed_from_terminal = False
                if not audit.get("native_type_mass_ledger") or not audit.get("partvtk_initial", {}).get("type_counts"):
                    generated_prefix = Path(str(registered.get("generated_prefix", "")))
                    if generated_prefix.with_suffix(".xml").is_file():
                        candidate = audit_postprocessors(output_root_raw / "native", generated_prefix, str(registered.get("mechanism_id")))
                        if candidate.get("status") == "pass":
                            recomputed = candidate
                            recomputed_from_terminal = True
                evidence["audit"] = {
                    "path": str(audit_path),
                    "sha256": sha256_file(audit_path),
                    "status": recomputed.get("status"),
                    "errors": recomputed.get("errors", []),
                    "hdf5": recomputed.get("hdf5"),
                    "partvtk_initial": recomputed.get("partvtk_initial"),
                    "native_type_mass_ledger": recomputed.get("native_type_mass_ledger"),
                    "floating_info": recomputed.get("floating_info"),
                    "compute_forces": recomputed.get("compute_forces"),
                    "rigid_state_contract": recomputed.get("rigid_state_contract"),
                    "unsupported": recomputed.get("unsupported", []),
                    "recomputed_from_terminal_files": recomputed_from_terminal,
                }
        native_evidence.append(evidence)
    native_plan["requests_terminal"] = native_evidence
    native_pass = [item.get("audit", {}).get("status") == "pass" for item in native_evidence]
    native_plan["status"] = "terminal_native_audit_pass" if native_evidence and all(native_pass) else "native_audit_pending_or_failed"
    write_json(native_plan_path, native_plan)
    result = {"schema": POSTPROCESS_SCHEMA, "family_id": "F6", "status": "evidence_bound", "resolution_plan": str(plan_path.resolve()), "gencase": [{"case_id": row["case_id"], "status": row["status"], "actual_counts": row.get("actual_counts"), "audit": row["gencase_audit"]} for row in gencase_rows], "native": native_evidence, "native_plan_status": native_plan["status"], "qualification_claim": "none; complete-window parent solver and postprocessor evidence remains QI/QN pending"}
    write_json(output_root / "resolution_evidence.json", result)
    return result


def _parse_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return [], []
    delimiter = ";" if lines[0].count(";") >= lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    rows = list(reader)
    return [str(name or "") for name in (reader.fieldnames or [])], rows


def _parse_partvtk_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Skip PartVTK's frame-statistics preamble before reading particle rows."""
    lines = [line for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    header_index = next((index for index, line in enumerate(lines) if "Pos.x" in line and "Type" in line and "Mk" in line), None)
    if header_index is None:
        return [], []
    reader = csv.DictReader(lines[header_index:], delimiter=";")
    return [str(name or "") for name in (reader.fieldnames or [])], list(reader)


def _normal_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _has_header_group(headers: Sequence[str], needles: Sequence[str]) -> bool:
    normalized = [_normal_header(item) for item in headers]
    return any(any(needle in value for needle in needles) for value in normalized)


def audit_postprocessors(output_dir: Path, generated_prefix: Path, mechanism: str) -> dict[str, Any]:
    """Audit the completed native HDF5 and official rigid-state CSVs."""
    output_dir = Path(output_dir)
    h5_path = output_dir / "native_all_types.h5"
    partvtk_candidates = sorted(output_dir.glob("PartVTK_0000*"))
    partvtk_path = next((path for path in partvtk_candidates if path.suffix.lower() in {".csv", ".txt"}), None)
    floating_candidates = sorted(output_dir.glob("FloatingMotion*") )
    force_candidates = sorted(output_dir.glob("FloatingForce*") )
    floating_path = next((path for path in floating_candidates if path.suffix.lower() in {".csv", ".txt"}), None)
    force_path = next((path for path in force_candidates if path.suffix.lower() in {".csv", ".txt"}), None)
    result: dict[str, Any] = {"schema": POSTPROCESS_SCHEMA, "family_id": "F6", "mechanism_id": mechanism, "status": "pending", "errors": [], "unsupported": []}
    if not h5_path.is_file() or partvtk_path is None or floating_path is None or force_path is None:
        result["errors"] = ["native HDF5, PartVTK type/mass output, FloatingInfo output, or ComputeForces output is missing"]
        return result
    try:
        import h5py  # type: ignore
        import numpy as np  # type: ignore
        with h5py.File(h5_path, "r") as handle:
            required = {"time", "particle_id", "particle_type", "mk", "position", "velocity", "density", "mass", "pressure", "valid"}
            missing = sorted(required - set(handle.keys()))
            times = handle["time"][:]
            types = handle["particle_type"][:]
            valid = handle["valid"][:]
            h5_checks = {
                "required_datasets": not missing,
                "frames_positive": len(times) > 1,
                "time_monotonic": bool(len(times) > 1 and np.all(np.diff(times) > 0)),
                "all_native_types_present": bool(set(int(x) for x in np.unique(types)) >= {1, 2, 3} and (4 in set(int(x) for x in np.unique(types)) if mechanism == "wave_no_contact" else True)),
                "fixed_identity_valid": bool(valid[:, types == 1].all()) if np.any(types == 1) else False,
                "floating_identity_valid": bool(valid[:, types == 2].all()) if np.any(types == 2) else False,
                "fluid_identity_valid": bool(valid[:, types == 3].all()) if np.any(types == 3) else False,
                "moving_identity_valid": bool(valid[:, types == 4].all()) if np.any(types == 4) else (mechanism != "wave_no_contact"),
                "finite_position_velocity": bool(np.isfinite(handle["position"][:]).all() and np.isfinite(handle["velocity"][:]).all()),
            }
            h5_summary = {"path": str(h5_path), "sha256": sha256_file(h5_path), "frames": int(len(times)), "particles": int(len(handle["particle_id"])), "type_counts": {str(int(value)): int(np.sum(types == value)) for value in np.unique(types)}, "time_start_s": float(times[0]), "time_end_s": float(times[-1]), "checks": h5_checks, "missing": missing, "attrs": {str(key): str(value) for key, value in handle.attrs.items()}}
        floating_headers, floating_rows = _parse_csv(floating_path)
        force_headers, force_rows = _parse_csv(force_path)
        partvtk_headers, partvtk_rows = _parse_partvtk_csv(partvtk_path)
        partvtk_type_counts: dict[str, int] = {}
        partvtk_type_masses: dict[str, set[str]] = {}
        type_header = next((header for header in partvtk_headers if _normal_header(header) == "type"), None)
        mass_header = next((header for header in partvtk_headers if "mass" in _normal_header(header)), None)
        if type_header is not None:
            for row in partvtk_rows:
                key = str(row.get(type_header, "")).strip()
                partvtk_type_counts[key] = partvtk_type_counts.get(key, 0) + 1
                if mass_header is not None:
                    partvtk_type_masses.setdefault(key, set()).add(str(row.get(mass_header, "")).strip())
        partvtk_checks = {
            "rows_positive": len(partvtk_rows) > 0,
            "particle_type_column": _has_header_group(partvtk_headers, ("type",)),
            "mass_column": _has_header_group(partvtk_headers, ("mass",)),
            "mk_column": _has_header_group(partvtk_headers, ("mk",)),
            "floating_type2_present": partvtk_type_counts.get("2", 0) > 0,
        }
        floating_checks = {
            "rows_positive": len(floating_rows) > 1,
            "time_column": _has_header_group(floating_headers, ("time", "timestep")),
            "pose_center": _has_header_group(floating_headers, ("center", "pos", "com")),
            "orientation_euler": _has_header_group(floating_headers, ("roll", "pitch", "yaw")),
            "linear_velocity": _has_header_group(floating_headers, ("fvel", "vel", "velocity")),
            "angular_velocity": _has_header_group(floating_headers, ("fomega", "omega", "angular")),
            "fluid_force": _has_header_group(floating_headers, ("fluidforcelin", "forcefluid", "fluidforce")),
            "fluid_torque": _has_header_group(floating_headers, ("fluidforceang", "moment", "torque")),
        }
        force_checks = {
            "rows_positive": len(force_rows) > 1,
            "time_column": _has_header_group(force_headers, ("time", "timestep")),
            "force_fluid": _has_header_group(force_headers, ("forcefluid", "fluidforce")),
            "force_total": _has_header_group(force_headers, ("forcetotal", "totalforce")),
            "torque_or_moment": _has_header_group(force_headers, ("moment", "torque")),
        }
        generated_root = ET.parse(Path(generated_prefix).with_suffix(".xml")).getroot()
        generated_floating = generated_root.find("./execution/particles/floating")
        massbody_node = generated_floating.find("massbody") if generated_floating is not None else None
        masspart_node = generated_floating.find("masspart") if generated_floating is not None else None
        aggregate_mass = float(massbody_node.get("value")) if massbody_node is not None else None
        per_particle_mass = float(masspart_node.get("value")) if masspart_node is not None else None
        result.update({"hdf5": h5_summary, "partvtk_initial": {"path": str(partvtk_path), "sha256": sha256_file(partvtk_path), "headers": partvtk_headers, "rows": len(partvtk_rows), "checks": partvtk_checks, "type_counts": partvtk_type_counts, "type_particle_masses_kg": {key: sorted(values) for key, values in partvtk_type_masses.items()}}, "native_type_mass_ledger": {"type2_semantics": "PartVTK Type=2 floating particles; Mass is per-particle MassBound, not aggregate rigid-body mass", "type2_count": partvtk_type_counts.get("2", 0), "type2_mass_values_kg": sorted(partvtk_type_masses.get("2", set())), "generated_masspart_kg": per_particle_mass, "generated_massbody_kg": aggregate_mass, "aggregate_body_mass_is_distinct": True}, "floating_info": {"path": str(floating_path), "sha256": sha256_file(floating_path), "headers": floating_headers, "rows": len(floating_rows), "checks": floating_checks}, "compute_forces": {"path": str(force_path), "sha256": sha256_file(force_path), "headers": force_headers, "rows": len(force_rows), "checks": force_checks}})
        result["unsupported"].append("orientation_quaternion: FloatingInfo v5.4 native output provides roll/pitch/yaw; no quaternion field was claimed")
        result["status"] = "pass" if all(h5_checks.values()) and all(partvtk_checks.values()) and all(floating_checks.values()) and all(force_checks.values()) else "fail"
        result["errors"].extend([f"hdf5:{name}" for name, passed in h5_checks.items() if not passed])
        result["errors"].extend([f"partvtk_initial:{name}" for name, passed in partvtk_checks.items() if not passed])
        result["errors"].extend([f"floating_info:{name}" for name, passed in floating_checks.items() if not passed])
        result["errors"].extend([f"compute_forces:{name}" for name, passed in force_checks.items() if not passed])
        result["rigid_state_contract"] = {"pose": floating_checks["pose_center"], "orientation": floating_checks["orientation_euler"], "linear_velocity": floating_checks["linear_velocity"], "angular_velocity": floating_checks["angular_velocity"], "mass": "generated XML aggregate massbody plus PartVTK Type=2 per-particle masspart; HDF5 mass ledger keeps per-particle values", "inertia": "generated XML floating inertia; no frame-varying inertia claimed", "force": floating_checks["fluid_force"] and force_checks["force_fluid"], "torque": floating_checks["fluid_torque"] and force_checks["torque_or_moment"]}
        result["qualification_claim"] = "none; complete-window native evidence candidate only"
    except (OSError, ValueError, TypeError, ImportError) as exc:
        result.update(status="fail", errors=[f"postprocessor audit error: {type(exc).__name__}: {exc}"])
    return result


def _generated_groups(generated_xml: Path) -> dict[str, Any]:
    root = ET.parse(generated_xml).getroot()
    particles = root.find("./execution/particles")
    constants = root.find("./execution/constants")
    if particles is None or constants is None:
        raise ValueError("generated XML lacks particles/constants")
    groups: list[dict[str, Any]] = []
    role_to_type = {"fixed": 1, "moving": 4, "floating": 2, "fluid": 3}
    for node in particles:
        if node.tag not in role_to_type or node.get("begin") is None:
            continue
        groups.append({"role": node.tag, "type": role_to_type[node.tag], "begin": int(node.get("begin")), "count": int(node.get("count", "0")), "mk": int(node.get("mk", "0")), "mkbound": node.get("mkbound")})
    if not groups:
        raise ValueError("no particle groups")
    return {"groups": groups, "np": max(item["begin"] + item["count"] for item in groups), "dp": float(constants.find("dp").get("value")), "rhop0": float(constants.find("rhop0").get("value")), "gamma": float(constants.find("gamma").get("value")), "b": float(constants.find("b").get("value")), "massfluid": float(constants.find("massfluid").get("value")), "massbound": float(constants.find("massbound").get("value"))}


def _native_frame(frame: Path, temporary: Path, decoder: Path):
    if temporary.exists():
        shutil.rmtree(temporary)
    subprocess.run([str(decoder), str(frame), str(temporary)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    root = ET.parse(str(temporary) + ".xml").getroot()
    parent = root.find("item")
    if parent is None or parent.find("item") is None:
        raise ValueError(f"decoder metadata missing: {frame}")
    node = parent.find("item")
    metadata = {item.get("name"): item.get("v") for item in parent if item.tag != "item"}
    info = {item.get("name"): item.get("v") for item in node if item.tag != "item"}
    folder = temporary / node.get("name")
    import numpy as np  # type: ignore
    ids = np.fromfile(folder / "Idp.bin", np.uint32)
    position_file = folder / "Posd.bin" if (folder / "Posd.bin").is_file() else folder / "Pos.bin"
    position = np.fromfile(position_file, np.float64 if position_file.name == "Posd.bin" else np.float32).reshape(-1, 3)
    velocity = np.fromfile(folder / "Vel.bin", np.float32).reshape(-1, 3)
    density = np.fromfile(folder / "Rhop.bin", np.float32)
    order = np.argsort(ids)
    if len(set(int(value) for value in ids)) != len(ids):
        raise ValueError(f"duplicate native ids: {frame}")
    return ids[order], position[order], velocity[order], density[order], metadata, info


def convert_native_all_types(data_dir: Path, generated_xml: Path, output: Path, decoder: Path) -> dict[str, Any]:
    """Convert every saved native frame and every generated particle role to H5."""
    import h5py  # type: ignore
    import numpy as np  # type: ignore
    groups = _generated_groups(generated_xml)
    generated_root = ET.parse(generated_xml).getroot()
    generated_floating = generated_root.find("./execution/particles/floating")
    massbody_node = generated_floating.find("massbody") if generated_floating is not None else None
    masspart_node = generated_floating.find("masspart") if generated_floating is not None else None
    generated_inertia = _inertia_from_generated(generated_floating)
    frame_paths = sorted(Path(data_dir).glob("Part_[0-9][0-9][0-9][0-9].bi4"))
    if len(frame_paths) < 2:
        raise ValueError("fewer than two native frames")
    particle_ids = np.arange(groups["np"], dtype=np.uint32)
    particle_type = np.zeros(groups["np"], dtype=np.int8)
    mk = np.zeros(groups["np"], dtype=np.int16)
    for group in groups["groups"]:
        begin, end = group["begin"], group["begin"] + group["count"]
        particle_type[begin:end] = group["type"]
        mk[begin:end] = group["mk"]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    with tempfile.TemporaryDirectory(prefix="f6-bi4-h5-") as temp:
        with h5py.File(partial, "w") as h5:
            h5.attrs.update(schema=POSTPROCESS_SCHEMA, representation="native DualSPHysics BI4 frames", conversion_complete=False, orientation_semantics="FloatingInfo Euler roll/pitch/yaw; quaternion unsupported", generated_xml_sha256=sha256_file(generated_xml), generated_xml=str(generated_xml.resolve()), particle_identity="native Idp", qualification_claim="none", floating_massbody_kg=float(massbody_node.get("value")) if massbody_node is not None else float("nan"), floating_masspart_kg=float(masspart_node.get("value")) if masspart_node is not None else float("nan"), floating_inertia_kg_m2=json.dumps(generated_inertia, separators=(",", ":")), type2_mass_semantics="particle mass is MassPart/MassBound; aggregate rigid mass is floating massbody")
            h5.create_dataset("particle_id", data=particle_ids)
            h5.create_dataset("particle_type", data=particle_type)
            h5.create_dataset("mk", data=mk)
            nframes, nparticles = len(frame_paths), len(particle_ids)
            h5.create_dataset("time", shape=(nframes,), dtype="f8")
            chunk = min(nparticles, 32768)
            for name, dtype, fill in (("position", "f8", np.nan), ("velocity", "f4", np.nan), ("density", "f4", np.nan), ("mass", "f4", np.nan), ("pressure", "f4", np.nan), ("valid", "bool", False)):
                h5.create_dataset(name, shape=(nframes, nparticles, 3) if name in {"position", "velocity"} else (nframes, nparticles), dtype=dtype, chunks=(1, chunk, 3) if name in {"position", "velocity"} else (1, chunk), compression="lzf", fillvalue=fill)
            previous = -math.inf
            for index, frame in enumerate(frame_paths):
                ids, pos, vel, rho, metadata, info = _native_frame(frame, Path(temp) / f"frame-{index:04d}", decoder)
                if len(ids) != nparticles or not np.array_equal(ids, particle_ids):
                    raise ValueError(f"native identity set changed at {frame.name}")
                time_s = float(info.get("TimeStep", "nan"))
                if not math.isfinite(time_s) or time_s <= previous:
                    raise ValueError(f"non-increasing native time at {frame.name}")
                previous = time_s
                h5["time"][index] = time_s
                h5["position"][index] = pos
                h5["velocity"][index] = vel
                h5["density"][index] = rho
                h5["valid"][index] = True
                mass = np.full(nparticles, float(metadata.get("MassFluid", groups["massfluid"])), dtype=np.float32)
                for group in groups["groups"]:
                    begin, end = group["begin"], group["begin"] + group["count"]
                    if group["role"] == "floating":
                        mass[begin:end] = float(metadata.get("MassBound", groups["massbound"]))
                    elif group["role"] in {"fixed", "moving"}:
                        mass[begin:end] = float(metadata.get("MassBound", groups["massbound"]))
                h5["mass"][index] = mass
                gamma, rhop0, b = groups["gamma"], groups["rhop0"], groups["b"]
                h5["pressure"][index] = b * ((rho.astype(np.float64) / rhop0) ** gamma - 1.0)
                h5.attrs["conversion_complete_frames"] = index + 1
            h5.attrs["conversion_complete"] = True
    partial.replace(output)
    return {"path": str(output.resolve()), "sha256": sha256_file(output), "frames": len(frame_paths), "particles": int(len(particle_ids)), "type_counts": {str(int(value)): int(np.sum(particle_type == value)) for value in np.unique(particle_type)}}


def run_postprocessors(mechanism: str, data_dir: Path, generated_prefix: Path, output_dir: Path, decoder: Path, threads: int = 4) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    generated_xml = Path(generated_prefix).with_suffix(".xml")
    groups = _generated_groups(generated_xml)
    center = None
    floating_group = next((g for g in groups["groups"] if g["role"] == "floating"), None)
    if floating_group:
        generated = ET.parse(generated_xml).getroot()
        node = generated.find("./execution/particles/floating")
        cnode = node.find("center") if node is not None else None
        if cnode is not None:
            center = [float(cnode.get(axis)) for axis in "xyz"]
    floating_stem = output_dir / "FloatingMotion"
    force_stem = output_dir / "FloatingForce"
    partvtk_stem = output_dir / "PartVTK_0000"
    partvtk_data = output_dir / "partvtk_data"
    partvtk_data.mkdir(parents=True, exist_ok=True)
    # PartVTK v5.4 deliberately ignores -filexml and requires a sibling XML
    # named after the BI4 frame.  Keep this compatibility copy in the new
    # audit attempt; never add it to or mutate the solver's raw data folder.
    partvtk_frame = Path(data_dir) / "Part_0000.bi4"
    shutil.copyfile(partvtk_frame, partvtk_data / "Part_0000.bi4")
    shutil.copyfile(generated_xml, partvtk_data / "Part_0000.xml")
    floating_command = [str(FLOATING_INFO_BINARY.resolve()), "-dirdata", str(Path(data_dir).resolve()), "-onlymk:60", "-savedata", str(floating_stem), "-savemotion:1", "-csvsep:0"]
    force_command = [str(COMPUTE_FORCES_BINARY.resolve()), "-dirdata", str(Path(data_dir).resolve()), "-filexml", str(generated_xml.resolve()), "-onlymk:60", "-viscoauto", "-gravity:0:0:-9.81", "-momentin_xyz:" + ":".join(_fmt(value) for value in (center or [0.0, 0.0, 0.0])), "-momentex_xyz:" + ":".join(_fmt(value) for value in (center or [0.0, 0.0, 0.0])), "-savecsv", str(force_stem), "-threads:" + str(threads), "-csvsep:0"]
    partvtk_command = [str(PARTVTK_BINARY.resolve()), "-filedata", str((partvtk_data / "Part_0000.bi4").resolve()), "-savecsv", str(partvtk_stem), "-vars:+idp,+type,+mass,+mk", "-csvsep:0", "-threads:" + str(threads)]
    commands = []
    completed = subprocess.run(partvtk_command, cwd=output_dir, capture_output=True, text=True)
    (output_dir / "PartVTK.stdout.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    commands.append({"tool": "PartVTK", "command": partvtk_command, "returncode": completed.returncode, "log": str((output_dir / "PartVTK.stdout.log").resolve())})
    if completed.returncode != 0:
        raise RuntimeError(f"PartVTK failed with code {completed.returncode}")
    for label, command in (("FloatingInfo", floating_command), ("ComputeForces", force_command)):
        completed = subprocess.run(command, cwd=output_dir, capture_output=True, text=True)
        (output_dir / f"{label}.stdout.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        commands.append({"tool": label, "command": command, "returncode": completed.returncode, "log": str((output_dir / f"{label}.stdout.log").resolve())})
        if completed.returncode != 0:
            raise RuntimeError(f"{label} failed with code {completed.returncode}")
    h5 = convert_native_all_types(data_dir, generated_xml, output_dir / "native_all_types.h5", decoder)
    result = audit_postprocessors(output_dir, generated_prefix, mechanism)
    result["commands"] = commands
    result["native_h5"] = h5
    write_json(output_dir / "native_rigid_state_audit.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--output-root", type=Path, default=RESOLUTION_ROOT)
    post = sub.add_parser("prepare-postprocessors")
    post.add_argument("--output-root", type=Path, default=RESOLUTION_ROOT)
    refresh = sub.add_parser("refresh-evidence")
    refresh.add_argument("--output-root", type=Path, default=RESOLUTION_ROOT)
    audit = sub.add_parser("audit-gencase")
    audit.add_argument("--case", type=Path, required=True)
    audit.add_argument("--receipt", type=Path)
    run = sub.add_parser("run-postprocessors")
    run.add_argument("--mechanism", choices=MECHANISMS, required=True)
    run.add_argument("--data-dir", type=Path, required=True)
    run.add_argument("--generated-prefix", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--decoder", type=Path, default=BI4_DECODER)
    run.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare_resolution_study(args.output_root)
    elif args.command == "prepare-postprocessors":
        result = prepare_postprocess_requests(args.output_root)
    elif args.command == "refresh-evidence":
        result = refresh_evidence(args.output_root)
    elif args.command == "audit-gencase":
        result = audit_gencase(args.case, args.receipt)
    else:
        result = run_postprocessors(args.mechanism, args.data_dir, args.generated_prefix, args.output_dir, args.decoder, args.threads)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"registered_gencase_pending", "ready_for_shared_cpu_postprocessing", "pass", "pending"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
