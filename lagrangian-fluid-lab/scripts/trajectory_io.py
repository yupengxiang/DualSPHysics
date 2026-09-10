#!/usr/bin/env python3
"""Streaming, resumable CSV-to-HDF5 trajectory conversion and auditing."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

import h5py
import numpy as np
import pandas as pd


VECTOR_COLUMNS = {
    "position": ["Pos.x [m]", "Pos.y [m]", "Pos.z [m]"],
    "velocity": ["Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]"],
}
SCALAR_COLUMNS = {
    "density": ("Rhop [kg/m^3]", np.float32, np.nan),
    "mass": ("Mass [kg]", np.float32, np.nan),
    "pressure": ("Press [Pa]", np.float32, np.nan),
    "type": ("Type", np.int8, -1),
    "mk": ("Mk", np.int16, -1),
}


def frame_time(path: Path):
    with path.open(errors="replace") as stream:
        next(stream)
        return float(next(stream).split(",")[0])


def read_frame(path: Path, identity_only=False):
    # PartVTK emits leading spaces in the particle header.  Applying a
    # usecols predicate before pandas has normalized those names can silently
    # drop Idp/Zone and makes otherwise valid solver output unauditable.
    frame = pd.read_csv(path, skiprows=3)
    frame.columns = [str(column).strip() for column in frame.columns]
    frame = frame.loc[:, ~frame.columns.str.startswith("Unnamed")]
    if identity_only:
        frame = frame[["Idp", "Zone"]]
    if "Zone" not in frame:
        frame["Zone"] = 0
    return frame


def source_fingerprint(csv_paths):
    records = [{"name": path.name, "bytes": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns} for path in csv_paths]
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def scan_identity_axis(csv_paths):
    if not csv_paths:
        raise ValueError("no particle CSV frames were supplied")
    identity_keys = set()
    times = []
    for path in csv_paths:
        times.append(frame_time(path))
        frame = read_frame(path, identity_only=True)
        identity_keys.update(zip(frame["Zone"].astype(int), frame["Idp"].astype(int)))
    times = np.asarray(times, dtype=np.float64)
    if len(times) < 2 or not np.all(np.diff(times) > 0):
        raise ValueError("CSV frame times must be strictly increasing and contain at least two frames")
    keys = np.asarray(sorted(identity_keys), dtype=np.int64)
    return times, keys


def create_partial(path, record, times, keys, fingerprint):
    frames, particles = len(times), len(keys)
    particle_chunk = max(1, min(particles, 65536))
    with h5py.File(path, "w") as h5:
        h5.attrs.update({
            "schema_version": 3, "case_id": record["id"], "family": record["family"],
            "mechanism": record["mechanism"], "solver": "DualSPHysics 5.4.355",
            "source_fingerprint": fingerprint, "conversion_complete_frames": 0,
            "conversion_complete": False,
        })
        shifting = record.get("shifting")
        h5.attrs["particle_shifting"] = ("disabled" if shifting == 0 else
                                          f"configuration value: {shifting}" if shifting is not None else
                                          "unknown")
        multi_zone = bool(np.any(keys[:, 0] != 0))
        h5.attrs["identity_key"] = "(particle_zone, particle_id)" if multi_zone else "particle_id"
        h5.attrs["trajectory_semantics"] = (
            "variable-resolution numerical-node identity; split/merge material lineage is not inferred"
            if multi_zone else "numerical SPH particle identity; material fidelity requires a separate audit")
        h5.create_dataset("time", data=times)
        h5.create_dataset("particle_zone", data=keys[:, 0].astype(np.int16))
        h5.create_dataset("particle_id", data=keys[:, 1].astype(np.int64))
        h5.create_dataset("valid", shape=(frames, particles), dtype=bool,
                          chunks=(1, particle_chunk), compression="gzip", fillvalue=False)
        for name in VECTOR_COLUMNS:
            h5.create_dataset(name, shape=(frames, particles, 3), dtype=np.float32,
                              chunks=(1, particle_chunk, 3), compression="gzip", fillvalue=np.nan)
        for name, (_, dtype, fillvalue) in SCALAR_COLUMNS.items():
            h5.create_dataset(name, shape=(frames, particles), dtype=dtype,
                              chunks=(1, particle_chunk), compression="gzip", fillvalue=fillvalue)


def write_frames(partial_path, csv_paths, keys, start_frame=0, fail_after_frames=None):
    key_to_index = {(int(zone), int(pid)): index for index, (zone, pid) in enumerate(keys)}
    with h5py.File(partial_path, "r+") as h5:
        for frame_index in range(start_frame, len(csv_paths)):
            frame = read_frame(csv_paths[frame_index])
            frame_keys = np.column_stack((frame["Zone"].to_numpy(np.int64),
                                          frame["Idp"].to_numpy(np.int64)))
            if len(np.unique(frame_keys, axis=0)) != len(frame_keys):
                raise ValueError(f"duplicate (zone,idp) key in frame {frame_index}")
            indices = np.asarray([key_to_index[(int(zone), int(pid))]
                                  for zone, pid in frame_keys])
            order = np.argsort(indices)
            indices = indices[order]
            h5["valid"][frame_index, indices] = True
            for name, columns in VECTOR_COLUMNS.items():
                h5[name][frame_index, indices, :] = frame[columns].to_numpy(np.float32)[order]
            for name, (column, dtype, _) in SCALAR_COLUMNS.items():
                h5[name][frame_index, indices] = frame[column].to_numpy(dtype)[order]
            h5.attrs.modify("conversion_complete_frames", frame_index + 1)
            h5.flush()
            if fail_after_frames is not None and frame_index + 1 >= fail_after_frames:
                raise RuntimeError("injected conversion interruption")
        h5.attrs.modify("conversion_complete", True)
        h5.flush()


def convert_streaming(record, csv_paths, out_path, *, resume=True, fail_after_frames=None):
    """Two-pass conversion with per-frame writes, resume metadata, and atomic commit."""
    csv_paths = [Path(path) for path in csv_paths]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = out_path.with_suffix(out_path.suffix + ".partial")
    times, keys = scan_identity_axis(csv_paths)
    fingerprint = source_fingerprint(csv_paths)
    start_frame = 0
    if partial_path.exists() and resume:
        with h5py.File(partial_path, "r") as h5:
            compatible = (h5.attrs.get("source_fingerprint") == fingerprint and
                          h5["valid"].shape == (len(times), len(keys)) and
                          np.array_equal(h5["particle_id"][:], keys[:, 1]) and
                          np.array_equal(h5["particle_zone"][:], keys[:, 0]))
            start_frame = int(h5.attrs.get("conversion_complete_frames", 0)) if compatible else 0
        if not compatible:
            partial_path.unlink()
    if not partial_path.exists():
        create_partial(partial_path, record, times, keys, fingerprint)
    write_frames(partial_path, csv_paths, keys, start_frame, fail_after_frames)
    os.replace(partial_path, out_path)
    return out_path


def audit_hdf5(record, out_path, run_root, lab_root):
    """Compute bounded-memory trajectory and lifecycle evidence from normalized HDF5."""
    with h5py.File(out_path, "r") as h5:
        times = h5["time"][:]
        valid_initial = h5["valid"][0]
        valid_final = h5["valid"][-1]
        common = valid_initial & valid_final
        pos_initial = h5["position"][0]
        pos_final = h5["position"][-1]
        vel_initial_type = h5["type"][0]
        type_final = h5["type"][-1]
        mk_initial = h5["mk"][0]
        mass_initial = h5["mass"][0]
        displacement = np.linalg.norm(pos_final[common] - pos_initial[common], axis=1)
        fluid_initial = valid_initial & (vel_initial_type == 3)
        fluid_common = fluid_initial & valid_final
        floating_common = common & (vel_initial_type == 2)
        fluid_displacement = np.linalg.norm(pos_final[fluid_common] - pos_initial[fluid_common], axis=1)
        floating_displacement = np.linalg.norm(pos_final[floating_common] - pos_initial[floating_common], axis=1)
        max_speed = 0.0
        density_min, density_max = np.inf, -np.inf
        crossing_candidates = fluid_initial & (pos_initial[:, 0] < 0.6)
        first_crossing = np.full(len(valid_initial), np.nan)
        for frame_index, time_value in enumerate(times):
            frame_valid = h5["valid"][frame_index]
            frame_velocity = h5["velocity"][frame_index]
            frame_density = h5["density"][frame_index]
            if frame_valid.any():
                max_speed = max(max_speed, float(np.linalg.norm(frame_velocity[frame_valid], axis=1).max()))
                density_min = min(density_min, float(frame_density[frame_valid].min()))
                density_max = max(density_max, float(frame_density[frame_valid].max()))
            pending = crossing_candidates & np.isnan(first_crossing) & frame_valid
            if pending.any():
                crossed = pending & (h5["position"][frame_index, :, 0] >= 0.6)
                first_crossing[crossed] = time_value

        # Legacy world-x bins are retained only as a diagnostic, but now use
        # initial mass as denominator and expose numerical loss explicitly.
        source_destination = {}
        for source_mk in sorted(int(x) for x in np.unique(mk_initial[fluid_initial])):
            source = fluid_initial & (mk_initial == source_mk)
            initial_mass = float(np.nansum(mass_initial[source]))
            surviving = source & valid_final
            missing = source & ~valid_final
            final_x = pos_final[:, 0]
            categories = {
                "left_x_lt_0p4": surviving & (final_x < 0.4),
                "middle_0p4_to_0p8": surviving & (final_x >= 0.4) & (final_x < 0.8),
                "right_x_ge_0p8": surviving & (final_x >= 0.8),
                "numerically_missing": missing,
            }
            source_destination[str(source_mk)] = {
                "initial_count": int(source.sum()), "initial_mass_kg": initial_mass,
                **{name + "_mass_fraction": float(np.nansum(mass_initial[mask]) / max(initial_mass, 1e-30))
                   for name, mask in categories.items()},
            }
        zones = h5["particle_zone"][:]
        ids = h5["particle_id"][:]
        valid_any = h5["valid"][:].any(axis=0)
        type_values = sorted(int(x) for x in np.unique(np.concatenate([
            h5["type"][frame][h5["valid"][frame]] for frame in range(len(times))])))
        mk_values = sorted(int(x) for x in np.unique(np.concatenate([
            h5["mk"][frame][h5["valid"][frame]] for frame in range(len(times))])))

    run_path = Path(run_root) / record["id"] / "Run.out"
    run_text = run_path.read_text(errors="replace") if run_path.is_file() else ""
    excluded_match = re.search(r"Excluded particles\.+:\s*([0-9,]+)", run_text)
    crossing_times = first_crossing[np.isfinite(first_crossing)]
    return {
        "id": record["id"], "family": record["family"], "mechanism": record["mechanism"],
        "frames": len(times), "time_start": float(times[0]), "time_end": float(times[-1]),
        "particle_ids": int(len(ids)), "identity_keys": int(len(ids)),
        "identity_key": "(zone,idp)" if np.any(zones != 0) else "idp",
        "zones": sorted(int(x) for x in np.unique(zones)),
        "ids_common_first_last": int(common.sum()),
        "identity_retention": float(common.sum() / max(1, valid_initial.sum())),
        "particles_initial": int(valid_initial.sum()), "particles_final": int(valid_final.sum()),
        "identities_introduced_after_initial": int((~valid_initial & valid_any).sum()),
        "initial_identities_missing_at_final": int((valid_initial & ~valid_final).sum()),
        "mean_displacement": float(displacement.mean()) if len(displacement) else None,
        "max_displacement": float(displacement.max()) if len(displacement) else None,
        "fluid_mean_displacement": float(fluid_displacement.mean()) if len(fluid_displacement) else None,
        "floating_mean_displacement": float(floating_displacement.mean()) if len(floating_displacement) else None,
        "floating_max_displacement": float(floating_displacement.max()) if len(floating_displacement) else None,
        "max_speed": max_speed, "density_min": density_min, "density_max": density_max,
        "excluded_particles": int(excluded_match.group(1).replace(",", "")) if excluded_match else None,
        "mk_values": mk_values, "type_values": type_values,
        "source_destination_mass_world_x_legacy": source_destination,
        "initial_left_particles": int(crossing_candidates.sum()),
        "fraction_initial_left_crossing_x_0p6": float(len(crossing_times) / max(1, crossing_candidates.sum())),
        "median_first_crossing_time_x_0p6": float(np.median(crossing_times)) if len(crossing_times) else None,
        "hdf5": str(Path(out_path).relative_to(lab_root)), "hdf5_bytes": Path(out_path).stat().st_size,
    }


def normalize_streaming(record, csv_paths, run_root, data_root, lab_root, **kwargs):
    out_path = (Path(data_root) / f"{record['id']}.h5").resolve()
    convert_streaming(record, csv_paths, out_path, **kwargs)
    return audit_hdf5(record, out_path, Path(run_root).resolve(), Path(lab_root).resolve())
