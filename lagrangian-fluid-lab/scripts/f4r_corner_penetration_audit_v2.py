#!/usr/bin/env python3
"""Bounded, read-only follow-up for the archived F4R fine-grid corner particles.

The tool verifies each selected trajectory hash before opening the same held
file descriptor with h5py. It reads the particle-ID axis plus the selected
four IDs' time, position, velocity, validity, and initial-Mk slices only. It
does not run or resume a solver and does not alter the older forensic receipt.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import h5py
import numpy as np

try:
    from scripts.finite_wall_audit import outside_closed_face_masks, segment_crossing_events
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from finite_wall_audit import outside_closed_face_masks, segment_crossing_events


LAB = Path(__file__).resolve().parents[1]
MATRIX_PATH = Path("campaigns/l2-multifamily/resume-c6b28c8/f4r-matrix.json")
FORENSICS_PATH = Path("campaigns/core-v1/cfd/f4-forensics.json")
OUTPUT_DIR = Path("campaigns/core-v1/cfd/f4r-corner-penetration-audit-v2")
TEST_PATH = Path("tests/test_f4r_corner_penetration_audit_v2.py")
CASE_IDS = (
    "F4R_center_drop_pool_dp006",
    "F4R_offset_drop_pool_dp006",
)
EXPECTED_PARTICLE_IDS = (67069, 68341, 292573, 293845)
MAX_SMALL_INPUT_BYTES = 4 * 1024 * 1024
MAX_HDF5_BYTES = 256 * 1024 * 1024
MAX_FRAMES = 64
MAX_PARTICLES = 400_000
MAX_HDF5_DIMENSION = MAX_FRAMES * MAX_PARTICLES * 3
HASH_BLOCK_BYTES = 8 * 1024 * 1024
WALL_TOLERANCE_M = 1e-8
INITIAL_GEOMETRY_TOLERANCE_M = 1e-7
WALL_BOUNDS = {
    "xmin": 0.0,
    "xmax": 1.2,
    "ymin": 0.0,
    "ymax": 0.4,
    "zmin": 0.0,
    "zmax": 0.6,
}
CLOSED_FACES = ("bottom", "left", "right", "front", "back")
CONTINUOUS_SOURCE_MASS_KG = (46.592, 5.824)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_identity(before: os.stat_result, after: os.stat_result) -> bool:
    fields = ("st_dev", "st_ino", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    return all(getattr(before, field) == getattr(after, field) for field in fields)


def _open_regular_nofollow(path: Path, *, size_cap: int) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        identity = os.fstat(fd)
        if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
            raise ValueError(f"input must be a regular single-link file: {path}")
        if identity.st_size < 0 or identity.st_size > size_cap:
            raise ValueError(f"input exceeds its byte cap: {path}")
        return fd, identity
    except BaseException:
        os.close(fd)
        raise


def _read_bound_bytes(path: Path, *, size_cap: int) -> tuple[bytes, dict[str, Any]]:
    fd, before = _open_regular_nofollow(path, size_cap=size_cap)
    try:
        chunks: list[bytes] = []
        total = 0
        digest = hashlib.sha256()
        while True:
            block = os.read(fd, min(HASH_BLOCK_BYTES, size_cap + 1 - total))
            if not block:
                break
            total += len(block)
            if total > size_cap:
                raise ValueError(f"input grew beyond its byte cap: {path}")
            digest.update(block)
            chunks.append(block)
        after = os.fstat(fd)
        if not _stable_identity(before, after) or total != before.st_size:
            raise ValueError(f"input changed while being read: {path}")
        return b"".join(chunks), {
            "path": path.relative_to(LAB).as_posix(),
            "bytes": total,
            "sha256": digest.hexdigest(),
        }
    finally:
        os.close(fd)


def _read_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, binding = _read_bound_bytes(LAB / path, size_cap=MAX_SMALL_INPUT_BYTES)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value, binding


def _repo_path(raw_path: str) -> Path:
    raw = Path(raw_path)
    if raw.is_absolute():
        marker = "/lagrangian-fluid-lab/"
        text = raw.as_posix()
        if marker not in text:
            raise ValueError(f"historical path is outside the repository: {raw_path}")
        raw = Path(text.split(marker, 1)[1])
    elif raw.parts and raw.parts[0] == "lagrangian-fluid-lab":
        raw = Path(*raw.parts[1:])
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(f"unsafe repository-relative path: {raw_path}")
    return raw


def _bind(path: Path, role: str, *, cap: int = MAX_SMALL_INPUT_BYTES) -> dict[str, Any]:
    _, binding = _read_bound_bytes(LAB / path, size_cap=cap)
    return {**binding, "role": role}


def _as_box(box: dict[str, Any]) -> dict[str, list[float]]:
    low = [float(box["point"][axis]) for axis in ("x", "y", "z")]
    size = [float(box["size"][axis]) for axis in ("x", "y", "z")]
    if not np.isfinite(np.asarray(low + size, dtype=np.float64)).all() or min(size) <= 0:
        raise ValueError("drawbox coordinates must be finite with positive sizes")
    return {"low": low, "high": [a + b for a, b in zip(low, size)]}


def _parse_definition(raw: bytes, *, case_id: str) -> dict[str, Any]:
    root = ET.fromstring(raw)
    definition = root.find("./casedef/geometry/definition")
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if definition is None or mainlist is None:
        raise ValueError(f"missing geometry contract in {case_id}")
    dp = float(definition.attrib["dp"])
    current_mk: int | None = None
    boxes: list[dict[str, Any]] = []
    for command in mainlist:
        if command.tag == "setmkfluid":
            current_mk = int(command.attrib["mk"])
        elif command.tag == "drawbox":
            point, size, fill = command.find("point"), command.find("size"), command.find("boxfill")
            if point is None or size is None or fill is None:
                raise ValueError(f"incomplete drawbox in {case_id}")
            boxes.append({
                "point": {axis: float(point.attrib[axis]) for axis in ("x", "y", "z")},
                "size": {axis: float(size.attrib[axis]) for axis in ("x", "y", "z")},
                "fill": (fill.text or "").strip(),
                "mkfluid": current_mk,
            })
    if len(boxes) != 3 or not math.isclose(dp, 0.006, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError(f"unexpected F4R geometry layout in {case_id}")
    pool, drop, tank = map(_as_box, boxes)
    expected_pool = {"low": [0.08, 0.04, 0.04], "high": [1.12, 0.36, 0.18]}
    expected_tank = {"low": [0.0, 0.0, 0.0], "high": [1.2, 0.4, 0.6]}
    box_matches = lambda actual, expected: all(
        np.allclose(actual[key], expected[key], rtol=0.0, atol=1e-14)
        for key in ("low", "high")
    )
    if not box_matches(pool, expected_pool) or not box_matches(tank, expected_tank):
        raise ValueError(f"F4R pool/tank geometry drifted in {case_id}")
    if boxes[0]["mkfluid"] != 0 or boxes[1]["mkfluid"] != 1:
        raise ValueError(f"F4R source labels drifted in {case_id}")
    return {
        "dp_m": dp,
        "pool": pool,
        "drop": drop,
        "tank": tank,
        "drop_initial_x_m": drop["low"][0],
        "drop_source_label": boxes[1]["mkfluid"],
        "pool_source_label": boxes[0]["mkfluid"],
    }


def analyze_selected_tracks(
    times: Any,
    positions: Any,
    velocities: Any,
    valid: Any,
    particle_ids: Any,
    *,
    bounds: dict[str, float] = WALL_BOUNDS,
    tolerance_m: float = WALL_TOLERANCE_M,
) -> dict[str, Any]:
    """Separate finite-face endpoint states, AABB exterior states, and chord events."""
    time = np.asarray(times, dtype=np.float64)
    pos = np.asarray(positions, dtype=np.float64)
    vel = np.asarray(velocities, dtype=np.float64)
    mask = np.asarray(valid, dtype=bool)
    ids = [int(value) for value in particle_ids]
    nframes, nparticles = pos.shape[:2] if pos.ndim == 3 else (0, 0)
    if (
        time.ndim != 1 or pos.ndim != 3 or pos.shape[2] != 3
        or vel.shape != pos.shape or mask.shape != pos.shape[:2]
        or len(ids) != nparticles or len(time) != nframes or nframes < 2
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("selected track axes or identities are inconsistent")
    if not np.isfinite(time).all() or np.any(np.diff(time) <= 0.0):
        raise ValueError("selected time axis must be finite and strictly increasing")
    if not np.isfinite(pos[mask]).all() or not np.isfinite(vel[mask]).all():
        raise ValueError("valid selected positions and velocities must be finite")

    spec = {"container_interior": dict(bounds), "closed_faces": list(CLOSED_FACES)}
    tracks: list[dict[str, Any]] = []
    finite_events: list[dict[str, Any]] = []
    for column, particle_id in enumerate(ids):
        endpoint_face_counts = {face: 0 for face in CLOSED_FACES}
        aabb_outside_frames: list[int] = []
        finite_face_endpoint_frames: list[int] = []
        first_aabb: dict[str, Any] | None = None
        for frame in range(nframes):
            if not mask[frame, column]:
                continue
            point = pos[frame, column]
            face_masks = outside_closed_face_masks(point.reshape(1, 3), spec, tolerance_m)
            outside_faces = [face for face, values in face_masks.items() if bool(values[0])]
            for face in outside_faces:
                endpoint_face_counts[face] += 1
            if outside_faces:
                finite_face_endpoint_frames.append(frame)
            outside = (
                point[0] < bounds["xmin"] - tolerance_m
                or point[0] > bounds["xmax"] + tolerance_m
                or point[1] < bounds["ymin"] - tolerance_m
                or point[1] > bounds["ymax"] + tolerance_m
                or point[2] < bounds["zmin"] - tolerance_m
                or point[2] > bounds["zmax"] + tolerance_m
            )
            if outside:
                aabb_outside_frames.append(frame)
                if first_aabb is None:
                    first_aabb = {
                        "frame": frame,
                        "time_s": float(time[frame]),
                        "position_m": point.tolist(),
                    }
        tracks.append({
            "particle_id": particle_id,
            "valid_frame_count": int(mask[:, column].sum()),
            "finite_face_endpoint_violation_frame_count": len(finite_face_endpoint_frames),
            "finite_face_endpoint_counts_by_face": {
                face: count for face, count in endpoint_face_counts.items() if count
            },
            "outside_tank_aabb_frame_count": len(aabb_outside_frames),
            "outside_tank_aabb_frames_without_finite_wall_endpoint": [
                frame for frame in aabb_outside_frames if frame not in finite_face_endpoint_frames
            ],
            "first_outside_closed_aabb": first_aabb,
        })

    for frame in range(1, nframes):
        common = mask[frame - 1] & mask[frame]
        if not common.any():
            continue
        selected_columns = np.flatnonzero(common)
        for event in segment_crossing_events(
            pos[frame - 1, common], pos[frame, common], spec, tolerance_m
        ):
            column = int(selected_columns[int(event["point_index"])])
            fraction = float(event["fraction"])
            finite_events.append({
                "particle_id": ids[column],
                "from_frame": frame - 1,
                "to_frame": frame,
                "time_interval_s": [float(time[frame - 1]), float(time[frame])],
                "fraction_of_saved_chord": fraction,
                "chord_time_estimate_s": float(time[frame - 1] + fraction * (time[frame] - time[frame - 1])),
                "face": event["face"],
                "crossing_position_m": event["crossing_position_m"],
            })
    return {
        "time_start_s": float(time[0]),
        "time_end_s": float(time[-1]),
        "saved_frame_count": int(nframes),
        "selected_particle_count": len(ids),
        "tracks": tracks,
        "finite_wall_saved_chord_outward_crossings": finite_events,
        "saved_chord_is_exact_solver_substep_path": False,
    }


def scan_hdf5_case(
    path: Path,
    *,
    expected_sha256: str,
    expected_frames: int,
    expected_particles: int,
    expected_initial: list[dict[str, Any]],
    relative_path: str,
) -> dict[str, Any]:
    fd, before = _open_regular_nofollow(path, size_cap=MAX_HDF5_BYTES)
    try:
        stream = os.fdopen(fd, "rb", closefd=False)
        digest = hashlib.sha256()
        bytes_hashed = 0
        while True:
            block = stream.read(HASH_BLOCK_BYTES)
            if not block:
                break
            bytes_hashed += len(block)
            if bytes_hashed > MAX_HDF5_BYTES:
                raise ValueError("trajectory grew beyond the frozen byte cap")
            digest.update(block)
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"trajectory SHA-256 mismatch: {relative_path}")
        stream.seek(0)
        with h5py.File(stream, "r") as h5:
            required = {"particle_id", "time", "position", "velocity", "valid", "mk"}
            if not required.issubset(h5.keys()):
                raise ValueError(f"trajectory is missing required datasets: {relative_path}")
            ids_ds = h5["particle_id"]
            time_ds = h5["time"]
            position_ds = h5["position"]
            velocity_ds = h5["velocity"]
            valid_ds = h5["valid"]
            mk_ds = h5["mk"]
            if ids_ds.ndim != 1 or ids_ds.shape[0] != expected_particles:
                raise ValueError("particle-ID axis differs from the frozen matrix")
            if ids_ds.shape[0] > MAX_PARTICLES:
                raise ValueError("particle-ID axis exceeds the frozen element cap")
            if time_ds.ndim != 1 or not 2 <= time_ds.shape[0] <= MAX_FRAMES:
                raise ValueError("saved-frame axis exceeds the frozen cap")
            expected_shape = (int(time_ds.shape[0]), int(ids_ds.shape[0]))
            if position_ds.shape != expected_shape + (3,) or velocity_ds.shape != position_ds.shape:
                raise ValueError("position/velocity shape is inconsistent with the frozen axes")
            if valid_ds.shape != expected_shape or mk_ds.shape != expected_shape:
                raise ValueError("valid/Mk shape is inconsistent with the frozen axes")
            if int(time_ds.shape[0]) != expected_frames:
                raise ValueError("saved-frame count differs from the frozen matrix")
            if int(np.prod(position_ds.shape, dtype=np.int64)) > MAX_HDF5_DIMENSION:
                raise ValueError("trajectory state array exceeds the frozen dimension cap")
            particle_ids = np.asarray(ids_ds[:])
            if not np.issubdtype(particle_ids.dtype, np.integer) or len(np.unique(particle_ids)) != len(particle_ids):
                raise ValueError("particle IDs must be unique integers")
            expected_ids = [int(item["id"]) for item in expected_initial]
            if expected_ids != list(EXPECTED_PARTICLE_IDS):
                raise ValueError("historical corner-particle identity set drifted")
            index_by_id = {int(pid): index for index, pid in enumerate(particle_ids)}
            if any(pid not in index_by_id for pid in expected_ids):
                raise ValueError("one or more frozen corner IDs are absent")
            selected = sorted((index_by_id[pid], pid) for pid in expected_ids)
            indices = [index for index, _ in selected]
            selected_ids = [pid for _, pid in selected]
            times = np.asarray(time_ds[:], dtype=np.float64)
            positions = np.asarray(position_ds[:, indices, :], dtype=np.float64)
            velocities = np.asarray(velocity_ds[:, indices, :], dtype=np.float64)
            validity = np.asarray(valid_ds[:, indices], dtype=bool)
            initial_mk = np.asarray(mk_ds[0, indices])
            by_id = {int(item["id"]): item for item in expected_initial}
            initial_rows = []
            for column, particle_id in enumerate(selected_ids):
                expected = by_id[particle_id]
                observed_position = positions[0, column]
                expected_position = np.asarray(expected["position"], dtype=np.float64)
                if not np.array_equal(observed_position, expected_position):
                    raise ValueError(f"initial position differs from the immutable forensic record for ID {particle_id}")
                if int(initial_mk[column]) != int(expected["source_mk"]):
                    raise ValueError(f"initial source label differs for ID {particle_id}")
                initial_rows.append({
                    "particle_id": particle_id,
                    "position_m": observed_position.tolist(),
                    "initial_source_mk": int(initial_mk[column]),
                    "initial_velocity_mps": velocities[0, column].tolist(),
                })
            summary = analyze_selected_tracks(times, positions, velocities, validity, selected_ids)
        after = os.fstat(fd)
        if not _stable_identity(before, after) or bytes_hashed != before.st_size:
            raise ValueError(f"trajectory identity changed during bounded scan: {relative_path}")
        return {
            "source": {
                "path": relative_path,
                "bytes": bytes_hashed,
                "sha256": actual_sha256,
                "frames": expected_frames,
                "particles": expected_particles,
                "scan_policy": "hash whole held FD first; then read ID axis and only selected trajectory slices",
            },
            "initial_corner_particles": initial_rows,
            "track_summary": summary,
            "fd_identity_stable": True,
        }
    finally:
        os.close(fd)


def _mass_summary(forensic_cells: list[dict[str, Any]]) -> dict[str, Any]:
    if len(forensic_cells) != 6:
        raise ValueError("F4R mass summary requires the original six-cell denominator")
    rows: list[dict[str, Any]] = []
    for cell in forensic_cells:
        discrete = [float(value) for value in cell["discrete_source_mass_kg"]]
        continuous = [float(value) for value in cell["continuous_source_mass_kg"]]
        recorded_errors = [float(value) for value in cell["source_mass_relative_errors"]]
        if len(discrete) != 2 or len(continuous) != 2 or len(recorded_errors) != 2:
            raise ValueError("F4R source mass arrays must contain pool and drop values")
        if not np.isfinite(np.asarray(discrete + continuous + recorded_errors)).all() or min(continuous) <= 0.0:
            raise ValueError("F4R source mass values must be finite and positive")
        recomputed = [mass / exact - 1.0 for mass, exact in zip(discrete, continuous)]
        if not np.allclose(recomputed, recorded_errors, rtol=0.0, atol=1e-12):
            raise ValueError("source-mass error no longer matches the immutable forensic record")
        total_discrete = sum(discrete)
        total_continuous = sum(continuous)
        rows.append({
            "case_id": str(cell["case_id"]),
            "dp_m": float(cell["dp_m"]),
            "background": "offset" if "offset" in str(cell["case_id"]) else "center",
            "pool_discrete_mass_kg": discrete[0],
            "drop_discrete_mass_kg": discrete[1],
            "total_discrete_mass_kg": total_discrete,
            "total_continuous_mass_kg": total_continuous,
            "pool_relative_error": recomputed[0],
            "drop_relative_error": recomputed[1],
            "total_relative_error": total_discrete / total_continuous - 1.0,
        })
    if any(
        not math.isclose(row["total_continuous_mass_kg"], sum(CONTINUOUS_SOURCE_MASS_KG), rel_tol=0.0, abs_tol=1e-10)
        for row in rows
    ):
        raise ValueError("continuous source geometry mass differs across the frozen six-cell scope")
    summary: dict[str, Any] = {"cells": rows, "continuous_total_mass_kg": sum(CONTINUOUS_SOURCE_MASS_KG)}
    background_spreads = {}
    for background in ("center", "offset"):
        values = [row["total_discrete_mass_kg"] for row in rows if row["background"] == background]
        if len(values) != 3:
            raise ValueError(f"expected three resolutions for {background} background")
        spread = max(values) - min(values)
        background_spreads[background] = {
            "minimum_total_discrete_mass_kg": min(values),
            "maximum_total_discrete_mass_kg": max(values),
            "spread_kg": spread,
            "spread_fraction_of_max": spread / max(values),
        }
    all_totals = [row["total_discrete_mass_kg"] for row in rows]
    summary["cross_resolution_spread_by_background"] = background_spreads
    summary["all_six_total_mass_span"] = {
        "minimum_total_discrete_mass_kg": min(all_totals),
        "maximum_total_discrete_mass_kg": max(all_totals),
        "spread_kg": max(all_totals) - min(all_totals),
        "spread_fraction_of_max": (max(all_totals) - min(all_totals)) / max(all_totals),
    }
    summary["mass_rescaling_applied"] = False
    return summary


def _case_rows(matrix: dict[str, Any], forensic_cells: list[dict[str, Any]]) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    matrix_rows = {
        str(cell["cell"]["case_id"]): cell
        for cell in matrix.get("cells", [])
        if isinstance(cell, dict) and isinstance(cell.get("cell"), dict)
    }
    forensic_rows = {str(cell["case_id"]): cell for cell in forensic_cells}
    if len(matrix_rows) != 6 or set(matrix_rows) != set(forensic_rows):
        raise ValueError("matrix and forensic source do not close over the same six F4R cells")
    output = {}
    for case_id in CASE_IDS:
        matrix_cell = matrix_rows.get(case_id)
        forensic_cell = forensic_rows.get(case_id)
        if matrix_cell is None or forensic_cell is None:
            raise ValueError(f"missing frozen fine-grid case: {case_id}")
        if not math.isclose(float(matrix_cell["cell"]["resolution_m"]), 0.006, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError(f"unexpected fine-grid resolution for {case_id}")
        expected_hash = matrix_cell["audit"].get("hdf5_sha256")
        if expected_hash != forensic_cell.get("hdf5_sha256"):
            raise ValueError(f"matrix/forensic HDF5 digest mismatch for {case_id}")
        output[case_id] = (matrix_cell, forensic_cell)
    return output


def _assert_frozen_fine_grid_observations(case_scans: list[dict[str, Any]]) -> None:
    """Fail closed if the report's explicit four-particle findings drift."""
    if len(case_scans) != len(CASE_IDS):
        raise ValueError("fine-grid observation assertion requires both frozen backgrounds")
    expected_face = {
        EXPECTED_PARTICLE_IDS[0]: "left",
        EXPECTED_PARTICLE_IDS[1]: "left",
        EXPECTED_PARTICLE_IDS[2]: "right",
        EXPECTED_PARTICLE_IDS[3]: "right",
    }
    for case in case_scans:
        rows = case["initial_corner_geometry"]
        initial_by_id = {int(row["particle_id"]): row for row in rows}
        if set(initial_by_id) != set(EXPECTED_PARTICLE_IDS):
            raise ValueError(f"initial corner-particle IDs drifted in {case['case_id']}")
        for row in initial_by_id.values():
            outside = np.asarray(row["outside_continuous_pool_by_axis_m"], dtype=np.float64)
            if (
                not math.isclose(float(outside[0]), 0.002, rel_tol=0.0, abs_tol=INITIAL_GEOMETRY_TOLERANCE_M)
                or not np.allclose(outside[1:], 0.0, rtol=0.0, atol=INITIAL_GEOMETRY_TOLERANCE_M)
                or not row["inside_physical_tank_at_frame0"]
            ):
                raise ValueError(f"frozen initial geometry observation drifted for ID {row['particle_id']}")
        events = [
            event for event in case["track_summary"]["finite_wall_saved_chord_outward_crossings"]
            if event["from_frame"] == 8 and event["to_frame"] == 9
        ]
        by_id = {int(event["particle_id"]): event for event in events}
        if set(by_id) != set(EXPECTED_PARTICLE_IDS) or len(events) != len(EXPECTED_PARTICLE_IDS):
            raise ValueError(f"frame 8->9 crossing identity set drifted in {case['case_id']}")
        if any(by_id[particle_id]["face"] != face for particle_id, face in expected_face.items()):
            raise ValueError(f"frame 8->9 finite wall face attribution drifted in {case['case_id']}")


