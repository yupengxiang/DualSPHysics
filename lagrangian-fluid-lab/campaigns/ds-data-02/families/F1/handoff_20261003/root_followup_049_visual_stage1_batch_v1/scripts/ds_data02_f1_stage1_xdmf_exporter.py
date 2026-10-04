#!/usr/bin/env python3
"""Publish immutable typed SPH state as a full temporal ParaView XDMF sidecar.

Family F1 Stage 1 Visual Product generator.
Read-only source; references actual stored positions, identities, weights and time values.
This is a viewing product, not an accuracy certification or visual acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import h5py
import numpy as np

FIELDS = (
    "valid",
    "initial_type",
    "particle_id",
    "particle_zone",
    "initial_mk",
    "initial_mass",
    "mass",
    "velocity",
    "density",
    "pressure",
    "type",
)


def sha(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def append_data_item(
    parent: ET.Element,
    dataset: h5py.Dataset,
    source: Path,
    frame: int,
    frames: int,
    particles: int,
) -> None:
    shape = dataset.shape
    dtype = dataset.dtype
    assert dtype.kind in "uifb", (dataset.name, str(dtype))
    dynamic = len(shape) >= 2 and shape[:2] == (frames, particles)
    assert dynamic or shape == (particles,), (dataset.name, shape)
    outshape = shape[1:] if dynamic else shape
    dimensions = " ".join(map(str, outshape))
    target = parent
    if dynamic:
        target = ET.SubElement(
            parent,
            "DataItem",
            ItemType="HyperSlab",
            Dimensions=dimensions,
            Type="HyperSlab",
        )
        selection = ET.SubElement(
            target,
            "DataItem",
            Dimensions=f"3 {len(shape)}",
            Format="XML",
        )
        selection.text = (
            "\n"
            + "\n".join(
                " ".join(map(str, row))
                for row in (
                    [frame] + [0] * (len(shape) - 1),
                    [1] * len(shape),
                    [1] + list(shape[1:]),
                )
            )
            + "\n"
        )
    ET.SubElement(
        target,
        "DataItem",
        Dimensions=" ".join(map(str, shape)),
        NumberType="Float" if dtype.kind == "f" else "UInt" if dtype.kind in "ub" else "Int",
        Precision=str(dtype.itemsize),
        Format="HDF",
    ).text = str(source) + ":" + dataset.name


def export_xdmf(binding_path: Path, output_dir: Path) -> dict:
    binding = json.loads(binding_path.read_text())
    output_dir.mkdir(parents=True, exist_ok=True)
    out_xmf = output_dir / "case.xmf"

    for key in ("typed_receipt", "native_receipt"):
        p = Path(binding[key])
        assert p.exists(), f"Missing {key}: {p}"
        receipt = json.loads(p.read_text())
        assert (receipt.get("status"), receipt.get("returncode")) == ("completed", 0), (
            f"Receipt not completed 0: {p}"
        )

    report_p = Path(binding["conversion_report"])
    assert report_p.exists(), f"Missing conversion report: {report_p}"
    report = json.loads(report_p.read_text())

    source = Path(binding["trajectory_h5"])
    assert source.exists(), f"Missing trajectory H5: {source}"
    original_sha = sha(source)
    assert original_sha == report["output_sha256"], "Typed source changed after conversion"

    root = ET.Element("Xdmf", Version="2.0")
    domain = ET.SubElement(root, "Domain")
    collection = ET.SubElement(
        domain,
        "Grid",
        Name=binding["physical_case_id"],
        GridType="Collection",
        CollectionType="Temporal",
    )

    with h5py.File(source, "r") as h:
        assert {"time", "position", *FIELDS} <= set(h)
        times = np.asarray(h["time"][:], dtype=np.float64)
        frames, particles, dimension = h["position"].shape
        assert frames == report["frames"] == binding["expected_frames"]
        assert particles == report["particles"] and dimension == 3
        assert len(times) == frames and times[0] == 0 and np.all(np.diff(times) > 0)
        assert times[-1] >= binding["physical_window_s"][1] - 1e-4

        metadata = {
            name: {"shape": list(h[name].shape), "dtype": str(h[name].dtype)}
            for name in ("time", "position", *FIELDS)
        }

        for frame, time in enumerate(times):
            grid = ET.SubElement(
                collection,
                "Grid",
                Name=f"frame_{frame:04d}",
                GridType="Uniform",
            )
            ET.SubElement(grid, "Time", Value=format(float(time), ".17g"))
            ET.SubElement(
                grid,
                "Topology",
                TopologyType="Polyvertex",
                NumberOfElements=str(particles),
            )
            geometry = ET.SubElement(grid, "Geometry", GeometryType="XYZ")
            append_data_item(geometry, h["position"], source, frame, frames, particles)

            for name in FIELDS:
                field = h[name]
                attribute = ET.SubElement(
                    grid,
                    "Attribute",
                    Name=name,
                    Center="Node",
                    AttributeType="Vector" if name == "velocity" else "Scalar",
                )
                append_data_item(attribute, field, source, frame, frames, particles)

        if "physical_condition_sha256" in h.attrs:
            cond = str(h.attrs["physical_condition_sha256"])
            assert cond == binding["physical_condition_sha256"]

    ET.indent(root)
    ET.ElementTree(root).write(out_xmf, encoding="utf-8", xml_declaration=True)
    assert sha(source) == original_sha, "Source mutated while publishing sidecar"

    manifest = {
        **binding,
        "schema": "ds02.stage1.paraview-temporal-product.v1",
        "xdmf": str(out_xmf),
        "xdmf_sha256": sha(out_xmf),
        "source_h5_sha256": original_sha,
        "fields": metadata,
        "frames": frames,
        "particles": particles,
        "actual_time_s": times.tolist(),
        "coordinate_frame": report.get("coordinate_frame", "world_fixed_z_up"),
        "source_h5_read_only": True,
        "relative_or_absolute_paths": "Absolute local immutable HDF5 reference",
        "identity_and_state": (
            "All original stored particles/fields, including fixed/moving/floating geometry; "
            "select valid=1 for active points"
        ),
        "visual_status": "pending actual ParaView full-animation review",
        "numerical_precision_status": (
            "not accepted for stage1 product; historical numerical evidence retained"
        ),
        "independent_case_increment": 0,
        "count_policy": (
            "This is a derived viewing entry for one existing physical condition; "
            "count once after stage1 acceptance"
        ),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output_dir / "README.txt").write_text(
        "Open case.xmf in ParaView 6.1.1, Apply, then Play. All original saved frames are included.\n"
        "Color or Threshold by type (fluid=3, fixed=0, moving=1, floating=2); filter valid=1.\n"
        "The source HDF5 remains in its original immutable location; keep that file when copying this entry.\n"
        "Visual review pending. Numerical precision is not certified. Derived views do not add independent cases.\n"
    )
    return {"xdmf": str(out_xmf), "frames": frames, "particles": particles}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    res = export_xdmf(args.binding, args.output_dir)
    print(json.dumps(res), flush=True)


if __name__ == "__main__":
    main()
