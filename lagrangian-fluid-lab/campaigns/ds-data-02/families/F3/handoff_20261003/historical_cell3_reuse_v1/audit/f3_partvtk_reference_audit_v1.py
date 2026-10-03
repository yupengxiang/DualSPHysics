#!/usr/bin/env python3
"""Bounded official PartVTK 0/mid/end audit for historical fluid-only references.

Verifies actual native/source position, mass, and IDs at anchor frames (0, mid, end)
against official DualSPHysics PartVTK binary output without creating a materialized
trajectory conversion.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import subprocess
import tempfile

import h5py
import numpy as np

PARTVTK_TOLERANCES = {
    "position": 1.0e-6,
    "velocity": 1.0e-6,
    "density": 1.0e-3,
    "mass": 1.0e-7,
    "pressure": 5.0e-2,
}


def audit_reference_partvtk(
    partvtk_bin: Path,
    data_root: Path,
    h5_path: Path,
    expected_case_id: str,
    expected_total_particles: int,
    expected_fixed_particles: int,
    expected_fluid_particles: int,
    expected_fluid_id_range: tuple[int, int],
    target_frames: list[int],
    threads: int = 2,
) -> dict:
    h5_path = h5_path.resolve()
    partvtk_bin = partvtk_bin.resolve()
    data_root = data_root.resolve()

    frame_results = []
    with h5py.File(h5_path, "r") as h5:
        h5_ids = h5["particle_id"][:]
        h5_time = h5["time"][:]
        h5_zones = h5["particle_zone"][:] if "particle_zone" in h5 else np.zeros_like(h5_ids)
        h5_type = h5["type"][:] if "type" in h5 else None
        h5_mk = h5["mk"][:] if "mk" in h5 else None

        # Verify H5 fluid cohort dimensions
        assert len(h5_ids) == expected_fluid_particles, f"H5 particle count {len(h5_ids)} != expected {expected_fluid_particles}"
        assert int(h5_ids.min()) == expected_fluid_id_range[0], f"H5 min ID {h5_ids.min()} != {expected_fluid_id_range[0]}"
        assert int(h5_ids.max()) == expected_fluid_id_range[1], f"H5 max ID {h5_ids.max()} != {expected_fluid_id_range[1]}"

        h5_id_to_idx = {int(pid): idx for idx, pid in enumerate(h5_ids)}

        for frame in target_frames:
            with tempfile.TemporaryDirectory(prefix=f"partvtk_audit_{expected_case_id}_f{frame}_") as td:
                prefix = Path(td) / f"frame_{frame:04d}"
                cmd = [
                    str(partvtk_bin),
                    "-dirdata", str(data_root),
                    f"-first:{frame}", f"-last:{frame}",
                    f"-threads:{threads}",
                    "-savecsv", str(prefix),
                    "-onlytype:+all",
                    "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone",
                    "-csvsep:1",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                csv_path = prefix.parent / f"{prefix.name}_{frame:04d}.csv"
                if not csv_path.exists():
                    candidates = list(prefix.parent.glob(f"{prefix.name}_*.csv"))
                    assert candidates, f"PartVTK produced no CSV for frame {frame}"
                    csv_path = candidates[0]

                # Parse CSV
                with csv_path.open("r", newline="") as f:
                    reader = csv.reader(f, delimiter=",")
                    hdr_summary = next(reader)
                    val_summary = next(reader)
                    empty = next(reader)
                    col_names = [c.strip() for c in next(reader) if c.strip()]

                    # Check summary header
                    # TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid
                    partvtk_sim_time = float(val_summary[0])
                    np_total = int(val_summary[1])
                    np_bound = int(val_summary[2])
                    np_fixed = int(val_summary[3])
                    np_fluid = int(val_summary[6])

                    col_idx = {name: idx for idx, name in enumerate(col_names)}

                    fluid_ids = []
                    fixed_ids = []
                    fluid_masses = []
                    fluid_pos_errors = []
                    fluid_vel_errors = []
                    fluid_rho_errors = []
                    fluid_press_errors = []

                    h5_pos_frame = h5["position"][frame]
                    h5_vel_frame = h5["velocity"][frame]
                    h5_rho_frame = h5["density"][frame] if "density" in h5 else None
                    h5_press_frame = h5["pressure"][frame] if "pressure" in h5 else None
                    h5_mass_frame = h5["mass"][frame] if "mass" in h5 else None

                    for row in reader:
                        if not row or not any(row):
                            continue
                        ptype = int(row[col_idx["Type"]])
                        pid = int(row[col_idx["Idp"]])
                        pmass = float(row[col_idx["Mass [kg]"]])
                        if ptype == 3:  # fluid
                            fluid_ids.append(pid)
                            fluid_masses.append(pmass)
                            # Compare with H5
                            assert pid in h5_id_to_idx, f"Fluid ID {pid} not found in H5"
                            h5_idx = h5_id_to_idx[pid]
                            pv_pos = np.array([float(row[col_idx["Pos.x [m]"]]), float(row[col_idx["Pos.y [m]"]]), float(row[col_idx["Pos.z [m]"]])])
                            pv_vel = np.array([float(row[col_idx["Vel.x [m/s]"]]), float(row[col_idx["Vel.y [m/s]"]]), float(row[col_idx["Vel.z [m/s]"]])])
                            pos_err = np.max(np.abs(pv_pos - h5_pos_frame[h5_idx]))
                            vel_err = np.max(np.abs(pv_vel - h5_vel_frame[h5_idx]))
                            fluid_pos_errors.append(pos_err)
                            fluid_vel_errors.append(vel_err)
                            if h5_rho_frame is not None:
                                rho_err = abs(float(row[col_idx["Rhop [kg/m^3]"]]) - float(h5_rho_frame[h5_idx]))
                                fluid_rho_errors.append(rho_err)
                            if h5_press_frame is not None:
                                press_err = abs(float(row[col_idx["Press [Pa]"]]) - float(h5_press_frame[h5_idx]))
                                fluid_press_errors.append(press_err)
                        else:
                            fixed_ids.append(pid)

                # Frame summary assertions
                assert np_total == expected_total_particles, f"Total particles {np_total} != {expected_total_particles}"
                assert np_fixed == expected_fixed_particles, f"Fixed particles {np_fixed} != {expected_fixed_particles}"
                assert np_fluid == expected_fluid_particles, f"Fluid particles {np_fluid} != {expected_fluid_particles}"
                assert len(fluid_ids) == expected_fluid_particles
                assert len(fixed_ids) == expected_fixed_particles

                max_pos_err = float(max(fluid_pos_errors))
                max_vel_err = float(max(fluid_vel_errors))
                max_rho_err = float(max(fluid_rho_errors)) if fluid_rho_errors else 0.0
                max_press_err = float(max(fluid_press_errors)) if fluid_press_errors else 0.0
                total_fluid_mass = float(sum(fluid_masses))

                time_err = abs(partvtk_sim_time - float(h5_time[frame]))

                passed = (
                    max_pos_err <= PARTVTK_TOLERANCES["position"] and
                    max_vel_err <= PARTVTK_TOLERANCES["velocity"] and
                    max_rho_err <= PARTVTK_TOLERANCES["density"] and
                    max_press_err <= PARTVTK_TOLERANCES["pressure"] and
                    time_err <= 5.0e-5 and
                    abs(total_fluid_mass - 14.58) / 14.58 <= 0.01
                )

                frame_results.append({
                    "frame": frame,
                    "partvtk_sim_time_s": partvtk_sim_time,
                    "h5_time_s": float(h5_time[frame]),
                    "time_abs_error_s": time_err,
                    "np_total": np_total,
                    "np_fixed": np_fixed,
                    "np_fluid": np_fluid,
                    "fixed_id_range": [int(min(fixed_ids)), int(max(fixed_ids))],
                    "fluid_id_range": [int(min(fluid_ids)), int(max(fluid_ids))],
                    "total_fluid_mass_kg": total_fluid_mass,
                    "max_abs_error": {
                        "position_m": max_pos_err,
                        "velocity_m_s": max_vel_err,
                        "density_kg_m3": max_rho_err,
                        "pressure_pa": max_press_err,
                    },
                    "passed": passed,
                })

    return {
        "case_id": expected_case_id,
        "h5_path": str(h5_path),
        "data_root": str(data_root),
        "partvtk_bin": str(partvtk_bin),
        "expected_particles": {
            "total": expected_total_particles,
            "fixed": expected_fixed_particles,
            "fluid": expected_fluid_particles,
            "fluid_id_range": list(expected_fluid_id_range),
        },
        "frames": frame_results,
        "all_frames_passed": all(f["passed"] for f in frame_results),
        "status": "completed_pass" if all(f["passed"] for f in frame_results) else "failed",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--h5-path", type=Path, required=True)
    parser.add_argument("--partvtk-bin", type=Path, required=True)
    parser.add_argument("--expected-total", type=int, required=True)
    parser.add_argument("--expected-fixed", type=int, required=True)
    parser.add_argument("--expected-fluid", type=int, required=True)
    parser.add_argument("--fluid-id-min", type=int, required=True)
    parser.add_argument("--fluid-id-max", type=int, required=True)
    parser.add_argument("--frames", type=int, nargs="+", default=[0, 418, 835])
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = audit_reference_partvtk(
        partvtk_bin=args.partvtk_bin,
        data_root=args.data_root,
        h5_path=args.h5_path,
        expected_case_id=args.case_id,
        expected_total_particles=args.expected_total,
        expected_fixed_particles=args.expected_fixed,
        expected_fluid_particles=args.expected_fluid,
        expected_fluid_id_range=(args.fluid_id_min, args.fluid_id_max),
        target_frames=args.frames,
        threads=args.threads,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "all_frames_passed": result["all_frames_passed"], "output": str(args.output)}, sort_keys=True))
    return 0 if result["all_frames_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
