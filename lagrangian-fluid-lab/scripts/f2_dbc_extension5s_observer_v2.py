#!/usr/bin/env python3
"""Independent read-only observer diagnostic for the F2 DBC extension.

The original dynamic observer shrinks the moving cup by one ``dp`` in every
direction.  That is appropriate for an inset liquid box, but the F2 side-wet
initial condition deliberately samples a continuum box that reaches the
physical cup faces.  This module re-audits the completed trajectory with the
physical cup interior for cup classification only.  It does not alter the
stored audit, hard gates, thresholds, or solver result and it never writes to
the trajectory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_f2_qualification as f2q


SCHEMA = "core.f2.dbc_duration.observer_reaudit.v2"
OBSERVER_REVISION = "F2_geometry_aware_observer_v2_full_cup_physical_cup_contract"
OUTPUT_INTERVAL_S = 0.01
RECEIVER_CONTACT_FRACTION = 0.01
SPILL_FRACTION = 0.01
SETTLE_SPEED_M_S = 0.10
SETTLE_KE_FRACTION = 0.05
SETTLE_HOLD_S = 0.20
POST_SETTLE_OBSERVATION_S = 0.35


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _initial_native_box(config: dict[str, Any]) -> dict[str, Any]:
    boxes = config.get("fluid_boxes", [])
    if len(boxes) != 1:
        raise ValueError("v2 full-cup observer expects one continuous fluid box")
    box = boxes[0]
    low = np.asarray(box["low"], dtype=float)
    high = low + np.asarray(box["size"], dtype=float)
    return {"low": low.tolist(), "high": high.tolist(), "source": "config fluid_boxes physical continuum faces"}


def _inside(points: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    return np.all((points >= low) & (points <= high), axis=1)


def _summarize(trajectory: Path, prepared: Path, original_observations: dict[str, Any]) -> dict[str, Any]:
    prepared_data = json.loads(prepared.read_text())
    config = prepared_data["config"]
    cup = config["cup"]
    receiver = config["receiver"]
    tray = config["tray"]
    dp = float(config["dp_m"])
    physical_cup = _initial_native_box(config)
    cup_low = np.asarray(cup["low"], dtype=float)
    cup_high = cup_low + np.asarray(cup["size"], dtype=float)
    receiver_low = np.asarray(receiver["low"], dtype=float) + dp
    receiver_high = receiver_low + np.asarray(receiver["size"], dtype=float) - 2.0 * dp
    tray_low = np.asarray(tray["low"], dtype=float) + dp
    tray_high = np.asarray(tray["low"], dtype=float) + np.asarray(tray["size"], dtype=float) - np.asarray([dp, dp, 0.0])
    duration_s = float(config["parameter"]["value"])
    motion_complete_s = f2q.MOTION_START_S + duration_s
    with h5py.File(trajectory, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        masses = np.asarray(handle["mass"][0], dtype=float)
        initial = valid[0] & np.isfinite(positions[0]).all(axis=1)
        initial_mass = float(masses[initial].sum())
        initial_position = positions[0, initial]
        initial_potential = float(np.sum(masses[initial] * 9.81 * (initial_position[:, 2] - float(cup["low"][2]))))
        cup_fraction, receiver_fraction, tray_fraction, outside_fraction = [], [], [], []
        kinetic_fraction, speed_p95 = [], []
        for index, time_s in enumerate(times):
            active = initial & valid[index] & np.isfinite(positions[index]).all(axis=1) & np.isfinite(velocities[index]).all(axis=1)
            point = positions[index]
            speed = np.linalg.norm(velocities[index], axis=1)
            body = f2q.body_positions(point, f2q.cup_world_from_body(f2q.motion_angle(float(time_s), duration_s)))
            cup_mask = active & _inside(body, cup_low, cup_high)
            receiver_mask = active & _inside(point, receiver_low, receiver_high)
            tray_mask = active & _inside(point, tray_low, tray_high)
            classified = cup_mask | receiver_mask | tray_mask
            cup_fraction.append(float(masses[cup_mask].sum() / max(initial_mass, 1e-30)))
            receiver_fraction.append(float(masses[receiver_mask].sum() / max(initial_mass, 1e-30)))
            tray_fraction.append(float(masses[tray_mask].sum() / max(initial_mass, 1e-30)))
            outside_fraction.append(float(masses[active & ~classified].sum() / max(initial_mass, 1e-30)))
            active_speed = speed[active]
            speed_p95.append(float(np.quantile(active_speed, 0.95)) if len(active_speed) else float("nan"))
            kinetic_fraction.append(float(np.sum(0.5 * masses[active] * active_speed ** 2) / max(initial_potential, 1e-30)))

    cup_fraction = np.asarray(cup_fraction)
    receiver_fraction = np.asarray(receiver_fraction)
    tray_fraction = np.asarray(tray_fraction)
    outside_fraction = np.asarray(outside_fraction)
    kinetic_fraction = np.asarray(kinetic_fraction)
    speed_p95 = np.asarray(speed_p95)
    receiver_indices = np.flatnonzero(receiver_fraction >= RECEIVER_CONTACT_FRACTION)
    spill_indices = np.flatnonzero(outside_fraction >= SPILL_FRACTION)
    settle_candidate = (times >= motion_complete_s) & (kinetic_fraction <= SETTLE_KE_FRACTION) & (speed_p95 <= SETTLE_SPEED_M_S)
    settle_index = None
    if len(times) > 1:
        needed = max(1, int(np.ceil(SETTLE_HOLD_S / max(np.median(np.diff(times)), 1e-12))))
        for index in np.flatnonzero(settle_candidate):
            if index + needed <= len(times) and bool(np.all(settle_candidate[index:index + needed])):
                settle_index = int(index)
                break
    last_required = max(
        motion_complete_s,
        float(times[receiver_indices[0]]) if len(receiver_indices) else -np.inf,
        float(times[settle_index]) if settle_index is not None else -np.inf,
    )
    complete = bool(
        len(receiver_indices) and settle_index is not None
        and times[-1] >= last_required + POST_SETTLE_OBSERVATION_S
        and times[-1] >= float(config["time_max_s"]) - 1e-6
    )
    original_outside = np.asarray(original_observations["outside_observation_mass_fraction"], dtype=float)
    original_cup = np.asarray(original_observations["cup_mass_fraction"], dtype=float)
    return {
        "schema": SCHEMA,
        "observer_revision": OBSERVER_REVISION,
        "case_id": config["case_id"],
        "contract_change": {
            "cup_classification_before": "moving body-frame box shrunk by +dp/-dp",
            "cup_classification_after": "physical cup interior faces from config, no artificial one-dp shrink",
            "receiver_and_tray_classification": "unchanged one-dp-clear observer boxes",
            "numeric_thresholds_changed": False,
            "hard_audit_changed": False,
        },
        "physical_cup_contract": physical_cup,
        "initial_frame_counterexample": {
            "original_cup_fraction": float(original_cup[0]),
            "original_outside_fraction": float(original_outside[0]),
            "revised_cup_fraction": float(cup_fraction[0]),
            "revised_outside_fraction": float(outside_fraction[0]),
            "original_spill_threshold_crossed_at_t0": bool(original_outside[0] >= SPILL_FRACTION),
            "revised_spill_threshold_crossed_at_t0": bool(outside_fraction[0] >= SPILL_FRACTION),
            "interpretation": "the original t=0 spill event is an observation-volume classification artifact for the side-wet initial layer",
        },
        "revised_event_times_s": {
            "motion_complete": motion_complete_s,
            "receiver_contact": float(times[receiver_indices[0]]) if len(receiver_indices) else None,
            "spill_or_escape": float(times[spill_indices[0]]) if len(spill_indices) else None,
            "settled": float(times[settle_index]) if settle_index is not None else None,
            "event_window_complete": float(times[-1]) if complete else None,
        },
        "revised_tail": {
            "last_time_s": float(times[-1]),
            "last_cup_mass_fraction": float(cup_fraction[-1]),
            "last_receiver_mass_fraction": float(receiver_fraction[-1]),
            "last_tray_mass_fraction": float(tray_fraction[-1]),
            "last_outside_mass_fraction": float(outside_fraction[-1]),
            "max_kinetic_fraction_after_motion": float(kinetic_fraction[times >= motion_complete_s].max()),
            "min_kinetic_fraction_after_motion": float(kinetic_fraction[times >= motion_complete_s].min()),
            "min_speed_p95_after_motion_m_s": float(speed_p95[times >= motion_complete_s].min()),
            "max_speed_p95_after_motion_m_s": float(speed_p95[times >= motion_complete_s].max()),
            "settled_candidate_frame_count": int(np.sum(settle_candidate)),
        },
        "original_observer_reference": {
            "observer_revision": original_observations.get("observer_revision"),
            "event_times_s": original_observations.get("event_times_s"),
            "event_window_complete": original_observations.get("event_window_complete"),
        },
        "qualification_effect": {
            "hard_integrity_pass_inherited": True,
            "event_window_complete": False,
            "canary_qualification_claim": "none",
            "matrix_launch": "not authorized by this diagnostic; root must review the independent observer version",
        },
    }


def reaudit(prepared: Path, product: Path, output: Path) -> dict[str, Any]:
    prepared, product, output = Path(prepared).resolve(), Path(product).resolve(), Path(output).resolve()
    trajectory = product / "trajectory.h5"
    observations_path = product / "observations.json"
    audit_path = product / "audit.json"
    if not trajectory.is_file() or (product / "trajectory.h5.partial").exists():
        raise RuntimeError("trajectory is missing or still partial; refuse observer re-audit")
    if not observations_path.is_file() or not audit_path.is_file():
        raise RuntimeError("original JSON evidence is incomplete")
    original_observations = json.loads(observations_path.read_text())
    original_audit = json.loads(audit_path.read_text())
    report = _summarize(trajectory, prepared, original_observations)
    report.update({
        "created_at": _stamp(),
        "prepared": {"path": str(prepared), "sha256": _sha256(prepared)},
        "product": str(product),
        "trajectory_sha256": _sha256(trajectory),
        "original_audit_sha256": _sha256(audit_path),
        "original_observations_sha256": _sha256(observations_path),
        "original_hard_integrity_pass": bool(original_audit.get("hard_integrity_pass")),
        "reaudit_code": {"path": str(Path(__file__).resolve()), "sha256": _sha256(Path(__file__).resolve())},
        "trajectory_opened_read_only": True,
        "solver_rerun": False,
        "qualification_claim": "none; independent observer diagnostic only",
    })
    _write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = reaudit(args.prepared, args.product, args.output)
    print(json.dumps({
        "observer_revision": report["observer_revision"],
        "original_spill_t0": report["initial_frame_counterexample"]["original_spill_threshold_crossed_at_t0"],
        "revised_spill_t0": report["initial_frame_counterexample"]["revised_spill_threshold_crossed_at_t0"],
        "revised_settled": report["revised_event_times_s"]["settled"],
        "revised_event_window_complete": report["revised_event_times_s"]["event_window_complete"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
