import json
import hashlib
from dataclasses import replace

import h5py
import numpy as np
import pytest
import torch

from scripts.core_cfd_dataset import adapt_manifest, known_inputs_from_cfd_config
from scripts.core_dataset import CoreDataset, compactify_manifest
from scripts.core_models import (DualIncrementModel, neighbor_table, tensors,
                                 two_hop_halo)
from scripts.core_contract import State


def _f8_config(root, *, samples=None, time_max_s=1.5):
    if samples is None:
        samples = np.array([
            [0., 0., 0., 0., 0., 0., 0.],
            [.5, .01, 0., 0., 0., 0., 0.],
            [1., 0., 0., 0., 0., 0., 0.],
            [1.5, -.01, 0., 0., 0., 0., 0.],
        ])
    control_path = root / "f8-control.csv"
    lines = ["#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ"]
    lines.extend(";".join(f"{value:.17g}" for value in row) for row in samples)
    payload = ("\n".join(lines) + "\n").encode()
    control_path.write_bytes(payload)
    return {
        "family": "F8",
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_R008",
        "stage": "qualification",
        "qualification_only": True,
        "dp_m": .0075,
        "density_kg_m3": 1000.,
        "gravity_m_s2": [0., 0., 0.],
        "physical_kinematic_viscosity_m2_s": .0005,
        "viscosity_formulation": "laminar",
        "time_max_s": time_max_s,
        "periodic_axes": "xy",
        "periodic_lengths_m": [.24, .12, 0.],
        "wall_bounds": {"xmin": 0., "xmax": .24, "ymin": 0., "ymax": .12,
                        "zmin": -.045, "zmax": .045},
        "closed_faces": ["bottom", "top"],
        "control_amplitude_m_s2": .01,
        "omega_rad_s": .9876543209876544,
        "alpha": 2.,
        "control_asset": {
            "path": control_path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "format": "dualsphysics_accinput_csv_v1",
        },
    }


def _state(position, time_s=0.):
    position = np.asarray(position, dtype=np.float64)
    count = len(position)
    return State(time_s, position, np.zeros_like(position), np.arange(count),
                 np.zeros(count, dtype=np.int64), np.ones(count),
                 np.ones(count, dtype=bool))


def test_f8_reader_binds_csv_schedule_and_exposes_only_fixed_z_walls(tmp_path):
    config = _f8_config(tmp_path)
    known = known_inputs_from_cfd_config(config, family="F8", data_root=tmp_path)

    assert known.control.semantics == "dualsphysics_accinput_v1"
    assert known.control.source_sha256 == config["control_asset"]["sha256"]
    assert known.control.source_path == "f8-control.csv"
    assert known.control.source_bytes == config["control_asset"]["bytes"]
    assert known.control.source_format == "dualsphysics_accinput_csv_v1"
    assert known.control.at(.25)[0][0] == pytest.approx(.005)
    assert np.allclose(known.control.acceleration(_state([[.1, .05, 0.]], time_s=.25)),
                       [[.005, 0., 0.]])
    assert known.physics["gravity_mps2"] == (0., 0., 0.)
    assert known.physics["periodic_lengths_m"] == (.24, .12, 0.)
    assert known.physics["physical_kinematic_viscosity_m2_s"] == pytest.approx(.0005)
    assert known.geometry.triangles.shape == (4, 3, 3)
    assert set(np.unique(known.geometry.triangles[:, :, 2])) == {-.045, .045}


