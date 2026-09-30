#!/usr/bin/env python3
"""Render actual F3 saved states as a PNG preview.

The preview reads the immutable converted HDF5 only.  It decimates points for
the bitmap, while keeping the complete trajectory in the source artifact.  A
preview is evidence of rendering and provenance, not a numerical
qualification result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SCHEMA = "ds02.f3.actual-preview.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _geometry(metadata: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    try:
        tank = metadata["physical_binding"]["geometry"]["tank"]
        low = np.asarray(tank["low_m"], dtype=float)
        size = np.asarray(tank["size_m"], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("F3 owner metadata lacks physical_binding.geometry.tank") from exc
    if low.shape != (3,) or size.shape != (3,) or not np.isfinite(low).all() or not np.isfinite(size).all() or np.any(size <= 0):
        raise ValueError("F3 tank geometry must contain finite positive 3D low_m/size_m")
    return low, low + size


def _source_sha_from_report(report_path: Path | None) -> tuple[str | None, str]:
    if report_path is None:
        return None, "not_recomputed_preview_only"
    report = json.loads(report_path.read_text())
    value = report.get("output_sha256")
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("conversion report lacks output_sha256")
    return value, "conversion_report_output_sha256"


def render(
    source: Path,
    metadata: Mapping[str, Any],
    output: Path,
    *,
    report_path: Path | None = None,
    max_points: int = 6000,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"preview already exists: {output}")
    if max_points < 100:
        raise ValueError("max_points must be at least 100")
    low, high = _geometry(metadata)
    source_sha256, source_hash_status = _source_sha_from_report(report_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with h5py.File(source, "r") as h5:
        for name in ("time", "position", "valid", "type", "mass"):
            if name not in h5:
                raise ValueError(f"converted F3 HDF5 lacks {name}")
        times = np.asarray(h5["time"][:], dtype=float)
        if times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
            raise ValueError("F3 preview requires finite strictly increasing time")
        frames, particles = h5["valid"].shape
        if h5["position"].shape != (frames, particles, 3) or h5["type"].shape != (frames, particles):
            raise ValueError("F3 preview source shapes are inconsistent")
        initial_valid = np.asarray(h5["valid"][0], dtype=bool)
        initial_type = np.asarray(h5["type"][0])
        initial_fluid = initial_valid & (initial_type == 3)
        initial_position = np.asarray(h5["position"][0], dtype=float)
        source_code = np.where(initial_position[:, 0] < 0.0, 0, 1)
        initial_mass = float(np.asarray(h5["mass"][0], dtype=float)[initial_fluid].sum(dtype=np.float64))
        targets = np.linspace(times[0], times[-1], 5)
        selected = np.asarray([int(np.argmin(np.abs(times - target))) for target in targets], dtype=int)
        selected = np.unique(selected)

        figure, axes = plt.subplots(2, len(selected), figsize=(4.1 * len(selected), 7.2), squeeze=False, constrained_layout=True)
        fluid_counts: list[int] = []
        for column, frame in enumerate(selected):
            valid = np.asarray(h5["valid"][frame], dtype=bool)
            particle_type = np.asarray(h5["type"][frame])
            fluid = valid & (particle_type == 3)
            fluid_indices = np.flatnonzero(fluid)
            stride = max(1, int(np.ceil(len(fluid_indices) / max_points)))
            fluid_indices = fluid_indices[::stride]
            fluid_counts.append(int(np.sum(fluid)))
            boundary_indices = np.flatnonzero(valid & (particle_type != 3))[::8]
            positions = np.asarray(h5["position"][frame], dtype=float)
            boundary = positions[boundary_indices]
            points = positions[fluid_indices]
            colors = np.where(source_code[fluid_indices] == 0, "#2878b5", "#e58e26")

            for row, transverse_axis in enumerate((1, 2)):
                axis = axes[row, column]
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
                axis.set_title(f"t = {times[frame]:.4f} s", fontsize=9)
                if transverse_axis == 2:
                    axis.axhline(high[2], color="#a33", linewidth=0.7, linestyle=":", alpha=0.7)

        figure.suptitle(
            f"F3 legacy plain actual saved states; fluid mass {initial_mass:.6f} kg\n"
            "blue/orange = initial x<0/x≥0; gray = typed non-fluid; Q-N pending",
            fontsize=12,
        )
        figure.savefig(output, dpi=160, format="png")
        plt.close(figure)
        coordinate_frame = h5.attrs.get("coordinate_frame", "")
        if isinstance(coordinate_frame, bytes):
            coordinate_frame = coordinate_frame.decode()

    return {
        "schema": SCHEMA,
        "status": "actual_saved_state_png_rendered",
        "source": str(source),
        "source_sha256": source_sha256,
        "source_sha256_status": source_hash_status,
        "preview": str(output),
        "preview_sha256": _sha256(output),
        "frames": int(frames),
        "particles": int(particles),
        "selected_frames": selected.tolist(),
        "selected_times_s": times[selected].tolist(),
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
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source-report", type=Path)
    parser.add_argument("--max-points", type=int, default=6000)
    args = parser.parse_args(argv)
    result = render(
        args.source,
        json.loads(args.metadata.read_text()),
        args.output,
        report_path=args.source_report,
        max_points=args.max_points,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