def build_receipt() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    matrix, matrix_binding = _read_json(MATRIX_PATH)
    forensic, forensic_binding = _read_json(FORENSICS_PATH)
    matrix_digest = matrix_binding["sha256"]
    if forensic.get("schema") != "core.cfd.v1" or forensic.get("source_sha256") != matrix_digest:
        raise ValueError("existing F4 forensics is not bound to the current six-cell matrix")
    forensic_cells = forensic.get("cells")
    if not isinstance(forensic_cells, list):
        raise ValueError("existing F4 forensics has no six-cell source list")
    case_rows = _case_rows(matrix, forensic_cells)
    bindings = {
        "matrix": {**matrix_binding, "role": "six-cell run/input/audit identity"},
        "prior_forensics": {**forensic_binding, "role": "original six-cell masses and corner-ID attribution"},
        "definitions": {},
        "implementation": _bind(Path("scripts/finite_wall_audit.py"), "finite-face endpoint and saved-chord semantics"),
        "audit_script": _bind(Path("scripts/f4r_corner_penetration_audit_v2.py"), "bounded follow-up implementation"),
        "tests": _bind(TEST_PATH, "synthetic-only regression tests"),
    }
    geometry_by_case: dict[str, dict[str, Any]] = {}
    case_scans: list[dict[str, Any]] = []
    bytes_hashed = 0
    for case_id in CASE_IDS:
        matrix_cell, forensic_cell = case_rows[case_id]
        definition_path = _repo_path(matrix_cell["input"]["definition"])
        definition_bytes, definition_binding = _read_bound_bytes(LAB / definition_path, size_cap=MAX_SMALL_INPUT_BYTES)
        if definition_binding["sha256"] != matrix_cell["input"]["definition_sha256"]:
            raise ValueError(f"definition hash mismatch for {case_id}")
        bindings["definitions"][case_id] = {**definition_binding, "role": "frozen F4R generated input geometry"}
        geometry = _parse_definition(definition_bytes, case_id=case_id)
        geometry_by_case[case_id] = geometry
        initial_records = forensic_cell.get("initial_affected", [])
        source_path = _repo_path(str(forensic_cell["hdf5"]))
        matrix_source = _repo_path(str(matrix_cell["audit"]["hdf5"]))
        if source_path != matrix_source:
            raise ValueError(f"matrix/forensic trajectory paths differ for {case_id}")
        scan = scan_hdf5_case(
            LAB / source_path,
            expected_sha256=str(forensic_cell["hdf5_sha256"]),
            expected_frames=int(matrix_cell["audit"]["frame_count"]),
            expected_particles=int(matrix_cell["audit"]["particle_count"]),
            expected_initial=initial_records,
            relative_path=source_path.as_posix(),
        )
        bytes_hashed += int(scan["source"]["bytes"])
        pool = geometry["pool"]
        initial_geometry = []
        for record in scan["initial_corner_particles"]:
            point = np.asarray(record["position_m"], dtype=np.float64)
            low = np.asarray(pool["low"], dtype=np.float64)
            high = np.asarray(pool["high"], dtype=np.float64)
            outside = np.maximum(np.maximum(low - point, point - high), 0.0)
            tank_low = np.asarray(geometry["tank"]["low"], dtype=np.float64)
            tank_high = np.asarray(geometry["tank"]["high"], dtype=np.float64)
            in_tank = bool(np.all(point >= tank_low - WALL_TOLERANCE_M) and np.all(point <= tank_high + WALL_TOLERANCE_M))
            initial_geometry.append({
                "particle_id": record["particle_id"],
                "source_mk": record["initial_source_mk"],
                "position_m": record["position_m"],
                "outside_continuous_pool_by_axis_m": outside.tolist(),
                "inside_physical_tank_at_frame0": in_tank,
            })
        case_scans.append({
            "case_id": case_id,
            "background": "offset" if "offset" in case_id else "center",
            "dp_m": geometry["dp_m"],
            "continuous_pool_bounds_m": geometry["pool"],
            "continuous_tank_bounds_m": geometry["tank"],
            "drop_initial_x_m": geometry["drop_initial_x_m"],
            "initial_corner_geometry": initial_geometry,
            **scan,
        })
    _assert_frozen_fine_grid_observations(case_scans)
    # Bind every prior forensic HDF5 digest to the matrix, while only opening
    # the two explicitly selected dp=0.006 source files above.
    mass_summary = _mass_summary(forensic_cells)
    return {
        "schema": "l2r.f4r.corner_penetration_followup.v2",
        "record_id": "f4r-dp006-corner-penetration-followup-v2",
        "created_at_utc": started.isoformat(),
        "status": "bounded_saved_data_diagnostic_complete_causality_unresolved",
        "scope": {
            "family": "F4R",
            "selected_cases": list(CASE_IDS),
            "selected_particle_ids": list(EXPECTED_PARTICLE_IDS),
            "original_cell_denominator": 6,
            "original_time_horizon_s": 0.6,
            "float32_initial_geometry_comparison_tolerance_m": INITIAL_GEOMETRY_TOLERANCE_M,
            "qualification_claim": "none",
            "credit": 0,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
        },
        "input_bindings": bindings,
        "resource_policy_and_observation": {
            "hdf5_file_size_cap_bytes": MAX_HDF5_BYTES,
            "hdf5_frame_cap": MAX_FRAMES,
            "hdf5_particle_cap": MAX_PARTICLES,
            "whole_file_sha256_before_hdf5_open": True,
            "same_held_fd_for_hash_and_hdf5_read": True,
            "hdf5_bytes_hashed": bytes_hashed,
            "opened_hdf5_count": len(case_scans),
            "full_dynamic_state_axis_scanned": False,
            "selected_particle_track_rows_read": len(case_scans) * len(EXPECTED_PARTICLE_IDS),
        },
        "mass_summary_from_bound_six_cell_forensics": mass_summary,
        "fine_grid_cases": case_scans,
        "interpretation": {
            "initial_geometry_observation": "The four recorded source-pool particle centers lie outside the continuous pool's x bounds by 0.002 m (= dp/3) at t=0, while all four remain inside the physical tank bounds. This observation alone does not identify the generator's lattice/drawbox rule.",
            "later_boundary_state": "The verified saved tracks cross the finite left/right wall faces on the frame 8->9 chords in both backgrounds; endpoint time is only localized to the saved interval, not an exact native solver substep.",
            "causal_attribution": "unresolved: the initial particle-center/continuous-box mismatch is proven, and later finite-wall crossings are proven on saved-frame chords, but these observations alone do not establish the generator rule or that a lattice phase caused the solver penetration.",
            "endpoint_vs_chord": "finite-face endpoint counts, outside-closed-AABB samples, and saved-chord events are separate diagnostics; they must not be added or relabeled as exact physical path events.",
            "mass_policy": "The six-cell forensic values show resolution/background-dependent discrete source masses; no particle-mass rescaling is applied or recommended.",
        },
        "execution_controls": {
            "solver_started": False,
            "gencase_started": False,
            "native_decoder_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "historical_receipts_modified": False,
            "scientific_denominator_changed": False,
        },
    }