def test_f8_control_rejects_changed_hash_bad_axes_and_short_coverage(tmp_path):
    config = _f8_config(tmp_path)
    (tmp_path / config["control_asset"]["path"]).write_text("# changed\n0;0;0;0;0;0;0\n1;0;0;0;0;0;0\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        known_inputs_from_cfd_config(config, family="F8", data_root=tmp_path)

    bad_axes = _f8_config(tmp_path, samples=np.array([
        [0., 0., 0., 0., 0., 0., 0.], [.5, .01, .001, 0., 0., 0., 0.],
        [1., 0., 0., 0., 0., 0., 0.], [1.5, -.01, 0., 0., 0., 0., 0.],
    ]))
    with pytest.raises(ValueError, match="x-only"):
        known_inputs_from_cfd_config(bad_axes, family="F8", data_root=tmp_path)

    short = _f8_config(tmp_path, samples=np.array([
        [0., 0., 0., 0., 0., 0., 0.], [.5, .01, 0., 0., 0., 0., 0.],
        [1., 0., 0., 0., 0., 0., 0.],
    ]))
    with pytest.raises(ValueError, match="does not cover"):
        known_inputs_from_cfd_config(short, family="F8", data_root=tmp_path)


def test_f8_static_qualification_lineage_cannot_be_relabelled_for_training(tmp_path):
    config = _f8_config(tmp_path)
    trajectory = tmp_path / "trajectory.h5"
    with h5py.File(trajectory, "w") as handle:
        handle["time"] = [0., .01]
        handle["position"] = np.array([
            [[.05, .05, 0.], [.06, .05, 0.]],
            [[.0501, .05, 0.], [.0601, .05, 0.]],
        ])
        handle["velocity"] = np.zeros((2, 2, 3))
        handle["particle_id"] = [1, 2]
        handle["particle_zone"] = [0, 0]
        handle["mass"] = [1., 1.]
        handle["valid"] = [[True, True], [True, True]]
    payload = trajectory.read_bytes()
    source = {
        "schema": "core.f8.oscillatory_pressure_channel.v1",
        "family": "F8",
        "cases": [{
            "case_id": "f8-q",
            "family": "F8",
            "split": "train",
            "qualification_only": False,
            "prepared_record": {"config": config},
            "hdf5": trajectory.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }],
    }
    manifest = adapt_manifest(source, tmp_path)
    assert manifest["cases"][0]["split"] == "qualification"
    assert manifest["cases"][0]["qualification_case"] is True
    assert manifest["cases"][0]["known_inputs"]["control"]["source_sha256"] == config["control_asset"]["sha256"]

    manifest_path = tmp_path / "f8-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    compact = compactify_manifest(manifest_path, tmp_path)
    with CoreDataset(compact, tmp_path) as dataset:
        compact_known = dataset.known_inputs("f8-q")
    assert compact_known.control.source_sha256 == config["control_asset"]["sha256"]
    assert compact_known.control.source_path == "f8-control.csv"
    assert compact_known.control.source_bytes == config["control_asset"]["bytes"]


def test_periodic_xy_neighbors_provenance_halo_and_edges_share_minimum_image(tmp_path):
    positions = np.array([
        [.002, .03, -.01], [.238, .03, -.01],
        [.12, .03, -.044], [.12, .03, .044],
        [.15, .002, 0.], [.15, .118, 0.],
    ])
    state = _state(positions)
    table, _, provenance = neighbor_table(
        state, .01, limit=16, return_provenance=True,
        periodic_lengths=(.24, .12, 0.))
    assert 1 in table[0]
    assert 0 in table[1]
    assert 5 in table[4] and 4 in table[5]
    assert 3 not in table[2] and 2 not in table[3]  # z remains nonperiodic
    assert provenance.neighbor_distance2[0, list(table[0]).index(1)] == pytest.approx(.004 ** 2)
    _, halo = two_hop_halo([0], table, provenance=provenance,
                           position=state.position)
    assert set(halo) == set(provenance.required_two_hop_sources([0])[0])

    changed_metric = replace(provenance, periodic_lengths=np.array([0., 0., 0.]))
    with pytest.raises(ValueError, match="distance"):
        two_hop_halo([0], table, provenance=changed_metric, position=state.position)

    config = _f8_config(tmp_path)
    known = known_inputs_from_cfd_config(config, family="F8", data_root=tmp_path)
    args, _, _ = tensors(state, known, .01, "cpu")
    model = DualIncrementModel("graph_raw", hidden=8).eval()
    captured = []
    hook = model.messages[0][0].register_forward_pre_hook(
        lambda _module, values: captured.append(values[0].detach().clone()))
    with torch.no_grad():
        model(*args, centers=torch.tensor([0]))
    hook.remove()
    first_edge = captured[0]
    source_slot = int(np.flatnonzero(table[0] == 1)[0])
    assert first_edge[0, source_slot, 16].item() == pytest.approx(
        -.004 / known.numerics["h_m"], abs=1e-6)


def test_periodic_search_radius_must_not_ambiguously_include_multiple_images():
    state = _state([[.01, .02, 0.], [.02, .02, 0.]])
    with pytest.raises(ValueError, match="twice the neighbor radius"):
        neighbor_table(state, .03, periodic_lengths=(.1, .2, 0.))
