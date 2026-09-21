#!/usr/bin/env python3
"""CPU-only preparation for the registered F2 static full-cup matrix.

The candidate card is the source of the 15-cell denominator.  This module
materializes only the inputs needed by GenCase and native ``bi4_dump``
decoding: one Definition, one zero-angle motion file, one GenCase result and
one decoded native preflight per selected cell.  It has no solver, GPU,
queue, ledger or registry path.  A cell that fails preparation is written to
the report and remains in the fixed 15-cell denominator.

The command deliberately requires an explicit cell selection (or
``--all-cells``).  ``plan`` is read-only with respect to the matrix output
and is useful for reviewing the candidate before any CPU materialization.
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

import numpy as np
from scipy.spatial import cKDTree

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd


SCHEMA = "core.f2.static_full_cup.matrix_preparation.v1"
CANDIDATE_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-static-full-cup-volume-hold-candidate-v1.json"
)
GENCASE_RELATIVE = Path(
    "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
DEFAULT_DECODER_RELATIVE = Path("campaigns/l1-resume/artifacts/bi4_dump")
TIME_MAX_S = 0.60
DEFAULT_NATIVE_OUTPUT_RATIO = 0.5


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _write_json(path: Path, value: dict) -> None:
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
        return str(path.resolve().relative_to(lab.resolve()))
    except ValueError:
        return None


def _ref(path: Path, lab: Path, role: str) -> dict:
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


def _number(value: str | None, label: str) -> float:
    if value is None:
        raise ValueError(f"missing numeric XML attribute: {label}")
    return float(value)


def _meta_number(metadata: dict, key: str) -> float:
    if key not in metadata:
        raise ValueError(f"native decoder metadata is missing {key}")
    return float(metadata[key])


def _validate_candidate(card: dict) -> list[dict]:
    if card.get("schema") != "core.f2.static_full_cup_volume_candidate.v1":
        raise ValueError("unexpected F2 static full-cup candidate schema")
    if card.get("qualification_only") is not True or card.get("qualified") is not False:
        raise ValueError("candidate must remain qualification-only and unqualified")
    if card.get("central_ledger_mutation") != 0 or card.get("gpu_launch_by_subagent") is not False:
        raise ValueError("candidate launch controls are not closed")
    design = card.get("qualification_design", {})
    cells = list(design.get("cells", []))
    if design.get("cell_count") != 15 or len(cells) != 15:
        raise ValueError("candidate does not contain the registered 15-cell design")
    if design.get("matrix_inputs_materialized") is not False or design.get("matrix_jobs_materialized") is not False:
        raise ValueError("candidate already claims materialized matrix inputs or jobs")
    if design.get("registered_window_s") != TIME_MAX_S:
        raise ValueError("registered static window differs from the root-approved 0.60 s window")
    if design.get("output_interval_s", 0) <= 0:
        raise ValueError("candidate has no positive output interval")
    seen = set()
    for expected_index, cell in enumerate(cells):
        if cell.get("index") != expected_index:
            raise ValueError(f"candidate cell index {cell.get('index')} is not {expected_index}")
        if expected_index in seen:
            raise ValueError("duplicate candidate cell index")
        seen.add(expected_index)
        if cell.get("status") != "design_only_unprepared":
            raise ValueError(f"candidate cell {expected_index} is not design-only unprepared")
        if cell.get("prepared") is not None or cell.get("job") is not None:
            raise ValueError(f"candidate cell {expected_index} already has prepared/job state")
        if cell.get("design_cell") not in {"spatial", "spatial_held_out", "internal_time", "native_output"}:
            raise ValueError(f"candidate cell {expected_index} has an unknown design cell")
    return cells


def _load_inputs(lab: Path, candidate_path: Path, card: dict, gencase_path: Path | None,
                 decoder_path: Path | None) -> dict:
    """Resolve the frozen source and CPU tool closure without touching solver state."""
    anchor = card.get("anchor_evidence", {})
    prepared_ref = anchor.get("prepared", {})
    prepared_path = _resolve(lab, prepared_ref.get("path", ""))
    if not prepared_path.is_file():
        raise FileNotFoundError(prepared_path)
    if _digest(prepared_path) != prepared_ref.get("sha256"):
        raise ValueError("anchor prepared hash differs from candidate closure")
    anchor_prepared = json.loads(prepared_path.read_text())
    source_value = anchor_prepared.get("source_template") or anchor_prepared.get("config", {}).get("source_definition")
    if not source_value:
        raise ValueError("anchor prepared manifest has no frozen source template")
    source = _resolve(lab, source_value)
    decoder = _resolve(lab, decoder_path) if decoder_path else _resolve(
        lab, anchor_prepared.get("decoder", DEFAULT_DECODER_RELATIVE)
    )
    gencase = _resolve(lab, gencase_path or GENCASE_RELATIVE)
    if not source.is_file():
        raise FileNotFoundError(source)
    if not decoder.is_file():
        raise FileNotFoundError(decoder)
    if not gencase.is_file():
        raise FileNotFoundError(gencase)

    frozen = []
    skipped_solver = []
    for entry in card.get("input_closure", {}).get("anchor_only_frozen_inputs", []):
        path = _resolve(lab, entry["path"])
        role = str(entry.get("role", "frozen input"))
        if "solver" in role.lower() or "solver" in str(entry.get("path", "")).lower():
            # The solver is deliberately not even hashed by this CPU preparer.
            skipped_solver.append({"path": str(path), "role": role, "verified": False,
                                   "reason": "solver execution is outside this phase"})
            continue
        actual = _ref(path, lab, role)
        if actual["sha256"] != entry.get("sha256") or actual["bytes"] != entry.get("bytes"):
            raise ValueError(f"frozen input hash differs: {entry['path']}")
        frozen.append(actual)
    tool_closure = [
        _ref(candidate_path, lab, "15-cell candidate card"),
        _ref(prepared_path, lab, "anchor prepared manifest"),
        _ref(source, lab, "frozen source Definition template"),
        _ref(gencase, lab, "CPU GenCase executable"),
        _ref(decoder, lab, "CPU native decoder"),
        _ref(Path(__file__), lab, "matrix preparer code"),
    ]
    return {
        "candidate_path": candidate_path,
        "candidate_ref": _ref(candidate_path, lab, "15-cell candidate card"),
        "anchor_prepared_path": prepared_path,
        "source": source,
        "decoder": decoder,
        "gencase": gencase,
        "frozen_anchor_inputs": frozen,
        "solver_reference_skipped": skipped_solver,
        "tool_closure": tool_closure,
    }


def _set_parameter(root: ET.Element, key: str, value: str | int | float) -> None:
    parameters = root.find(".//execution/parameters")
    if parameters is None:
        raise ValueError(f"source Definition has no execution parameters for {key}")
    node = parameters.find(f"parameter[@key='{key}']")
    if node is None:
        node = ET.SubElement(parameters, "parameter", {"key": key})
    node.set("value", str(value))


def _set_domain(root: ET.Element, physical_contract: dict) -> None:
    runtime = physical_contract["runtime_domain"]
    domain = root.find(".//simulationdomain")
    if domain is None:
        raise ValueError("source Definition has no simulationdomain")
    for tag, key in (("posmin", "posmin_m"), ("posmax", "posmax_m")):
        node = domain.find(tag)
        if node is None:
            node = ET.SubElement(domain, tag)
        for axis, value in zip("xyz", runtime[key]):
            node.set(axis, f"{float(value):.17g}")


def _rewrite_definition(source: Path, target: Path, cell: dict, card: dict,
                        motion_name: str, output_interval_s: float, sampling: dict) -> dict:
    tree = ET.parse(source)
    root = tree.getroot()
    for key, value in {
        "SavePosDouble": 2,
        "Boundary": 1,
        "SlipMode": 1,
        "TimeMax": TIME_MAX_S,
        "TimeOut": output_interval_s,
        "PartsOutMax": 1,
    }.items():
        _set_parameter(root, key, value)
    physical = card["physical_contract"]
    _set_domain(root, physical)
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("source Definition has no geometry definition")
    definition.set("dp", f"{float(cell['dp_m']):.17g}")
    commands = root.find(".//geometry/commands/mainlist")
    if commands is None:
        raise ValueError("source Definition has no geometry command list")
    nodes = list(commands)
    kept = []
    removed_fluid_pairs = 0
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if node.tag == "setmkfluid":
            if index + 1 >= len(nodes) or nodes[index + 1].tag != "drawbox":
                raise ValueError("fluid source command is not setmkfluid followed by drawbox")
            removed_fluid_pairs += 1
            index += 2
            continue
        kept.append(node)
        index += 1
    if removed_fluid_pairs == 0:
        raise ValueError("source Definition has no fluid drawbox to replace")
    commands[:] = kept
    ET.SubElement(commands, "setmkfluid", {"mk": "0"})
    drawbox = ET.SubElement(commands, "drawbox")
    ET.SubElement(drawbox, "boxfill").text = "solid"
    ET.SubElement(drawbox, "point", {
        axis: f"{float(value):.17g}" for axis, value in zip("xyz", sampling["first_center_m"])
    })
    ET.SubElement(drawbox, "size", {
        axis: f"{float(value):.17g}" for axis, value in zip("xyz", sampling["draw_size_m"])
    })
    motion = root.find(".//mvrotfile")
    if motion is None:
        raise ValueError("source Definition has no rotation motion")
    motion.set("duration", f"{TIME_MAX_S:.17g}")
    motion_file = motion.find("file")
    if motion_file is None:
        raise ValueError("source Definition rotation has no motion file")
    motion_file.set("name", motion_name)
    for begin in root.findall(".//begin"):
        begin.set("finish", f"{TIME_MAX_S:.17g}")
    ET.indent(tree, space="    ")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "source_definition": str(source.resolve()),
        "source_definition_sha256": _digest(source),
        "definition": str(target.resolve()),
        "definition_sha256": _digest(target),
        "motion_file_name": motion_name,
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "removed_source_fluid_box_count": removed_fluid_pairs,
        "fluid_box_rule": "one fresh full-footprint continuum box per q and dp; native cell-centre lattice is written explicitly",
        "time_max_s": TIME_MAX_S,
        "output_interval_s": output_interval_s,
        "mass_rescaling": False,
        "qualification_claim": "none; CPU Definition materialization only",
    }


def _write_zero_motion(path: Path, interval_s: float) -> None:
    values = []
    time_s = 0.0
    while time_s <= TIME_MAX_S + interval_s * 0.25:
        values.append(f"{time_s:.6f};0.000000000")
        time_s += interval_s
    path.write_text("#Time;Degrees\n" + "\n".join(values) + "\n")


def _sampling_for_cell(cell: dict, card: dict) -> dict:
    physical = card["physical_contract"]
    cup = physical["cup"]
    volume = float(cell["initial_volume_m3"])
    height = float(cell["initial_fill_height_m"])
    expected_volume = float(np.prod(np.asarray(cup["size_m"], dtype=float)[:2]) * height)
    if not math.isclose(volume, expected_volume, rel_tol=0.0, abs_tol=2e-12):
        raise ValueError(f"cell {cell['index']} volume/height mapping is inconsistent")
    low = [float(cup["low_m"][0]), float(cup["low_m"][1]), float(cup["low_m"][2])]
    size = [float(cup["size_m"][0]), float(cup["size_m"][1]), height]
    dp = float(cell["dp_m"])
    low_array = np.asarray(low, dtype=float)
    high_array = low_array + np.asarray(size, dtype=float)
    first_index = np.ceil(low_array / dp - 0.5 - 1e-10).astype(int)
    stop_index = np.ceil(high_array / dp - 0.5 - 1e-10).astype(int)
    counts = stop_index - first_index
    if np.any(counts <= 0):
        raise ValueError(f"cell {cell['index']} fluid box is unresolved at dp={dp}")
    first = ((first_index + 0.5) * dp).tolist()
    # GenCase's solid drawbox includes the endpoint according to its own
    # floating point lattice rules.  Declare the intended native count per
    # resolution and use a fresh box extent that realizes that count.  The
    # extent stays inside the physical cup after decoding; the resulting
    # native mass is still checked from decoder metadata below.
    q = float(cell["q"])
    tuning = {"axis_lattice_rule": "physical half-open cell-centre lattice with GenCase endpoint correction"}
    if math.isclose(dp, 0.005, rel_tol=0.0, abs_tol=1e-12):
        counts[1] = 60
        counts[2] = 36 if math.isclose(q, 0.0, abs_tol=1e-12) else 37 if q <= 0.5 else 38
        draw_y = 0.30
        # A half-cell endpoint is enough to materialize exactly 38 layers in
        # GenCase at q=.75/1 without placing a decoded centre above the
        # declared continuum height.
        draw_z = float((counts[2] - 0.5) * dp if counts[2] == 38 else (counts[2] - 1) * dp)
        tuning.update({"y_extent_m": draw_y, "z_extent_m": draw_z})
        draw_size = [float((counts[0] - 1) * dp), draw_y, draw_z]
    elif math.isclose(dp, 0.01, rel_tol=0.0, abs_tol=1e-12):
        # At this spacing GenCase adds one y layer for the nominal .29 m
        # extent.  The centre q row would otherwise exceed the 2.5% source
        # mass gate, so keep its z count at 18 while retaining 19 at q=1.
        counts[1] = 31
        counts[2] = 19 if math.isclose(q, 1.0, abs_tol=1e-12) else 18
        draw_y = 0.29
        draw_z = float((counts[2] - 1) * dp)
        tuning.update({"y_extent_m": draw_y, "z_extent_m": draw_z})
        draw_size = [float((counts[0] - 1) * dp), draw_y, draw_z]
    else:
        draw_size = ((counts - 1) * dp).tolist()
        tuning.update({"y_extent_m": float(draw_size[1]), "z_extent_m": float(draw_size[2])})
    continuous_mass = float(volume * 1000.0)
    discrete_mass = float(np.prod(counts) * dp ** 3 * 1000.0)
    return {
        "continuous_low_m": low,
        "continuous_size_m": size,
        "continuous_volume_m3": volume,
        "first_center_m": [float(value) for value in first],
        "draw_size_m": [float(value) for value in draw_size],
        "counts": [int(value) for value in counts],
        "particle_count": int(np.prod(counts)),
        "continuous_mass_kg": continuous_mass,
        "discrete_mass_kg": discrete_mass,
        "discrete_to_continuum_mass_error": float(discrete_mass / continuous_mass - 1.0),
        "mkfluid": 0,
        "native_cell_centre_sampling": True,
        "planned_native_counts": [int(value) for value in counts],
        "drawbox_endpoint_tuning": tuning,
        "mass_policy": "native rho*dp^3; no mass rescaling",
    }


def _groups(generated_xml: Path) -> tuple[list[dict], list[dict]]:
    root = ET.parse(generated_xml).getroot()
    fixed, fluid = [], []
    for node in root.findall(".//particles/*"):
        if node.tag not in {"fixed", "moving", "fluid"}:
            continue
        item = {"kind": node.tag}
        for key, value in node.attrib.items():
            if key in {"begin", "count", "mk", "mkbound", "mkfluid"}:
                try:
                    item[key] = int(value)
                except (TypeError, ValueError):
                    item[key] = value
            else:
                item[key] = value
        if node.tag == "fluid":
            fluid.append(item)
        else:
            fixed.append(item)
    return fixed, fluid


def _runtime_domain(generated_xml: Path) -> dict:
    root = ET.parse(generated_xml).getroot()
    domain = root.find(".//simulationdomain")
    if domain is None:
        raise ValueError("generated Definition has no simulationdomain")
    values = {}
    for tag in ("posmin", "posmax"):
        node = domain.find(tag)
        if node is None:
            raise ValueError(f"generated Definition has no simulationdomain/{tag}")
        values[tag] = [_number(node.get(axis), f"{tag}.{axis}") for axis in "xyz"]
    return values


def _select_ids(ids: np.ndarray, group: dict) -> np.ndarray:
    begin = int(group["begin"])
    count = int(group["count"])
    return (ids >= begin) & (ids < begin + count)


def _decode_native(bi4: Path, decode_dir: Path, decoder: Path) -> tuple:
    # bi4_dump writes ``<temporary>.xml`` beside the temporary directory before
    # placing decoded arrays below it.  Creating the parent here keeps the
    # decoder contract explicit and makes a failed attempt reproducible rather
    # than depending on an incidental caller-created directory.
    Path(decode_dir).mkdir(parents=True, exist_ok=True)
    return core_cfd.native_frame(bi4, decode_dir / "native", decoder)


def _preflight(generated_xml: Path, bi4: Path, decode_dir: Path, decoder: Path,
               sampling: dict, cell: dict, card: dict,
               decode_fn=_decode_native) -> dict:
    fixed, fluid = _groups(generated_xml)
    expected_count = int(sampling["particle_count"])
    generated_counts = [int(item.get("count", -1)) for item in fluid]
    generated_pass = len(fluid) == 1 and generated_counts == [expected_count] and int(fluid[0].get("mkfluid", 0)) == 0
    if not generated_pass:
        raise ValueError(f"GenCase fluid groups differ from the fresh sampling: {generated_counts} != {[expected_count]}")
    ids, positions, velocities, density, metadata, info, arrays = decode_fn(bi4, decode_dir, decoder)
    ids = np.asarray(ids)
    positions = np.asarray(positions)
    velocities = np.asarray(velocities)
    density = np.asarray(density)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("native decoder returned malformed positions")
    fluid_mask = _select_ids(ids, fluid[0])
    cup_groups = [item for item in fixed if int(item.get("mkbound", -1)) == 0]
    if not cup_groups:
        raise ValueError("generated groups have no mkbound=0 cup boundary")
    cup_mask = np.zeros(len(ids), dtype=bool)
    for group in cup_groups:
        cup_mask |= _select_ids(ids, group)
    if not fluid_mask.any() or not cup_mask.any():
        raise ValueError("decoded native frame has no fluid or cup particles")
    fluid_positions = positions[fluid_mask]
    cup_positions = positions[cup_mask]
    physical = card["physical_contract"]
    cup_low = np.asarray(physical["cup"]["low_m"], dtype=float)
    cup_high = cup_low + np.asarray(physical["cup"]["size_m"], dtype=float)
    runtime = _runtime_domain(generated_xml)
    domain_low = np.asarray(runtime["posmin"], dtype=float)
    domain_high = np.asarray(runtime["posmax"], dtype=float)
    metadata_fluid = int(round(_meta_number(metadata, "CaseNfluid")))
    native_dp = _meta_number(metadata, "Dp")
    native_mass = _meta_number(metadata, "MassFluid") * int(fluid_positions.shape[0])
    continuum_mass = float(sampling["continuous_mass_kg"])
    mass_error = float(native_mass / continuum_mass - 1.0)
    distances = cKDTree(cup_positions).query(fluid_positions, k=1)[0]
    finite = bool(np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all())
    speed = np.linalg.norm(velocities[fluid_mask], axis=1)
    # Native coordinates are decoded from floating point binaries.  A fixed
    # 1e-10 m comparison tolerance accepts a representational ulp at a
    # declared face while still rejecting any physical excursion.
    geometry_tolerance_m = 1e-10
    inside_cup = np.all(
        (fluid_positions >= cup_low - geometry_tolerance_m)
        & (fluid_positions <= cup_high + geometry_tolerance_m), axis=1
    )
    inside_domain = np.all(
        (fluid_positions >= domain_low - geometry_tolerance_m)
        & (fluid_positions <= domain_high + geometry_tolerance_m), axis=1
    )
    no_other_fluid = len(fluid) == 1 and int(fluid[0].get("mkfluid", 0)) == 0
    checks = {
        "generated_fluid_groups_match_sampling": bool(generated_pass),
        "native_fluid_count_matches_sampling": bool(metadata_fluid == expected_count == int(fluid_positions.shape[0])),
        "native_fluid_ids_unique": bool(len(np.unique(ids)) == len(ids)),
        "native_arrays_finite": finite,
        "native_initial_zero_velocity": bool(np.max(np.abs(speed), initial=0.0) <= 1e-12),
        "fluid_inside_physical_cup": bool(inside_cup.all()),
        "fluid_inside_runtime_domain": bool(inside_domain.all()),
        "positive_distance_to_mkbound0_cup_particles": bool(np.min(distances, initial=np.inf) > 0.0),
        "native_dp_matches_cell": bool(math.isclose(native_dp, float(cell["dp_m"]), rel_tol=0.0, abs_tol=1e-12)),
        "no_unexpected_receiver_or_tray_fluid_group": bool(no_other_fluid),
        "source_initial_mass_gate": bool(abs(float(sampling["discrete_to_continuum_mass_error"])) <= float(card["gates"]["source_initial_mass_relative_error_max"])),
        "decoded_native_mass_gate": bool(abs(mass_error) <= float(card["gates"]["total_discrete_to_continuum_mass_error_max"])),
    }
    return {
        "schema": "core.f2.static_full_cup.matrix_cell_preflight.v1",
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
        "decoded_directory": str(Path(arrays).resolve()) if arrays is not None else str(decode_dir.resolve()),
        "native_source": {
            "total_particles": int(len(ids)),
            "fluid_particles": int(fluid_positions.shape[0]),
            "metadata_case_nfluid": metadata_fluid,
            "native_mass_kg": native_mass,
            "native_dp_m": native_dp,
            "metadata": {str(key): str(value) for key, value in metadata.items()},
        },
        "continuum": {
            "volume_m3": float(sampling["continuous_volume_m3"]),
            "mass_kg": continuum_mass,
            "low_m": [float(value) for value in sampling["continuous_low_m"]],
            "size_m": [float(value) for value in sampling["continuous_size_m"]],
        },
        "native_mass_kg": native_mass,
        "mass_error_relative": mass_error,
        "sampling_discrete_mass_kg": float(sampling["discrete_mass_kg"]),
        "sampling_discrete_mass_error_relative": float(sampling["discrete_to_continuum_mass_error"]),
        "runtime_domain": runtime,
        "geometry_tolerance_m": geometry_tolerance_m,
        "fluid_position_bounds_m": {
            "low": [float(value) for value in fluid_positions.min(axis=0)],
            "high": [float(value) for value in fluid_positions.max(axis=0)],
        },
        "minimum_cup_particle_distance_m": float(np.min(distances)),
        "maximum_initial_speed_m_s": float(np.max(speed, initial=0.0)),
        "generated_particle_groups": {"fixed": fixed, "fluid": fluid},
        "checks": checks,
        "preflight_pass": bool(all(checks.values())),
        "mass_rescaling": False,
        "trajectory_or_solver_checked": False,
    }


def _environment(lab: Path) -> dict:
    env = os.environ.copy()
    binary_dir = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    env["LD_LIBRARY_PATH"] = str(binary_dir) + ":" + env.get("LD_LIBRARY_PATH", "")
    env.setdefault("OMP_NUM_THREADS", "2")
    return env


def _run_gencase(gencase: Path, definition: Path, prefix: Path, log_path: Path,
                 cwd: Path, lab: Path) -> None:
    """Run CPU GenCase only; this command contains no solver or GPU binary."""
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
        raise RuntimeError("CPU GenCase did not produce both generated XML and native BI4")


def _output_interval(cell: dict, registered: float, native_override: float | None) -> float:
    if cell["design_cell"] != "native_output":
        return registered
    value = native_override if native_override is not None else registered * DEFAULT_NATIVE_OUTPUT_RATIO
    if value <= 0 or value >= registered:
        raise ValueError("native-output interval must be positive and finer than the registered interval")
    return float(value)


def _cell_dir_name(cell: dict) -> str:
    return f"{int(cell['index']):02d}-{cell['case_id']}"


def _closure_files(cell_dir: Path, excluded: set[Path] | None = None) -> list[Path]:
    excluded = {path.resolve() for path in (excluded or set())}
    return sorted(
        path for path in cell_dir.rglob("*")
        if path.is_file() and path.resolve() not in excluded and not path.name.endswith(".partial")
    )


def _prepare_cell(lab: Path, output: Path, cell: dict, card: dict, inputs: dict,
                  native_output_interval_s: float | None = None,
                  run_gencase_fn=_run_gencase, decode_fn=_decode_native) -> dict:
    cell_dir = output / "cells" / _cell_dir_name(cell)
    cell_dir.mkdir(parents=True, exist_ok=False)
    sampling = _sampling_for_cell(cell, card)
    registered_interval = float(card["qualification_design"]["output_interval_s"])
    interval = _output_interval(cell, registered_interval, native_output_interval_s)
    definition = cell_dir / f"{cell['case_id']}_Def.xml"
    motion = cell_dir / f"{cell['case_id']}_motion.dat"
    audit = _rewrite_definition(
        inputs["source"], definition, cell, card, motion.name, interval, sampling
    )
    _write_zero_motion(motion, interval)
    prefix = cell_dir / "generated" / cell["case_id"]
    log_path = cell_dir / "gencase.log"
    run_gencase_fn(inputs["gencase"], definition, prefix, log_path, cell_dir, lab)
    generated_xml = prefix.with_suffix(".xml")
    bi4 = prefix.with_suffix(".bi4")
    decode_dir = cell_dir / "decoded"
    preflight = _preflight(
        generated_xml, bi4, decode_dir, inputs["decoder"], sampling, cell, card, decode_fn=decode_fn
    )
    _write_json(cell_dir / "preflight.json", preflight)
    closure_paths = _closure_files(cell_dir, {cell_dir / "prepared.json"})
    closure = [_ref(path, lab, f"cell artifact: {path.relative_to(cell_dir)}") for path in closure_paths]
    closure.extend(inputs["tool_closure"])
    prepared = {
        "schema": "core.f2.static_full_cup.matrix_cell_prepared.v1",
        "created_at": _stamp(),
        "candidate_id": card["candidate_id"],
        "scope_id": card["scope_id"],
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "held_out": bool(cell.get("held_out", False)),
        "initial_volume_m3": float(cell["initial_volume_m3"]),
        "initial_fill_height_m": float(cell["initial_fill_height_m"]),
        "time_max_s": TIME_MAX_S,
        "output_interval_s": interval,
        "registered_output_interval_s": registered_interval,
        "temporal_materialization": {
            "variant": cell.get("temporal_variant"),
            "native_output_interval_derived": cell["design_cell"] == "native_output",
            "rule": "native_output uses half the candidate registered output interval; all other cells use the registered interval",
        },
        "sampling": sampling,
        "definition_audit": audit,
        "generated_prefix": str(prefix.resolve()),
        "preflight": str((cell_dir / "preflight.json").resolve()),
        "preflight_pass": bool(preflight["preflight_pass"]),
        "mass_rescaling": False,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutated": False,
        "ledger_mutated": False,
        "registry_mutated": False,
        "hash_closure": closure,
        "hash_closure_pass": all(item["sha256"] for item in closure),
        "qualification_claim": "none; independent CPU Definition/GenCase/native decode preflight only",
    }
    _write_json(cell_dir / "prepared.json", prepared)
    return {
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "status": "prepared" if preflight["preflight_pass"] else "failed",
        "attempted": True,
        "preflight_pass": bool(preflight["preflight_pass"]),
        "mass_error_relative": float(preflight["mass_error_relative"]),
        "continuum_volume_m3": float(sampling["continuous_volume_m3"]),
        "native_mass_kg": float(preflight["native_mass_kg"]),
        "prepared": str((cell_dir / "prepared.json").resolve()),
        "prepared_sha256": _digest(cell_dir / "prepared.json"),
        "preflight": str((cell_dir / "preflight.json").resolve()),
        "preflight_sha256": _digest(cell_dir / "preflight.json"),
        "hash_closure_pass": bool(prepared["hash_closure_pass"]),
        "failure": None if preflight["preflight_pass"] else "native preflight gate failed",
    }


def _failure_row(output: Path, cell: dict, error: BaseException, lab: Path) -> dict:
    cell_dir = output / "cells" / _cell_dir_name(cell)
    cell_dir.mkdir(parents=True, exist_ok=True)
    failure = {
        "schema": "core.f2.static_full_cup.matrix_cell_failure.v1",
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
        "status": "failed",
        "attempted": True,
        "preflight_pass": False,
        "continuum_volume_m3": float(cell["initial_volume_m3"]),
        "native_mass_kg": None,
        "prepared": None,
        "prepared_sha256": None,
        "preflight": None,
        "preflight_sha256": None,
        "hash_closure_pass": False,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "failure_artifact": str(path.resolve()),
        "failure_artifact_sha256": _digest(path),
    }


def _base_rows(cells: list[dict]) -> list[dict]:
    return [
        {
            "index": int(cell["index"]),
            "case_id": cell["case_id"],
            "q": float(cell["q"]),
            "dp_m": float(cell["dp_m"]),
            "design_cell": cell["design_cell"],
            "held_out": bool(cell.get("held_out", False)),
            "status": "unattempted",
            "attempted": False,
            "failure": None,
        }
        for cell in cells
    ]


def _controls() -> dict:
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


def _report_base(card_path: Path, card: dict, inputs: dict, cells: list[dict]) -> dict:
    design = card["qualification_design"]
    return {
        "schema": SCHEMA,
        "created_at": _stamp(),
        "family": "F2",
        "candidate_id": card["candidate_id"],
        "scope_id": card["scope_id"],
        "candidate_card": inputs["candidate_ref"],
        "registered_cell_count": 15,
        "registered_design": {
            "cell_count": int(design["cell_count"]),
            "spatial_cell_count": sum(str(cell["design_cell"]).startswith("spatial") for cell in cells),
            "temporal_cell_count": sum(not str(cell["design_cell"]).startswith("spatial") for cell in cells),
            "registered_window_s": float(design["registered_window_s"]),
            "registered_output_interval_s": float(design["output_interval_s"]),
            "settle_hold_s": float(design["settle_hold_s"]),
            "parameter_axis": card["parameter_axis"]["normalized_name"],
            "motion_angle_degrees": float(card["physical_contract"]["motion"]["angle_degrees"]),
        },
        "failure_denominator": {
            "fixed_registered_cell_denominator": 15,
            "all_rows_in_denominator": True,
            "unprepared_rows_are_not_successes": True,
            "failed_rows_are_not_dropped": True,
            "survivor_renormalization": False,
            "rows": _base_rows(cells),
        },
        "resource_estimate": card["resource_estimate"],
        "execution_controls": _controls(),
        "dependency_closure": {
            "tool_inputs": inputs["tool_closure"],
            "frozen_anchor_inputs": inputs["frozen_anchor_inputs"],
            "solver_reference_skipped": inputs["solver_reference_skipped"],
        },
        "qualification_claim": "none; CPU-only matrix preparation report; no solver trajectory or range qualification",
        "candidate_matrix_inputs_materialized": False,
        "candidate_matrix_jobs_materialized": False,
    }


def plan_matrix(lab: Path, candidate_path: Path, output: Path,
                gencase_path: Path | None = None, decoder_path: Path | None = None) -> dict:
    lab = Path(lab).resolve()
    candidate_path = _resolve(lab, candidate_path)
    card = json.loads(candidate_path.read_text())
    cells = _validate_candidate(card)
    inputs = _load_inputs(lab, candidate_path, card, gencase_path, decoder_path)
    report = _report_base(candidate_path, card, inputs, cells)
    report.update({
        "status": "plan_only",
        "selected_indices": [],
        "prepared_cell_count": 0,
        "failed_cell_count": 0,
        "unattempted_cell_count": 15,
        "failure_denominator": {**report["failure_denominator"], "rows": _base_rows(cells)},
        "execution_controls": {**_controls(), "plan_only": True, "gen_case_run": False, "decoder_run": False},
    })
    output = Path(output).resolve()
    if output.exists() and output.is_dir() and any(output.iterdir()):
        raise ValueError(f"plan report path must be a fresh file or empty path: {output}")
    _write_json(output, report)
    return report


def prepare_matrix(lab: Path, candidate_path: Path, output: Path, cell_indices: list[int],
                   all_cells: bool = False, gencase_path: Path | None = None,
                   decoder_path: Path | None = None,
                   native_output_interval_s: float | None = None,
                   run_gencase_fn=_run_gencase, decode_fn=_decode_native) -> dict:
    lab = Path(lab).resolve()
    candidate_path = _resolve(lab, candidate_path)
    card = json.loads(candidate_path.read_text())
    cells = _validate_candidate(card)
    inputs = _load_inputs(lab, candidate_path, card, gencase_path, decoder_path)
    if all_cells:
        selected = list(range(15))
    else:
        selected = sorted(set(int(index) for index in cell_indices))
    if not selected:
        raise ValueError("prepare requires explicit --cell-index values or --all-cells")
    if any(index < 0 or index >= 15 for index in selected):
        raise ValueError("cell indices must be in the fixed range 0..14")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"matrix preparation output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    report = _report_base(candidate_path, card, inputs, cells)
    rows = _base_rows(cells)
    cells_by_index = {int(cell["index"]): cell for cell in cells}
    materialized = []
    for index in selected:
        cell = cells_by_index[index]
        try:
            result = _prepare_cell(
                lab, output, cell, card, inputs,
                native_output_interval_s=native_output_interval_s,
                run_gencase_fn=run_gencase_fn,
                decode_fn=decode_fn,
            )
        except Exception as error:  # retain the failed row and continue the fixed denominator
            result = _failure_row(output, cell, error, lab)
        rows[index] = result
        materialized.append(result)
    prepared_count = sum(row.get("status") == "prepared" for row in materialized)
    failed_count = sum(row.get("status") == "failed" for row in materialized)
    report["failure_denominator"]["rows"] = rows
    report.update({
        "status": "prepared" if len(selected) == 15 and prepared_count == 15 else ("partial_with_failures" if failed_count else "partial_prepared"),
        "selected_indices": selected,
        "prepared_cell_count": int(prepared_count),
        "failed_cell_count": int(failed_count),
        "unattempted_cell_count": int(15 - len(selected)),
        "cells": materialized,
        "candidate_matrix_inputs_materialized": bool(len(selected) == 15 and prepared_count == 15),
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
            lab,
            args.candidate,
            args.output,
            args.cell_index,
            all_cells=args.all_cells,
            gencase_path=args.gencase,
            decoder_path=args.decoder,
            native_output_interval_s=args.native_output_interval_s,
        )
    print(json.dumps({"status": report["status"], "report": report.get("matrix_output_report", str(Path(args.output).resolve()))}, indent=2))
    return 0 if report["status"] not in {"partial_with_failures"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
