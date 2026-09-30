from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.ds_data02_f3_gencase import generate_definition
from scripts.ds_data02_f3_weak import _canonical_hash, _finite_aperture_labels


def _write_small_trajectory(path: Path) -> None:
    """Three fluid identities: two cross the finite top aperture, one is rejected."""
    frames, particles = 3, 3
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=np.asarray([0.0, 1.0, 2.0], dtype="f8"))
        h5.create_dataset("particle_id", data=np.asarray([10, 11, 12], dtype="u4"))
        h5.create_dataset("particle_zone", data=np.zeros(particles, dtype="i2"))
        h5.create_dataset("initial_type", data=np.full(particles, 3, dtype="i1"))
        h5.create_dataset("initial_mk", data=np.ones(particles, dtype="i2"))
        h5.create_dataset("initial_mass", data=np.asarray([1.0, 2.0, 3.0], dtype="f4"))
        h5.create_dataset("valid", data=np.ones((frames, particles), dtype=bool))
        h5.create_dataset("type", data=np.full((frames, particles), 3, dtype="i1"))
        h5.create_dataset("mk", data=np.ones((frames, particles), dtype="i2"))
        positions = np.asarray(
            [
                [[0.0, 0.0, 0.49], [0.60, 0.0, 0.49], [0.1, 0.0, 0.49]],
                [[0.0, 0.0, 0.52], [0.60, 0.0, 0.52], [0.1, 0.0, 0.52]],
                [[0.0, 0.0, 0.49], [0.60, 0.0, 0.55], [0.1, 0.0, 0.52]],
            ],
            dtype="f4",
        )
        h5.create_dataset("position", data=positions)
        h5.create_dataset("velocity", data=np.zeros((frames, particles, 3), dtype="f4"))
        h5.create_dataset("density", data=np.full((frames, particles), 1000.0, dtype="f4"))
        h5.create_dataset("mass", data=np.broadcast_to(np.asarray([1.0, 2.0, 3.0], dtype="f4"), (frames, particles)))
        h5.create_dataset("pressure", data=np.zeros((frames, particles), dtype="f4"))


def test_finite_aperture_labels_use_interpolated_crossings_and_mass_units(tmp_path: Path) -> None:
    trajectory = tmp_path / "trajectory.h5"
    labels = tmp_path / "labels.json"
    timeseries = tmp_path / "timeseries.csv"
    _write_small_trajectory(trajectory)

    result = _finite_aperture_labels(
        trajectory,
        labels,
        timeseries,
        aperture={
            "z_plane_m": 0.51,
            "x_low_m": -0.45,
            "x_high_m": 0.45,
            "y_low_m": -0.09,
            "y_high_m": 0.09,
            "z_low_m": 0.0,
        },
    )
    data = json.loads(labels.read_text())
    assert result["per_particle_count"] == 3
    assert data["aggregate"]["positive_crossings"] == 2
    assert data["aggregate"]["positive_crossing_mass_kg"] == 4.0
    assert data["aggregate"]["negative_crossings"] == 1
    assert data["aggregate"]["negative_crossing_mass_kg"] == 1.0
    assert data["aggregate"]["aperture_rejected_crossings"] == 1
    by_id = {row["idp"]: row for row in data["per_particle"]}
    assert by_id[10]["first_passage_s"] == pytest.approx(2.0 / 3.0)
    assert by_id[11]["positive_crossings"] == 0
    assert by_id[11]["final_category"] == "outside_finite_aperture"
    assert by_id[10]["residence_mass_time_kg_s"] > 0.0
    assert data["operator"]["residence_mass_time_unit"] == "kg*s"
    assert timeseries.is_file()


def test_f3_physical_binding_hash_excludes_numeric_view_metadata() -> None:
    owner = json.loads(
        Path(
            "campaigns/ds-data-02/families/F3/weak_dual_scope_001/f3_weak_owner_metadata.json"
        ).read_text()
    )
    binding = owner["physical_binding"]
    first = _canonical_hash(binding)
    changed_view = dict(owner)
    changed_view["resolution"] = "dp_0p006"
    changed_view["time_variant"] = "half_save"
    assert _canonical_hash(changed_view["physical_binding"]) == first
    changed_physics = json.loads(json.dumps(binding))
    changed_physics["controls"]["viscosity"]["value"] = 0.06
    assert _canonical_hash(changed_physics) != first


def test_gencase_matrix_changes_only_resolution_lattice_insets(tmp_path: Path) -> None:
    source = tmp_path / "source_Def.xml"
    source.write_text(
        """<case><casedef><geometry><definition dp=\"0.1\"><pointref x=\"0.05\" y=\"0.05\" z=\"0.05\"/></definition><commands>
        <list name=\"GeometryForNormals\"><drawbox><point x=\"-0.45\" y=\"-0.09\" z=\"0\"/><size x=\"0.9\" y=\"0.18\" z=\"0.51\"/></drawbox></list>
        <mainlist><drawbox><point x=\"-0.4\" y=\"-0.04\" z=\"0.05\"/><size x=\"0.8\" y=\"0.08\" z=\"0.04\"/></drawbox>
        <drawbox><boxfill>all^top</boxfill><point x=\"-0.5\" y=\"-0.14\" z=\"-0.05\"/><size x=\"1.0\" y=\"0.28\" z=\"0.56\"/></drawbox></mainlist>
        </commands></geometry></casedef><execution><special><accinputs><accinput><acctimesfile value=\"control.csv\"/></accinput></accinputs></special></execution></case>""",
        encoding="utf-8",
    )
    output = tmp_path / "candidate_Def.xml"
    manifest = generate_definition(source, output, 0.05)
    import xml.etree.ElementTree as ET

    generated = ET.parse(output).getroot()
    assert generated.find(".//geometry/definition").get("dp") == "0.05"
    assert manifest["continuous_geometry"]["tank_size_m"] == [0.9, 0.18, 0.51]
    assert manifest["candidate_dp_m"] == 0.05
    assert generated.find(".//geometry/commands/mainlist/drawbox/point").get("x") == "-0.425"
    boundary = generated.findall(".//geometry/commands/mainlist/drawbox")[1]
    assert boundary.find("size").get("z") == "0.535"
