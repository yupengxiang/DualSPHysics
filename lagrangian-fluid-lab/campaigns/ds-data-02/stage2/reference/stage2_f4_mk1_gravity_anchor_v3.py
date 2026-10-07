#!/usr/bin/env python3
"""Bounded pre-contact gravity anchor for the F4 MK1 drop.

The worker decodes only explicitly selected native Part files.  It uses the
actual frame-0 MK1 centre and velocity as the initial condition, then checks
the bounded analytic trajectory

    C(t) = C0 + V0*t + 0.5*g*t*t
    V(t) = V0 + g*t

against exact RunPARTs timestamps.  It is a local pre-contact diagnostic.  It
does not interpolate frames, extrapolate after the selected window, infer a
rigid-body mass, or grant QI/QN/QE credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Iterable

import numpy as np

try:
    from scipy.spatial import cKDTree
except Exception as exc:  # pragma: no cover - reported as UNKNOWN at runtime.
    cKDTree = None
    _SCIPY_IMPORT_ERROR = repr(exc)
else:
    _SCIPY_IMPORT_ERROR = None

from stage2_f4_physical_observer_v1 import (  # noqa: E402
    UnsupportedSemantics,
    assign_particle_ranges,
    atomic_json,
    decode_frame,
    file_record,
    parse_source_xml,
    read_runparts,
)


SCHEMA = "ds02.stage2.f4-mk1-gravity-anchor.v3"
# Eight explicitly selected native frames spanning frame 0 through the bounded
# approximately 0.05 s pre-contact window.  The v2 six-frame artifact remains
# immutable; this forward version changes only the selected-frame contract.
ANCHOR_FRAMES = (0, 10, 20, 30, 40, 60, 80, 100)
ANCHOR_MAX_TIME_S = 0.06
TIME_TOLERANCE_S = 1.0e-10
SEPARATION_FACTOR = 2.0
POSITION_FRACTION_OF_DOMAIN = 0.02
POSITION_SCALED_NONZERO_FRACTION = 0.05
VELOCITY_SCALED_NONZERO_FRACTION = 0.05
VELOCITY_SCALE_FLOOR_M_PER_S = 1.0e-3
POSITION_SCALE_FLOOR_M = 1.0e-6


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _finite_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise UnsupportedSemantics(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise UnsupportedSemantics(f"{label} is non-finite: {value!r}")
    return number


def _vec3(values: Iterable[Any], label: str) -> np.ndarray:
    result = np.asarray([_finite_float(value, label) for value in values], dtype=np.float64)
    if result.shape != (3,):
        raise UnsupportedSemantics(f"{label} must have three components")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_source_contract(jsph: Path, gpu: Path, kernel: Path) -> dict[str, Any]:
    """Record source evidence used by the bounded analytic assumption.

    These checks establish the official kernel support factor, gravity loading,
    no-shifting configuration path, and the GPU loop's motion/step ordering.
    They do not prove that a particular numerical run has zero residual pair
    force; that limitation remains explicit in the output.
    """

    contracts = {
        "jsph_cpp": {
            "path": jsph,
            "patterns": {
                "gravity_loaded_from_case_constants": "Gravity=ToTFloat3(ctes.GetGravity());",
                "shifting_parameter_loaded": 'if(eparms.Exists("Shifting"))',
                "kernel_size_from_h": "KernelSize=float(kh);",
                "kernel_radius_squared": "KernelSize2=KernelSize*KernelSize;",
            },
        },
        "jsph_gpu_single_cpp": {
            "path": gpu,
            "patterns": {
                "gravity_motion_step_order": "if(CaseNmoving)CalcMotion(dt);",
                "time_step_increment": "TimeStep+=stepdt;",
                "step_counter_increment": "Nstep++;",
                "save_data_at_output_boundary": "SaveData();",
            },
        },
        "fun_sph_kernel_h": {
            "path": kernel,
            "patterns": {
                "wendland_factor_two": "GetKernelWendland_Factor(){ return(2.0f); }",
                "kernel_factor_dispatch": "GetKernel_Factor(TpKernel tker)",
            },
        },
    }
    result: dict[str, Any] = {}
    for label, item in contracts.items():
        path = Path(item["path"]).resolve()
        if not path.is_file() or path.is_symlink():
            raise UnsupportedSemantics(f"source contract file missing or symlinked: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        checks = {name: pattern in text for name, pattern in item["patterns"].items()}
        if not all(checks.values()):
            missing = [name for name, present in checks.items() if not present]
            raise UnsupportedSemantics(f"source contract patterns missing in {path}: {missing}")
        result[label] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "checks": checks,
        }
    result["interpretation"] = (
        "Source establishes gravity loading, kernel support factor 2h, the "
        "Shifting configuration path, and that motion is conditional on "
        "CaseNmoving. It does not measure residual internal pair force."
    )
    return result


def _execution_node(root: ET.Element) -> ET.Element:
    for node in root.iter():
        if _local(node.tag) == "execution":
            return node
    raise UnsupportedSemantics("generated XML has no execution node")


def parse_anchor_source(xml_path: Path) -> dict[str, Any]:
    source = parse_source_xml(xml_path)
    root = ET.parse(xml_path).getroot()
    execution = _execution_node(root)
    constants = next((node for node in execution if _local(node.tag) == "constants"), None)
    parameters = next((node for node in execution if _local(node.tag) == "parameters"), None)
    motion = next((node for node in execution if _local(node.tag) == "motion"), None)
    if constants is None or parameters is None or motion is None:
        raise UnsupportedSemantics("execution constants/parameters/motion are incomplete")

    gravity_node = next((node for node in constants if _local(node.tag) == "gravity"), None)
    h_node = next((node for node in constants if _local(node.tag) == "h"), None)
    if gravity_node is None or h_node is None:
        raise UnsupportedSemantics("execution constants lack gravity or h")
    gravity = _vec3([gravity_node.get(axis) for axis in ("x", "y", "z")], "gravity")
    h = _finite_float(h_node.get("value"), "kernel h")
    if h <= 0:
        raise UnsupportedSemantics(f"kernel h must be positive: {h}")

    params: dict[str, Any] = {}
    for node in parameters:
        if _local(node.tag) != "parameter" or node.get("key") is None:
            continue
        key = str(node.get("key"))
        raw = node.get("value")
        try:
            params[key] = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            params[key] = raw

    if motion.attrib or list(motion):
        raise UnsupportedSemantics("execution motion is not empty")
    special = next((node for node in execution if _local(node.tag) == "special"), None)
    special_tags = [] if special is None else [_local(node.tag) for node in special]
    unexpected_special = [tag for tag in special_tags if tag != "savedt"]
    if unexpected_special:
        raise UnsupportedSemantics(f"unsupported special/external control nodes: {unexpected_special}")

    forbidden_tags = {
        "moving", "floating", "inout", "periodic", "periodicboundary", "wavepaddles",
        "relaxzone", "damping", "moorings", "chrono", "forcepoints", "flexstruc",
    }
    forbidden = sorted({_local(node.tag) for node in root.iter() if _local(node.tag) in forbidden_tags})
    if forbidden:
        raise UnsupportedSemantics(f"external motion/force controls are present: {forbidden}")

    if int(float(params.get("Kernel", -1))) != 2:
        raise UnsupportedSemantics(f"analytic anchor requires Kernel=2 Wendland, got {params.get('Kernel')!r}")
    if float(params.get("Shifting", -1)) != 0.0:
        raise UnsupportedSemantics(f"analytic anchor requires Shifting=0, got {params.get('Shifting')!r}")

    massfluid = source["constants"].get("massfluid_kg")
    if massfluid is None or not math.isfinite(float(massfluid)) or float(massfluid) <= 0:
        raise UnsupportedSemantics(f"positive XML massfluid is required, got {massfluid!r}")

    drop_blocks = [block for block in source["blocks"] if block["kind"] == "fluid" and block["mk"] == 1]
    pool_blocks = [block for block in source["blocks"] if block["kind"] == "fluid" and block["mk"] == 0]
    fixed_blocks = [block for block in source["blocks"] if block["kind"] == "fixed"]
    if len(drop_blocks) != 1 or len(pool_blocks) != 1 or not fixed_blocks:
        raise UnsupportedSemantics(
            f"anchor requires one MK1 drop, one MK0 pool and fixed particles; "
            f"got drop={len(drop_blocks)} pool={len(pool_blocks)} fixed={len(fixed_blocks)}"
        )
    if any(block["kind"] in {"moving", "floating"} for block in source["blocks"]):
        raise UnsupportedSemantics("moving/floating particle block is unsupported")

    initials = next((node for node in root.iter() if _local(node.tag) == "initials"), None)
    initial_velocity_node = None
    if initials is not None:
        for node in initials:
            if _local(node.tag) == "velocity" and node.get("mkfluid") == "1":
                initial_velocity_node = node
                break
    if initial_velocity_node is None:
        raise UnsupportedSemantics("MK1 initial velocity declaration is missing")
    initial_velocity = _vec3(
        [initial_velocity_node.get(axis, "0") for axis in ("x", "y", "z")],
        "MK1 initial velocity",
    )

    support_radius = 2.0 * h
    return {
        "xml": file_record(xml_path.resolve()),
        "blocks": source["blocks"],
        "drop_block": drop_blocks[0],
        "pool_block": pool_blocks[0],
        "fixed_blocks": fixed_blocks,
        "massfluid_kg": float(massfluid),
        "gravity_m_s2": [float(value) for value in gravity],
        "kernel": {
            "parameter_value": int(float(params["Kernel"])),
            "name": "Wendland",
            "h_m": h,
            "support_factor": 2.0,
            "support_radius_m": support_radius,
            "source_formula": "KernelSize = h * GetKernel_Factor(Wendland), GetKernel_Factor=2",
        },
        "controls": {
            "external_motion": "PASS_EMPTY_EXECUTION_MOTION_AND_NO_MOVING_FLOATING_BLOCK",
            "shifting": "PASS_PARAMETER_Shifting_0",
            "periodic_or_external_force_nodes": "PASS_NONE_FOUND",
            "special_nodes": special_tags,
            "step_algorithm": params.get("StepAlgorithm"),
            "rigid_algorithm": params.get("RigidAlgorithm"),
            "time_max_s": params.get("TimeMax"),
            "time_out_s": params.get("TimeOut"),
        },
        "mk1_initial_velocity_xml_m_s": [float(value) for value in initial_velocity],
        "mass_semantics": (
            "constant XML massfluid applied to every fluid sample; no rigid or "
            "continuum mass inferred from particle sum"
        ),
    }


def _distance_record(drop: np.ndarray, other: np.ndarray, label: str, support_radius: float) -> dict[str, Any]:
    if cKDTree is None:
        raise UnsupportedSemantics(f"scipy.spatial.cKDTree unavailable: {_SCIPY_IMPORT_ERROR}")
    if drop.size == 0 or other.size == 0:
        raise UnsupportedSemantics(f"empty distance set for {label}")
    distances, _ = cKDTree(other).query(drop, k=1)
    minimum = float(np.min(distances))
    required = SEPARATION_FACTOR * support_radius
    return {
        "label": label,
        "min_distance_m": minimum,
        "support_radius_2h_m": support_radius,
        "required_far_margin_distance_m": required,
        "distance_over_2h": minimum / support_radius,
        "margin_beyond_2h_m": minimum - support_radius,
        "status": "PASS_FARTHER_THAN_TWO_SUPPORT_RADII" if minimum >= required else "FAIL_WITHIN_TWO_SUPPORT_RADII",
    }


def evaluate_preconditions(
    *,
    mass_kg: float,
    particle_count: int,
    gravity: Iterable[float],
    external_motion_status: str,
    shifting_status: str,
    id_status: str,
    internal_pair_force_status: str,
    separation_records: Iterable[dict[str, Any]],
    gravity_uniform: bool = True,
) -> dict[str, Any]:
    """Apply the explicit local-anchor gates, including manufactured rejects."""

    failures: list[str] = []
    if not math.isfinite(float(mass_kg)) or float(mass_kg) <= 0:
        failures.append("REJECT_NONPOSITIVE_OR_NONFINITE_PARTICLE_MASS")
    if int(particle_count) <= 0:
        failures.append("REJECT_EMPTY_DROP")
    gravity_values = [float(value) for value in gravity]
    if len(gravity_values) != 3 or not all(math.isfinite(value) for value in gravity_values):
        failures.append("REJECT_NONFINITE_GRAVITY")
    if not gravity_uniform:
        failures.append("REJECT_NONUNIFORM_GRAVITY")
    if external_motion_status != "PASS_EMPTY_EXECUTION_MOTION_AND_NO_MOVING_FLOATING_BLOCK":
        failures.append("REJECT_EXTERNAL_MOTION_OR_FORCE_CONTROL")
    if shifting_status != "PASS_PARAMETER_Shifting_0":
        failures.append("REJECT_PARTICLE_SHIFTING")
    if id_status != "PASS_NO_ID_EXCLUSION_OR_REUSE":
        failures.append("REJECT_ID_EXCLUSION_OR_REUSE")
    if internal_pair_force_status in {
        "NONZERO_INTERNAL_PAIR_FORCE",
        "UNBALANCED_INTERNAL_PAIR_FORCE",
        "INTERNAL_FORCE_NOT_CANCELLING",
    }:
        failures.append("REJECT_NONZERO_OR_UNBALANCED_INTERNAL_PAIR_FORCE")
    distance_statuses = [record.get("status") for record in separation_records]
    if not distance_statuses or any(status != "PASS_FARTHER_THAN_TWO_SUPPORT_RADII" for status in distance_statuses):
        failures.append("REJECT_CONTACT_OR_UNSUPPORTED_SPATIAL_SEPARATION")
    if failures:
        return {
            "status": "REJECTED_PRECONTACT_ANCHOR",
            "reasons": failures,
            "internal_pair_force_status": internal_pair_force_status,
        }
    if internal_pair_force_status == "UNKNOWN_NOT_DIRECTLY_OBSERVED":
        return {
            "status": "UNKNOWN_INTERNAL_PAIR_FORCE_NOT_DIRECTLY_OBSERVED",
            "reasons": ["internal pair force residual is not present in selected native fields"],
            "internal_pair_force_status": internal_pair_force_status,
        }
    return {
        "status": "PASS_CONDITIONAL_PRECONTACT_ANCHOR_DOMAIN",
        "reasons": [],
        "internal_pair_force_status": internal_pair_force_status,
    }


def _scaled_tolerances(com0: np.ndarray, predicted_com: np.ndarray, predicted_vel: np.ndarray, domain_extent: np.ndarray, initial_vel: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    displacement_scale = np.maximum(np.abs(predicted_com - com0), POSITION_SCALE_FLOOR_M)
    position_tolerance = np.maximum(
        POSITION_FRACTION_OF_DOMAIN * domain_extent,
        POSITION_SCALED_NONZERO_FRACTION * displacement_scale,
    )
    velocity_scale = np.maximum(np.maximum(np.abs(predicted_vel), np.abs(initial_vel)), VELOCITY_SCALE_FLOOR_M_PER_S)
    velocity_tolerance = VELOCITY_SCALED_NONZERO_FRACTION * velocity_scale
    return position_tolerance, velocity_tolerance


def compare_trajectory(observations: list[dict[str, Any]], gravity: np.ndarray, domain_extent: np.ndarray) -> dict[str, Any]:
    if not observations or observations[0].get("frame") != 0:
        raise UnsupportedSemantics("frame 0 is required for actual initial self-calibration")
    initial = observations[0]
    com0 = np.asarray(initial["drop_com_m"], dtype=np.float64)
    vel0 = np.asarray(initial["drop_mean_velocity_m_per_s"], dtype=np.float64)
    t0 = float(initial["runparts_time_s"])
    if not np.isfinite(com0).all() or not np.isfinite(vel0).all():
        raise UnsupportedSemantics("frame-0 COM/velocity is non-finite")
    rows: list[dict[str, Any]] = []
    all_pass = True
    for item in observations:
        time_s = float(item["runparts_time_s"])
        dt = time_s - t0
        predicted_com = com0 + vel0 * dt + 0.5 * gravity * (dt * dt)
        predicted_vel = vel0 + gravity * dt
        observed_com = np.asarray(item["drop_com_m"], dtype=np.float64)
        observed_vel = np.asarray(item["drop_mean_velocity_m_per_s"], dtype=np.float64)
        if not np.isfinite(observed_com).all() or not np.isfinite(observed_vel).all():
            raise UnsupportedSemantics(f"non-finite observed MK1 COM/velocity at frame {item['frame']}")
        position_tolerance, velocity_tolerance = _scaled_tolerances(com0, predicted_com, predicted_vel, domain_extent, vel0)
        position_error = np.abs(observed_com - predicted_com)
        velocity_error = np.abs(observed_vel - predicted_vel)
        position_pass = bool(np.all(position_error <= position_tolerance))
        velocity_pass = bool(np.all(velocity_error <= velocity_tolerance))
        row_pass = position_pass and velocity_pass and item["time_status"] == "PASS_DECODED_TIME_MATCH"
        all_pass = all_pass and row_pass
        rows.append({
            "frame": int(item["frame"]),
            "runparts_time_s": time_s,
            "decoded_time_s": float(item["decoded_time_s"]),
            "dt_from_frame0_s": dt,
            "observed_com_m": [float(value) for value in observed_com],
            "predicted_com_m": [float(value) for value in predicted_com],
            "com_abs_error_m": [float(value) for value in position_error],
            "com_tolerance_m": [float(value) for value in position_tolerance],
            "observed_velocity_m_per_s": [float(value) for value in observed_vel],
            "predicted_velocity_m_per_s": [float(value) for value in predicted_vel],
            "velocity_abs_error_m_per_s": [float(value) for value in velocity_error],
            "velocity_tolerance_m_per_s": [float(value) for value in velocity_tolerance],
            "position_status": "PASS_WITHIN_FROZEN_SCALED_TOLERANCE" if position_pass else "FAIL_OUTSIDE_FROZEN_SCALED_TOLERANCE",
            "velocity_status": "PASS_WITHIN_FROZEN_SCALED_TOLERANCE" if velocity_pass else "FAIL_OUTSIDE_FROZEN_SCALED_TOLERANCE",
            "status": "PASS_LOCAL_ANCHOR_SAMPLE" if row_pass else "FAIL_LOCAL_ANCHOR_SAMPLE",
        })
    return {
        "initial_self_calibration": {
            "frame": 0,
            "time_s": t0,
            "com0_m": [float(value) for value in com0],
            "velocity0_m_per_s": [float(value) for value in vel0],
            "source": "actual decoded native frame 0; no expected geometry substituted",
        },
        "gravity_m_s2": [float(value) for value in gravity],
        "rows": rows,
        "status": "PASS_LOCAL_PRECONTACT_GRAVITY_ANCHOR" if all_pass else "FAIL_LOCAL_PRECONTACT_GRAVITY_ANCHOR",
        "post_window_extrapolation": False,
    }


def _frame_metrics(frame: dict[str, Any], source: dict[str, Any], expected_time_s: float, state: dict[str, Any]) -> dict[str, Any]:
    ids = frame["ids"]
    kind, mk = assign_particle_ranges(ids, source["blocks"])
    if not np.all(np.isfinite(frame["position"])) or not np.all(np.isfinite(frame["velocity"])):
        raise UnsupportedSemantics(f"non-finite native position/velocity at frame {frame['frame']}")
    if abs(frame["decoded_time_s"] - expected_time_s) > TIME_TOLERANCE_S:
        time_status = "FAIL_DECODED_TIME_MISMATCH"
    else:
        time_status = "PASS_DECODED_TIME_MATCH"

    drop_mask = (kind == "fluid") & (mk == 1)
    pool_mask = (kind == "fluid") & (mk == 0)
    fixed_mask = kind == "fixed"
    if not np.any(drop_mask) or not np.any(pool_mask) or not np.any(fixed_mask):
        raise UnsupportedSemantics(f"missing MK1/MK0/fixed particle range at frame {frame['frame']}")
    expected_count = int(sum(block["count"] for block in source["blocks"]))
    if int(ids.size) != expected_count:
        raise UnsupportedSemantics(f"decoded particle count {ids.size} differs from XML {expected_count}")

    current_ids = np.asarray(ids, dtype=np.uint32)
    if state.get("initial_ids") is None:
        state["initial_ids"] = current_ids.copy()
        state["initial_counts"] = {
            "drop_mk1": int(np.sum(drop_mask)),
            "pool_mk0": int(np.sum(pool_mask)),
            "fixed": int(np.sum(fixed_mask)),
        }
        state["domain_extent_m"] = np.max(frame["position"].astype(np.float64, copy=False), axis=0) - np.min(frame["position"].astype(np.float64, copy=False), axis=0)
    elif not np.array_equal(current_ids, state["initial_ids"]):
        raise UnsupportedSemantics(f"ID axis changed or excluded at frame {frame['frame']}")
    counts = {"drop_mk1": int(np.sum(drop_mask)), "pool_mk0": int(np.sum(pool_mask)), "fixed": int(np.sum(fixed_mask))}
    if counts != state["initial_counts"]:
        raise UnsupportedSemantics(f"particle class counts changed at frame {frame['frame']}: {counts}")

    drop_pos = frame["position"][drop_mask].astype(np.float64, copy=False)
    drop_vel = frame["velocity"][drop_mask].astype(np.float64, copy=False)
    all_pos = frame["position"].astype(np.float64, copy=False)
    mass = float(source["massfluid_kg"])
    distance_records = [
        _distance_record(drop_pos, all_pos[pool_mask], "MK1_drop_vs_MK0_pool", state["support_radius_m"]),
        _distance_record(drop_pos, all_pos[fixed_mask], "MK1_drop_vs_fixed_boundary", state["support_radius_m"]),
    ]
    return {
        "frame": int(frame["frame"]),
        "runparts_time_s": float(expected_time_s),
        "decoded_time_s": float(frame["decoded_time_s"]),
        "time_status": time_status,
        "drop_particle_count": int(drop_pos.shape[0]),
        "drop_sample_mass_kg": float(drop_pos.shape[0] * mass),
        "drop_com_m": [float(value) for value in np.mean(drop_pos, axis=0, dtype=np.float64)],
        "drop_mean_velocity_m_per_s": [float(value) for value in np.mean(drop_vel, axis=0, dtype=np.float64)],
        "distance_checks": distance_records,
        "id_status": "PASS_NO_ID_EXCLUSION_OR_REUSE",
        "raw_part": frame["saved_file"],
        "raw_field_digest_sha256": frame["field_digest_sha256"],
        "decoder_xml_sha256": frame["decoder_xml_sha256"],
        "position_dtype": frame["position_dtype"],
        "counts": counts,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = args.raw_root.resolve()
    runparts_path = args.runparts.resolve()
    source_xml = args.generated_xml.resolve()
    decoder = args.decoder.resolve()
    output = args.output.resolve()
    scratch_root = args.scratch_root.resolve()
    if not raw_root.is_dir():
        raise ValueError(f"native raw root is missing: {raw_root}")
    if not decoder.is_file() or not os.access(decoder, os.X_OK):
        raise ValueError(f"official decoder is not executable: {decoder}")
    rows = read_runparts(runparts_path)
    if args.expected_frame_count is not None and len(rows) != args.expected_frame_count:
        raise ValueError(f"RunPARTs rows {len(rows)} != expected {args.expected_frame_count}")
    if args.expected_final_time_s is not None and abs(rows[-1]["time_s"] - args.expected_final_time_s) > args.final_time_tolerance_s:
        raise ValueError(f"RunPARTs final time {rows[-1]['time_s']} differs from expected {args.expected_final_time_s}")
    source = parse_anchor_source(source_xml)
    source_contract = verify_source_contract(args.solver_source_jsph, args.solver_source_gpu, args.solver_source_kernel)
    selected_frames = [int(value) for value in args.frames]
    if selected_frames != sorted(set(selected_frames)) or not selected_frames or selected_frames[0] != 0:
        raise ValueError(f"frames must be sorted, unique and start at frame 0: {selected_frames}")
    if any(frame < 0 or frame >= len(rows) for frame in selected_frames):
        raise ValueError(f"selected frame outside RunPARTs: {selected_frames}")
    selected_times = [rows[frame]["time_s"] for frame in selected_frames]
    if selected_times[-1] > args.anchor_max_time_s:
        raise ValueError(f"selected anchor window ends at {selected_times[-1]}, beyond {args.anchor_max_time_s}")

    state: dict[str, Any] = {
        "initial_ids": None,
        "initial_counts": None,
        "domain_extent_m": None,
        "support_radius_m": float(source["kernel"]["support_radius_m"]),
    }
    observations: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    for frame_number in selected_frames:
        frame_path = raw_root / f"Part_{frame_number:04d}.bi4"
        decoded = decode_frame(frame_path, decoder, scratch_root, frame_number)
        raw_records.append(decoded["saved_file"])
        observations.append(_frame_metrics(decoded, source, rows[frame_number]["time_s"], state))

    domain_extent = np.asarray(state["domain_extent_m"], dtype=np.float64)
    if domain_extent.shape != (3,) or not np.isfinite(domain_extent).all():
        raise UnsupportedSemantics("frame-0 position field is unavailable for domain scale")
    if np.any(domain_extent <= 0):
        raise UnsupportedSemantics(f"non-positive initial domain extent: {domain_extent.tolist()}")

    separation_records = [record for observation in observations for record in observation["distance_checks"]]
    gate = evaluate_preconditions(
        mass_kg=source["massfluid_kg"],
        particle_count=state["initial_counts"]["drop_mk1"],
        gravity=source["gravity_m_s2"],
        external_motion_status=source["controls"]["external_motion"],
        shifting_status=source["controls"]["shifting"],
        id_status="PASS_NO_ID_EXCLUSION_OR_REUSE",
        internal_pair_force_status=args.internal_pair_force_status,
        separation_records=separation_records,
        gravity_uniform=True,
    )
    trajectory = compare_trajectory(observations, np.asarray(source["gravity_m_s2"], dtype=np.float64), domain_extent)
    if gate["status"].startswith("REJECT"):
        trajectory["status"] = "REJECTED_PRECONDITION_GATE"
    elif gate["status"].startswith("UNKNOWN"):
        trajectory["status"] = "UNKNOWN_INTERNAL_PAIR_FORCE_NOT_DIRECTLY_OBSERVED"

    return {
        "schema": SCHEMA,
        "status": (
            "PASS_BOUNDED_NATIVE_PRECONTACT_ANALYTIC_DIAGNOSTIC"
            if gate["status"] == "PASS_CONDITIONAL_PRECONTACT_ANCHOR_DOMAIN"
            else (
                "UNKNOWN_BOUNDED_NATIVE_PRECONTACT_ANALYTIC_DIAGNOSTIC"
                if gate["status"].startswith("UNKNOWN")
                else "REJECTED_BOUNDED_NATIVE_PRECONTACT_ANALYTIC_DIAGNOSTIC"
            )
        ),
        "scope": {
            "selected_frames": selected_frames,
            "selected_frame_count": len(selected_frames),
            "runparts_frame_count": len(rows),
            "selected_window_s": [selected_times[0], selected_times[-1]],
            "full_native_tree_scanned": False,
            "full_native_tree_sha256": "NOT_COMPUTED_BY_WORKER",
            "hdf5_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "post_anchor_extrapolation": False,
        },
        "source": {
            "raw_root": str(raw_root),
            "runparts": file_record(runparts_path),
            "generated_xml": source["xml"],
            "decoder": file_record(decoder),
            "solver_source_contract": source_contract,
            "particle_semantics": source,
            "selected_part_records": raw_records,
        },
        "time_sampling": {
            "policy": "exact RunPARTs saved timestamps; no frame interpolation",
            "selected_frames": selected_frames,
            "selected_times_s": selected_times,
            "brackets": [[time, time] for time in selected_times],
            "decoded_time_tolerance_s": TIME_TOLERANCE_S,
        },
        "precondition_gate": gate,
        "anchor_contract": {
            "formula_position": "C(t)=C0+V0*t+0.5*g*t^2",
            "formula_velocity": "V(t)=V0+g*t",
            "initial_condition": "actual decoded frame 0 MK1 COM and mean velocity",
            "valid_domain": "selected pre-contact window only; no extrapolation after last selected timestamp",
            "internal_pair_force_status": args.internal_pair_force_status,
            "not_global_qe": True,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "frozen_tolerances": {
            "position_fraction_of_initial_domain_extent": POSITION_FRACTION_OF_DOMAIN,
            "position_scaled_nonzero_fraction": POSITION_SCALED_NONZERO_FRACTION,
            "position_floor_m": POSITION_SCALE_FLOOR_M,
            "velocity_scaled_nonzero_fraction": VELOCITY_SCALED_NONZERO_FRACTION,
            "velocity_scale_floor_m_per_s": VELOCITY_SCALE_FLOOR_M_PER_S,
            "spatial_separation_required_factor_times_2h": SEPARATION_FACTOR,
        },
        "domain_extent_initial_m": [float(value) for value in domain_extent],
        "observations": observations,
        "trajectory": trajectory,
        "mass_semantics": "XML constant massfluid for MK1 samples; no rigid/continuum mass inference",
        "source_deleted": False,
    }


def unknown_sidecar(output: Path, reason: str) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": "UNKNOWN_UNSUPPORTED_ANCHOR_SEMANTICS",
        "reason": reason,
        "scope": {"hdf5_read": False, "full_native_tree_scanned": False, "typed_conversion": "NOT_PERFORMED"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--runparts", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--solver-source-jsph", type=Path, required=True)
    parser.add_argument("--solver-source-gpu", type=Path, required=True)
    parser.add_argument("--solver-source-kernel", type=Path, required=True)
    parser.add_argument("--expected-frame-count", type=int, required=True)
    parser.add_argument("--expected-final-time-s", type=float, required=True)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-12)
    parser.add_argument("--anchor-max-time-s", type=float, default=ANCHOR_MAX_TIME_S)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    parser.add_argument(
        "--internal-pair-force-status",
        default="UNKNOWN_NOT_DIRECTLY_OBSERVED",
        choices=(
            "UNKNOWN_NOT_DIRECTLY_OBSERVED",
            "PAIRWISE_INTERNAL_FORCE_COM_CANCELLATION_SOURCE_CONTRACT",
            "NONZERO_INTERNAL_PAIR_FORCE",
            "UNBALANCED_INTERNAL_PAIR_FORCE",
            "INTERNAL_FORCE_NOT_CANCELLING",
        ),
    )
    args = parser.parse_args()
    try:
        result = run(args)
    except UnsupportedSemantics as exc:
        result = unknown_sidecar(args.output.resolve(), str(exc))
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