def render_markdown(receipt: dict[str, Any]) -> str:
    masses = receipt["mass_summary_from_bound_six_cell_forensics"]
    lines = [
        "# F4R 细网格角粒子、穿墙与初始质量差异复核",
        "",
        "日期：2026-09-26。此报告是只读诊断，不是资格判定或新 solver 结果。",
        "",
        "## 结果",
        "",
        f"- 两个 `dp=0.006 m` 背景中相同四个初始池源粒子，均在连续池体的 x 边界外约 `0.002 m = dp/3`（float32 坐标比较容差 `{receipt['scope']['float32_initial_geometry_comparison_tolerance_m']:.1e} m`），但初态仍处于物理水槽内；这是粒子中心与连续几何的观测差异，尚不能单独识别生成器的格点/包含规则。",
        "- 两背景的四条选中轨迹均在保存帧 `8→9` 的 chord 上穿越左右有限壁面；区间分别见下表。chord 不是精确 solver 子步轨迹。",
        "- 原始六例离散总质量的跨分辨率 spread 已量化；不得以修改粒子质量人为对齐。",
        "",
        "## 六例初始质量（原始绑定取证）",
        "",
        "| 背景 | dp (m) | 池离散质量 (kg) | 液滴离散质量 (kg) | 总离散质量 (kg) | 相对连续总质量误差 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in masses["cells"]:
        lines.append(
            f"| {row['background']} | {row['dp_m']:.9f} | {row['pool_discrete_mass_kg']:.9f} | "
            f"{row['drop_discrete_mass_kg']:.9f} | {row['total_discrete_mass_kg']:.9f} | {row['total_relative_error'] * 100:.3f}% |"
        )
    lines.extend([
        "",
        f"连续总质量为 `{masses['continuous_total_mass_kg']:.3f} kg`。center 三档总质量范围为 `{masses['cross_resolution_spread_by_background']['center']['spread_fraction_of_max'] * 100:.3f}%`（以该背景最大值为分母）；offset 为 `{masses['cross_resolution_spread_by_background']['offset']['spread_fraction_of_max'] * 100:.3f}%`。六例合并的 min–max span 为 `{masses['all_six_total_mass_span']['spread_fraction_of_max'] * 100:.3f}%`。",
        "",
        "## 穿墙时序与因果边界",
        "",
        "对中心和偏置 `dp=0.006 m` 轨迹，初始四点的来源标签、ID、position 与旧 forensic receipt 精确匹配；HDF5 在同一 held FD 上先整文件复算 SHA，再只读取 ID 轴、time 和这四个 ID 的 position/velocity/valid/Mk 切片。",
        "",
        "在保存帧 8→9 的区间，四个 ID 分别沿左/右有限壁面越界；点采样只把现象定位到区间，不能确定哪个 native substep 首次越界。帧9时个别点同时在两个平面之外，因此有限面 endpoint、AABB 外点与 chord crossing 的计数语义不同。报告不把它们混成一个 gate。",
        "",
        "已证实的是：四个初始粒子中心相对连续池箱 x 边界偏出 dp/3；后续数值轨迹出现保存弦线壁面穿越。尚未证实的是生成器采用何种格点/包含规则、二者间的因果关系、边界离散生成责任与压力/数值更新的相对贡献。cell-centre/初始格点相位可以作为待检验假设，但不能作为已确立原因；不能按本诊断直接修改质量或边界阈值。",
        "",
        "## 可复现性与边界",
        "",
        "- 运行：`.venv/bin/python -m scripts.f4r_corner_penetration_audit_v2 --write`（工作目录 `lagrangian-fluid-lab`）。",
        "- 回归：`.venv/bin/python -m pytest tests/test_f4r_corner_penetration_audit_v2.py -q`。合成测试不读取上述生产轨迹。",
        f"- 本次只对两份细网格 HDF5 做完整 SHA 流式校验，共 `{receipt['resource_policy_and_observation']['hdf5_bytes_hashed']}` bytes；动态数组只读选定四粒子的轨迹切片。",
        "- 未运行 solver、GenCase、native decoder、worker、GPU 或 queue；未改变六例分母、历史 receipts、registry 或 ledger；qualification credit 为 0。",
        "- 该结果可用于后续候选卡及边界条件研究设计；不可作为 T1/T2、source/runtime 认证或精确子步穿墙结论。",
        "",
    ])
    return "\n".join(lines)


def write_outputs(receipt: dict[str, Any], *, output_dir: Path = LAB / OUTPUT_DIR) -> tuple[Path, Path]:
    parent = output_dir.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("audit output parent must be an existing, non-symlink directory")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"immutable audit output already exists: {output_dir}")
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}.tmp-", dir=parent) as temporary:
        staging = Path(temporary)
        payloads = {
            "receipt.json": json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
            "report.zh-CN.md": render_markdown(receipt),
        }
        for name, payload in payloads.items():
            path = staging / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        directory_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        # Linux renameat2(RENAME_NOREPLACE) publishes the complete directory
        # atomically and refuses an existing namespace, including an empty dir.
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise RuntimeError("atomic no-replace directory publication is unavailable")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, os.fsencode(staging), -100, os.fsencode(output_dir), 1)
        if result != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(output_dir))
        parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    return output_dir / "receipt.json", output_dir / "report.zh-CN.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="publish once into a fresh audit directory")
    args = parser.parse_args(argv)
    receipt = build_receipt()
    if args.write:
        receipt_path, report_path = write_outputs(receipt)
        print(json.dumps({"receipt": str(receipt_path.relative_to(LAB)), "report": str(report_path.relative_to(LAB)), "status": receipt["status"]}, indent=2))
    else:
        print(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
