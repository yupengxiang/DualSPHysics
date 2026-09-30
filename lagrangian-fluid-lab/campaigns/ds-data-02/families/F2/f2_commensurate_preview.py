#!/usr/bin/env python3
"""Create an evidence-bound F2 native preview manifest.

The output is a list of real HDF5 frame references and actual rigid-body pose
samples.  It is intentionally a preview manifest rather than a qualification
or production decision.  No particles are synthesized and no prescribed
motion is substituted for the saved Type=1 moving-node pose.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import h5py
import numpy as np


class PreviewError(RuntimeError):
    """Raised when preview evidence is incomplete or unbound."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PreviewError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PreviewError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise PreviewError(f"{label} must be an object: {path}")
    return value


def binding(path: Path) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise PreviewError(f"preview input is missing: {path}")
    return {"path": str(path), "sha256": sha256(path)}


def _motion_phases(path: Path) -> dict[str, float]:
    times: list[float] = []
    angles: list[float] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split(";", 1)
        if len(fields) != 2:
            raise PreviewError(f"motion row has no time/angle pair: {path}")
        times.append(float(fields[0]))
        angles.append(float(fields[1]))
    if len(times) < 2 or not np.all(np.diff(times) > 0):
        raise PreviewError(f"motion control has no strictly increasing time axis: {path}")
    angle_array = np.asarray(angles, dtype=np.float64)
    time_array = np.asarray(times, dtype=np.float64)
    start_candidates = np.flatnonzero(np.abs(angle_array - angle_array[0]) > 1e-9)
    start_index = int(start_candidates[0]) if len(start_candidates) else 0
    # The prescribed table keeps the initial angle through the control sample
    # at the hold endpoint and changes on the next 5 ms row.  The phase
    # boundary is therefore the last unchanged sample, not the first changed
    # row.
    hold_index = max(0, start_index - 1)
    final_angle = float(angle_array[-1])
    stop_candidates = np.flatnonzero((np.arange(len(angle_array)) >= start_index) & (np.abs(angle_array - final_angle) <= 1e-9))
    stop_index = int(stop_candidates[0]) if len(stop_candidates) else len(time_array) - 1
    return {
        "static_hold_end_s": float(time_array[hold_index]),
        "rotation_start_s": float(time_array[hold_index]),
        "rotation_stop_s": float(time_array[stop_index]),
        "event_window_end_s": float(time_array[-1]),
        "prescribed_angle_start_deg": float(angle_array[0]),
        "prescribed_angle_end_deg": final_angle,
    }


def _event_time(labels_report: Mapping[str, Any], *names: str) -> float | None:
    ledger = labels_report.get("event_ledger", {})
    first = ledger.get("first_time_s_by_code", {}) if isinstance(ledger, Mapping) else {}
    values = [first.get(name) for name in names if isinstance(first, Mapping) and first.get(name) is not None]
    return min((float(value) for value in values), default=None)


def _frame_ref(index: int, times: np.ndarray, rigid: np.ndarray) -> dict[str, Any]:
    row = rigid[index]
    finite_fields = ("actual_angle_rad", "actual_omega_rad_s", "actual_com_x_m", "actual_com_y_m", "actual_com_z_m",
                     "position_rms_m", "position_max_m", "velocity_rms_m_s", "velocity_max_m_s")
    if any(field not in rigid.dtype.names for field in finite_fields):
        raise PreviewError("rigid_body_state lacks actual pose/velocity fields")
    return {
        "frame_index": int(index),
        "time_s": float(times[index]),
        "actual_pose_valid": bool(row["valid"]),
        "actual_angle_rad": float(row["actual_angle_rad"]),
        "actual_omega_rad_s": float(row["actual_omega_rad_s"]),
        "actual_com_m": [float(row[name]) for name in ("actual_com_x_m", "actual_com_y_m", "actual_com_z_m")],
        "pose_position_rms_m": float(row["position_rms_m"]),
        "pose_position_max_m": float(row["position_max_m"]),
        "pose_velocity_rms_m_s": float(row["velocity_rms_m_s"]),
        "pose_velocity_max_m_s": float(row["velocity_max_m_s"]),
        "moving_node_count": int(row["moving_node_count"]),
        "expected_node_count": int(row["expected_node_count"]),
    }


