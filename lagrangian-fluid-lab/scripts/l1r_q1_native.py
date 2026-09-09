"""Read all Q1 BI4 frames through upstream JBinaryData, checked against PartVTK."""

import subprocess, json, time, xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import h5py
from scripts.l1r_continuation_evidence import LAB, OUT, write, runtime_domain
from scripts import l1r_q2_mdbc_bridge as q2
from scripts.trajectory_io import read_frame as read_csv_frame, VECTOR_COLUMNS
from scripts.finite_wall_audit import wall_penetration, segment_crossing_events


def read_frame(path, temp):
    executable = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
    subprocess.run(
        [str(executable), str(path), str(temp)], check=True, stdout=subprocess.DEVNULL
    )
    root = ET.parse(str(temp) + ".xml").getroot()
    node = root.find(".//item/item")
    metadata = {e.get("name"): e.get("v") for e in root.find("item") if e.tag != "item"}
    info = {e.get("name"): e.get("v") for e in node}
    data = temp / node.get("name")
    ids = np.fromfile(data / "Idp.bin", np.uint32)
    order = np.argsort(ids)
    n = len(ids)
    posfile = data / "Pos.bin"
    posdouble = data / "Posd.bin"
    p = np.fromfile(
        posfile if posfile.exists() else posdouble,
        np.float32 if posfile.exists() else np.float64,
    ).reshape(n, 3)[order]
    v = np.fromfile(data / "Vel.bin", np.float32).reshape(n, 3)[order]
    rho = np.fromfile(data / "Rhop.bin", np.float32)[order]
    return ids[order], p, v, rho, metadata, info


