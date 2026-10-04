#!/usr/bin/env python3
"""Source-backed H5/native-fluid versus continuous-bed diagnostic worker.

The committed module is a future Root-strict-worker implementation.  Merely
importing it, or running ``--check``, does not open an H5/BI4/CSV source and
does not render a ParaView scene.  A real invocation is intentionally separate
from this source-only handoff and must be authorized by Root.

The worker scans every typed native frame, retaining every valid Type-3 fluid
row in its denominators.  It computes geometry diagnostics against the exact
piecewise bed nodes and writes three ordinary matplotlib x/z overlays for
frames 0, 400, and 800.  The 1-DP and 2-DP distances are diagnostic bins; they
are not acceptance thresholds, a convergence gate, a rescaling instruction,
or permission to mask/drop a valid fluid row.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SCHEMA = "ds02.f5.stage1.nativefluid-bed-support-diagnostic.v1"
FLUID_TYPE = 3
DP_M = 0.02
DEPTH_TOLERANCES_M = (0.02, 0.04)
BED_NODES_XZ_M = np.asarray(
    (
        (-0.2, 0.0),
        (2.0, 0.0),
        (3.0, 0.28),
        (3.6, 0.448),
        (3.9, 0.448),
        (4.4, 0.05),
        (4.8, 0.05),
    ),
    dtype=np.float64,
)
BED_X_BOUNDS_M = (float(BED_NODES_XZ_M[0, 0]), float(BED_NODES_XZ_M[-1, 0]))
BED_Y_BOUNDS_M = (-0.15, 0.15)
FLUME_Y_BOUNDS_M = (-0.18, 0.18)
TANK_Z_BOUNDS_M = (-0.15, 0.80)
PLANE_HALF_WIDTH_M = DP_M / 2.0
DEFAULT_SAMPLE_LIMIT = 10


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def bed_profile_z(x: np.ndarray | Sequence[float] | float) -> np.ndarray:
    """Return the piecewise-linear continuous-bed z for x.

    Values outside the declared x domain are NaN.  The caller must retain
    those points in its native-fluid denominator and report them as
    unevaluable; this function never clips or extrapolates them.
    """

    values = np.asarray(x, dtype=np.float64)
    flat = values.reshape(-1)
    result = np.full(flat.shape, np.nan, dtype=np.float64)
    inside = (flat >= BED_X_BOUNDS_M[0]) & (flat <= BED_X_BOUNDS_M[1])
    result[inside] = np.interp(
        flat[inside], BED_NODES_XZ_M[:, 0], BED_NODES_XZ_M[:, 1]
    )
    return result.reshape(values.shape)


def uid_digest(ids: np.ndarray | Sequence[int]) -> str:
    """Digest sorted particle IDs as explicit little-endian uint64 values."""

    values = np.asarray(ids, dtype="<u8").reshape(-1)
    return sha256_bytes(np.sort(values, kind="stable").tobytes(order="C"))


def _fraction(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _finite_scalar(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def _sample_rows(
    indices: np.ndarray,
    positions: np.ndarray,
    bed_z: np.ndarray,
    depths: np.ndarray,
    masses: np.ndarray,
    particle_ids: np.ndarray,
    limit: int,
) -> list[dict[str, Any]]:
    """Return deterministic deepest rows, retaining native coordinates."""

    if indices.size == 0:
        return []
    order = indices[np.argsort(depths[indices], kind="stable")[::-1][:limit]]
    rows: list[dict[str, Any]] = []
    for rank, index in enumerate(order, start=1):
        mass = float(masses[index]) if math.isfinite(float(masses[index])) else None
        rows.append(
            {
                "rank": rank,
                "particle_id": int(particle_ids[index]),
                "x_m": float(positions[index, 0]),
                "y_m": float(positions[index, 1]),
                "z_m": float(positions[index, 2]),
                "bed_z_m": float(bed_z[index]),
                "depth_below_bed_m": float(depths[index]),
                "mass_kg": mass,
            }
        )
    return rows


def frame_metrics(
    *,
    frame_index: int,
    time_s: float,
    positions: np.ndarray,
    valid: np.ndarray,
    particle_type: np.ndarray,
    mass: np.ndarray,
    particle_ids: np.ndarray,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    """Compute one frame's native-fluid and bed-distance diagnostics.

    ``valid_type3`` is the complete native fluid row set.  All fractions use
    that set unless a field explicitly names ``finite_position`` or
    ``distance_evaluable`` as its denominator.  No invalid row is silently
    deleted from the report.
    """

    position_array = np.asarray(positions, dtype=np.float64)
    valid_array = np.asarray(valid).reshape(-1).astype(bool, copy=False)
    type_array = np.asarray(particle_type).reshape(-1)
    mass_array = np.asarray(mass, dtype=np.float64).reshape(-1)
    id_array = np.asarray(particle_ids).reshape(-1)
    if position_array.ndim != 2 or position_array.shape[1] != 3:
        raise ValueError("positions must have shape (particles, 3)")
    particle_count = position_array.shape[0]
    for name, array in (
        ("valid", valid_array),
        ("particle_type", type_array),
        ("mass", mass_array),
        ("particle_ids", id_array),
    ):
        if array.shape[0] != particle_count:
            raise ValueError(f"{name} length does not match positions")

    valid_type3 = valid_array & (type_array == FLUID_TYPE)
    finite_position = np.isfinite(position_array).all(axis=1)
    finite_fluid = valid_type3 & finite_position
    x = position_array[:, 0]
    y = position_array[:, 1]
    z = position_array[:, 2]
    x_in_bed = finite_fluid & (x >= BED_X_BOUNDS_M[0]) & (x <= BED_X_BOUNDS_M[1])
    y_in_bed = finite_fluid & (y >= BED_Y_BOUNDS_M[0]) & (y <= BED_Y_BOUNDS_M[1])
    y_in_flume = finite_fluid & (y >= FLUME_Y_BOUNDS_M[0]) & (y <= FLUME_Y_BOUNDS_M[1])
    z_in_tank = finite_fluid & (z >= TANK_Z_BOUNDS_M[0]) & (z <= TANK_Z_BOUNDS_M[1])
    distance_evaluable = finite_fluid & x_in_bed
    profile_z = np.full(particle_count, np.nan, dtype=np.float64)
    profile_z[distance_evaluable] = bed_profile_z(x[distance_evaluable])
    depth = profile_z - z
    mass_finite = np.isfinite(mass_array)
    finite_mass_fluid = valid_type3 & mass_finite

    depth_bins: dict[str, Any] = {}
    for tolerance_m in DEPTH_TOLERANCES_M:
        key = f"{tolerance_m:.2f}m"
        below = distance_evaluable & (depth > tolerance_m)
        finite_mass_below = below & mass_finite
        depth_bins[key] = {
            "tolerance_m": tolerance_m,
            "interpretation": "diagnostic_distance_bin_only",
            "count": int(below.sum()),
            "fraction_of_valid_type3_native": _fraction(int(below.sum()), int(valid_type3.sum())),
            "fraction_of_distance_evaluable": _fraction(
                int(below.sum()), int(distance_evaluable.sum())
            ),
            "mass_sum_finite_kg": float(mass_array[finite_mass_below].sum()),
            "mass_nonfinite_count": int((below & ~mass_finite).sum()),
            "deepest_samples": _sample_rows(
                np.flatnonzero(below),
                position_array,
                profile_z,
                depth,
                mass_array,
                id_array,
                sample_limit,
            ),
        }

    deepest = _sample_rows(
        np.flatnonzero(distance_evaluable),
        position_array,
        profile_z,
        depth,
        mass_array,
        id_array,
        sample_limit,
    )
    finite_mass_values = mass_array[finite_mass_fluid]
    result: dict[str, Any] = {
        "frame": int(frame_index),
        "time_s": float(time_s),
        "particle_axis_count": int(particle_count),
        "valid_count": int(valid_array.sum()),
        "valid_type3_native_count": int(valid_type3.sum()),
        "type3_fraction_of_particle_axis": _fraction(
            int(valid_type3.sum()), particle_count
        ),
        "finite_position_count_valid_type3": int(finite_fluid.sum()),
        "nonfinite_position_count_valid_type3": int((valid_type3 & ~finite_position).sum()),
        "x_in_actual_bed_domain_count": int(x_in_bed.sum()),
        "x_outside_actual_bed_domain_count_finite_type3": int(
            (finite_fluid & ~x_in_bed).sum()
        ),
        "y_in_bed_width_count": int(y_in_bed.sum()),
        "y_in_flume_count": int(y_in_flume.sum()),
        "y_outside_flume_count_finite_type3": int((finite_fluid & ~y_in_flume).sum()),
        "z_in_tank_envelope_count_diagnostic": int(z_in_tank.sum()),
        "distance_evaluable_count": int(distance_evaluable.sum()),
        "distance_unevaluable_count": int((valid_type3 & ~distance_evaluable).sum()),
        "mass_finite_count_valid_type3": int(finite_mass_fluid.sum()),
        "mass_nonfinite_count_valid_type3": int((valid_type3 & ~mass_finite).sum()),
        "mass_sum_finite_kg": float(finite_mass_values.sum()),
        "uid_digest_sorted_uint64le_sha256": uid_digest(id_array[valid_type3]),
        "finite_position_uid_digest_sorted_uint64le_sha256": uid_digest(
            id_array[finite_fluid]
        ),
        "finite_fluid_extrema_m": _extrema(position_array[finite_fluid]),
        "deepest_evaluable_samples": deepest,
        "depth_bins": depth_bins,
        "denominator_policy": {
            "native_fluid": "valid && type == 3; retained even if position/mass is nonfinite or outside declared profile domain",
            "finite_position": "valid_type3_native && all position coordinates finite",
            "distance_evaluable": "finite_position && x lies within exact bed node x domain",
            "no_mask_or_drop": True,
        },
    }
    return result


def _extrema(points: np.ndarray) -> dict[str, list[float] | None]:
    if points.size == 0:
        return {"min_m": None, "max_m": None}
    return {
        "min_m": [float(value) for value in np.min(points, axis=0)],
        "max_m": [float(value) for value in np.max(points, axis=0)],
    }


def initial_plane_occupancy(
    *,
    positions: np.ndarray,
    valid: np.ndarray,
    particle_type: np.ndarray,
    mass: np.ndarray,
    particle_ids: np.ndarray,
    plane_half_width_m: float = PLANE_HALF_WIDTH_M,
) -> dict[str, Any]:
    """Describe frame-zero occupancy around each exact bed-node x plane."""

    position_array = np.asarray(positions, dtype=np.float64)
    valid_type3 = np.asarray(valid).reshape(-1).astype(bool) & (
        np.asarray(particle_type).reshape(-1) == FLUID_TYPE
    )
    finite = valid_type3 & np.isfinite(position_array).all(axis=1)
    profile = bed_profile_z(position_array[:, 0])
    masses = np.asarray(mass, dtype=np.float64).reshape(-1)
    ids = np.asarray(particle_ids).reshape(-1)
    planes: list[dict[str, Any]] = []
    for x_plane, bed_z in BED_NODES_XZ_M:
        near = finite & (np.abs(position_array[:, 0] - x_plane) <= plane_half_width_m)
        near_evaluable = near & np.isfinite(profile)
        depth = profile - position_array[:, 2]
        planes.append(
            {
                "x_plane_m": float(x_plane),
                "bed_z_m": float(bed_z),
                "half_width_m": float(plane_half_width_m),
                "occupancy_count_valid_type3": int(near.sum()),
                "occupancy_fraction_of_frame0_native_fluid": _fraction(
                    int(near.sum()), int(valid_type3.sum())
                ),
                "distance_evaluable_count": int(near_evaluable.sum()),
                "z_min_m": _finite_scalar(np.min(position_array[near, 2])) if near.any() else None,
                "z_max_m": _finite_scalar(np.max(position_array[near, 2])) if near.any() else None,
                "below_bed_count_over_1dp": int(
                    (near_evaluable & (depth > DEPTH_TOLERANCES_M[0])).sum()
                ),
                "below_bed_count_over_2dp": int(
                    (near_evaluable & (depth > DEPTH_TOLERANCES_M[1])).sum()
                ),
                "uid_digest_sorted_uint64le_sha256": uid_digest(ids[near]),
                "mass_sum_finite_kg": float(masses[near & np.isfinite(masses)].sum()),
            }
        )
    return {
        "plane_definition": "exact continuous-bed node x coordinates",
        "plane_half_width_m": float(plane_half_width_m),
        "retains_all_valid_type3_in_frame0": True,
        "planes": planes,
    }


def _parse_times(xdmf_path: Path, expected_frames: int) -> list[float]:
    root = ET.parse(xdmf_path).getroot()
    times = [float(node.attrib["Value"]) for node in root.iter("Time")]
    if len(times) != expected_frames:
        raise ValueError(
            f"XDMF has {len(times)} Time entries; expected {expected_frames}"
        )
    return times


def _dataset(handle: Any, name: str) -> Any:
    if name in handle:
        return handle[name]
    slash_name = "/" + name
    if slash_name in handle:
        return handle[slash_name]
    raise KeyError(f"required H5 dataset missing: {name}")


def _deterministic_indices(count: int, max_points: int) -> np.ndarray:
    if count <= max_points:
        return np.arange(count, dtype=np.int64)
    return np.unique(np.linspace(0, count - 1, max_points, dtype=np.int64))


def _write_overlay(
    *,
    frame_index: int,
    time_s: float,
    positions: np.ndarray,
    valid: np.ndarray,
    particle_type: np.ndarray,
    output_path: Path,
    max_points: int,
) -> None:
    """Write one standard matplotlib diagnostic overlay.

    This function is called only by an authorized real worker invocation.  It
    receives one frame at a time and never changes the source H5/XDMF data.
    """

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    valid_type3 = np.asarray(valid).reshape(-1).astype(bool) & (
        np.asarray(particle_type).reshape(-1) == FLUID_TYPE
    )
    positions = np.asarray(positions, dtype=np.float64)
    finite = valid_type3 & np.isfinite(positions).all(axis=1)
    fluid_indices = np.flatnonzero(finite)
    selected = fluid_indices[_deterministic_indices(fluid_indices.size, max_points)]
    x = positions[selected, 0]
    z = positions[selected, 2]
    depth = bed_profile_z(x) - z
    below = depth > DEPTH_TOLERANCES_M[0]
    fig, ax = plt.subplots(figsize=(12, 5), dpi=150)
    if selected.size:
        ax.scatter(x[~below], z[~below], s=1.0, c="#2070b4", alpha=0.45, linewidths=0)
        if below.any():
            ax.scatter(x[below], z[below], s=4.0, c="#d7301f", alpha=0.85, linewidths=0)
    ax.plot(BED_NODES_XZ_M[:, 0], BED_NODES_XZ_M[:, 1], color="#333333", linewidth=2.0, label="exact continuous bed")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    ax.set_title(f"F5 native Type-3 fluid versus bed, frame {frame_index}, t={time_s:.9f} s")
    ax.grid(True, alpha=0.2)
    ax.legend(loc="best")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)


def run_worker(
    *,
    trajectory_h5: Path,
    xdmf: Path,
    output_dir: Path,
    expected_h5_sha256: str | None,
    expected_xdmf_sha256: str | None,
    overlay_frames: Sequence[int],
    max_plot_points: int,
    sample_limit: int,
) -> dict[str, Any]:
    """Run the future full-frame scan; this function is never called by tests."""

    import h5py

    expected_frames = 801
    times = _parse_times(xdmf, expected_frames)
    h5_sha = sha256_file(trajectory_h5)
    xdmf_sha = sha256_file(xdmf)
    if expected_h5_sha256 and h5_sha != expected_h5_sha256:
        raise ValueError(f"H5 SHA256 mismatch: {h5_sha} != {expected_h5_sha256}")
    if expected_xdmf_sha256 and xdmf_sha != expected_xdmf_sha256:
        raise ValueError(f"XDMF SHA256 mismatch: {xdmf_sha} != {expected_xdmf_sha256}")

    output_dir.mkdir(parents=True, exist_ok=True)
    frame_reports: list[dict[str, Any]] = []
    overlay_paths: list[dict[str, Any]] = []
    with h5py.File(trajectory_h5, "r") as handle:
        positions_ds = _dataset(handle, "position")
        valid_ds = _dataset(handle, "valid")
        type_ds = _dataset(handle, "type")
        mass_ds = _dataset(handle, "mass")
        particle_ids_ds = _dataset(handle, "particle_id")
        if positions_ds.shape[0] != expected_frames:
            raise ValueError(f"position frame count is {positions_ds.shape[0]}, expected {expected_frames}")
        particle_ids = np.asarray(particle_ids_ds[...]).reshape(-1)
        particle_count = int(positions_ds.shape[1])
        if particle_count != 214515:
            raise ValueError(f"particle axis is {particle_count}, expected 214515")
        for frame_index in range(expected_frames):
            positions = np.asarray(positions_ds[frame_index, ...])
            valid = np.asarray(valid_ds[frame_index, ...])
            particle_type = np.asarray(type_ds[frame_index, ...])
            mass = np.asarray(mass_ds[frame_index, ...])
            report = frame_metrics(
                frame_index=frame_index,
                time_s=times[frame_index],
                positions=positions,
                valid=valid,
                particle_type=particle_type,
                mass=mass,
                particle_ids=particle_ids,
                sample_limit=sample_limit,
            )
            frame_reports.append(report)
            if frame_index in overlay_frames:
                overlay_path = output_dir / f"nativefluid_bed_overlay_frame_{frame_index:04d}.png"
                _write_overlay(
                    frame_index=frame_index,
                    time_s=times[frame_index],
                    positions=positions,
                    valid=valid,
                    particle_type=particle_type,
                    output_path=overlay_path,
                    max_points=max_plot_points,
                )
                overlay_paths.append(
                    {
                        "frame": frame_index,
                        "time_s": times[frame_index],
                        "path": str(overlay_path),
                        "sha256": sha256_file(overlay_path),
                    }
                )
            if frame_index == 0:
                frame0_occupancy = initial_plane_occupancy(
                    positions=positions,
                    valid=valid,
                    particle_type=particle_type,
                    mass=mass,
                    particle_ids=particle_ids,
                )

    if len(frame_reports) != expected_frames:
        raise AssertionError("full frame scan did not produce 801 reports")
    report = {
        "schema": SCHEMA,
        "status": "completed_worker_output_pending_root_review",
        "diagnostic_only": True,
        "production_approval": "none",
        "q_n_status": "not_granted",
        "visual_review_status": "pending_root_review",
        "source_arrays_modified": False,
        "source_arrays_dropped_or_masked": False,
        "source": {
            "trajectory_h5": str(trajectory_h5),
            "trajectory_h5_sha256": h5_sha,
            "trajectory_h5_sha256_expected": expected_h5_sha256,
            "xdmf": str(xdmf),
            "xdmf_sha256": xdmf_sha,
            "xdmf_sha256_expected": expected_xdmf_sha256,
            "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
            "datasets": ["position", "valid", "type", "mass", "particle_id"],
        },
        "scan": {
            "frames_scanned": len(frame_reports),
            "frame_indices": [0, 400, 800],
            "full_scan_range": [0, 800],
            "times_s": {"first": times[0], "last": times[-1]},
            "particle_axis_count": 214515,
            "type_alias": {"fluid": 3},
            "bed_nodes_xz_m": BED_NODES_XZ_M.tolist(),
            "bed_x_domain_m": list(BED_X_BOUNDS_M),
            "bed_y_domain_m": list(BED_Y_BOUNDS_M),
            "flume_y_domain_m": list(FLUME_Y_BOUNDS_M),
            "depth_tolerances_m": list(DEPTH_TOLERANCES_M),
        },
        "frame_reports": frame_reports,
        "initial_frame_0_extrema_and_plane_occupancy": {
            "frame": 0,
            "extrema": frame_reports[0]["finite_fluid_extrema_m"],
            "plane_occupancy": frame0_occupancy,
        },
        "overlays": overlay_paths,
        "interpretation_boundary": {
            "depth_values_are_geometry_diagnostics": True,
            "tolerances_are_not_acceptance_thresholds": True,
            "no_convergence_or_rescale_claim": True,
            "no_root_cause_inferred": True,
            "valid_type3_denominator_retained": True,
        },
    }
    output_path = output_dir / "nativefluid_bed_support_diagnostic.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _synthetic_check() -> None:
    """Bounded API check; no H5, BI4, CSV, or plotting input is opened."""

    if not np.allclose(bed_profile_z(np.asarray([-0.2, 2.0, 3.0, 4.8])), [0, 0, 0.28, 0.05]):
        raise AssertionError("piecewise bed interpolation mismatch")
    positions = np.asarray(
        [[0.0, 0.0, 0.01], [3.0, 0.0, 0.20], [4.9, 0.0, 0.0], [0.0, 0.0, np.nan]],
        dtype=np.float64,
    )
    metrics = frame_metrics(
        frame_index=0,
        time_s=0.0,
        positions=positions,
        valid=np.asarray([1, 1, 1, 1], dtype=np.uint8),
        particle_type=np.asarray([3, 3, 3, 3], dtype=np.int8),
        mass=np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float64),
        particle_ids=np.asarray([10, 11, 12, 13], dtype=np.uint32),
    )
    assert metrics["valid_type3_native_count"] == 4
    assert metrics["finite_position_count_valid_type3"] == 3
    assert metrics["x_outside_actual_bed_domain_count_finite_type3"] == 1
    assert metrics["distance_unevaluable_count"] == 2
    assert metrics["denominator_policy"]["no_mask_or_drop"] is True
    occupancy = initial_plane_occupancy(
        positions=positions,
        valid=np.asarray([1, 1, 1, 1], dtype=np.uint8),
        particle_type=np.asarray([3, 3, 3, 3], dtype=np.int8),
        mass=np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float64),
        particle_ids=np.asarray([10, 11, 12, 13], dtype=np.uint32),
    )
    assert len(occupancy["planes"]) == len(BED_NODES_XZ_M)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run source-only synthetic API checks")
    parser.add_argument("--trajectory-h5", type=Path)
    parser.add_argument("--xdmf", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--expected-h5-sha256")
    parser.add_argument("--expected-xdmf-sha256")
    parser.add_argument("--overlay-frames", default="0,400,800")
    parser.add_argument("--max-plot-points", type=int, default=80000)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    args = parser.parse_args(argv)
    if args.check:
        _synthetic_check()
        print("source-only synthetic API checks passed")
        return 0
    required = (args.trajectory_h5, args.xdmf, args.output_dir)
    if any(value is None for value in required):
        parser.error("--trajectory-h5, --xdmf, and --output-dir are required for a real worker invocation")
    overlay_frames = tuple(int(item) for item in args.overlay_frames.split(",") if item.strip())
    if args.max_plot_points <= 0 or args.sample_limit <= 0:
        parser.error("--max-plot-points and --sample-limit must be positive")
    run_worker(
        trajectory_h5=args.trajectory_h5,
        xdmf=args.xdmf,
        output_dir=args.output_dir,
        expected_h5_sha256=args.expected_h5_sha256,
        expected_xdmf_sha256=args.expected_xdmf_sha256,
        overlay_frames=overlay_frames,
        max_plot_points=args.max_plot_points,
        sample_limit=args.sample_limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
