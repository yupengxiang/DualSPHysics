"""Chunked native Q1 export with full-frame integrity/geometry evidence."""

import json, subprocess, time, shutil
import numpy as np
import h5py
from scripts import trajectory_io as io
from scripts.l1r_continuation_evidence import LAB, OUT, write, runtime_domain
from scripts import l1r_q2_mdbc_bridge as q2
from scripts.finite_wall_audit import wall_penetration, segment_crossing_events


def main():
    started = time.monotonic()
    attempt = next(
        (LAB / "campaigns/l1-resume/runs/q1-official").glob("*/attempts/*.complete")
    )
    dest = LAB / "campaigns/l1-resume/data/q1-chunks"
    dest.mkdir(exist_ok=True)
    spec = {
        "container_interior": dict(
            xmin=0.005, xmax=3.215, ymin=0.005, ymax=0.995, zmin=0.005, zmax=1.0
        ),
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "obstacles": [
            dict(
                id="central",
                xmin=0.655,
                xmax=0.825,
                ymin=0.295,
                ymax=0.705,
                zmin=0.005,
                zmax=0.165,
            )
        ],
        "runtime_domain": runtime_domain(attempt),
    }
    write(
        "Q1-SCENE.json",
        {
            "spec": spec,
            "geometry_semantics": "actual mDBC normal surfaces (dp/2 from nominal source boxes); finite open-top tank and central obstacle",
            "source": q2.fingerprint(
                LAB
                / "vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml"
            ),
            "saved_frames": 601,
            "time_domain_s": [0, 6],
            "dp_m": 0.01,
            "h_m": 0.02,
            "new_solver_attempts": 0,
        },
    )
    summaries = []
    initial_ids = None
    initial_bound = None
    prev = None
    for first in range(0, 601, 10):
        last = min(first + 9, 600)
        chunk = dest / f"frames-{first:04d}-{last:04d}.h5"
        evidence = dest / f"frames-{first:04d}-{last:04d}.json"
        temp = dest / f"csv-{first:04d}"
        temp.mkdir(exist_ok=True)
        cmd = [
            str(q2.BIN / "PartVTK_linux64"),
            "-dirdata",
            str(attempt / "data"),
            f"-first:{first}",
            f"-last:{last}",
            "-threads:8",
            "-savecsv",
            str(temp / "Particles"),
            "-onlytype:+all",
            "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone",
            "-csvsep:1",
        ]
        if (
            len(list(temp.glob("Particles_[0-9][0-9][0-9][0-9].csv")))
            != last - first + 1
        ):
            with (temp / "export.log").open("w") as log:
                proc = subprocess.run(
                    cmd,
                    cwd=LAB,
                    env=q2.environment(cpu=True),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            if proc.returncode:
                raise RuntimeError(f"export {first}: {proc.returncode}")
        paths = sorted(temp.glob("Particles_[0-9][0-9][0-9][0-9].csv"))
        if len(paths) != last - first + 1:
            raise ValueError("incomplete export")
        rows = []
        with h5py.File(chunk.with_suffix(".h5.partial"), "w") as h5:
            h5.attrs["scene_spec"] = json.dumps(spec)
            h5.attrs["source_attempt"] = str(attempt.relative_to(LAB))
            h5.attrs["complete"] = False
            for path in paths:
                frame = io.read_frame(path)
                t = io.frame_time(path)
                ids = frame.Idp.to_numpy(np.int64)
                types = frame.Type.to_numpy()
                order = np.argsort(ids)
                ids = ids[order]
                frame = frame.iloc[order]
                types = types[order]
                if len(np.unique(ids)) != len(ids):
                    raise ValueError("duplicate identity in native frame")
                p = frame[io.VECTOR_COLUMNS["position"]].to_numpy(float)
                fluid = types == 3
                bound = types == 0
                if initial_ids is None:
                    initial_ids = ids.copy()
                    initial_bound = (ids[bound].copy(), p[bound].copy())
                fields = frame[
                    [
                        "Pos.x [m]",
                        "Pos.y [m]",
                        "Pos.z [m]",
                        "Vel.x [m/s]",
                        "Vel.y [m/s]",
                        "Vel.z [m/s]",
                        "Rhop [kg/m^3]",
                        "Mass [kg]",
                        "Press [Pa]",
                    ]
                ].to_numpy(float)
                mass = frame["Mass [kg]"].to_numpy(float)
                row = {
                    "time_s": t,
                    "count": len(ids),
                    "fluid_count": int(fluid.sum()),
                    "fixed_count": int(bound.sum()),
                    "nonfinite_rows": int((~np.isfinite(fields).all(axis=1)).sum()),
                    "same_identity_axis": bool(np.array_equal(ids, initial_ids)),
                    "fixed_boundary_unchanged": bool(
                        np.array_equal(ids[bound], initial_bound[0])
                        and np.array_equal(p[bound], initial_bound[1])
                    ),
                    "fluid_mass_kg": float(mass[fluid].sum()),
                    **wall_penetration(p[fluid], mass[fluid], spec, 0.0051),
                }
                if prev is not None and np.array_equal(ids[fluid], prev[0]):
                    events = segment_crossing_events(prev[1], p[fluid], spec, 0.0051)
                    row["geometric_crossings"] = len(events)
                    row["first_geometric_crossing"] = events[0] if events else None
                prev = (ids[fluid].copy(), p[fluid].copy())
                rows.append(row)
                group = h5.create_group(f"frame_{first+len(rows)-1:04d}")
                group.attrs["time_s"] = t
                for name, values in [
                    ("particle_id", ids),
                    ("type", types),
                    ("mk", frame.Mk.to_numpy()),
                    ("position", p),
                    ("velocity", frame[io.VECTOR_COLUMNS["velocity"]].to_numpy()),
                    ("density", frame["Rhop [kg/m^3]"].to_numpy()),
                    ("mass", mass),
                    ("pressure", frame["Press [Pa]"].to_numpy()),
                ]:
                    group.create_dataset(
                        name, data=values, compression="gzip", compression_opts=1
                    )
            h5.attrs["complete"] = True
        chunk.with_suffix(".h5.partial").replace(chunk)
        q2.atomic_json(evidence, rows)
        summaries += rows
        write(
            "Q1-STREAM-PROGRESS.json",
            {
                "completed_frames": len(summaries),
                "elapsed_seconds": time.monotonic() - started,
                "last_chunk": q2.fingerprint(chunk),
            },
        )
        shutil.rmtree(temp)  # Only this process's reproducible temporary CSV export.
        print(f"Q1 {last+1}/601 frames", flush=True)
    write(
        "Q1-FULL-FRAME-AUDIT.json",
        {
            "frames": summaries,
            "elapsed_seconds": time.monotonic() - started,
            "cpu_core_hours_upper_bound": 8 * (time.monotonic() - started) / 3600,
            "raw_source_untouched": True,
            "normalized_chunks": str(dest.relative_to(LAB)),
            "external_validation": "see independent Q1 probe evidence",
        },
    )


if __name__ == "__main__":
    main()