def main():
    if (OUT / "Q1-FULL-FRAME-AUDIT.json").exists():
        print(
            "Completed Q1 conversion already exists; use reconciliation to re-audit it."
        )
        return
    start = time.monotonic()
    cpu = time.process_time()
    attempt = next(
        (LAB / "campaigns/l1-resume/runs/q1-official").glob("*/attempts/*.complete")
    )
    paths = sorted((attempt / "data").glob("Part_[0-9][0-9][0-9][0-9].bi4"))
    temp = LAB / "campaigns/l1-resume/artifacts/q1-native-temp"
    dest = LAB / "campaigns/l1-resume/data/q1-native.h5"
    spec = json.loads((OUT / "Q1-SCENE.json").read_text())["spec"]
    # PartVTK's independently exported initial frame supplies immutable type/mk;
    # equality and numeric tolerances verify the native decoder before use.
    refdir = LAB / "campaigns/l1-resume/artifacts/q1-native-reference"
    refdir.mkdir(exist_ok=True)
    csv = refdir / "Particles_0000.csv"
    if not csv.exists():
        with (refdir / "partvtk.log").open("w") as log:
            subprocess.run(
                [
                    str(q2.BIN / "PartVTK_linux64"),
                    "-dirdata",
                    str(attempt / "data"),
                    "-first:0",
                    "-last:0",
                    "-threads:8",
                    "-savecsv",
                    str(refdir / "Particles"),
                    "-onlytype:+all",
                    "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone",
                    "-csvsep:1",
                ],
                env=q2.environment(cpu=True),
                cwd=LAB,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
    frame = read_csv_frame(csv).sort_values("Idp")
    baseids = frame.Idp.to_numpy()
    types = frame.Type.to_numpy()
    mk = frame.Mk.to_numpy()
    reference = {
        "position": frame[VECTOR_COLUMNS["position"]].to_numpy(),
        "velocity": frame[VECTOR_COLUMNS["velocity"]].to_numpy(),
        "density": frame["Rhop [kg/m^3]"].to_numpy(),
        "pressure": frame["Press [Pa]"].to_numpy(),
    }
    ids, p, v, rho, meta, info = read_frame(paths[0], temp)
    checks = {"identity_exact": bool(np.array_equal(ids, baseids))}
    pressure = float(meta["B"]) * (
        (rho.astype(float) / float(meta["Rhop0"])) ** float(meta["Gamma"]) - 1
    )
    for name, native, tol in [
        ("position", p, 1e-6),
        ("velocity", v, 1e-6),
        ("density", rho, 1e-3),
        ("pressure", pressure, 0.01),
    ]:
        error = float(np.max(abs(reference[name] - native)))
        checks[name] = {"max_abs_error": error, "tolerance": tol, "passed": error < tol}
    if not checks["identity_exact"] or not all(
        x["passed"] for x in checks.values() if isinstance(x, dict)
    ):
        raise ValueError("native adapter fails independent PartVTK check")
    write(
        "Q1-NATIVE-READER-VALIDATION.json",
        {
            "checks": checks,
            "reader_source": q2.fingerprint(LAB / "scripts/native/bi4_dump.cpp"),
            "upstream_source": q2.fingerprint(
                LAB.parent / "src/source/JBinaryData.cpp"
            ),
            "semantics": "unmodified upstream parser; EOS-derived pressure; type/mk mapped from native PartVTK identity; no coordinate/mass edits",
        },
    )
    fluid = types == 3
    fixed = types == 0
    initial_pos = p.copy()
    previous = None
    rows = []
    unique_cross = set()
    unique_out = np.zeros(len(ids), bool)
    lastt = -1
    partial = dest.with_suffix(".h5.partial")
    with h5py.File(partial, "w") as h5:
        h5.attrs.update(
            complete=False,
            scene=json.dumps(spec),
            source_attempt=str(attempt.relative_to(LAB)),
            pressure_semantics="EOS from native density and native B/Rhop0/Gamma",
        )
        for name, val in [("particle_id", ids), ("type", types), ("mk", mk)]:
            h5.create_dataset(name, data=val)
        validds = h5.create_dataset(
            "valid",
            shape=(len(paths), len(ids)),
            dtype="bool",
            chunks=(1, 65536),
            compression="lzf",
            fillvalue=False,
        )
        ds = {
            name: h5.create_dataset(
                name,
                shape=(
                    (len(paths), len(ids), 3)
                    if name in ("position", "velocity")
                    else (len(paths), len(ids))
                ),
                dtype="f4",
                chunks=(
                    (1, 65536, 3) if name in ("position", "velocity") else (1, 65536)
                ),
                compression="lzf",
            )
            for name in ("position", "velocity", "density", "pressure")
        }
        h5.create_dataset("time", shape=(len(paths),), dtype="f8")
        h5.attrs["MassFluid"] = float(meta["MassFluid"])
        h5.attrs["MassBound"] = float(meta["MassBound"])
        for fi, path in enumerate(paths):
            ids, p, v, rho, meta, info = read_frame(path, temp)
            t = float(info["TimeStep"])
            indices = np.searchsorted(baseids, ids)
            if np.any(indices >= len(baseids)) or not np.array_equal(
                baseids[indices], ids
            ):
                raise ValueError("unexpected introduced identity")
            present = np.zeros(len(baseids), bool)
            present[indices] = True
            fullp = np.full((len(baseids), 3), np.nan, np.float32)
            fullv = fullp.copy()
            fullrho = np.full(len(baseids), np.nan, np.float32)
            fullp[indices] = p
            fullv[indices] = v
            fullrho[indices] = rho
            p = fullp
            v = fullv
            rho = fullrho
            current_fluid = fluid & present
            current_fixed = fixed & present
            if not t > lastt:
                raise ValueError("nonmonotonic time")
            pressure = float(meta["B"]) * (
                (rho.astype(float) / float(meta["Rhop0"])) ** float(meta["Gamma"]) - 1
            )
            mass = np.full(current_fluid.sum(), float(meta["MassFluid"]))
            row = {
                "frame": fi,
                "time_s": t,
                "particle_count": len(ids),
                "fluid_count": int(current_fluid.sum()),
                "fixed_count": int(current_fixed.sum()),
                "missing_initial_identities": int((~present).sum()),
                "identity_unique": len(np.unique(ids)) == len(ids),
                "identity_axis_unchanged": bool(present.all()),
                "fixed_positions_unchanged": bool(
                    np.array_equal(p[current_fixed], initial_pos[current_fixed])
                ),
                "fixed_velocity_max": float(
                    np.linalg.norm(v[current_fixed], axis=1).max()
                ),
                "nonfinite_rows": int(
                    (
                        present
                        & ~(
                            np.isfinite(p).all(1)
                            & np.isfinite(v).all(1)
                            & np.isfinite(rho)
                            & np.isfinite(pressure)
                        )
                    ).sum()
                ),
                "fluid_mass_kg": float(mass.sum()),
                "native_nout": int(info["Nout"]),
                **wall_penetration(p[current_fluid], mass, spec, 0.0051),
            }
            if previous is not None:
                common = fluid & present & np.isfinite(previous).all(1)
                events = segment_crossing_events(
                    previous[common], p[common], spec, 0.0051
                )
                row["geometric_event_count"] = len(events)
                unique_cross.update(
                    int(baseids[common][e["point_index"]]) for e in events
                )
            previous = p.copy()
            lastt = t
            rows.append(row)
            validds[fi] = present
            for name, val in [
                ("position", p),
                ("velocity", v),
                ("density", rho),
                ("pressure", pressure),
            ]:
                ds[name][fi] = val
            h5["time"][fi] = t
            h5.attrs["completed_frames"] = fi + 1
            if fi % 25 == 0:
                h5.flush()
                write(
                    "Q1-NATIVE-PROGRESS.json",
                    {
                        "completed_frames": fi + 1,
                        "elapsed_seconds": time.monotonic() - start,
                    },
                )
                print(f"Q1 native {fi+1}/{len(paths)}", flush=True)
        h5.attrs["complete"] = True
    partial.replace(dest)
    write(
        "Q1-FULL-FRAME-AUDIT.json",
        {
            "source": q2.fingerprint(dest),
            "frames": rows,
            "unique_geometric_event_identities": len(unique_cross),
            "elapsed_seconds": time.monotonic() - start,
            "cpu_seconds": time.process_time() - cpu,
            "cpu_core_hours_upper_bound": 8 * (time.monotonic() - start) / 3600,
            "new_solver_attempts": 0,
            "geometry": spec,
            "identity_and_type_semantics": "native ID every frame; static type/mk from initial native PartVTK crosscheck and fixed components; no moving/floating components",
        },
    )


if __name__ == "__main__":
    main()
