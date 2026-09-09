"""Normalize single-fluid, fixed-boundary BI4 cases without CSV intermediates."""

import time
import xml.etree.ElementTree as ET
import numpy as np
import h5py
from scripts.l1r_q1_native import read_frame
from scripts.l1r_continuation_evidence import LAB


def normalize(record, attempt, output):
    started = time.monotonic()
    paths = sorted((attempt / "data").glob("Part_[0-9][0-9][0-9][0-9].bi4"))
    temp = attempt / "native-export"
    ids, p, v, rho, meta, info = read_frame(paths[0], temp)
    if int(meta["CaseNmoving"]) or int(meta["CaseNfloat"]):
        raise ValueError("adapter requires fixed boundaries")
    generated = ET.parse(LAB / (record["generated_prefix"] + ".xml")).getroot()
    blocks = generated.findall(".//particles/fluid")
    if len(blocks) != 1:
        raise ValueError("adapter requires one fluid Mk block")
    fluid_mk = int(blocks[0].get("mk"))
    nbound = int(meta["CaseNfixed"])
    base = ids[ids >= nbound]
    n = len(base)
    nt = len(paths)
    if n != int(meta["CaseNfluid"]):
        raise ValueError("fluid ID partition disagrees with native header")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".h5.partial")
    with h5py.File(partial, "w") as h:
        h.attrs.update(
            conversion_complete=False,
            case_id=record["id"],
            source="native JBinaryData arrays; no posthoc particle corrections",
            pressure_semantics="native EOS",
            mass_semantics="native MassFluid header",
            particle_shifting="disabled",
        )
        h.create_dataset("particle_id", data=base)
        h.create_dataset("particle_zone", data=np.zeros(n, np.int16))
        h.create_dataset("time", shape=(nt,), dtype="f8")
        h.create_dataset(
            "valid",
            shape=(nt, n),
            dtype=bool,
            chunks=(1, min(n, 65536)),
            compression="lzf",
            fillvalue=False,
        )
        for name in (
            "position",
            "velocity",
            "density",
            "mass",
            "pressure",
            "type",
            "mk",
        ):
            vector = name in ("position", "velocity")
            shape = (nt, n, 3) if vector else (nt, n)
            h.create_dataset(
                name,
                shape=shape,
                dtype="f4",
                chunks=(1, min(n, 65536), 3) if vector else (1, min(n, 65536)),
                compression="lzf",
                fillvalue=np.nan,
            )
        for fi, path in enumerate(paths):
            ids, p, v, rho, meta, info = read_frame(path, temp)
            mask = ids >= nbound
            index = np.searchsorted(base, ids[mask])
            if np.any(index >= n) or not np.array_equal(base[index], ids[mask]):
                raise ValueError("new/unknown fluid identity")
            valid = np.zeros(n, bool)
            valid[index] = True
            h["valid"][fi] = valid
            h["time"][fi] = float(info["TimeStep"])
            pressure = float(meta["B"]) * (
                (rho[mask].astype(float) / float(meta["Rhop0"])) ** float(meta["Gamma"])
                - 1
            )
            for name, values in [
                ("position", p[mask]),
                ("velocity", v[mask]),
                ("density", rho[mask]),
                ("pressure", pressure),
                ("mass", np.full(mask.sum(), float(meta["MassFluid"]))),
                ("type", np.full(mask.sum(), 3)),
                ("mk", np.full(mask.sum(), fluid_mk)),
            ]:
                full = np.full(
                    (n, 3) if name in ("position", "velocity") else (n,),
                    np.nan,
                    np.float32,
                )
                full[index] = values
                h[name][fi] = full
            # Temporary raw arrays are reproducible exports, not source BI4.
            import shutil

            shutil.rmtree(temp)
        h.attrs["conversion_complete"] = True
    partial.replace(output)
    return {
        "hdf5": str(output.relative_to(LAB)),
        "frames": nt,
        "elapsed_seconds": time.monotonic() - started,
        "normalization_status": "completed",
        "known_scope": "one mkfluid=0; static boundaries; source IDs checked every frame",
    }