def build_preview(*, trajectory: Path, labels: Path, labels_report_path: Path, qi_report_path: Path,
                  owner_metadata: Path, conversion_report: Path, motion: Path,
                  event_definitions: Path, quality_contract: Path, output: Path) -> dict[str, Any]:
    owner = load_json(owner_metadata, "owner metadata")
    labels_report = load_json(labels_report_path, "native labels report")
    qi_report = load_json(qi_report_path, "full Q-I report")
    events = load_json(event_definitions, "event definitions")
    quality = load_json(quality_contract, "quality contract")
    case_id = str(owner.get("case_id", ""))
    if owner.get("family_id") != "F2" or not case_id.startswith("F2_COMM4_"):
        raise PreviewError("preview requires a V4 F2 owner metadata record")
    for supplied_case, label in ((labels_report.get("case_id"), "labels report"), (qi_report.get("case_id"), "Q-I report")):
        if supplied_case != case_id:
            raise PreviewError(f"{label} case id does not match owner metadata: {supplied_case} != {case_id}")
    if labels_report.get("qualification_claim") not in {"none", None} or qi_report.get("production_eligibility") not in {"not_evaluated", None}:
        raise PreviewError("preview input carries an unexpected qualification or production claim")
    if not labels.is_file() or not trajectory.is_file():
        raise PreviewError("trajectory and native label HDF5 inputs are required")
    phases = _motion_phases(motion)
    background = str(owner.get("background"))
    event_contract = events.get("backgrounds", {}).get(background)
    quality_contract = quality.get("background_contracts", {}).get(background)
    if not isinstance(event_contract, Mapping) or not isinstance(quality_contract, Mapping):
        raise PreviewError(f"no frozen event/quality contract for background {background}")
    label_trajectory_binding = labels_report.get("trajectory", {})
    if label_trajectory_binding.get("sha256") and label_trajectory_binding["sha256"] != sha256(trajectory):
        raise PreviewError("native labels report is bound to a different trajectory HDF5")

    with h5py.File(trajectory, "r") as state, h5py.File(labels, "r") as native_labels:
        required_state = {"time", "position", "velocity", "density", "mass", "type", "mk", "valid",
                          "particle_zone", "particle_id", "rigid_body_state"}
        missing_state = sorted(required_state - set(state.keys()))
        if missing_state:
            raise PreviewError(f"full-state HDF5 is missing typed datasets: {missing_state}")
        if native_labels.attrs.get("trajectory_sha256") not in {None, sha256(trajectory)}:
            raise PreviewError("native label HDF5 trajectory hash does not match full-state HDF5")
        times = np.asarray(state["time"][:], dtype=np.float64)
        positions_shape = state["position"].shape
        velocities_shape = state["velocity"].shape
        if len(times) < 2 or not np.all(np.isfinite(times)) or not np.all(np.diff(times) > 0):
            raise PreviewError("trajectory time axis is not finite and strictly increasing")
        if len(positions_shape) != 3 or positions_shape[-1] != 3 or velocities_shape != positions_shape:
            raise PreviewError("trajectory does not contain full 3D position and velocity arrays")
        rigid = state["rigid_body_state"][:]
        if len(rigid) != len(times):
            raise PreviewError("actual rigid-body state does not cover every trajectory frame")
        pose_valid = np.asarray(rigid["valid"], dtype=bool)
        finite_pose = np.ones(len(rigid), dtype=bool)
        for field in ("actual_angle_rad", "actual_omega_rad_s", "actual_com_x_m", "actual_com_y_m", "actual_com_z_m",
                      "position_rms_m", "position_max_m", "velocity_rms_m_s", "velocity_max_m_s"):
            finite_pose &= np.isfinite(rigid[field])
        moving_nodes = np.asarray(rigid["moving_node_count"], dtype=np.int64)
        actual_pose_complete = bool(np.all(pose_valid & finite_pose & (moving_nodes > 0)))
        phase_targets: dict[str, float | None] = {
            "static_hold_start": float(times[0]),
            "static_hold_end": phases["static_hold_end_s"],
            "first_cup_mouth_departure": _event_time(labels_report, "cup_departure"),
            "first_receiver_or_tray_entry": _event_time(labels_report, "receiver_entry", "tray_entry"),
            "rotation_stop": phases["rotation_stop_s"],
            "post_stop_residence_end": min(phases["event_window_end_s"], float(times[-1])),
        }
        frame_references: list[dict[str, Any]] = []
        seen_frames: set[int] = set()
        for name, target in phase_targets.items():
            if target is None:
                frame_references.append({"phase": name, "observed": False, "frame_index": None, "time_s": None})
                continue
            index = int(np.argmin(np.abs(times - target)))
            ref = _frame_ref(index, times, rigid)
            ref.update({"phase": name, "observed": True, "target_time_s": float(target),
                        "target_frame_time_error_s": float(abs(times[index] - target))})
            frame_references.append(ref)
            seen_frames.add(index)
        event_ledger = labels_report.get("event_ledger", {})
        physical_walls = qi_report.get("events", {}).get("physical_walls", [])
        open_boundary_faces = qi_report.get("events", {}).get("open_boundary_faces", [])
        preview = {
            "schema": "ds-data-02.f2-native-preview-manifest.v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "family_id": "F2",
            "case_id": case_id,
            "scope_id": owner.get("scope_id"),
            "background": background,
            "resolution": owner.get("resolution"),
            "physical_condition_hash": labels_report.get("physical_condition_hash"),
            "numerical_recipe_hash": labels_report.get("numerical_recipe_hash"),
            "qualification_claim": "none",
            "production_claim": "none",
            "evidence_only": True,
            "sources": {
                "trajectory": binding(trajectory),
                "native_labels": binding(labels),
                "native_labels_report": binding(labels_report_path),
                "qi_report": binding(qi_report_path),
                "owner_metadata": binding(owner_metadata),
                "conversion_report": binding(conversion_report),
                "motion": binding(motion),
                "event_definitions": binding(event_definitions),
                "quality_contract": binding(quality_contract),
            },
            "actual_state": {
                "solver_dimension": int(state.attrs.get("solver_dimension", -1)),
                "coordinate_components": int(positions_shape[-1]),
                "frames": int(len(times)),
                "particles": int(positions_shape[1]),
                "time_start_s": float(times[0]),
                "time_end_s": float(times[-1]),
                "actual_rigid_body_dataset": "rigid_body_state",
                "actual_pose_complete": actual_pose_complete,
                "actual_pose_valid_frames": int(np.count_nonzero(pose_valid & finite_pose)),
                "moving_node_count_min": int(moving_nodes.min()),
                "moving_node_count_max": int(moving_nodes.max()),
                "control_sha256": str(state["rigid_body_state"].attrs.get("control_reference_sha256", "")),
            },
            "frozen_phase_contract": {
                "event_window_s": float(event_contract.get("event_window_s", phases["event_window_end_s"])),
                "common_event_order": events.get("common_event_order", []),
                "motion_phases": phases,
                "quality_thresholds": quality_contract.get("event_thresholds", {}),
            },
            "finite_surface_transport": {
                "finite_region_geometry": labels_report.get("geometry_evidence", {}).get("finite_3d_boxes"),
                "physical_walls": physical_walls,
                "open_boundary_faces": open_boundary_faces,
                "event_ledger_status": event_ledger.get("status"),
                "unknown_is_separate_from_spill_or_tray": bool(event_ledger.get("unknown_is_separate_from_spill_or_tray", False)),
                "actual_pose_source": labels_report.get("geometry_evidence", {}).get("actual_rigid_body_dataset"),
            },
            "frame_references": frame_references,
            "animation": {
                "status": "ready_from_native_frame_references",
                "trajectory_h5": str(trajectory.resolve()),
                "frame_indices": sorted(seen_frames),
                "requires_native_particles": True,
                "requires_actual_rigid_pose": True,
                "synthetic_particle_generation": False,
            },
            "q_i_evidence": qi_report.get("q_i", {}),
            "q_n_evidence": qi_report.get("q_n", {"status": "not_assessed"}),
            "next_gate": "root reviews Q-I/Q-N and strict continuous-mass sidecar; this preview manifest grants no qualification or production status",
        }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return preview


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("trajectory", "labels", "labels-report", "qi-report", "owner-metadata", "conversion-report",
                 "motion", "event-definitions", "quality-contract", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        preview = build_preview(trajectory=args.trajectory.resolve(), labels=args.labels.resolve(),
                                labels_report_path=args.labels_report.resolve(), qi_report_path=args.qi_report.resolve(),
                                owner_metadata=args.owner_metadata.resolve(), conversion_report=args.conversion_report.resolve(),
                                motion=args.motion.resolve(), event_definitions=args.event_definitions.resolve(),
                                quality_contract=args.quality_contract.resolve(), output=args.output.resolve())
    except (PreviewError, OSError, ValueError, KeyError, json.JSONDecodeError, OSError) as error:
        print(f"f2_commensurate_preview: {error}")
        return 2
    print(json.dumps({"status": "preview_manifest_written", "path": str(args.output.resolve()),
                      "sha256": sha256(args.output.resolve()), "case_id": preview["case_id"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
