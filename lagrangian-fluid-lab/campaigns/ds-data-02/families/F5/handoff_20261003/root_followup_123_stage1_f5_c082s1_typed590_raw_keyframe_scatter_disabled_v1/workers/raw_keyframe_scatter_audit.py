#!/usr/bin/env python3
"""Read-only native keyframe scatter audit for F5 C082S1.

Root owns the registered CPU invocation. The worker opens the producer-attested
typed590 H5 read-only, selects exact saved frame indices, and plots original
particle rows. It never writes the source H5, hashes it, interpolates it,
resamples it, or reconstructs a free surface.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

SCIENCE_SUFFIXES = {".h5", ".dat", ".bi4", ".csv", ".vtk"}
BINDING_SCHEMA = "ds02.f5.c082s1.raw-keyframe-scatter-binding.fresh123.v1"
REPORT_SCHEMA = "ds02.f5.c082s1.raw-keyframe-scatter-audit.fresh123.v1"
FOCUS_FRAMES = (0, 97, 153, 219, 400, 718, 800)
EXPECTED_FRAMES = 801
EXPECTED_PARTICLES = 194427
EXPECTED_COUNTS = {"total": 194427, "fixed": 158559, "moving": 4210, "fluid": 31658, "floating": 0}
FLUID_TYPE = 3
MOVING_TYPE = 1
FIXED_TYPE = 0
FLOATING_TYPE = 2
VELOCITY_SCALE_MPS = (0.0, 0.6)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def finite_rows(values: Any, np: Any) -> Any:
    return np.isfinite(values).all(axis=-1)


def verify_binding(binding: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    require(binding.get("schema") == BINDING_SCHEMA, "binding schema")
    require(binding.get("source_only") is True and binding.get("read_only") is True, "source gate")
    require(binding.get("execution_allowed") is False, "binding must remain disabled")
    require(binding.get("expected_frames") == EXPECTED_FRAMES, "frame count")
    require(binding.get("expected_particles") == EXPECTED_PARTICLES, "particle axis")
    require(binding.get("expected_counts") == EXPECTED_COUNTS, "population counts")
    require(binding.get("focus_frames") == list(FOCUS_FRAMES), "focus frames")
    require(binding.get("no_resampling") is True and binding.get("no_interpolation") is True, "plot policy")
    require(binding.get("no_array_edit") is True, "array policy")
    require(binding.get("datasets_required") == ["time", "position", "velocity", "valid", "particle_id", "type", "mk"], "dataset contract")
    require(binding.get("native_bed_marker_mk") == 50 and binding.get("source_mkbound") == 40, "Mk marker mapping")
    h5_path = Path(binding["trajectory_h5"]).resolve()
    require(h5_path.is_file(), f"producer H5 missing: {h5_path}")
    manifest = load_json(Path(binding["xmf_manifest"]))
    require(manifest.get("trajectory_h5") == str(h5_path), "manifest H5 path")
    require(manifest.get("trajectory_h5_sha256") == binding["trajectory_h5_sha256"], "producer H5 SHA attestation")
    require(manifest.get("frames") == EXPECTED_FRAMES and manifest.get("particles") == EXPECTED_PARTICLES, "manifest shape")
    conversion = load_json(Path(binding["conversion_report"]))
    require(conversion.get("conversion_status") == "completed", "typed conversion status")
    require(conversion.get("output_hdf5") == str(h5_path), "conversion H5 path")
    require(conversion.get("output_sha256") == binding["trajectory_h5_sha256"], "conversion H5 attestation")
    require(conversion.get("frames") == EXPECTED_FRAMES and conversion.get("particles") == EXPECTED_PARTICLES, "conversion shape")
    solver_dimension = conversion.get("solver_dimension", {})
    require(solver_dimension.get("solver_dimension") == 3 and solver_dimension.get("xml_data2d") == "false", "3D producer")
    receipt = load_json(Path(binding["typed_receipt"]))
    require(receipt.get("returncode", receipt.get("status")) in (0, "completed"), "typed receipt status")
    require(binding.get("fullnative_gate", {}).get("status") == "WAIT", "fullnative gate")
    return manifest, conversion, receipt


def uid_difference(expected: Any, observed: Any, np: Any) -> tuple[int, int]:
    expected = np.asarray(expected, dtype=np.uint64)
    observed = np.asarray(observed, dtype=np.uint64)
    return int(np.setdiff1d(expected, observed).size), int(np.setdiff1d(observed, expected).size)


def plot_scatter(
    *,
    plt: Any,
    np: Any,
    frame: int,
    time_s: float,
    position: Any,
    velocity: Any,
    valid: Any,
    particle_type: Any,
    initial_position: Any,
    initial_valid: Any,
    output_dir: Path,
    tag: str,
    mode: str,
    window: dict[str, list[float]],
) -> str:
    finite_position = finite_rows(position, np)
    finite_velocity = finite_rows(velocity, np)
    active = valid & finite_position
    fluid = active & (particle_type == FLUID_TYPE) & finite_velocity
    fixed_moving = active & np.isin(particle_type, [FIXED_TYPE, MOVING_TYPE])
    if mode == "all-domain-xz":
        selected = active
        xlim = None
        ylim = None
        xlabel, ylabel = "x (m)", "z (m)"
        xdata, ydata = position[selected, 0], position[selected, 2]
        initial_selected = initial_valid & finite_rows(initial_position, np)
        initial_x, initial_y = initial_position[initial_selected, 0], initial_position[initial_selected, 2]
        fluid_selected, fixed_selected = fluid, fixed_moving
    elif mode == "shoreline-local-xz":
        selected = active & (position[:, 0] >= window["x_m"][0]) & (position[:, 0] <= window["x_m"][1]) & (position[:, 1] >= window["y_m"][0]) & (position[:, 1] <= window["y_m"][1]) & (position[:, 2] >= window["z_m"][0]) & (position[:, 2] <= window["z_m"][1])
        xlim, ylim = window["x_m"], window["z_m"]
        xlabel, ylabel = "x (m)", "z (m)"
        xdata, ydata = position[selected, 0], position[selected, 2]
        initial_selected = initial_valid & finite_rows(initial_position, np) & (initial_position[:, 0] >= window["x_m"][0]) & (initial_position[:, 0] <= window["x_m"][1]) & (initial_position[:, 1] >= window["y_m"][0]) & (initial_position[:, 1] <= window["y_m"][1]) & (initial_position[:, 2] >= window["z_m"][0]) & (initial_position[:, 2] <= window["z_m"][1])
        initial_x, initial_y = initial_position[initial_selected, 0], initial_position[initial_selected, 2]
        fluid_selected, fixed_selected = fluid & selected, fixed_moving & selected
    elif mode == "shoreline-local-yz":
        selected = active & (position[:, 0] >= window["x_m"][0]) & (position[:, 0] <= window["x_m"][1]) & (position[:, 1] >= window["y_m"][0]) & (position[:, 1] <= window["y_m"][1]) & (position[:, 2] >= window["z_m"][0]) & (position[:, 2] <= window["z_m"][1])
        xlim, ylim = window["y_m"], window["z_m"]
        xlabel, ylabel = "y (m)", "z (m)"
        xdata, ydata = position[selected, 1], position[selected, 2]
        initial_selected = initial_valid & finite_rows(initial_position, np) & (initial_position[:, 0] >= window["x_m"][0]) & (initial_position[:, 0] <= window["x_m"][1]) & (initial_position[:, 1] >= window["y_m"][0]) & (initial_position[:, 1] <= window["y_m"][1]) & (initial_position[:, 2] >= window["z_m"][0]) & (initial_position[:, 2] <= window["z_m"][1])
        initial_x, initial_y = initial_position[initial_selected, 1], initial_position[initial_selected, 2]
        fluid_selected, fixed_selected = fluid & selected, fixed_moving & selected
    else:
        raise ValueError(f"unknown plot mode: {mode}")

    fig, ax = plt.subplots(figsize=(11, 6), constrained_layout=True)
    if fixed_selected.any():
        if mode == "shoreline-local-yz":
            ax.scatter(position[fixed_selected, 1], position[fixed_selected, 2], s=0.35, c="0.55", alpha=0.55, linewidths=0, rasterized=True)
        else:
            ax.scatter(position[fixed_selected, 0], position[fixed_selected, 2], s=0.35, c="0.55", alpha=0.55, linewidths=0, rasterized=True)
    if fluid_selected.any():
        speed = np.linalg.norm(velocity[fluid_selected], axis=1)
        if mode == "shoreline-local-yz":
            xfluid, yfluid = position[fluid_selected, 1], position[fluid_selected, 2]
        else:
            xfluid, yfluid = position[fluid_selected, 0], position[fluid_selected, 2]
        scatter = ax.scatter(xfluid, yfluid, c=speed, cmap="viridis", vmin=VELOCITY_SCALE_MPS[0], vmax=VELOCITY_SCALE_MPS[1], s=0.45, linewidths=0, rasterized=True)
        colorbar = fig.colorbar(scatter, ax=ax)
        colorbar.set_label("fluid velocity magnitude (m/s)")
    if initial_x.size:
        ax.scatter(initial_x, initial_y, s=0.25, facecolors="none", edgecolors="black", alpha=0.18, linewidths=0.2, rasterized=True, label="frame 0 original fluid positions")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{tag} | frame {frame:04d} | actual t={time_s:.9g} s | native rows | diagnostic only")
    ax.grid(False)
    if xlim is not None:
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
    if initial_x.size:
        ax.legend(loc="upper left", markerscale=4, fontsize=7)
    output = output_dir / f"{tag}-frame-{frame:04d}-{mode}.png"
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return str(output)


def run(binding_path: Path, output_dir: Path) -> dict[str, Any]:
    import h5py
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    binding = load_json(binding_path)
    manifest, conversion, receipt = verify_binding(binding)
    require(not output_dir.exists(), f"refusing to reuse output directory: {output_dir}")
    output_dir.mkdir(parents=True)

    focus = list(FOCUS_FRAMES)
    window = binding["display_window_m"]
    h5_path = Path(binding["trajectory_h5"]).resolve()
    rows: list[dict[str, Any]] = []
    plot_paths: list[str] = []
    with h5py.File(h5_path, "r") as h5:
        required = tuple(binding["datasets_required"])
        for name in required:
            require(name in h5, f"missing H5 dataset: {name}")
        time_ds, ids_ds = h5["time"], h5["particle_id"]
        position_ds, velocity_ds = h5["position"], h5["velocity"]
        valid_ds, type_ds, mk_ds = h5["valid"], h5["type"], h5["mk"]
        require(time_ds.shape == (EXPECTED_FRAMES,), "time shape")
        require(ids_ds.shape == (EXPECTED_PARTICLES,), "UID axis shape")
        require(position_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES, 3), "position shape")
        require(velocity_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES, 3), "velocity shape")
        require(valid_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES), "valid shape")
        require(type_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES), "type shape")
        require(mk_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES), "Mk shape")
        times = np.asarray(time_ds[...], dtype=np.float64)
        particle_ids = np.asarray(ids_ds[...], dtype=np.uint64)
        require(np.isfinite(times).all() and np.all(np.diff(times) > 0), "H5 time axis not finite/increasing")
        require(np.unique(particle_ids).size == EXPECTED_PARTICLES, "UID axis not unique")
        initial_valid = np.asarray(valid_ds[0, ...]).astype(bool, copy=False)
        initial_type = np.asarray(type_ds[0, ...])
        initial_mk = np.asarray(mk_ds[0, ...])
        initial_position = np.asarray(position_ds[0, ...], dtype=np.float64)
        initial_fluid = initial_valid & (initial_type == FLUID_TYPE)
        require(int(initial_fluid.sum()) == EXPECTED_COUNTS["fluid"], "initial fluid count")
        require(int((initial_valid & (initial_type == MOVING_TYPE)).sum()) == EXPECTED_COUNTS["moving"], "initial moving count")
        require(int((initial_valid & (initial_type == FIXED_TYPE)).sum()) == EXPECTED_COUNTS["fixed"], "initial fixed count")
        require(int((initial_valid & (initial_type == FLOATING_TYPE)).sum()) == EXPECTED_COUNTS["floating"], "initial floating count")
        require(np.isfinite(initial_position[initial_valid]).all(), "initial active position nonfinite")
        initial_fluid_ids = particle_ids[initial_fluid]
        for frame in focus:
            valid = np.asarray(valid_ds[frame, ...]).astype(bool, copy=False)
            particle_type = np.asarray(type_ds[frame, ...])
            position = np.asarray(position_ds[frame, ...], dtype=np.float64)
            velocity = np.asarray(velocity_ds[frame, ...], dtype=np.float64)
            mk = np.asarray(mk_ds[frame, ...])
            finite_position = np.isfinite(position).all(axis=1)
            finite_velocity = np.isfinite(velocity).all(axis=1)
            fluid = valid & (particle_type == FLUID_TYPE)
            fluid_finite = fluid & finite_position & finite_velocity
            fluid_ids = particle_ids[fluid]
            missing_uid, extra_uid = uid_difference(initial_fluid_ids, fluid_ids, np)
            current_active = valid
            rows.append({
                "frame": frame,
                "actual_time_step_index": frame,
                "actual_time_s": float(times[frame]),
                "valid_count": int(valid.sum()),
                "fluid_count": int(fluid.sum()),
                "fixed_count": int((valid & (particle_type == FIXED_TYPE)).sum()),
                "moving_count": int((valid & (particle_type == MOVING_TYPE)).sum()),
                "floating_count": int((valid & (particle_type == FLOATING_TYPE)).sum()),
                "uid_missing_vs_frame0_fluid": missing_uid,
                "uid_extra_vs_frame0_fluid": extra_uid,
                "nonfinite_active_position_count": int((current_active & ~finite_position).sum()),
                "nonfinite_active_velocity_count": int((current_active & ~finite_velocity).sum()),
                "type_changed_from_frame0_count": int((particle_type != initial_type).sum()),
                "mk_changed_from_frame0_count": int((mk != initial_mk).sum()),
                "native_mk50_valid_count": int((valid & (mk == int(binding["native_bed_marker_mk"]))).sum()),
                "fluid_speed_max_mps": float(np.linalg.norm(velocity[fluid_finite], axis=1).max()) if fluid_finite.any() else math.nan,
                "fluid_speed_p95_mps": float(np.percentile(np.linalg.norm(velocity[fluid_finite], axis=1), 95.0)) if fluid_finite.any() else math.nan,
                "display_policy": "original rows only; local plots select rows by camera window without editing source",
            })
            tag = str(binding["candidate_id"])
            for mode in ("all-domain-xz", "shoreline-local-xz", "shoreline-local-yz"):
                plot_paths.append(plot_scatter(
                    plt=plt, np=np, frame=frame, time_s=float(times[frame]),
                    position=position, velocity=velocity, valid=valid, particle_type=particle_type,
                    initial_position=initial_position, initial_valid=initial_fluid,
                    output_dir=output_dir, tag=tag, mode=mode, window=window,
                ))
    report = {
        "schema": REPORT_SCHEMA,
        "status": "completed_raw_keyframe_scatter_audit",
        "case_id": binding["case_id"],
        "candidate_id": binding["candidate_id"],
        "condition_id": binding["condition_id"],
        "inputs": {
            "trajectory_h5": str(h5_path),
            "trajectory_h5_sha256": binding["trajectory_h5_sha256"],
            "source_h5_opened_read_only": True,
            "source_h5_hashed_by_worker": False,
            "root598_manifest": binding["xmf_manifest"],
            "root598_manifest_sha256": binding["xmf_manifest_sha256"],
            "conversion_report": binding["conversion_report"],
            "typed_receipt": binding["typed_receipt"],
        },
        "actual_saved_frames": rows,
        "plot_outputs": plot_paths,
        "plot_contract": {
            "focus_frames": focus,
            "actual_time_step_index": "saved H5 frame index; no uniform-spacing assumption",
            "coordinates": "native source metres",
            "fluid_color": "native velocity magnitude m/s",
            "velocity_color_scale_mps": list(VELOCITY_SCALE_MPS),
            "fixed_moving_color": "gray",
            "initial_overlay": "original frame-0 fluid positions",
            "all_original_rows_used": True,
            "resampling": False,
            "interpolation": False,
            "array_edit": False,
            "free_surface_reconstruction": False,
        },
        "interpretation": {
            "diagnostic_only": True,
            "visual_mechanism_acceptance": False,
            "precision_granted": False,
            "q_n_granted": False,
            "case_increment": 0,
            "fullnative_gate": "WAIT",
        },
    }
    report_path = output_dir / "raw-keyframe-scatter-audit.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.binding, args.output_dir)
    print(json.dumps({
        "status": report["status"],
        "candidate_id": report["candidate_id"],
        "frames": len(report["actual_saved_frames"]),
        "png_count": len(report["plot_outputs"]),
        "h5_hashed_by_worker": report["inputs"]["source_h5_hashed_by_worker"],
        "visual_mechanism_acceptance": report["interpretation"]["visual_mechanism_acceptance"],
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
