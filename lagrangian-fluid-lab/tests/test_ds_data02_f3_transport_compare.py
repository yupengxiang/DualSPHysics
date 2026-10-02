import json
from pathlib import Path

import h5py
import numpy as np

from scripts import ds_data02_f3_transport_compare as compare


def _labels(path: Path, shift: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "coordinate_frame": "fixed",
        "events": [{"id": "exchange"}],
    }
    times = np.array([0.0, 5.0, 10.0])
    source = np.array([1, 2, 0, 0], dtype=np.int16)
    mass = np.array([1.0, 2.0, 0.0, 0.0])
    interval = np.full((4, 1, 2), np.nan)
    interval[0, 0] = [1.0 + shift, 2.0 + shift]
    interval[1, 0] = [3.0 + shift, 4.0 + shift]
    censor = np.ones((4, 1), dtype=np.int8)
    censor[:2, 0] = 0
    with h5py.File(path, "w") as h5:
        h5.attrs.update(
            complete=True, schema="ds-data-02.native-labels.v1", coordinate_frame="fixed",
            config_json=json.dumps(config), source_hdf5_sha256="source", q_n_status="not_assessed",
        )
        h5.create_dataset("time", data=times)
        h5.create_dataset("particle_id", data=np.arange(4, dtype=np.uint32))
        h5.create_dataset("particle_zone", data=np.zeros(4, dtype=np.int16))
        h5.create_dataset("source_label", data=source)
        h5.create_dataset("initial_fluid_mass_kg", data=mass)
        h5.create_dataset("first_passage_interval", data=interval)
        h5.create_dataset("first_passage_chord_time", data=np.array([[1.5 + shift], [3.5 + shift], [np.nan], [np.nan]]))
        h5.create_dataset("first_passage_censor", data=censor)
        h5.create_dataset("forward_backward_mass_kg", data=np.array([[[0.0, 0.0]], [[1.0, 0.5]], [[2.0, 1.0]]]))
        h5.create_dataset("cumulative_net_flux_kg", data=np.array([[0.0], [0.5], [1.0]]))
        h5.create_dataset("residence_time_s", data=np.array([[1.0, 0.0], [2.0, 1.0], [0.0, 0.0], [0.0, 0.0]]))
        h5.create_dataset("unknown_mass_kg", data=np.zeros(3))
        h5.create_dataset("numerical_loss_mass_kg", data=np.zeros(3))
        h5.create_dataset("invalid_state_mass_kg", data=np.zeros(3))


def test_transport_comparison_retains_censor_and_mass_time(tmp_path):
    baseline = tmp_path / "base.h5"
    variant = tmp_path / "variant.h5"
    output = tmp_path / "comparison.json"
    _labels(baseline)
    _labels(variant, shift=0.25)
    result = compare.compare(baseline, [variant], output=output, particle_chunk=2)
    base = result["baseline"]
    assert base["initial_fluid_mass_kg"] == 3.0
    assert base["passage"][0]["observed_mass_kg"] == 3.0
    assert base["passage"][0]["censored_mass_kg"] == 0.0
    assert base["residence"][0]["residence_mass_time_kg_s"] == 5.0
    assert base["residence"][0]["time_unit"] == "s"
    assert base["residence"][0]["mass_time_unit"] == "kg*s"
    assert result["variants"]["variant"]["qualification_status"] == "not_assessed"
