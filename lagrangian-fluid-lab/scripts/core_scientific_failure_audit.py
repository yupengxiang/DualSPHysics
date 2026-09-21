"""Independent scientific-failure overlay for finite rollout receipts.

This module is deliberately separate from ``core_evaluation``.  The registered
Core score defines numerical completion and fixed penalties for missing or
non-finite frames; it does not silently turn a physical wall event into an
execution failure.  This audit adds a pre-declared, failure-aware view for
review: the first finite saved-chord wall crossing, a closed-face endpoint
exit, or a finite state-explosion threshold censors that frame and all later
frames in the same fixed denominator.  It never edits the registered receipt
or changes model/reproduction tolerances.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from scripts.core_evaluation import score_case

SCHEMA = "core.scientific_failure_audit.v2"
POLICY = {
    "schema": "core.scientific_failure_policy.v2",
    "version": "vNext-candidate-only",
    "release_state": "candidate_only; no formal training or old reproduction gate",
    "wall_chord": {
        "source": "core_physics.static_wall_crossings saved-state chord",
        "diagnostic_tolerance_m": 1.0e-9,
        "threshold_status": "implementation diagnostic; not a registered scientific gate",
        "category": "finite_wall_penetration",
        "limitations": [
            "finite static triangles only",
            "saved-state chord, not the exact solver substep path",
            "moving surfaces return unsupported rather than pass",
        ],
    },
    "closed_face_endpoint": {
        "source": "finite_wall_audit.outside_closed_face_masks",
        "diagnostic_tolerance_m": 1.0e-9,
        "threshold_status": "caller diagnostic value; no F3 formal declaration",
        "category": "closed_face_domain_exit",
        "open_top": True,
        "limitations": [
            "registered finite face projection only",
            "runtime solver-domain AABB is not inferred",
        ],
    },
    "nonfinite": {
        "category": "nonfinite_state",
        "scope": "active saved position or native velocity",
    },
    "state_magnitude": {
        "status": "diagnostic_only",
        "category": None,
        "threshold": None,
        "basis": "no preregistered explosion threshold exists; report magnitudes only",
    },
    "precedence": [
        "nonfinite_state",
        "finite_wall_penetration",
        "closed_face_domain_exit",
    ],
    "denominator": "all registered future frames; first failure frame and all later frames receive frame_penalty=1",
}


def _finite_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _first(values: list[int]) -> int | None:
    return min(values) if values else None


def _failure_event(category: str, frame: int, detail: dict[str, Any]) -> dict[str, Any]:
    return {"category": category, "first_failure_frame": int(frame), **detail}


def _closed_face_endpoint_events(position: np.ndarray, valid: np.ndarray, *, bounds: dict[str, float], tolerance: float) -> dict[str, Any]:
    """Classify finite closed faces; the top is intentionally open for F3."""
    lower = np.asarray([bounds["xmin"], bounds["ymin"], bounds["zmin"]], dtype=np.float64)
    upper = np.asarray([bounds["xmax"], bounds["ymax"], bounds["zmax"]], dtype=np.float64)
    x = np.asarray(position, dtype=np.float64)
    active = np.asarray(valid, dtype=bool)
    if x.shape[0] != active.shape[0] or x.ndim != 2 or x.shape[1] != 3:
        raise ValueError("position/valid axes do not agree")
    # A finite face only counts an outward endpoint whose projection remains on
    # the registered rectangular face.  The open top is not classified.
    face_masks = {
        "left": (x[:, 0] < lower[0] - tolerance) & (x[:, 1] >= lower[1] - 1e-12) & (x[:, 1] <= upper[1] + 1e-12) & (x[:, 2] >= lower[2] - 1e-12) & (x[:, 2] <= upper[2] + 1e-12),
        "right": (x[:, 0] > upper[0] + tolerance) & (x[:, 1] >= lower[1] - 1e-12) & (x[:, 1] <= upper[1] + 1e-12) & (x[:, 2] >= lower[2] - 1e-12) & (x[:, 2] <= upper[2] + 1e-12),
        "front": (x[:, 1] < lower[1] - tolerance) & (x[:, 0] >= lower[0] - 1e-12) & (x[:, 0] <= upper[0] + 1e-12) & (x[:, 2] >= lower[2] - 1e-12) & (x[:, 2] <= upper[2] + 1e-12),
        "back": (x[:, 1] > upper[1] + tolerance) & (x[:, 0] >= lower[0] - 1e-12) & (x[:, 0] <= upper[0] + 1e-12) & (x[:, 2] >= lower[2] - 1e-12) & (x[:, 2] <= upper[2] + 1e-12),
        "bottom": (x[:, 2] < lower[2] - tolerance) & (x[:, 0] >= lower[0] - 1e-12) & (x[:, 0] <= upper[0] + 1e-12) & (x[:, 1] >= lower[1] - 1e-12) & (x[:, 1] <= upper[1] + 1e-12),
    }
    counts = {face: int(np.count_nonzero(mask & active)) for face, mask in face_masks.items()}
    union = np.zeros(len(x), dtype=bool)
    for mask in face_masks.values():
        union |= mask
    union &= active
    return {"count": int(union.sum()), "by_face": counts,
            "mass_indices": np.flatnonzero(union).astype(np.int64).tolist()[:32]}


def _load_receipt(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if not isinstance(value, dict):
        raise ValueError(f"receipt must be an object: {path}")
    return value


def audit_host(receipt_path: Path, trajectory_path: Path, *, bounds: dict[str, float], length_m: float, speed_mps: float, wall_tolerance_m: float = 1e-9) -> dict[str, Any]:
    receipt = _load_receipt(receipt_path)
    expected = int(receipt.get("score", {}).get("expected_frames", receipt.get("completed_transitions", 0)))
    if expected < 1:
        raise ValueError("receipt has no positive expected denominator")
    position_rmse = list(receipt.get("position_rmse", []))
    velocity_rmse = list(receipt.get("velocity_rmse", []))
    if len(position_rmse) != expected or len(velocity_rmse) != expected:
        raise ValueError("receipt frame arrays do not preserve expected denominator")
    physics = list(receipt.get("physics_frames", []))
    if len(physics) != expected:
        raise ValueError("receipt physics frame array does not preserve expected denominator")
    first_wall: int | None = None
    wall_counts: dict[int, int] = {}
    for index, row in enumerate(physics, start=1):
        wall = row.get("wall_chord", {}) if isinstance(row, dict) else {}
        count = wall.get("particle_count", 0) if isinstance(wall, dict) else 0
        if isinstance(count, (int, np.integer)) and int(count) > 0:
            wall_counts[index] = int(count)
            first_wall = index if first_wall is None else first_wall

    first_endpoint: int | None = None
    endpoint_by_frame: dict[int, dict[str, Any]] = {}
    first_nonfinite: int | None = None
    max_position_metric = 0.0
    max_speed_metric = 0.0
    with h5py.File(trajectory_path, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=np.float64)
        position = handle["position"]
        velocity = handle["velocity"]
        valid = handle["valid"]
        mass = np.asarray(handle["mass"][:], dtype=np.float64)
        if position.shape[0] != expected + 1 or velocity.shape != position.shape or valid.shape != (expected + 1, len(mass)):
            raise ValueError("trajectory shape does not match receipt denominator")
        initial = np.asarray(position[0], dtype=np.float64)
        initial_valid = np.asarray(valid[0], dtype=bool)
        if not np.isfinite(initial).all() or not initial_valid.all():
            raise ValueError("initial trajectory is not finite/complete")
        initial_com = np.sum(mass[:, None] * initial, axis=0) / np.sum(mass)
        for frame in range(1, expected + 1):
            p = np.asarray(position[frame], dtype=np.float64)
            v = np.asarray(velocity[frame], dtype=np.float64)
            active = np.asarray(valid[frame], dtype=bool)
            if not np.isfinite(p[active]).all() or not np.isfinite(v[active]).all():
                first_nonfinite = frame if first_nonfinite is None else first_nonfinite
            endpoint = _closed_face_endpoint_events(p, active, bounds=bounds, tolerance=wall_tolerance_m)
            if endpoint["count"]:
                endpoint_by_frame[frame] = endpoint
                first_endpoint = frame if first_endpoint is None else first_endpoint
            position_metric = float(np.max(np.linalg.norm(p[active] - initial_com, axis=1))) if active.any() else math.nan
            speed_metric = float(np.max(np.linalg.norm(v[active], axis=1))) if active.any() else math.nan
            max_position_metric = max(max_position_metric, position_metric)
            max_speed_metric = max(max_speed_metric, speed_metric)
    event_candidates = []
    if first_nonfinite is not None:
        event_candidates.append((first_nonfinite, 0, _failure_event("nonfinite_state", first_nonfinite, {})))
    if first_wall is not None:
        event_candidates.append((first_wall, 1, _failure_event("finite_wall_penetration", first_wall, {
            "wall_chord_particle_count": wall_counts[first_wall],
            "wall_event_frame_count": len(wall_counts),
            "wall_chord_particle_count_total": int(sum(wall_counts.values())),
            "wall_chord_last_frame": max(wall_counts),
        })))
    if first_endpoint is not None:
        event_candidates.append((first_endpoint, 2, _failure_event("closed_face_domain_exit", first_endpoint, {
            "endpoint_count": endpoint_by_frame[first_endpoint]["count"],
            "endpoint_by_face": endpoint_by_frame[first_endpoint]["by_face"],
            "open_top_excluded": True,
        })))
    selected = min(event_candidates, key=lambda item: (item[0], item[1]))[2] if event_candidates else None
    if selected is None:
        score = score_case(position_rmse, velocity_rmse, expected_frames=expected,
                           length_m=length_m, speed_mps=speed_mps,
                           executed=bool(receipt.get("score", {}).get("executed", True)))
    else:
        cutoff = max(0, int(selected["first_failure_frame"]) - 1)
        score = score_case(position_rmse[:cutoff], velocity_rmse[:cutoff], expected_frames=expected,
                           length_m=length_m, speed_mps=speed_mps,
                           executed=True, failure_category=selected["category"])
        score["censored_after_first_failure_frames"] = expected - cutoff
    raw_completed = int(receipt.get("completed_transitions", receipt.get("frames_executed", expected if receipt.get("status") == "complete" else 0)))
    raw_failure = receipt.get("failure_category")
    execution_complete = bool(raw_completed == expected and raw_failure is None and receipt.get("status") in (None, "complete"))
    finite_rollout_complete = bool(
        execution_complete
        and first_nonfinite is None
        and all(isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(float(value))
                for value in position_rmse + velocity_rmse)
    )
    scientific_status = "failed" if selected is not None else "not_assessed"
    return {
        "schema": SCHEMA, "host": receipt_path.parent.name,
        "receipt": {"path": str(receipt_path), "sha256": _finite_sha(receipt_path)},
        "trajectory": {"path": str(trajectory_path), "sha256": _finite_sha(trajectory_path)},
        "expected_frames": expected, "registered_scales": {"length_m": length_m, "speed_mps": speed_mps},
        "policy": POLICY,
        "execution_complete": execution_complete,
        "finite_rollout_complete": finite_rollout_complete,
        "failure_category": raw_failure,
        "first_failure_frame": receipt.get("first_failure_frame"),
        "scientific_status": scientific_status,
        "scientific_failure_category": selected.get("category") if selected else None,
        "scientific_first_failure_frame": selected.get("first_failure_frame") if selected else None,
        "events": {"selected": selected, "first_wall_frame": first_wall,
                    "first_endpoint_frame": first_endpoint, "first_nonfinite_frame": first_nonfinite,
                    "state_magnitude_threshold_applied": False,
                    "max_position_metric_m": max_position_metric, "max_speed_metric_mps": max_speed_metric},
        "failure_aware_score": score,
        "formal_receipt_semantics": {"status": receipt.get("status"), "failure_category": receipt.get("failure_category"),
                                      "first_failure_frame": receipt.get("first_failure_frame"),
                                      "score_complete": receipt.get("score", {}).get("complete"),
                                      "score_selection": receipt.get("score", {}).get("selection_score")},
    }


def compare_failure_aware(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    ls, rs = left["failure_aware_score"], right["failure_aware_score"]
    keys = ("selection_score", "raw_position_rmse_frame_mean_m", "raw_velocity_rmse_frame_mean_mps")
    differences = {key: abs(float(ls[key]) - float(rs[key])) for key in keys if ls.get(key) is not None and rs.get(key) is not None}
    def event_identity(row: dict[str, Any]) -> dict[str, Any] | None:
        event = row["events"].get("selected")
        if event is None:
            return None
        # Later wall counts are useful diagnostics but are allowed to diverge
        # after the first failure.  Identity is the registered scientific
        # comparison point: category, first frame, and first-frame evidence.
        return {
            "category": event.get("category"),
            "first_failure_frame": event.get("first_failure_frame"),
            "wall_chord_particle_count": event.get("wall_chord_particle_count"),
            "endpoint_count": event.get("endpoint_count"),
        }
    left_identity, right_identity = event_identity(left), event_identity(right)
    return {"schema": "core.scientific_failure_aware_comparison.v2",
            "failure_event_identity_equal": left_identity == right_identity,
            "left_failure_event_identity": left_identity,
            "right_failure_event_identity": right_identity,
            "scientific_status_equal": left.get("scientific_status") == right.get("scientific_status"),
            "left_scientific_status": left.get("scientific_status"),
            "right_scientific_status": right.get("scientific_status"),
            "failure_aware_score_differences": differences,
            "score_atol": 1.0e-4,
            "score_within_registered_comparison_atol": all(value <= 1.0e-4 for value in differences.values()),
            "scientific_success": False,
            "scientific_success_reason": "finite full-horizon execution has a finite saved-chord wall penetration; this overlay censors after its first frame",
            "full_trajectory_reproduction": False,
            "full_trajectory_reproduction_reason": "original full H5 comparator remains the authoritative reproduction result and remains failed",
            "left_event": left["events"]["selected"], "right_event": right["events"]["selected"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left-receipt", type=Path, required=True)
    parser.add_argument("--left-trajectory", type=Path, required=True)
    parser.add_argument("--right-receipt", type=Path, required=True)
    parser.add_argument("--right-trajectory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    bounds = {"xmin": -0.45, "xmax": 0.45, "ymin": -0.09, "ymax": 0.09, "zmin": 0.0, "zmax": 0.51}
    rows = [audit_host(args.left_receipt.resolve(), args.left_trajectory.resolve(), bounds=bounds, length_m=0.9, speed_mps=2.9713633234594523),
            audit_host(args.right_receipt.resolve(), args.right_trajectory.resolve(), bounds=bounds, length_m=0.9, speed_mps=2.9713633234594523)]
    result = {"schema": "core.scientific_failure_aware_comparison.v2", "policy": POLICY,
              "geometry": {"bounds_m": bounds, "closed_faces": ["bottom", "left", "right", "front", "back"], "open_faces": ["top"], "source": "registered F3 finite geometry triangles; no runtime AABB inferred"},
              "hosts": rows, "comparison": compare_failure_aware(rows[0], rows[1]),
              "original_full_result": "campaigns/core-v1/reproduction/float64-full835-collected/paired-comparison-v2.json",
              "gpu_started": False, "formal_protocol_modified": False}
    out=args.output.resolve(); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2,sort_keys=True))
    print(f"wrote {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
