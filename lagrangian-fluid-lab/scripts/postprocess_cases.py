#!/usr/bin/env python3
"""Convert BI4 outputs to normalized HDF5 and audit trajectory semantics."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

import h5py
import numpy as np
import pandas as pd


LAB_ROOT = Path(__file__).resolve().parents[1]
RUN_SUMMARY = LAB_ROOT / "reports" / "runtime" / "run-summary.json"
BIN = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
PARTVTK = BIN / "PartVTK_linux64"
DATA_ROOT = LAB_ROOT / "data"
AUDIT_REPORT = LAB_ROOT / "reports" / "runtime" / "trajectory-audit.json"


def convert_csv(record):
    case_id = record["id"]
    run_dir = LAB_ROOT / "runs" / case_id
    prefix = run_dir / "csv" / "Particles"
    prefix.parent.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    proc = subprocess.run([
        str(PARTVTK), "-dirdata", str(run_dir / "data"),
        "-savecsv", str(prefix), "-onlytype:-all,+fluid,+floating",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ], cwd=LAB_ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (run_dir / "partvtk.stdout.log").write_text(proc.stdout)
    if proc.returncode:
        raise RuntimeError(f"PartVTK failed for {case_id}")
    return sorted(prefix.parent.glob("Particles_[0-9][0-9][0-9][0-9].csv"))


def read_frame(path):
    preamble = path.read_text(errors="replace").splitlines()[:2]
    time_value = float(preamble[1].split(",")[0])
    frame = pd.read_csv(path, skiprows=3)
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame.loc[:, ~frame.columns.str.startswith("Unnamed")]
    return time_value, frame


def normalize(record, csv_paths, run_root=None, data_root=None):
    run_root = run_root or (LAB_ROOT / "runs")
    data_root = data_root or DATA_ROOT
    loaded = [read_frame(path) for path in csv_paths]
    # Standard SPH output has one row per Idp. Variable-resolution output can
    # legitimately contain the same Idp in several zones in one frame, so its
    # exported numerical-node identity is the pair (Zone, Idp).  This does not
    # claim material continuity across split/merge or zone transitions.
    for _, frame in loaded:
        if "Zone" not in frame:
            frame["Zone"] = 0
    all_keys = np.concatenate([
        np.column_stack((frame["Zone"].to_numpy(np.int64), frame["Idp"].to_numpy(np.int64)))
        for _, frame in loaded
    ])
    keys = np.unique(all_keys, axis=0)
    key_to_index = {(int(zone), int(pid)): index for index, (zone, pid) in enumerate(keys)}
    zones = keys[:, 0].astype(np.int16)
    ids = keys[:, 1].astype(np.int64)
    shape = (len(loaded), len(keys))
    valid = np.zeros(shape, dtype=bool)
    position = np.full(shape + (3,), np.nan, dtype=np.float32)
    velocity = np.full(shape + (3,), np.nan, dtype=np.float32)
    density = np.full(shape, np.nan, dtype=np.float32)
    mass = np.full(shape, np.nan, dtype=np.float32)
    pressure = np.full(shape, np.nan, dtype=np.float32)
    ptype = np.full(shape, -1, dtype=np.int8)
    mk = np.full(shape, -1, dtype=np.int16)
    times = np.asarray([time_value for time_value, _ in loaded], dtype=np.float64)

    for frame_index, (_, frame) in enumerate(loaded):
        frame_ids = frame["Idp"].to_numpy(np.int64)
        frame_zones = frame["Zone"].to_numpy(np.int64)
        frame_keys = np.column_stack((frame_zones, frame_ids))
        if len(np.unique(frame_keys, axis=0)) != len(frame_keys):
            raise ValueError(f"duplicate (zone, particle id) keys in {record['id']} frame {frame_index}")
        indices = np.asarray([key_to_index[(int(zone), int(pid))]
                              for zone, pid in frame_keys])
        valid[frame_index, indices] = True
        position[frame_index, indices] = frame[["Pos.x [m]", "Pos.y [m]", "Pos.z [m]"]].to_numpy(np.float32)
        velocity[frame_index, indices] = frame[["Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]"]].to_numpy(np.float32)
        density[frame_index, indices] = frame["Rhop [kg/m^3]"].to_numpy(np.float32)
        mass[frame_index, indices] = frame["Mass [kg]"].to_numpy(np.float32)
        pressure[frame_index, indices] = frame["Press [Pa]"].to_numpy(np.float32)
        ptype[frame_index, indices] = frame["Type"].to_numpy(np.int8)
        mk[frame_index, indices] = frame["Mk"].to_numpy(np.int16)

    out_path = data_root / f"{record['id']}.h5"
    data_root.mkdir(exist_ok=True)
    with h5py.File(out_path, "w") as h5:
        h5.attrs["schema_version"] = 2
        h5.attrs["case_id"] = record["id"]
        h5.attrs["family"] = record["family"]
        h5.attrs["mechanism"] = record["mechanism"]
        h5.attrs["solver"] = "DualSPHysics 5.4.355"
        shifting = record.get("shifting")
        h5.attrs["particle_shifting"] = ("disabled" if shifting == 0 else
                                           f"configuration value: {shifting}" if shifting is not None else
                                           "unspecified; inspect generated XML")
        multi_zone = bool(np.any(zones != 0))
        h5.attrs["identity_key"] = "(particle_zone, particle_id)" if multi_zone else "particle_id"
        h5.attrs["trajectory_semantics"] = (
            "variable-resolution numerical-node identity; continuity across zone transitions and split/merge is not assumed"
            if multi_zone else
            "numerical SPH particle identity; material fidelity pending audit"
        )
        h5.create_dataset("time", data=times)
        h5.create_dataset("particle_id", data=ids)
        h5.create_dataset("particle_zone", data=zones)
        h5.create_dataset("valid", data=valid, compression="gzip")
        h5.create_dataset("position", data=position, compression="gzip")
        h5.create_dataset("velocity", data=velocity, compression="gzip")
        h5.create_dataset("density", data=density, compression="gzip")
        h5.create_dataset("mass", data=mass, compression="gzip")
        h5.create_dataset("pressure", data=pressure, compression="gzip")
        h5.create_dataset("type", data=ptype, compression="gzip")
        h5.create_dataset("mk", data=mk, compression="gzip")

    common = valid[0] & valid[-1]
    displacement = np.linalg.norm(position[-1, common] - position[0, common], axis=1)
    speed = np.linalg.norm(velocity, axis=2)
    fluid_common = common & (ptype[0] == 3)
    floating_common = common & (ptype[0] == 2)
    fluid_displacement = np.linalg.norm(
        position[-1, fluid_common] - position[0, fluid_common], axis=1)
    floating_displacement = np.linalg.norm(
        position[-1, floating_common] - position[0, floating_common], axis=1)
    source_destination = {}
    for source_mk in sorted(int(x) for x in np.unique(mk[0, fluid_common])):
        source = fluid_common & (mk[0] == source_mk)
        final_x = position[-1, source, 0]
        bins = [final_x < 0.4, (final_x >= 0.4) & (final_x < 0.8), final_x >= 0.8]
        source_destination[str(source_mk)] = {
            "count": int(source.sum()),
            "left_x_lt_0p4": float(np.mean(bins[0])),
            "middle_0p4_to_0p8": float(np.mean(bins[1])),
            "right_x_ge_0p8": float(np.mean(bins[2])),
        }
    crossing_candidates = valid[0] & (ptype[0] == 3) & (position[0, :, 0] < 0.6)
    crossing_times = []
    for particle_index in np.flatnonzero(crossing_candidates):
        crossed = np.flatnonzero(valid[:, particle_index] & (position[:, particle_index, 0] >= 0.6))
        if len(crossed):
            crossing_times.append(float(times[crossed[0]]))
    run_text = (run_root / record["id"] / "Run.out").read_text(errors="replace")
    excluded_match = re.search(r"Excluded particles\.+:\s*([0-9,]+)", run_text)
    unique_mk = sorted(int(x) for x in np.unique(mk[valid]))
    unique_types = sorted(int(x) for x in np.unique(ptype[valid]))
    audit = {
        "id": record["id"], "family": record["family"], "mechanism": record["mechanism"],
        "frames": len(times), "time_start": float(times[0]), "time_end": float(times[-1]),
        "particle_ids": int(len(ids)), "identity_keys": int(len(keys)),
        "identity_key": "(zone,idp)" if np.any(zones != 0) else "idp",
        "zones": sorted(int(x) for x in np.unique(zones)),
        "ids_common_first_last": int(common.sum()),
        "identity_retention": float(common.sum() / max(1, valid[0].sum())),
        "particles_initial": int(valid[0].sum()), "particles_final": int(valid[-1].sum()),
        "identities_introduced_after_initial": int((~valid[0] & valid.any(axis=0)).sum()),
        "initial_identities_missing_at_final": int((valid[0] & ~valid[-1]).sum()),
        "mean_displacement": float(displacement.mean()) if len(displacement) else None,
        "max_displacement": float(displacement.max()) if len(displacement) else None,
        "fluid_mean_displacement": float(fluid_displacement.mean()) if len(fluid_displacement) else None,
        "floating_mean_displacement": float(floating_displacement.mean()) if len(floating_displacement) else None,
        "floating_max_displacement": float(floating_displacement.max()) if len(floating_displacement) else None,
        "max_speed": float(np.nanmax(speed)),
        "density_min": float(np.nanmin(density)), "density_max": float(np.nanmax(density)),
        "excluded_particles": int(excluded_match.group(1).replace(",", "")) if excluded_match else None,
        "mk_values": unique_mk, "type_values": unique_types,
        "source_destination_x": source_destination,
        "initial_left_particles": int(crossing_candidates.sum()),
        "fraction_initial_left_crossing_x_0p6": float(len(crossing_times) / max(1, crossing_candidates.sum())),
        "median_first_crossing_time_x_0p6": float(np.median(crossing_times)) if crossing_times else None,
        "hdf5": str(out_path.relative_to(LAB_ROOT)),
        "hdf5_bytes": out_path.stat().st_size,
    }
    return audit


def main():
    runs = json.loads(RUN_SUMMARY.read_text())
    prepared = json.loads((LAB_ROOT / "reports" / "runtime" / "prepare-summary.json").read_text())
    prepared_by_id = {record["id"]: record for record in prepared["cases"]}
    records = [{**r, "shifting": prepared_by_id.get(r["id"], {}).get("shifting")}
               for r in runs["cases"] if r["status"] == "completed"]
    audits = []
    for record in records:
        csv_paths = convert_csv(record)
        audit = normalize(record, csv_paths)
        audits.append(audit)
        print(f"{record['id']:28s} frames={audit['frames']:2d} ids={audit['particle_ids']:4d} "
              f"ret={audit['identity_retention']:.3f} mean_dx={audit['mean_displacement']:.3f}")
    report = {
        "schema_version": 1,
        "case_count": len(audits),
        "all_identity_retained": all(a["identity_retention"] == 1.0 for a in audits),
        "cases": audits,
    }
    AUDIT_REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"normalized={len(audits)} all_identity_retained={report['all_identity_retained']}")


if __name__ == "__main__":
    main()
