#!/usr/bin/env python3
"""Compare saved native moving-boundary positions with both XML angle signs.

This is a CPU-only, read-only probe for an already completed solver product.
The BI4 files are decoded by the official ``bi4_dump``/JBinaryData path before
this script is called.  It deliberately compares native moving particle IDs,
not fluid trajectories or a public geometry adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np


SCHEMA = "core.f2.native_moving_boundary_position_probe.v1"
AXES = ("x", "y", "z")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_motion_file(path: Path) -> tuple[np.ndarray, np.ndarray]:
    times, angles = [], []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        time_text, angle_text = line.split(";", 1)
        times.append(float(time_text))
        angles.append(float(angle_text))
    times_array = np.asarray(times, dtype=np.float64)
    angles_array = np.asarray(angles, dtype=np.float64)
    if len(times_array) < 2 or np.any(np.diff(times_array) <= 0):
        raise ValueError("motion file must contain strictly increasing times")
    return times_array, angles_array


def frame_time(xml_path: Path) -> float:
    text = xml_path.read_text()
    match = re.search(r'<double name="TimeStep" v="([^"]+)', text)
    if match is None:
        raise ValueError(f"missing TimeStep in {xml_path}")
    return float(match.group(1))


def rotation_y(angle_degrees: float) -> np.ndarray:
    angle = np.deg2rad(float(angle_degrees))
    c, s = np.cos(angle), np.sin(angle)
    return np.asarray(((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c)), dtype=np.float64)


def load_frame(decoded_root: Path, frame: str) -> tuple[np.ndarray, np.ndarray]:
    frame_dir = decoded_root / frame / f"PART_{frame}"
    ids = np.fromfile(frame_dir / "Idp.bin", dtype="<u4")
    positions = np.fromfile(frame_dir / "Posd.bin", dtype="<f8")
    if positions.size != ids.size * 3:
        raise ValueError(f"position/id size mismatch for frame {frame}")
    positions = positions.reshape((-1, 3))
    if len(np.unique(ids)) != len(ids) or not np.isfinite(positions).all():
        raise ValueError(f"invalid native identity/position arrays for frame {frame}")
    return ids, positions


def compare_frame(
    *,
    decoded_root: Path,
    frame: str,
    moving_ids: np.ndarray,
    initial_positions: np.ndarray,
    motion_times: np.ndarray,
    motion_angles: np.ndarray,
    pivot: np.ndarray,
) -> dict:
    ids, positions = load_frame(decoded_root, frame)
    lookup = {int(pid): index for index, pid in enumerate(ids)}
    if any(int(pid) not in lookup for pid in moving_ids):
        raise ValueError(f"frame {frame} does not retain every moving ID")
    actual = np.asarray([positions[lookup[int(pid)]] for pid in moving_ids])
    time_s = frame_time(decoded_root / f"{frame}.xml")
    angle_degrees = float(np.interp(time_s, motion_times, motion_angles))
    result = {
        "frame": int(frame),
        "time_s": time_s,
        "file_angle_degrees": angle_degrees,
        "moving_count": int(len(moving_ids)),
        "actual_bounds_m": {
            "low": actual.min(axis=0).tolist(),
            "high": actual.max(axis=0).tolist(),
        },
        "candidates": {},
    }
    for label, sign in (("Ry(+file_angle)", 1), ("Ry(-file_angle)", -1)):
        rotation = rotation_y(sign * angle_degrees)
        expected = (initial_positions - pivot) @ rotation.T + pivot
        error = actual - expected
        norms = np.linalg.norm(error, axis=1)
        components = np.abs(error)
        norm_index = int(np.argmax(norms))
        component_index = np.unravel_index(int(np.argmax(components)), components.shape)
        result["candidates"][label] = {
            "max_position_error_m": float(norms.max()),
            "rms_position_error_m": float(np.sqrt(np.mean(norms ** 2))),
            "mean_position_error_m": float(norms.mean()),
            "max_component_error_m": float(components.max()),
            "max_error_boundary_id": int(moving_ids[norm_index]),
            "max_error_actual_position_m": actual[norm_index].tolist(),
            "max_error_expected_position_m": expected[norm_index].tolist(),
            "max_component_boundary_id": int(moving_ids[component_index[0]]),
            "max_component_axis": AXES[component_index[1]],
            "max_component_signed_error_m": float(error[component_index]),
        }
    return result


def build_report(args: argparse.Namespace) -> dict:
    decoded_root = args.decoded_root.resolve()
    initial_ids, initial_all_positions = load_frame(decoded_root, args.frames[0])
    moving_ids = np.arange(args.moving_first, args.moving_first + args.moving_count, dtype=np.uint32)
    initial_lookup = {int(pid): index for index, pid in enumerate(initial_ids)}
    if any(int(pid) not in initial_lookup for pid in moving_ids):
        raise ValueError("moving ID range is not present in the initial native frame")
    initial_positions = np.asarray([initial_all_positions[initial_lookup[int(pid)]] for pid in moving_ids])
    motion_times, motion_angles = read_motion_file(args.motion_file)
    pivot = np.asarray(args.pivot, dtype=np.float64)
    frame_reports = [
        compare_frame(
            decoded_root=decoded_root,
            frame=frame,
            moving_ids=moving_ids,
            initial_positions=initial_positions,
            motion_times=motion_times,
            motion_angles=motion_angles,
            pivot=pivot,
        )
        for frame in args.frames
    ]

    nonzero = [item for item in frame_reports if abs(item["file_angle_degrees"]) > 1e-12]
    negative_errors = [item["candidates"]["Ry(-file_angle)"]["max_position_error_m"] for item in nonzero]
    positive_errors = [item["candidates"]["Ry(+file_angle)"]["max_position_error_m"] for item in nonzero]
    decoder_sources = [
        args.decoder_source,
        args.binary_source,
        args.jobject_source,
        args.exception_source,
        args.functions_source,
    ]
    return {
        "schema": SCHEMA,
        "scope": "F2_resting_fill_side_wet_full_cup_closed_catchment_mdbc_v2 H200 completed solver",
        "method": {
            "read_only": True,
            "gpu_launched_by_probe": False,
            "native_source": "official DualSPHysics JBinaryData decoded Idp/Posd arrays from solver Part_*.bi4",
            "moving_id_range": [int(moving_ids[0]), int(moving_ids[-1])],
            "moving_count": int(len(moving_ids)),
            "pivot_m": pivot.tolist(),
            "axis": "+y from XML axisp1=(0,-1,0.65) to axisp2=(0,1,0.65)",
            "comparison": "native saved moving positions against standard Ry(+file_angle) and Ry(-file_angle)",
            "saved_frames_only": True,
        },
        "inputs": {
            "decoded_root": str(decoded_root),
            "motion_file": str(args.motion_file.resolve()),
            "motion_file_sha256": sha256(args.motion_file),
            "part_motion_ref": str(args.part_motion_ref.resolve()),
            "part_motion_ref_sha256": sha256(args.part_motion_ref),
            "native_initial_part": str(args.initial_part.resolve()),
            "native_initial_part_sha256": sha256(args.initial_part),
            "frame_parts": {
                frame: {
                    "path": str(args.frame_parts[frame].resolve()),
                    "sha256": sha256(args.frame_parts[frame]),
                }
                for frame in args.frames
            },
            "decoder_sources": {str(path): sha256(path) for path in decoder_sources},
        },
        "frames": frame_reports,
        "aggregate": {
            "nonzero_motion_frames": [item["frame"] for item in nonzero],
            "max_error_m_by_candidate": {
                "Ry(+file_angle)": float(max(positive_errors, default=0.0)),
                "Ry(-file_angle)": float(max(negative_errors, default=0.0)),
            },
            "native_transform": "Ry(-file_angle)",
            "native_transform_confirmed": bool(nonzero and max(negative_errors) < 1e-10 and min(positive_errors) > 1e-1),
        },
        "limits": [
            "Positions are native saved output frames, not a continuous substep trajectory.",
            "Moving IDs are selected from the immutable GenCase block range; no ownership filtering or deletion is applied.",
            "This resolves the solver XML rotation sign only; it does not turn the v2 cup endpoint/chord failure into a qualification pass.",
        ],
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--decoded-root", type=Path, required=True)
    p.add_argument("--motion-file", type=Path, required=True)
    p.add_argument("--part-motion-ref", type=Path, required=True)
    p.add_argument("--initial-part", type=Path, required=True)
    p.add_argument("--frame", dest="frames", action="append", required=True)
    p.add_argument("--frame-part", action="append", required=True, metavar="FRAME=PATH")
    p.add_argument("--moving-first", type=int, required=True)
    p.add_argument("--moving-count", type=int, required=True)
    p.add_argument("--pivot", type=float, nargs=3, default=(0.0, 0.0, 0.65))
    p.add_argument("--decoder-source", type=Path, required=True)
    p.add_argument("--binary-source", type=Path, required=True)
    p.add_argument("--jobject-source", type=Path, required=True)
    p.add_argument("--exception-source", type=Path, required=True)
    p.add_argument("--functions-source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    return p


def main() -> None:
    args = parser().parse_args()
    frame_parts = {}
    for item in args.frame_part:
        frame, path = item.split("=", 1)
        frame_parts[frame] = Path(path)
    missing = set(args.frames) - set(frame_parts)
    if missing:
        raise SystemExit(f"missing --frame-part for {sorted(missing)}")
    args.frame_parts = frame_parts
    report = build_report(args)
    report["script"] = str(Path(__file__).resolve())
    report["script_sha256"] = sha256(Path(__file__).resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
