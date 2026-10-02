#!/usr/bin/env python3
"""Render a bounded GIF preview from an immutable F3 legacy typed HDF5.

The GIF is visual provenance only.  It samples five saved frames and never
changes or rewrites the source trajectory, labels, or existing PNG preview.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

SCHEMA = "ds02.f3.actual-gif-preview.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def geometry(metadata: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    tank = metadata["physical_binding"]["geometry"]["tank"]
    low = np.asarray(tank["low_m"], dtype=float)
    size = np.asarray(tank["size_m"], dtype=float)
    if low.shape != (3,) or size.shape != (3,) or not np.isfinite(low).all() or not np.isfinite(size).all() or np.any(size <= 0):
        raise ValueError("metadata tank geometry must be finite positive 3D low_m/size_m")
    return low, low + size


def render(
    source: Path,
    metadata: Mapping[str, Any],
    output: Path,
    report_path: Path | None = None,
    max_points: int = 6000,
    duration_ms: int = 350,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"GIF already exists: {output}")
    if max_points < 100 or duration_ms <= 0:
        raise ValueError("max_points must be >=100 and duration_ms must be positive")
    low, high = geometry(metadata)
    source_report_sha: str | None = None
    if report_path is not None:
        report = json.loads(report_path.read_text())
        source_report_sha = report.get("output_sha256")
        if not isinstance(source_report_sha, str) or len(source_report_sha) != 64:
            raise ValueError("source conversion report lacks output_sha256")

    output.parent.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    with h5py.File(source, "r") as h5:
        required = ("time", "position", "valid", "type", "mass")
        for name in required:
            if name not in h5:
                raise ValueError(f"source HDF5 lacks {name}")
        times = np.asarray(h5["time"][:], dtype=float)
        if times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
            raise ValueError("source time must be finite and strictly increasing")
        frame_count, particle_count = h5["valid"].shape
        if h5["position"].shape != (frame_count, particle_count, 3) or h5["type"].shape != (frame_count, particle_count):
            raise ValueError("source HDF5 shapes are inconsistent")
        initial_position = np.asarray(h5["position"][0], dtype=float)
        initial_type = np.asarray(h5["type"][0])
        initial_valid = np.asarray(h5["valid"][0], dtype=bool)
        initial_fluid = initial_valid & (initial_type == 3)
        source_code = np.where(initial_position[:, 0] < 0.0, 0, 1)
        initial_mass = float(np.asarray(h5["mass"][0], dtype=float)[initial_fluid].sum(dtype=np.float64))
        targets = np.linspace(times[0], times[-1], 5)
        selected = np.unique(np.asarray([int(np.argmin(np.abs(times - target))) for target in targets], dtype=int))
        fluid_counts: list[int] = []
        selected_times: list[float] = []
        for frame in selected:
            valid = np.asarray(h5["valid"][frame], dtype=bool)
            particle_type = np.asarray(h5["type"][frame])
            fluid = valid & (particle_type == 3)
            fluid_indices = np.flatnonzero(fluid)
            stride = max(1, int(np.ceil(len(fluid_indices) / max_points)))
            fluid_indices = fluid_indices[::stride]
            boundary_indices = np.flatnonzero(valid & (particle_type != 3))[::8]
            positions = np.asarray(h5["position"][frame], dtype=float)
            fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4), constrained_layout=True)
            boundary = positions[boundary_indices]
            points = positions[fluid_indices]
            colors = np.where(source_code[fluid_indices] == 0, "#2878b5", "#e58e26")
            for axis, transverse_axis, label in zip(axes, (1, 2), ("x-y", "x-z")):
                if len(boundary):
                    axis.scatter(boundary[:, 0], boundary[:, transverse_axis], s=1, c="#8a9399", alpha=0.28, rasterized=True)
                if len(points):
                    axis.scatter(points[:, 0], points[:, transverse_axis], s=2, c=colors, alpha=0.68, rasterized=True)
                axis.axvline(0.0, color="#4c4c4c", linewidth=0.7, linestyle="--", alpha=0.7)
                axis.set_xlim(low[0] - 0.02, high[0] + 0.02)
                axis.set_ylim(low[transverse_axis] - 0.02, high[transverse_axis] + 0.02)
                axis.set_aspect("equal", adjustable="box")
                axis.set_xlabel("x [m]")
                axis.set_ylabel("y [m]" if transverse_axis == 1 else "z [m]")
                axis.set_title(label)
                if transverse_axis == 2:
                    axis.axhline(high[2], color="#a33", linewidth=0.7, linestyle=":", alpha=0.8)
            fig.suptitle(f"F3 legacy plain saved state, t={times[frame]:.4f} s; Q-N pending", fontsize=12)
            buf = io.BytesIO()
            fig.savefig(buf, dpi=120, format="png")
            plt.close(fig)
            buf.seek(0)
            frames.append(Image.open(buf).convert("P", palette=Image.Palette.ADAPTIVE))
            buf.close()
            fluid_counts.append(int(np.sum(fluid)))
            selected_times.append(float(times[frame]))
        if not frames:
            raise ValueError("no frames selected")
        first, *rest = frames
        first.save(output, save_all=True, append_images=rest, duration=duration_ms, loop=0, optimize=False)
        coordinate_frame = h5.attrs.get("coordinate_frame", "")
        if isinstance(coordinate_frame, bytes):
            coordinate_frame = coordinate_frame.decode()

    return {
        "schema": SCHEMA,
        "status": "actual_saved_state_gif_rendered",
        "source": str(source),
        "source_sha256": sha256(source),
        "source_report_output_sha256": source_report_sha,
        "gif": str(output),
        "gif_sha256": sha256(output),
        "frames": int(frame_count),
        "particles": int(particle_count),
        "selected_frames": selected.tolist(),
        "selected_times_s": selected_times,
        "fluid_counts": fluid_counts,
        "initial_fluid_mass_kg": initial_mass,
        "coordinate_frame": coordinate_frame,
        "visual_decimation_only": True,
        "numerical_qualification": "not_assessed",
        "q_n_status": "not_assessed",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-report", type=Path)
    parser.add_argument("--max-points", type=int, default=6000)
    parser.add_argument("--duration-ms", type=int, default=350)
    args = parser.parse_args(argv)
    result = render(args.source, json.loads(args.metadata.read_text()), args.output, args.source_report, args.max_points, args.duration_ms)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
