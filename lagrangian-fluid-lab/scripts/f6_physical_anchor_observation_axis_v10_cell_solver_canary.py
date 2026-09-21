#!/usr/bin/env python3
"""Execute one root-authorized CPU solver canary for an F6 v10 matrix cell.

The worker is deliberately single-use. It validates fresh v10 hash-bound inputs,
runs the CPU DualSPHysics binary once, converts the floating-body output with
the pinned ``FloatingInfo`` utility, audits all native frames and writes the
body-state/force/torque sidecar. Scientific credit, registry, ledger and
matrix paths remain closed regardless of the result.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np


LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.core_cfd import native_frame  # noqa: E402


JOB = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/cell-00/job.json"
REVIEW = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/cell-00/root-review.json"
DEFAULT_OUTPUT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921/cell-00/attempt-001"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
FLOATING_INFO = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/FloatingInfo_linux64"
RUNTIME_SCRIPT = Path(__file__).resolve()

TMAX = 1.5
TOUT = 0.005
EXPECTED_FRAMES = 301
GEOMETRY_TOLERANCE_M = 1.0e-8
CADENCE_TOLERANCE_S = 1.0e-8
MAX_GAP_S = 0.0055
TERMINAL_TARGET_S = 1.5
TERMINAL_OVERSHOOT_MAX_S = 0.0005
OBSERVATION_START_S = 1.0
OBSERVATION_END_S = 1.5
SCOPE_ID = "F6_fluid_rigid_body_physical_anchor_aligned_sampling_v3"
REVISION_ID = "F6_observation_axis_13plus2_v4"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    try:
        display = str(path.relative_to(LAB))
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": sha256(path) if path.is_file() else None, "bytes": path.stat().st_size if path.is_file() else 0, "role": role}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def resolve_ref(item: dict[str, Any], label: str) -> Path:
    raw = item.get("path")
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label}: missing path")
    path = Path(raw)
    if not path.is_absolute():
        path = LAB / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path) or int(item.get("bytes", -1)) != path.stat().st_size:
        raise ValueError(f"{label}: hash or byte count mismatch")
    return path


def verify_authorization() -> tuple[dict[str, Any], dict[str, Any]]:
    job = load(JOB)
    review = load(REVIEW)
    if job.get("schema") != "core.f6.observation_axis.protected_solver_canary_job.v1":
        raise ValueError("unexpected F6 solver-canary job schema")
    if job.get("job_status") != "root_authorized_not_started" or job.get("attempt") != 1:
        raise ValueError("solver-canary job is not fresh exact-one authorization")
    if not isinstance(job.get("scope_id"), str) or not job.get("scope_id"):
        raise ValueError("solver-canary job is missing scope binding")
    if job.get("revision_id") != REVISION_ID:
        raise ValueError("solver-canary job is not bound to the frozen v4 revision")
    if job.get("qualification_claim") != "none" or job.get("qualification_credit") != 0 or job.get("T1") is not False:
        raise ValueError("solver-canary job carries science credit")
    policy = job.get("execution_policy", {})
    if any(policy.get(key) not in (False, 0) for key in ("same_input_retry", "resume", "queue_submission", "registry_mutation", "ledger_mutation", "matrix_submission")):
        raise ValueError("solver-canary job opens retry or mutation")
    if policy.get("exactly_one_solver_attempt") is not True:
        raise ValueError("solver-canary job is not exact-one")
    if review.get("schema") != "core.f6.observation_axis.protected_solver_canary_root_review.v1":
        raise ValueError("unexpected F6 root-review schema")
    decision = review.get("decision", {})
    if decision.get("authorized_solver") is not True or decision.get("authorized_cpu_solver") is not True or decision.get("authorized_gpu") is not False:
        raise ValueError("CPU solver authorization is not closed and explicit")
    if any(decision.get(key) for key in ("authorized_queue", "authorized_registry", "authorized_ledger", "authorized_matrix")):
        raise ValueError("root review opens forbidden protected state")
    if job.get("root_review", {}).get("sha256") != sha256(REVIEW):
        raise ValueError("job/root-review hash mismatch")
    for name, item in job.get("inputs", {}).items():
        resolve_ref(item, f"job input {name}")
    resolve_ref(job["solver"]["binary"], "solver binary")
    resolve_ref(job["floating_info"], "FloatingInfo binary")
    resolve_ref(job["decoder"], "native decoder")
    worker = resolve_ref(job["runtime_worker"], "runtime worker")
    if worker != RUNTIME_SCRIPT.resolve():
        raise ValueError("job runtime worker is not this single-use worker")
    return job, review


def _float(raw: str | None) -> float:
    value = float(str(raw).strip())
    if not math.isfinite(value):
        raise ValueError(f"non-finite numeric field: {raw!r}")
    return value


def run_summary(run_out: Path) -> dict[str, Any]:
    text = run_out.read_text(encoding="utf-8", errors="replace") if run_out.is_file() else ""
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    time_max = [float(x) for x in re.findall(rf"^TimeMax=({number})$", text, re.MULTILINE)]
    # DualSPHysics writes the requested output interval as ``TimePart`` in
    # Run.out (the CLI option is ``-tout``).  Accept the older ``TimeOut``
    # spelling only for compatibility with archived receipts.
    time_out = [float(x) for x in re.findall(rf"^(?:TimeOut|TimePart)=({number})$", text, re.MULTILINE)]
    excluded = re.search(r"Excluded particles\.+:\s*([\d,]+)", text)
    parts = re.search(r"PART files\.+:\s*([\d,]+)", text)
    finished = "Finished execution (code=0)" in text
    return {
        "path": str(run_out.relative_to(LAB)) if run_out.is_relative_to(LAB) else str(run_out),
        "present": run_out.is_file(),
        "finished_code_zero": finished,
        "timemax_s": time_max[-1] if time_max else None,
        "timeout_s": time_out[-1] if time_out else None,
        "excluded_particles": int(excluded.group(1).replace(",", "")) if excluded else None,
        "reported_part_files": int(parts.group(1).replace(",", "")) if parts else None,
        "sha256": sha256(run_out) if run_out.is_file() else None,
    }


def read_groups(generated_xml: Path) -> dict[str, dict[str, Any]]:
    root = ET.parse(generated_xml).getroot()
    groups: dict[str, dict[str, Any]] = {}
    for node in root.findall(".//particles/*"):
        kind = node.tag
        if kind not in {"fixed", "moving", "floating", "fluid"}:
            continue
        mk = node.get("mkbound") if kind in {"fixed", "moving", "floating"} else node.get("mkfluid")
        groups[kind] = {"begin": int(node.get("begin")), "count": int(node.get("count")), "mk": int(mk) if mk is not None else None}
    if set(groups) != {"fixed", "floating", "fluid"}:
        raise ValueError(f"unexpected generated group set: {groups}")
    return groups


def mask_range(ids: np.ndarray, group: dict[str, Any]) -> np.ndarray:
    begin, count = int(group["begin"]), int(group["count"])
    return (ids >= begin) & (ids < begin + count)


def quaternion_from_euler_deg(roll: float, pitch: float, yaw: float) -> list[float]:
    r, p, y = (math.radians(value) for value in (roll, pitch, yaw))
    cr, sr = math.cos(r / 2.0), math.sin(r / 2.0)
    cp, sp = math.cos(p / 2.0), math.sin(p / 2.0)
    cy, sy = math.cos(y / 2.0), math.sin(y / 2.0)
    # DualSPHysics FloatingInfo reports roll/pitch/yaw; retain the standard
    # intrinsic XYZ composition and make the convention explicit in the sidecar.
    return [sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy]


def parse_floating_csv(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = []
        for raw in reader:
            row = {str(key).strip(): _float(value) for key, value in raw.items() if key is not None and value is not None and str(key).strip()}
            rows.append(row)
    if not rows:
        raise ValueError("FloatingInfo CSV is empty")
    return rows


def field(row: dict[str, float], stem: str) -> float:
    key = next((name for name in row if name.startswith(stem)), None)
    if key is None:
        raise KeyError(f"missing FloatingInfo field {stem}")
    return row[key]


def make_sidecar(rows: list[dict[str, float]], frame_audits: list[dict[str, Any]], contract: dict[str, Any], output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    body = contract["body"]
    fluid = contract["fluid"]
    tank = contract["tank"]
    surface = float(fluid["free_surface_z_m"])
    low = np.asarray(tank["low_m"], dtype=float)
    high = low + np.asarray(tank["size_m"], dtype=float)
    contact_window = contract["predicted_events"]["contact_prediction_window_s"]
    times = [field(row, "time") for row in rows]
    contact_flags: list[bool] = []
    sidecar: dict[str, Any] = {
        "schema": "core.f6.physical_anchor.body_state_force_sidecar.v1",
        "status": "runtime_sidecar_from_native_solver_and_floating_info",
        "body_id": body["body_id"],
        "mkbound": body["mkbound"],
        "time_s": times,
        "body_position_m": [],
        "body_quaternion_xyzw": [],
        "linear_velocity_m_s": [],
        "angular_velocity_rad_s": [],
        "fluid_force_N": [],
        "fluid_torque_Nm": [],
        "contact_count": [],
        "penetration_depth_m": [],
        "boundary_contact_count": [],
        "open_face_mass_flux_kg_s": [],
        "event_status": [],
        "valid": [],
        "orientation_convention": "FloatingInfo roll/pitch/yaw, intrinsic XYZ, quaternion xyzw",
        "force_source": "DualSPHysics FloatingInfo fluidforcelin/fluidforceang",
        "contract_binding": {"body_mass_kg": body["mass_kg"], "body_com_m": body["com_m"], "body_inertia_about_com_kg_m2": body["inertia_about_com_kg_m2"]},
    }
    for row, frame in zip(rows, frame_audits):
        position = [field(row, f"center.{axis}") for axis in "xyz"]
        linear = [field(row, f"fvel.{axis}") for axis in "xyz"]
        angular = [field(row, f"fomega.{axis}") for axis in "xyz"]
        force = [field(row, f"fluidforcelin.{axis}") for axis in "xyz"]
        torque = [field(row, f"fluidforceang.{axis}") for axis in "xyz"]
        euler = [field(row, f"{name}") for name in ("roll", "pitch", "yaw")]
        contact = bool(frame["body_min_m"][2] <= surface + GEOMETRY_TOLERANCE_M)
        contact_flags.append(contact)
        penetration = max(0.0, max(float(low[0] - frame["body_min_m"][0]), float(frame["body_max_m"][0] - high[0]), float(low[1] - frame["body_min_m"][1]), float(frame["body_max_m"][1] - high[1]), float(low[2] - frame["body_min_m"][2])))
        boundary_contact = int(any(abs(value) <= GEOMETRY_TOLERANCE_M for value in (frame["body_min_m"][0] - low[0], high[0] - frame["body_max_m"][0], frame["body_min_m"][1] - low[1], high[1] - frame["body_max_m"][1], frame["body_min_m"][2] - low[2])))
        open_mass = float(frame["fluid_outside_top_count"] * frame["mass_per_particle_kg"] / TOUT) if frame["fluid_outside_top_count"] else 0.0
        status = "observation_hold" if times[len(sidecar["event_status"])] >= OBSERVATION_START_S else "fluid_contact" if contact else "pre_contact"
        sidecar["body_position_m"].append(position)
        sidecar["body_quaternion_xyzw"].append(quaternion_from_euler_deg(*euler))
        sidecar["linear_velocity_m_s"].append(linear)
        sidecar["angular_velocity_rad_s"].append(angular)
        sidecar["fluid_force_N"].append(force)
        sidecar["fluid_torque_Nm"].append(torque)
        sidecar["contact_count"].append(int(contact))
        sidecar["penetration_depth_m"].append(penetration)
        sidecar["boundary_contact_count"].append(boundary_contact)
        sidecar["open_face_mass_flux_kg_s"].append(open_mass)
        sidecar["event_status"].append(status)
        sidecar["valid"].append(bool(frame["finite"] and all(math.isfinite(value) for values in (position, linear, angular, force, torque) for value in values)))
    observed = [times[index] for index, flag in enumerate(contact_flags) if flag]
    contact_time = observed[0] if observed else None
    gaps = np.diff(times) if len(times) > 1 else np.asarray([], dtype=float)
    hold_rows = [index for index, value in enumerate(times) if OBSERVATION_START_S <= value <= OBSERVATION_END_S]
    hold_bracketed = bool(
        times
        and times[0] <= OBSERVATION_START_S <= times[-1]
        and times[-1] >= OBSERVATION_END_S
        and np.isfinite(gaps).all()
        and (not len(gaps) or float(np.max(gaps)) <= MAX_GAP_S)
    )
    checks = {
        "sidecar_frame_count": len(times) == EXPECTED_FRAMES,
        "sidecar_time_strictly_increasing": bool(len(times) == EXPECTED_FRAMES and np.all(np.diff(times) > 0.0)),
        "sidecar_native_gap_bound": bool(len(times) == EXPECTED_FRAMES and np.isfinite(gaps).all() and (not len(gaps) or float(np.max(gaps)) <= MAX_GAP_S)),
        "sidecar_terminal_bracket": bool(times and TERMINAL_TARGET_S <= times[-1] <= TERMINAL_TARGET_S + TERMINAL_OVERSHOOT_MAX_S),
        "sidecar_fields_finite": all(sidecar["valid"]),
        "body_identity_fixed": sidecar["body_id"] == body["body_id"],
        "contact_observed": contact_time is not None,
        "contact_time_in_predicted_window": contact_time is not None and contact_window[0] - MAX_GAP_S <= contact_time <= contact_window[1] + MAX_GAP_S,
        "closed_face_contact_zero": all(value == 0 for value in sidecar["boundary_contact_count"]),
        "closed_face_penetration_zero": max(sidecar["penetration_depth_m"], default=float("inf")) <= GEOMETRY_TOLERANCE_M,
        "open_face_mass_flux_zero": max(sidecar["open_face_mass_flux_kg_s"], default=float("inf")) <= 0.0,
        "observation_hold_bracketed": hold_bracketed,
        "observation_hold_no_equilibrium_claim": True,
    }
    sidecar["audit"] = {
        "contact_time_s": contact_time,
        "predicted_contact_window_s": contact_window,
        "observation_window_s": [OBSERVATION_START_S, OBSERVATION_END_S],
        "native_time_axis": "solver_reported_actual_TimeStep",
        "max_native_gap_s": float(np.max(gaps)) if len(gaps) else None,
        "equilibrium_status": "not_claimed",
        "checks": checks,
    }
    return sidecar, checks


def run(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    global TMAX, TOUT, EXPECTED_FRAMES, MAX_GAP_S, TERMINAL_TARGET_S
    global TERMINAL_OVERSHOOT_MAX_S, OBSERVATION_START_S, OBSERVATION_END_S, SCOPE_ID, JOB, REVIEW
    job, review = verify_authorization()
    TMAX = float(job["window"]["target_end_s"])
    TOUT = float(job["window"]["requested_output_interval_s"])
    EXPECTED_FRAMES = int(job["window"]["expected_frames"])
    MAX_GAP_S = float(job["window"]["max_gap_s"])
    TERMINAL_TARGET_S = float(job["window"]["terminal_target_s"])
    TERMINAL_OVERSHOOT_MAX_S = float(job["window"]["terminal_overshoot_max_s"])
    OBSERVATION_START_S = float(job["window"]["observation_window_s"][0])
    OBSERVATION_END_S = float(job["window"]["observation_window_s"][1])
    SCOPE_ID = str(job["scope_id"])
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"one-shot solver output is not fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "job.json", job)
    write_json(output / "root-review.json", review)
    contract_path = resolve_ref(job["inputs"]["definition_contract"], "Definition contract")
    contract = load(contract_path)
    generated_xml = resolve_ref(job["inputs"]["generated_xml"], "generated XML")
    groups = read_groups(generated_xml)
    prefix = resolve_ref(job["inputs"]["generated_xml"], "generated XML").with_suffix("")
    solver_dir = output / "solver"
    solver_dir.mkdir()
    binary = resolve_ref(job["solver"]["binary"], "solver binary")
    command = [str(binary), f"-tmax:{TMAX:g}", f"-tout:{TOUT:g}", str(prefix), str(solver_dir)]
    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = ""
    environment["LD_LIBRARY_PATH"] = str(binary.parent) + os.pathsep + environment.get("LD_LIBRARY_PATH", "")
    environment["OMP_NUM_THREADS"] = str(job["solver"].get("threads", 32))
    environment["OPENBLAS_NUM_THREADS"] = "1"
    environment["MKL_NUM_THREADS"] = "1"
    started = time.time()
    solver_log = output / "solver.stdout.log"
    return_code: int | None = None
    error: str | None = None
    solver_invoked = False
    try:
        solver_invoked = True
        with solver_log.open("w", encoding="utf-8") as stream:
            process = subprocess.run(command, cwd=prefix.parent, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False, timeout=int(job["solver"].get("timeout_seconds", 3600)))
        return_code = int(process.returncode)
    except Exception as exc:
        error = repr(exc)
    finished = time.time()
    run = run_summary(solver_dir / "Run.out")
    frames = []
    if (solver_dir / "data").is_dir():
        frames = sorted(
            (path for path in solver_dir.joinpath("data").glob("Part_*.bi4")
             if re.fullmatch(r"Part_(\d+)\.bi4", path.name)),
            key=lambda path: int(re.fullmatch(r"Part_(\d+)\.bi4", path.name).group(1)),
        )
    frame_indices = [int(match.group(1)) for path in frames if (match := re.fullmatch(r"Part_(\d+)\.bi4", path.name))]
    frame_audits: list[dict[str, Any]] = []
    native_times: list[float] = []
    native_identity: np.ndarray | None = None
    with tempfile.TemporaryDirectory(prefix="f6-v10-canary-native-") as temp_dir:
        for index, path in enumerate(frames):
            stem = Path(temp_dir) / f"frame-{index:04d}"
            try:
                ids, positions, velocities, density, metadata, info, _ = native_frame(path, stem, DECODER)
                finite = bool(np.isfinite(ids).all() and np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all())
                unique = len(np.unique(ids)) == len(ids)
                if native_identity is None:
                    native_identity = ids.copy()
                same_identity = bool(np.array_equal(native_identity, ids))
                body_mask = mask_range(ids, groups["floating"])
                fluid_mask = mask_range(ids, groups["fluid"])
                body_positions = positions[body_mask]
                fluid_positions = positions[fluid_mask]
                mass_per_particle = float(metadata.get("MassFluid", "nan"))
                frame_audits.append({
                    "index": frame_indices[index],
                    "time_s": float(info.get("TimeStep", "nan")),
                    "particle_count": int(len(ids)),
                    "fluid_count": int(fluid_mask.sum()),
                    "body_count": int(body_mask.sum()),
                    "finite": finite,
                    "ids_unique": unique,
                    "same_identity": same_identity,
                    "body_min_m": body_positions.min(axis=0).tolist() if len(body_positions) else [float("nan")] * 3,
                    "body_max_m": body_positions.max(axis=0).tolist() if len(body_positions) else [float("nan")] * 3,
                    "fluid_outside_top_count": int(np.sum(fluid_positions[:, 2] > contract["tank"]["high_m"][2] + GEOMETRY_TOLERANCE_M)) if len(fluid_positions) else -1,
                    "mass_per_particle_kg": mass_per_particle,
                })
                native_times.append(float(info.get("TimeStep", "nan")))
            except Exception as exc:
                frame_audits.append({"index": frame_indices[index], "time_s": float("nan"), "particle_count": 0, "fluid_count": 0, "body_count": 0, "finite": False, "ids_unique": False, "same_identity": False, "error": repr(exc), "body_min_m": [float("nan")] * 3, "body_max_m": [float("nan")] * 3, "fluid_outside_top_count": -1, "mass_per_particle_kg": float("nan")})
                native_times.append(float("nan"))
    floating_csv: Path | None = None
    floating_log = output / "floating-info.stdout.log"
    floating_error: str | None = None
    if solver_dir.joinpath("data/PartFloatInfo.ibi4").is_file():
        float_binary = resolve_ref(job["floating_info"], "FloatingInfo binary")
        try:
            command_float = [str(float_binary), "-dirdata", str(solver_dir / "data"), "-savedata", str(output / "floating-info"), "-csvsep:1"]
            with floating_log.open("w", encoding="utf-8") as stream:
                process_float = subprocess.run(command_float, cwd=output, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False, timeout=600)
            candidates = sorted(output.glob("floating-info_mk*.csv"))
            if process_float.returncode == 0 and candidates:
                floating_csv = candidates[0]
            else:
                floating_error = f"FloatingInfo return code {process_float.returncode}; candidates={len(candidates)}"
        except Exception as exc:
            floating_error = repr(exc)
    sidecar: dict[str, Any] | None = None
    sidecar_checks: dict[str, Any] = {}
    if floating_csv is not None:
        try:
            rows = parse_floating_csv(floating_csv)
            sidecar, sidecar_checks = make_sidecar(rows, frame_audits, contract, output)
            write_json(output / "body-state-force-torque-sidecar.json", sidecar)
        except Exception as exc:
            floating_error = f"sidecar construction failed: {exc!r}"
    native_checks = {
        "frame_count_exact": len(frames) == EXPECTED_FRAMES and frame_indices == list(range(EXPECTED_FRAMES)),
        "run_reported_frame_count_exact": run.get("reported_part_files") == EXPECTED_FRAMES,
        "native_time_count_exact": len(native_times) == EXPECTED_FRAMES,
        "native_time_gap_bound": bool(len(native_times) == EXPECTED_FRAMES and np.isfinite(np.diff(native_times)).all() and float(np.max(np.diff(native_times))) <= MAX_GAP_S),
        "native_terminal_bracket": bool(native_times and TERMINAL_TARGET_S <= native_times[-1] <= TERMINAL_TARGET_S + TERMINAL_OVERSHOOT_MAX_S),
        "native_observation_hold_bracketed": bool(native_times and native_times[0] <= OBSERVATION_START_S <= native_times[-1] and native_times[-1] >= OBSERVATION_END_S),
        "native_arrays_finite": bool(frame_audits) and all(item.get("finite") for item in frame_audits),
        "native_ids_unique": bool(frame_audits) and all(item.get("ids_unique") for item in frame_audits),
        "native_identity_fixed": bool(frame_audits) and all(item.get("same_identity") for item in frame_audits),
        "fluid_group_count_fixed": bool(frame_audits) and all(item.get("fluid_count") == groups["fluid"]["count"] for item in frame_audits),
        "body_group_count_fixed": bool(frame_audits) and all(item.get("body_count") == groups["floating"]["count"] for item in frame_audits),
        "no_fluid_outside_open_top": bool(frame_audits) and all(item.get("fluid_outside_top_count") == 0 for item in frame_audits),
    }
    hard_gates = {
        "solver_return_code_zero": return_code == 0 and error is None,
        "run_finished_code_zero": run["finished_code_zero"],
        "timemax_matches": run["timemax_s"] is not None and math.isclose(run["timemax_s"], TMAX, rel_tol=0.0, abs_tol=1.0e-9),
        "timeout_matches": run["timeout_s"] is not None and math.isclose(run["timeout_s"], TOUT, rel_tol=0.0, abs_tol=1.0e-9),
        "excluded_particles_zero": run["excluded_particles"] == 0,
        **native_checks,
        "floating_info_present": floating_csv is not None,
        "sidecar_present": sidecar is not None,
        **{f"sidecar_{key}": bool(value) for key, value in sidecar_checks.items()},
    }
    status = "solver_completed_sidecar_pass_pending_scientific_review" if all(hard_gates.values()) else "solver_completed_hard_failure" if solver_invoked else "solver_not_started_hard_failure"
    receipt = {
        "schema": "core.f6.observation_axis.protected_solver_canary_receipt.v1",
        "receipt_id": f"{job['job_id']}_receipt",
        "created_at_utc": stamp(),
        "status": status,
        "family": "F6",
        "scope_id": job["scope_id"],
        "revision_id": job.get("revision_id"),
        "cell_id": job.get("cell_id"),
        "case_id": job.get("case_id", job["cell_id"]),
        "attempt": 1,
        "root_review": ref(REVIEW, "root authorization"),
        "job": ref(JOB, "root-authorized canary job"),
        "runtime_worker": ref(RUNTIME_SCRIPT, "single-use canary worker"),
        "command": command,
        "environment": {"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": environment["OMP_NUM_THREADS"]},
        "started_at_unix": started,
        "finished_at_unix": finished,
        "returncode": return_code,
        "error": error,
        "run": run,
        "frames": {"count": len(frames), "indices_first": frame_indices[:3], "indices_last": frame_indices[-3:]},
        "native_frame_audit": ref(output / "native-frame-audit.json", "per-frame native audit") if frame_audits else None,
        "floating_info_csv": ref(floating_csv, "FloatingInfo body state/force output") if floating_csv is not None else None,
        "sidecar": ref(output / "body-state-force-torque-sidecar.json", "runtime body-state/force/torque sidecar") if sidecar is not None else None,
        "hard_gates": hard_gates,
        "sidecar_checks": sidecar_checks,
        "time_axis_contract": {
            "native_time_axis": "solver_reported_actual_TimeStep",
            "requested_output_interval_s": TOUT,
            "max_gap_s": MAX_GAP_S,
            "terminal_target_s": TERMINAL_TARGET_S,
            "terminal_overshoot_max_s": TERMINAL_OVERSHOOT_MAX_S,
            "observation_window_s": [OBSERVATION_START_S, OBSERVATION_END_S],
            "equilibrium_status": "not_claimed",
        },
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "qualification_only": True,
        "execution_controls": {"solver_invoked": solver_invoked, "gpu_started": False, "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0, "matrix_submission": False, "qualification_credit": 0},
        "failure_policy": "retain this exact-one receipt; no same-input retry, resume, matrix expansion or scientific credit",
    }
    write_json(output / "native-frame-audit.json", {"schema": "core.f6.physical_anchor.native_frame_audit.v1", "groups": groups, "frames": frame_audits, "native_times_s": native_times, "checks": native_checks})
    write_json(output / "execution-receipt.json", receipt)
    write_json(output / "worker-status.json", {"status": status, "finished_at_utc": stamp(), "hard_gate_pass": all(hard_gates.values())})
    return receipt


def main(argv: list[str] | None = None) -> int:
    global JOB, REVIEW
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, default=JOB)
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    JOB = args.job.resolve()
    REVIEW = args.review.resolve()
    receipt = run(args.output)
    print(json.dumps({"status": receipt["status"], "frames": receipt["frames"]["count"], "qualification_credit": 0, "output": str(args.output.resolve())}, indent=2, ensure_ascii=False))
    return 0 if receipt["status"] == "solver_completed_sidecar_pass_pending_scientific_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
