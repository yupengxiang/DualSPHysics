#!/usr/bin/env python3
"""Prepare an independent H2 mDBC static range matrix on CPU.

The H2 v2 canary is the immutable anchor for this candidate.  This module
materializes only Definition files, zero-angle motion files, CPU GenCase
outputs and native decoded initial states.  It never invokes DualSPHysics,
CUDA, the queue, the ledger or the registry.  The 15 registered rows remain
the denominator when a CPU preparation row fails or is not attempted.

The fluid source keeps the canary's three numerical fluid partitions.  q is a
normalized initial liquid volume, with q=.5 equal to the positive H2 canary
volume.  The three resolution rows use dp=.010, .0075 and .005 m; q=.25 and
q=.75 are held out at the two finer resolutions.  Rows 13 and 14 are the
registered internal-time/native-output comparison at q=.5, dp=.0075.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any, Callable

import numpy as np
from scipy.spatial import cKDTree

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd


SCHEMA = "core.f2.h2_mdbc.static_range_preparation.v1"
CANDIDATE_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v2.json"
)
GENCASE_RELATIVE = Path("vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
DEFAULT_DECODER_RELATIVE = Path("campaigns/l1-resume/artifacts/bi4_dump")
TIME_MAX_S = 0.60
REGISTERED_OUTPUT_INTERVAL_S = 0.02
DEFAULT_NATIVE_OUTPUT_INTERVAL_S = 0.01
EXPECTED_CELL_COUNT = 15
MASS_DENSITY_KG_M3 = 1000.0


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _resolve(lab: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = lab / path
    return path.resolve()


def _relative(path: Path, lab: Path) -> str | None:
    try:
        return str(Path(path).resolve().relative_to(Path(lab).resolve()))
    except ValueError:
        return None


def _ref(path: Path, lab: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "relative_to_lab": _relative(path, lab),
        "sha256": _digest(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _q_text(value: float) -> str:
    return f"{float(value):.8f}".replace(".", "p")


def _dp_text(value: float) -> str:
    return f"{float(value):.12f}".replace(".", "p")


def _half_up(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def _validate_candidate(card: dict[str, Any]) -> list[dict[str, Any]]:
    if card.get("schema") != "core.f2.h2_mdbc.static_range_candidate.v1":
        raise ValueError("unexpected H2 mDBC static-range candidate schema")
    if card.get("qualification_only") is not True or card.get("qualified") is not False:
        raise ValueError("candidate must remain qualification-only and unqualified")
    policy = card.get("launch_policy", {})
    if any(policy.get(key) is not False for key in ("solver_submit", "gpu_submit", "queue_submit", "ledger_submit", "registry_mutation")):
        raise ValueError("candidate launch policy is open")
    if card.get("physical_contract", {}).get("boundary_method") != 2:
        raise ValueError("candidate is not bound to mDBC Boundary=2")
    normal = card.get("physical_contract", {}).get("mdbc_normals", {})
    if normal.get("normal_construction_layers_vdp") != -0.5:
        raise ValueError("candidate does not bind vdp=-0.5 normal construction")
    if float(normal.get("normal_search_distance_h", 0.0)) != 3.0 or normal.get("svshapes") is not True:
        raise ValueError("candidate does not bind the H2 normal support repair")
    if card.get("input_closure", {}).get("matrix_jobs_materialized") is not False:
        raise ValueError("candidate already claims matrix jobs")
    design = card.get("qualification_design", {})
    cells = list(design.get("cells", []))
    if design.get("cell_count") != EXPECTED_CELL_COUNT or len(cells) != EXPECTED_CELL_COUNT:
        raise ValueError("candidate does not contain the fixed 15-cell design")
    if design.get("matrix_inputs_materialized") is not False or design.get("matrix_jobs_materialized") is not False:
        raise ValueError("candidate already claims materialized matrix state")
    if float(design.get("registered_window_s", -1.0)) != TIME_MAX_S:
        raise ValueError("registered static window must be 0.60 s")
    if float(design.get("output_interval_s", -1.0)) != REGISTERED_OUTPUT_INTERVAL_S:
        raise ValueError("registered output interval must be 0.02 s")
    seen: set[int] = set()
    for expected_index, cell in enumerate(cells):
        if int(cell.get("index", -1)) != expected_index or expected_index in seen:
            raise ValueError(f"candidate cell index is not the fixed row {expected_index}")
        seen.add(expected_index)
        if cell.get("status") != "design_only_unprepared":
            raise ValueError(f"candidate cell {expected_index} is not design-only")
        if cell.get("prepared") is not None or cell.get("job") is not None:
            raise ValueError(f"candidate cell {expected_index} already has prepared/job state")
        if cell.get("design_cell") not in {"spatial", "spatial_held_out", "internal_time", "native_output"}:
            raise ValueError(f"candidate cell {expected_index} has an unknown design cell")
        if float(cell.get("q", -1.0)) < 0.0 or float(cell.get("q", -1.0)) > 1.0:
            raise ValueError(f"candidate cell {expected_index} has q outside [0,1]")
        if float(cell.get("dp_m", 0.0)) not in {0.01, 0.0075, 0.005}:
            raise ValueError(f"candidate cell {expected_index} has an unregistered dp")
    if card.get("failure_denominator", {}).get("fixed_registered_cell_denominator") != EXPECTED_CELL_COUNT:
        raise ValueError("candidate failure denominator is not fixed at 15")
    return cells


def _load_inputs(lab: Path, candidate_path: Path, card: dict[str, Any],
                 gencase_path: Path | None, decoder_path: Path | None) -> dict[str, Any]:
    evidence = card.get("anchor_evidence", {})
    frozen = []
    for key in ("canary_evidence", "root_review", "prepared", "definition"):
        item = evidence.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"anchor evidence is missing {key}")
        path = _resolve(lab, item.get("path", ""))
        actual = _ref(path, lab, item.get("role", f"H2 anchor {key}"))
        if actual["sha256"] != item.get("sha256") or actual["bytes"] != int(item.get("bytes", -1)):
            raise ValueError(f"H2 anchor {key} hash or byte count differs")
        frozen.append(actual)

    prepared_path = _resolve(lab, evidence["prepared"]["path"])
    prepared = json.loads(prepared_path.read_text())
    prepared_scope_id = prepared.get("scope_id") or prepared.get("config", {}).get("scope_id")
    if prepared_scope_id != "F2_H2_mdbc_boundary_repair_canary_v1":
        raise ValueError("anchor prepared scope is not the H2 mDBC canary scope")
    if prepared.get("config", {}).get("boundary_method") != 2 or prepared.get("preflight_pass") is not True:
        raise ValueError("anchor prepared input is not a passed mDBC preflight")
    if prepared.get("native_initial", {}).get("zero_boundary_normals") != 0:
        raise ValueError("anchor prepared input has zero boundary normals")
    if prepared.get("static_diagnostic_preflight", {}).get("mdbc_normals_complete_nonzero") is not True:
        raise ValueError("anchor prepared input lacks complete mDBC normals")

    definition = _resolve(lab, evidence["definition"]["path"])
    anchored_definition = _resolve(lab, prepared.get("definition_audit", {}).get("definition", ""))
    if anchored_definition != definition or _digest(anchored_definition) != evidence["definition"]["sha256"]:
        raise ValueError("candidate definition reference does not bind the H2 prepared definition")

    source = _resolve(lab, card.get("source_template", ""))
    if source != definition:
        raise ValueError("H2 candidate source template must be the frozen v2 definition")
    gencase = _resolve(lab, gencase_path or GENCASE_RELATIVE)
    decoder = _resolve(lab, decoder_path or DEFAULT_DECODER_RELATIVE)
    if not gencase.is_file() or not decoder.is_file():
        raise FileNotFoundError("CPU GenCase or native decoder is missing")

    tool_closure = [
        _ref(candidate_path, lab, "15-cell H2 mDBC candidate card"),
        _ref(prepared_path, lab, "H2 v2 anchor prepared manifest"),
        _ref(definition, lab, "H2 v2 anchor mDBC Definition"),
        _ref(gencase, lab, "CPU GenCase executable"),
        _ref(decoder, lab, "CPU native decoder"),
        _ref(Path(__file__), lab, "H2 static-range CPU preparer code"),
    ]
    return {
        "candidate_path": candidate_path,
        "candidate_ref": _ref(candidate_path, lab, "15-cell H2 mDBC candidate card"),
        "anchor_prepared_path": prepared_path,
        "anchor_prepared": prepared,
        "source": source,
        "definition": definition,
        "gencase": gencase,
        "decoder": decoder,
        "frozen_anchor_inputs": frozen,
        "tool_closure": tool_closure,
        "solver_reference_skipped": {
            "verified": False,
            "reason": "solver binary is outside CPU materialization and was neither read nor hashed",
        },
    }


def _set_parameter(root: ET.Element, key: str, value: str | int | float) -> None:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None:
        raise ValueError(f"missing execution parameter {key}")
    node.set("value", str(value))


def _set_motion(root: ET.Element, motion_name: str) -> None:
    motion = root.find(".//mvrotfile")
    if motion is None:
        raise ValueError("anchor Definition has no mvrotfile")
    motion.set("duration", f"{TIME_MAX_S:.17g}")
    file_node = motion.find("file")
    if file_node is None:
        raise ValueError("anchor mvrotfile has no file")
    file_node.set("name", motion_name)
    for begin in root.findall(".//begin"):
        begin.set("finish", f"{TIME_MAX_S:.17g}")


def _fluid_node(mkfluid: int, first: list[float], draw_size: list[float]) -> tuple[ET.Element, ET.Element]:
    state = ET.Element("setmkfluid", {"mk": str(mkfluid)})
    draw = ET.Element("drawbox")
    ET.SubElement(draw, "boxfill").text = "solid"
    ET.SubElement(draw, "point", {axis: f"{float(value):.17g}" for axis, value in zip("xyz", first)})
    ET.SubElement(draw, "size", {axis: f"{float(value):.17g}" for axis, value in zip("xyz", draw_size)})
    return state, draw


def _rewrite_definition(source: Path, target: Path, cell: dict[str, Any],
                        sampling: dict[str, Any], motion_name: str,
                        output_interval_s: float, card: dict[str, Any]) -> dict[str, Any]:
    tree = ET.parse(source)
    root = tree.getroot()
    for key, value in {
        "SavePosDouble": 2,
        "Boundary": 2,
        "SlipMode": 1,
        "TimeMax": TIME_MAX_S,
        "TimeOut": output_interval_s,
        "PartsOutMax": 1,
    }.items():
        _set_parameter(root, key, value)
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("anchor Definition has no geometry definition")
    definition.set("dp", f"{float(cell['dp_m']):.17g}")
    commands = root.find(".//geometry/commands/mainlist")
    if commands is None:
        raise ValueError("anchor Definition has no geometry mainlist")
    nodes = list(commands)
    kept: list[ET.Element] = []
    removed = 0
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if node.tag == "setmkfluid":
            if index + 1 >= len(nodes) or nodes[index + 1].tag != "drawbox":
                raise ValueError("fluid source command is not setmkfluid followed by drawbox")
            removed += 1
            index += 2
            continue
        kept.append(node)
        index += 1
    if removed != 3:
        raise ValueError(f"H2 anchor must have exactly three fluid source boxes, found {removed}")
    commands[:] = kept
    for box in sampling["fluid_boxes"]:
        state, draw = _fluid_node(int(box["mkfluid"]), box["first_center_m"], box["draw_size_m"])
        commands.append(state)
        commands.append(draw)

    if root.find(".//execution/parameters/parameter[@key='Boundary']").get("value") != "2":
        raise ValueError("rewritten Definition lost mDBC Boundary=2")
    normals = root.find(".//casedef/normals")
    if normals is None or normals.get("active") != "true":
        raise ValueError("rewritten Definition lost active mDBC normals")
    norgeometry = normals.find("norgeometry")
    if norgeometry is None:
        raise ValueError("rewritten Definition lost normal geometry")
    if norgeometry.find("distanceh").get("v") != "3.0" or norgeometry.find("svshapes").get("v") != "true":
        raise ValueError("rewritten Definition lost H2 normal support settings")
    if not root.findall(".//geometry/commands/list[@name='GeometryForNormals']//*[@vdp='-0.5']"):
        raise ValueError("rewritten Definition lost vdp=-0.5 normal layers")
    _set_motion(root, motion_name)
    ET.indent(tree, space="    ")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "source_definition": str(source.resolve()),
        "source_definition_sha256": _digest(source),
        "definition": str(target.resolve()),
        "definition_sha256": _digest(target),
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "removed_anchor_fluid_box_count": removed,
        "boundary_method": "mDBC Boundary=2",
        "normal_construction_layers_vdp": -0.5,
        "normal_search_distance_h": 3.0,
        "svshapes": True,
        "time_max_s": TIME_MAX_S,
        "output_interval_s": output_interval_s,
        "motion_file_name": motion_name,
        "motion_angle_degrees": 0.0,
        "mass_rescaling": False,
        "physical_geometry_changed": False,
        "qualification_claim": "none; CPU Definition materialization only",
        "anchor_scope_id": card["anchor_evidence"]["prepared"]["scope_id"],
    }


def _write_zero_motion(path: Path, interval_s: float) -> None:
    values = []
    time_s = 0.0
    while time_s <= TIME_MAX_S + interval_s * 0.25:
        values.append(f"{time_s:.6f};0.000000000")
        time_s += interval_s
    path.write_text("#Time;Degrees\n" + "\n".join(values) + "\n")


def _lattice_count(size: float, dp: float, *, z_layer: bool = False) -> int:
    ratio = float(size) / float(dp)
    # The H2 source's x/y footprint uses the largest complete in-box lattice;
    # its .11 m source layers use the nearest native layer count, reproducing
    # 15 layers at the anchor dp=.0075.
    return max(1, _half_up(ratio) if z_layer else int(math.floor(ratio + 1e-9)))


def _first_center(low: float, dp: float) -> float:
    index = int(math.ceil(float(low) / float(dp) - 0.5 - 1e-10))
    return (index + 0.5) * float(dp)


def _draw_extent(axis: str, count: int, dp: float) -> tuple[float, float]:
    """Return a GenCase-safe extent and the applied endpoint guard.

    GenCase includes drawbox endpoints using floating-point comparisons.  Two
    exact decimal ratios in this matrix sit on opposite sides of that
    comparison: the 0.01 m, 11-layer source box loses one layer, while the
    0.005 m, 44-point transverse box gains one.  Move only the serialized
    endpoint by 1e-12 m; particle centres and the continuous geometry
    contract remain unchanged.
    """
    target = (int(count) - 1) * float(dp)
    guarded = target
    if axis == "z" and math.isclose(float(dp), 0.01, rel_tol=0.0, abs_tol=1e-15) and int(count) == 11:
        guarded = target + 1e-12
    elif axis == "y" and math.isclose(float(dp), 0.005, rel_tol=0.0, abs_tol=1e-15) and int(count) == 44:
        guarded = target - 1e-12
    return float(guarded), float(guarded - target)


def _select_third_layer_count(nx: int, ny: int, dp: float,
                              footprint_area: float, top_height: float,
                              total_volume: float,
                              base_count: int) -> tuple[int, float]:
    """Choose the third source layer count before any solver result exists."""
    cell_volume = float(nx * ny) * float(dp) ** 3
    top_volume = float(footprint_area) * float(top_height)
    target = top_volume / cell_volume
    lower = max(1, int(math.floor(target)))
    upper = max(lower, int(math.ceil(target)))
    candidates = sorted({max(1, value) for value in (lower - 1, lower, upper, upper + 1)})

    def score(count: int) -> tuple[float, float, int]:
        source_error = abs((float(count) * cell_volume) / top_volume - 1.0)
        total_error = abs((float(2 * base_count + count) * cell_volume) / float(total_volume) - 1.0)
        return source_error, total_error, int(count)

    selected = min(candidates, key=score)
    return int(selected), float(target)


def _sampling_for_cell(cell: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    contract = card["physical_contract"]
    footprint = contract["fluid_initial_condition"]["footprint"]
    axis = card["parameter_axis"]
    q = float(cell["q"])
    volume = float(axis["volume_at_q_m3"][str(q)])
    footprint_area = float(footprint["size_m"][0]) * float(footprint["size_m"][1])
    height = volume / footprint_area
    base_height = float(footprint["base_layer_height_m"])
    top_height = height - 2.0 * base_height
    if top_height <= 0.0:
        raise ValueError(f"q={q} has no positive third-layer height")
    dp = float(cell["dp_m"])
    low = [float(value) for value in footprint["low_m"]]
    x_size = float(footprint["size_m"][0])
    y_size = float(footprint["size_m"][1])
    nx = _lattice_count(x_size, dp)
    ny = _lattice_count(y_size, dp)
    source_layers = [base_height, base_height, top_height]
    base_counts = _lattice_count(base_height, dp, z_layer=True)
    top_count, target_top_count = _select_third_layer_count(
        nx, ny, dp, footprint_area, top_height, volume, base_counts
    )
    if top_count <= 0:
        raise ValueError(f"q={q}, dp={dp} produces an invalid third-layer count")
    counts_z = [base_counts, base_counts, top_count]
    boxes = []
    for mkfluid, (z_low, z_size, nz) in enumerate(zip(
            [low[2], low[2] + base_height, low[2] + 2.0 * base_height],
            source_layers,
            counts_z)):
        first = [_first_center(low[0], dp), _first_center(low[1], dp), _first_center(z_low, dp)]
        draw_size = []
        endpoint_guards = []
        for axis, count in zip("xyz", (nx, ny, nz)):
            extent, guard = _draw_extent(axis, count, dp)
            draw_size.append(extent)
            endpoint_guards.append(guard)
        box_volume = x_size * y_size * float(z_size)
        boxes.append({
            "continuous_low_m": [low[0], low[1], float(z_low)],
            "continuous_size_m": [x_size, y_size, float(z_size)],
            "first_center_m": [float(value) for value in first],
            "draw_size_m": [float(value) for value in draw_size],
            "drawbox_endpoint_guard_m": [float(value) for value in endpoint_guards],
            "counts": [int(nx), int(ny), int(nz)],
            "particle_count": int(nx * ny * nz),
            "continuous_volume_m3": float(box_volume),
            "continuous_mass_kg": float(box_volume * MASS_DENSITY_KG_M3),
            "discrete_mass_kg": float(nx * ny * nz * dp ** 3 * MASS_DENSITY_KG_M3),
            "mkfluid": int(mkfluid),
            "native_cell_centre_sampling": True,
            "mass_policy": "native rho*dp^3; no mass rescaling",
        })
    expected_particles = int(sum(item["particle_count"] for item in boxes))
    discrete_mass = float(expected_particles * dp ** 3 * MASS_DENSITY_KG_M3)
    return {
        "fluid_boxes": boxes,
        "expected_fluid_particles": expected_particles,
        "continuous_low_m": [low[0], low[1], low[2]],
        "continuous_size_m": [x_size, y_size, height],
        "continuous_volume_m3": volume,
        "continuous_mass_kg": float(volume * MASS_DENSITY_KG_M3),
        "sampled_mass_kg": discrete_mass,
        "counts": [int(nx), int(ny), int(sum(counts_z))],
        "z_layer_counts": [int(value) for value in counts_z],
        "target_total_native_layers": int(2 * base_counts + top_count),
        "target_third_layer_count": float(target_top_count),
        "selected_third_layer_count": int(top_count),
        "layer_count_selection": "minimum absolute third-source-layer discrete mass error; total-mass error and lower-count tie-breaks",
        "source_relative_errors": [float(item["discrete_mass_kg"] / item["continuous_mass_kg"] - 1.0)
                                   for item in boxes],
        "discrete_to_continuum_mass_error": float(discrete_mass / (volume * MASS_DENSITY_KG_M3) - 1.0),
        "mass_policy": "native rho*dp^3; no mass rescaling",
    }


def _groups(generated_xml: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = ET.parse(generated_xml).getroot()
    fixed: list[dict[str, Any]] = []
    fluid: list[dict[str, Any]] = []
    for node in root.findall(".//particles/*"):
        if node.tag not in {"fixed", "moving", "fluid"}:
            continue
        item: dict[str, Any] = {"kind": node.tag}
        for key, value in node.attrib.items():
            if key in {"begin", "count", "mk", "mkbound", "mkfluid"}:
                try:
                    item[key] = int(value)
                except (TypeError, ValueError):
                    item[key] = value
            else:
                item[key] = value
        (fluid if node.tag == "fluid" else fixed).append(item)
    return fixed, fluid


def _runtime_domain(generated_xml: Path) -> dict[str, list[float]]:
    root = ET.parse(generated_xml).getroot()
    domain = root.find(".//simulationdomain")
    if domain is None:
        raise ValueError("generated Definition has no simulationdomain")
    result: dict[str, list[float]] = {}
    for tag in ("posmin", "posmax"):
        node = domain.find(tag)
        if node is None:
            raise ValueError(f"generated Definition has no simulationdomain/{tag}")
        result[tag] = [float(node.get(axis)) for axis in "xyz"]
    return result


def _select_ids(ids: np.ndarray, group: dict[str, Any]) -> np.ndarray:
    begin = int(group["begin"])
    count = int(group["count"])
    return (ids >= begin) & (ids < begin + count)


def _decode_native(bi4: Path, decode_dir: Path, decoder: Path) -> tuple:
    decode_dir.mkdir(parents=True, exist_ok=True)
    return core_cfd.native_frame(bi4, decode_dir / "native", decoder)


def _preflight(generated_xml: Path, bi4: Path, decode_dir: Path, decoder: Path,
               sampling: dict[str, Any], cell: dict[str, Any], card: dict[str, Any],
               decode_fn: Callable[..., tuple] = _decode_native) -> dict[str, Any]:
    fixed, fluid = _groups(generated_xml)
    expected_counts = [int(item["particle_count"]) for item in sampling["fluid_boxes"]]
    generated_counts = [int(item.get("count", -1)) for item in fluid]
    generated_mks = [int(item.get("mkfluid", -1)) for item in fluid]
    generated_pass = (
        len(fluid) == 3
        and generated_counts == expected_counts
        and generated_mks == [0, 1, 2]
    )
    if not generated_pass:
        raise ValueError(f"GenCase fluid groups differ from H2 source sampling: {generated_counts}, {generated_mks}")
    ids, positions, velocities, density, metadata, _info, arrays = decode_fn(bi4, decode_dir, decoder)
    ids = np.asarray(ids)
    positions = np.asarray(positions)
    velocities = np.asarray(velocities)
    density = np.asarray(density)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("native decoder returned malformed positions")
    fluid_masks = [_select_ids(ids, item) for item in fluid]
    fluid_mask = np.logical_or.reduce(fluid_masks)
    boundary_mask = np.zeros(len(ids), dtype=bool)
    for group in fixed:
        boundary_mask |= _select_ids(ids, group)
    cup_groups = [item for item in fixed if int(item.get("mkbound", -1)) == 0]
    if not fluid_mask.any() or not boundary_mask.any() or not cup_groups:
        raise ValueError("decoded native frame has no fluid, boundary or cup particles")
    fluid_positions = positions[fluid_mask]
    cup_positions = positions[np.logical_or.reduce([_select_ids(ids, item) for item in cup_groups])]
    domain = _runtime_domain(generated_xml)
    physical = card["physical_contract"]
    cup = physical["cup"]
    cup_low = np.asarray(cup["low_m"], dtype=float)
    cup_high = cup_low + np.asarray(cup["size_m"], dtype=float)
    domain_low = np.asarray(domain["posmin"], dtype=float)
    domain_high = np.asarray(domain["posmax"], dtype=float)
    metadata_fluid = int(round(float(metadata["CaseNfluid"])))
    native_dp = float(metadata["Dp"])
    native_mass = float(metadata["MassFluid"]) * int(fluid_positions.shape[0])
    distances = cKDTree(cup_positions).query(fluid_positions, k=1)[0]
    finite = bool(np.isfinite(ids).all() and np.isfinite(positions).all()
                  and np.isfinite(velocities).all() and np.isfinite(density).all())
    speed = np.linalg.norm(velocities[fluid_mask], axis=1)
    tol = 1e-10
    inside_cup = np.all((fluid_positions >= cup_low - tol) & (fluid_positions <= cup_high + tol), axis=1)
    inside_domain = np.all((fluid_positions >= domain_low - tol) & (fluid_positions <= domain_high + tol), axis=1)
    normal_path = Path(arrays) / "BoundNor.bin"
    if normal_path.is_file():
        normal_values = np.fromfile(normal_path, dtype=np.float32)
        normal_values = normal_values.reshape((-1, 3)) if len(normal_values) % 3 == 0 else np.empty((0, 3))
    else:
        normal_values = np.empty((0, 3), dtype=np.float32)
    boundary_count = int(boundary_mask.sum())
    zero_normals = int(np.sum(np.linalg.norm(normal_values, axis=1) <= 1e-10)) if len(normal_values) else None
    expected_mass = float(sampling["continuous_mass_kg"])
    mass_error = float(native_mass / expected_mass - 1.0)
    per_group_native_counts = [int(mask.sum()) for mask in fluid_masks]
    checks = {
        "generated_fluid_groups_match_sampling": bool(generated_pass),
        "native_fluid_group_counts_match_sampling": per_group_native_counts == expected_counts,
        "native_fluid_count_matches_sampling": bool(metadata_fluid == sampling["expected_fluid_particles"] == int(fluid_positions.shape[0])),
        "native_fluid_ids_unique": bool(len(np.unique(ids)) == len(ids)),
        "native_arrays_finite": finite,
        "native_initial_zero_velocity": bool(np.max(np.abs(speed), initial=0.0) <= 1e-12),
        "fluid_inside_physical_cup": bool(inside_cup.all()),
        "fluid_inside_runtime_domain": bool(inside_domain.all()),
        "positive_distance_to_mkbound0_cup_particles": bool(np.min(distances, initial=np.inf) > 0.0),
        "native_dp_matches_cell": bool(math.isclose(native_dp, float(cell["dp_m"]), rel_tol=0.0, abs_tol=1e-12)),
        "source_initial_mass_gate": bool(max(abs(value) for value in sampling["source_relative_errors"]) <= float(card["gates"]["source_initial_mass_relative_error_max"])),
        "decoded_native_mass_gate": bool(abs(mass_error) <= float(card["gates"]["total_discrete_to_continuum_mass_error_max"])),
        "mdbc_normals_present": bool(normal_path.is_file()),
        "mdbc_normal_count_matches_boundary": bool(len(normal_values) == boundary_count),
        "mdbc_normals_finite": bool(len(normal_values) == boundary_count and np.isfinite(normal_values).all()),
        "mdbc_zero_boundary_normals_gate": bool(len(normal_values) == boundary_count and zero_normals == 0),
    }
    return {
        "schema": "core.f2.h2_mdbc.static_range.cell_preflight.v1",
        "case_id": cell["case_id"],
        "index": int(cell["index"]),
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "qualification_claim": "none; CPU GenCase/native decode preflight only",
        "generated_definition": str(generated_xml.resolve()),
        "generated_definition_sha256": _digest(generated_xml),
        "native_bi4": str(bi4.resolve()),
        "native_bi4_sha256": _digest(bi4),
        "decoder": str(decoder.resolve()),
        "decoder_sha256": _digest(decoder),
        "decoded_directory": str(Path(arrays).resolve()),
        "native_identity": {
            "total_particles": int(len(ids)),
            "boundary_particles": boundary_count,
            "fluid_particles": int(fluid_positions.shape[0]),
            "fluid_group_counts": per_group_native_counts,
            "metadata_case_nfluid": metadata_fluid,
            "native_dp_m": native_dp,
            "native_mass_kg": native_mass,
            "metadata": {str(key): str(value) for key, value in metadata.items()},
        },
        "mdbc_normal_gate": {
            "normal_file": str(normal_path.resolve()),
            "normal_count": int(len(normal_values)),
            "boundary_count": boundary_count,
            "zero_boundary_normals": zero_normals,
            "normal_construction_layers_vdp": -0.5,
            "normal_search_distance_h": 3.0,
            "svshapes": True,
        },
        "mass_gate": {
            "continuous_mass_kg": expected_mass,
            "native_mass_kg": native_mass,
            "mass_error_relative": mass_error,
            "source_relative_errors": list(sampling["source_relative_errors"]),
            "source_initial_mass_relative_error_max": float(card["gates"]["source_initial_mass_relative_error_max"]),
            "total_discrete_to_continuum_mass_error_max": float(card["gates"]["total_discrete_to_continuum_mass_error_max"]),
            "mass_rescaling": False,
        },
        "geometry_gate": {
            "runtime_domain": domain,
            "fluid_position_bounds_m": {
                "low": [float(value) for value in fluid_positions.min(axis=0)],
                "high": [float(value) for value in fluid_positions.max(axis=0)],
            },
            "minimum_cup_particle_distance_m": float(np.min(distances)),
            "geometry_tolerance_m": tol,
        },
        "generated_particle_groups": {"fixed": fixed, "fluid": fluid},
        "checks": checks,
        "preflight_pass": bool(all(checks.values())),
        "mass_rescaling": False,
        "trajectory_or_solver_checked": False,
    }


def _environment(lab: Path) -> dict[str, str]:
    env = os.environ.copy()
    binary_dir = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    env["LD_LIBRARY_PATH"] = str(binary_dir) + ":" + env.get("LD_LIBRARY_PATH", "")
    env.setdefault("OMP_NUM_THREADS", "2")
    return env


def _run_gencase(gencase: Path, definition: Path, prefix: Path, log_path: Path,
                 cwd: Path, lab: Path) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        process = subprocess.run(
            [str(gencase), str(definition.with_suffix("")), str(prefix), "-save:all"],
            cwd=cwd,
            env=_environment(lab),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    if process.returncode:
        raise RuntimeError(f"CPU GenCase failed with return code {process.returncode}")
    if not prefix.with_suffix(".xml").is_file() or not prefix.with_suffix(".bi4").is_file():
        raise RuntimeError("CPU GenCase did not produce generated XML and native BI4")


def _output_interval(cell: dict[str, Any], native_override: float | None) -> float:
    if cell["design_cell"] != "native_output":
        return REGISTERED_OUTPUT_INTERVAL_S
    interval = native_override if native_override is not None else DEFAULT_NATIVE_OUTPUT_INTERVAL_S
    if interval <= 0.0 or interval >= REGISTERED_OUTPUT_INTERVAL_S:
        raise ValueError("native-output interval must be positive and finer than 0.02 s")
    return float(interval)


def _cell_dir_name(cell: dict[str, Any]) -> str:
    return f"{int(cell['index']):02d}-{cell['case_id']}"


def _closure_files(cell_dir: Path, excluded: set[Path] | None = None) -> list[Path]:
    excluded = {Path(path).resolve() for path in (excluded or set())}
    return sorted(path for path in cell_dir.rglob("*")
                  if path.is_file() and path.resolve() not in excluded and not path.name.endswith(".partial"))


def _prepare_cell(lab: Path, output: Path, cell: dict[str, Any], card: dict[str, Any],
                  inputs: dict[str, Any], native_output_interval_s: float | None = None,
                  run_gencase_fn: Callable[..., None] = _run_gencase,
                  decode_fn: Callable[..., tuple] = _decode_native) -> dict[str, Any]:
    cell_dir = output / "cells" / _cell_dir_name(cell)
    cell_dir.mkdir(parents=True, exist_ok=False)
    sampling = _sampling_for_cell(cell, card)
    interval = _output_interval(cell, native_output_interval_s)
    definition = cell_dir / f"{cell['case_id']}_Def.xml"
    motion = cell_dir / f"{cell['case_id']}_motion.dat"
    audit = _rewrite_definition(inputs["source"], definition, cell, sampling, motion.name, interval, card)
    _write_zero_motion(motion, interval)
    prefix = cell_dir / "generated" / cell["case_id"]
    log_path = cell_dir / "gencase.log"
    run_gencase_fn(inputs["gencase"], definition, prefix, log_path, cell_dir, lab)
    generated_xml = prefix.with_suffix(".xml")
    bi4 = prefix.with_suffix(".bi4")
    decode_dir = cell_dir / "decoded"
    preflight = _preflight(generated_xml, bi4, decode_dir, inputs["decoder"], sampling, cell, card, decode_fn)
    _write_json(cell_dir / "preflight.json", preflight)
    closure = [_ref(path, lab, f"cell artifact: {path.relative_to(cell_dir)}")
               for path in _closure_files(cell_dir, {cell_dir / "prepared.json"})]
    closure.extend(inputs["tool_closure"])
    prepared = {
        "schema": "core.f2.h2_mdbc.static_range.cell_prepared.v1",
        "created_at": _stamp(),
        "candidate_id": card["candidate_id"],
        "scope_id": card["scope_id"],
        "anchor_scope_id": card["anchor_evidence"]["prepared"]["scope_id"],
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "held_out": bool(cell.get("held_out", False)),
        "temporal_variant": cell.get("temporal_variant"),
        "time_max_s": TIME_MAX_S,
        "output_interval_s": interval,
        "registered_output_interval_s": REGISTERED_OUTPUT_INTERVAL_S,
        "temporal_materialization": {
            "variant": cell.get("temporal_variant"),
            "native_output_interval_derived": cell["design_cell"] == "native_output",
            "solver_actual_step_unrun": True,
            "rule": "internal_time keeps registered output .02 s; native_output uses .01 s native output cadence",
        },
        "sampling": sampling,
        "definition_audit": audit,
        "generated_prefix": str(prefix.resolve()),
        "preflight": str((cell_dir / "preflight.json").resolve()),
        "preflight_pass": bool(preflight["preflight_pass"]),
        "mdbc_normal_gate": preflight["mdbc_normal_gate"],
        "mass_gate": preflight["mass_gate"],
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutated": False,
        "ledger_mutated": False,
        "registry_mutated": False,
        "hash_closure": closure,
        "hash_closure_pass": all(item["sha256"] for item in closure),
        "qualification_claim": "none; independent H2 mDBC CPU Definition/GenCase/native decode preflight only",
    }
    _write_json(cell_dir / "prepared.json", prepared)
    return {
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "held_out": bool(cell.get("held_out", False)),
        "status": "prepared" if preflight["preflight_pass"] else "failed",
        "attempted": True,
        "preflight_pass": bool(preflight["preflight_pass"]),
        "mass_error_relative": float(preflight["mass_gate"]["mass_error_relative"]),
        "native_zero_boundary_normals": preflight["mdbc_normal_gate"]["zero_boundary_normals"],
        "prepared": str((cell_dir / "prepared.json").resolve()),
        "prepared_sha256": _digest(cell_dir / "prepared.json"),
        "preflight": str((cell_dir / "preflight.json").resolve()),
        "preflight_sha256": _digest(cell_dir / "preflight.json"),
        "hash_closure_pass": bool(prepared["hash_closure_pass"]),
        "failure": None if preflight["preflight_pass"] else "native H2 mDBC preflight gate failed",
    }


def _failure_row(output: Path, cell: dict[str, Any], error: BaseException) -> dict[str, Any]:
    cell_dir = output / "cells" / _cell_dir_name(cell)
    cell_dir.mkdir(parents=True, exist_ok=True)
    failure = {
        "schema": "core.f2.h2_mdbc.static_range.cell_failure.v1",
        "created_at": _stamp(),
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "status": "failed",
        "error_type": type(error).__name__,
        "error": str(error),
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutated": False,
        "ledger_mutated": False,
        "registry_mutated": False,
        "qualification_claim": "none; raw CPU preparation failure retained",
    }
    path = cell_dir / "failure.json"
    _write_json(path, failure)
    return {
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "held_out": bool(cell.get("held_out", False)),
        "status": "failed",
        "attempted": True,
        "preflight_pass": False,
        "mass_error_relative": None,
        "native_zero_boundary_normals": None,
        "prepared": None,
        "prepared_sha256": None,
        "preflight": None,
        "preflight_sha256": None,
        "hash_closure_pass": False,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "failure_artifact": str(path.resolve()),
        "failure_artifact_sha256": _digest(path),
    }


def _base_rows(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "held_out": bool(cell.get("held_out", False)),
        "status": "unattempted",
        "attempted": False,
        "failure": None,
    } for cell in cells]


def _controls() -> dict[str, Any]:
    return {
        "cpu_gencase_allowed": True,
        "cpu_native_decoder_allowed": True,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "solver_binary_read_or_hashed": False,
        "matrix_jobs_materialized": False,
        "qualification_claim_allowed": False,
    }


def _report_base(card: dict[str, Any], inputs: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, Any]:
    design = card["qualification_design"]
    return {
        "schema": SCHEMA,
        "created_at": _stamp(),
        "family": "F2",
        "candidate_id": card["candidate_id"],
        "scope_id": card["scope_id"],
        "anchor_scope_id": card["anchor_evidence"]["prepared"]["scope_id"],
        "candidate_card": inputs["candidate_ref"],
        "registered_cell_count": EXPECTED_CELL_COUNT,
        "registered_design": {
            "cell_count": int(design["cell_count"]),
            "spatial_cell_count": sum(str(cell["design_cell"]).startswith("spatial") for cell in cells),
            "temporal_cell_count": sum(str(cell["design_cell"]) in {"internal_time", "native_output"} for cell in cells),
            "registered_window_s": TIME_MAX_S,
            "registered_output_interval_s": REGISTERED_OUTPUT_INTERVAL_S,
            "settle_hold_s": float(design["settle_hold_s"]),
            "parameter_axis": card["parameter_axis"]["normalized_name"],
            "boundary_method": "mDBC Boundary=2",
            "normal_support": {"vdp": -0.5, "distanceh": 3.0, "svshapes": True},
        },
        "failure_denominator": {
            "fixed_registered_cell_denominator": EXPECTED_CELL_COUNT,
            "all_rows_in_denominator": True,
            "unprepared_rows_are_not_successes": True,
            "failed_rows_are_not_dropped": True,
            "survivor_renormalization": False,
            "rows": _base_rows(cells),
        },
        "execution_controls": _controls(),
        "dependency_closure": {
            "tool_inputs": inputs["tool_closure"],
            "frozen_anchor_inputs": inputs["frozen_anchor_inputs"],
            "solver_reference_skipped": inputs["solver_reference_skipped"],
        },
        "qualification_claim": "none; CPU-only H2 mDBC matrix preparation; no solver trajectory or range qualification",
        "candidate_matrix_inputs_materialized": False,
        "candidate_matrix_jobs_materialized": False,
    }


def plan_matrix(lab: Path, candidate_path: Path, output: Path,
                gencase_path: Path | None = None, decoder_path: Path | None = None) -> dict[str, Any]:
    lab = Path(lab).resolve()
    candidate_path = _resolve(lab, candidate_path)
    card = json.loads(candidate_path.read_text())
    cells = _validate_candidate(card)
    inputs = _load_inputs(lab, candidate_path, card, gencase_path, decoder_path)
    report = _report_base(card, inputs, cells)
    report.update({
        "status": "plan_only",
        "selected_indices": [],
        "prepared_cell_count": 0,
        "failed_cell_count": 0,
        "unattempted_cell_count": EXPECTED_CELL_COUNT,
        "execution_controls": {**_controls(), "plan_only": True, "gen_case_run": False, "decoder_run": False},
    })
    output = Path(output).resolve()
    if output.exists() and output.is_dir() and any(output.iterdir()):
        raise ValueError(f"plan report path must be fresh or empty: {output}")
    _write_json(output, report)
    return report


def prepare_matrix(lab: Path, candidate_path: Path, output: Path, cell_indices: list[int],
                   all_cells: bool = False, gencase_path: Path | None = None,
                   decoder_path: Path | None = None,
                   native_output_interval_s: float | None = None,
                   run_gencase_fn: Callable[..., None] = _run_gencase,
                   decode_fn: Callable[..., tuple] = _decode_native) -> dict[str, Any]:
    lab = Path(lab).resolve()
    candidate_path = _resolve(lab, candidate_path)
    card = json.loads(candidate_path.read_text())
    cells = _validate_candidate(card)
    inputs = _load_inputs(lab, candidate_path, card, gencase_path, decoder_path)
    selected = list(range(EXPECTED_CELL_COUNT)) if all_cells else sorted(set(int(index) for index in cell_indices))
    if not selected:
        raise ValueError("prepare requires explicit --cell-index values or --all-cells")
    if any(index < 0 or index >= EXPECTED_CELL_COUNT for index in selected):
        raise ValueError("cell indices must be in the fixed range 0..14")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"matrix preparation output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    report = _report_base(card, inputs, cells)
    rows = _base_rows(cells)
    by_index = {int(cell["index"]): cell for cell in cells}
    materialized = []
    for index in selected:
        cell = by_index[index]
        try:
            result = _prepare_cell(
                lab, output, cell, card, inputs,
                native_output_interval_s=native_output_interval_s,
                run_gencase_fn=run_gencase_fn,
                decode_fn=decode_fn,
            )
        except Exception as error:  # retain the row and continue fixed denominator
            result = _failure_row(output, cell, error)
        rows[index] = result
        materialized.append(result)
    prepared_count = sum(row.get("status") == "prepared" for row in materialized)
    failed_count = sum(row.get("status") == "failed" for row in materialized)
    complete = len(selected) == EXPECTED_CELL_COUNT and prepared_count == EXPECTED_CELL_COUNT
    report["failure_denominator"]["rows"] = rows
    report.update({
        "status": "prepared_cpu_only" if complete else ("partial_with_failures" if failed_count else "partial_prepared"),
        "selected_indices": selected,
        "prepared_cell_count": int(prepared_count),
        "failed_cell_count": int(failed_count),
        "unattempted_cell_count": int(EXPECTED_CELL_COUNT - len(selected)),
        "cells": rows,
        "candidate_matrix_inputs_materialized": bool(complete),
        "candidate_matrix_jobs_materialized": False,
        "execution_controls": {**_controls(), "gen_case_run": True, "decoder_run": True},
        "matrix_output": str(output),
        "matrix_output_report": str((output / "matrix-preparation.json").resolve()),
    })
    _write_json(output / "matrix-preparation.json", report)
    return report


def _common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE_RELATIVE)
    parser.add_argument("--gencase", type=Path, default=None)
    parser.add_argument("--decoder", type=Path, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="write a no-execution review report")
    _common_parser(plan)
    plan.add_argument("--output", type=Path, required=True)
    prepare = sub.add_parser("prepare", help="materialize explicitly selected CPU cells")
    _common_parser(prepare)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--cell-index", type=int, action="append", default=[])
    prepare.add_argument("--all-cells", action="store_true")
    prepare.add_argument("--native-output-interval-s", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lab = Path(args.lab_root).resolve()
    if args.command == "plan":
        report = plan_matrix(lab, args.candidate, args.output, args.gencase, args.decoder)
    else:
        report = prepare_matrix(
            lab, args.candidate, args.output, args.cell_index,
            all_cells=args.all_cells,
            gencase_path=args.gencase,
            decoder_path=args.decoder,
            native_output_interval_s=args.native_output_interval_s,
        )
    print(json.dumps({"status": report["status"], "report": report.get("matrix_output_report", str(Path(args.output).resolve()))}, indent=2))
    return 0 if report["status"] not in {"partial_with_failures"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
