from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts.ds_data02_f4_observations import audit_observations


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    h5_path = tmp_path / "trajectory.h5"
    frames, particles = 3, 4
    position = np.asarray(
        [
            [[0.5, 0.5, 0.5], [0.6, 0.5, 0.5], [2.1, 0.5, 0.5], [2.2, 0.5, 0.5]],
            [[0.5, 0.5, 0.5], [0.6, 0.5, 0.5], [0.8, 0.5, 0.5], [0.9, 0.5, 0.5]],
            [[0.5, 0.5, 0.5], [0.6, 0.5, 0.5], [2.1, 0.5, 0.5], [2.2, 0.5, 0.5]],
        ],
        dtype="f4",
    )
    with h5py.File(h5_path, "w") as h5:
        h5.create_dataset("time", data=np.asarray([0.0, 0.5, 1.0]))
        h5.create_dataset("particle_id", data=np.arange(particles, dtype="u4"))
        h5.create_dataset("particle_zone", data=np.zeros(particles, dtype="i2"))
        h5.create_dataset("initial_type", data=np.full(particles, 3, dtype="i1"))
        h5.create_dataset("initial_mk", data=np.asarray([1, 1, 2, 2], dtype="i2"))
        h5.create_dataset("initial_mass", data=np.full(particles, 0.5, dtype="f4"))
        h5.create_dataset("valid", data=np.ones((frames, particles), dtype=bool))
        h5.create_dataset("type", data=np.full((frames, particles), 3, dtype="i1"))
        h5.create_dataset("mk", data=np.broadcast_to([1, 1, 2, 2], (frames, particles)).astype("i2"))
        h5.create_dataset("position", data=position)
        h5.create_dataset("velocity", data=np.zeros((frames, particles, 3), dtype="f4"))
        h5.create_dataset("density", data=np.full((frames, particles), 1000, dtype="f4"))
        h5.create_dataset("mass", data=np.full((frames, particles), 0.5, dtype="f4"))
        h5.create_dataset("pressure", data=np.zeros((frames, particles), dtype="f4"))
    binding = {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": "F4",
        "physical_case_id": "fixture",
        "mechanism_id": "finite_drop_pool",
        "geometry_family_id": "g",
        "control_family_id": "c",
        "geometry": {
            "pool": {"low_m": [0.0, 0.0, 0.0], "size_m": [1.0, 1.0, 1.0], "mkfluid": 0, "label": "pool"},
            "drop": {"low_m": [2.0, 0.0, 0.0], "size_m": [1.0, 1.0, 1.0], "mkfluid": 1, "label": "falling_drop"},
        },
        "initial_state": {
            "source_regions": {
                "pool": {"low_m": [0.0, 0.0, 0.0], "size_m": [1.0, 1.0, 1.0], "mkfluid": 0, "label": "pool"},
                "drop": {"low_m": [2.0, 0.0, 0.0], "size_m": [1.0, 1.0, 1.0], "mkfluid": 1, "label": "falling_drop"},
            },
            "velocities_m_per_s": {"mkfluid:0": [0, 0, 0], "mkfluid:1": [-1, 0, 0]},
            "source_labels": {"mkfluid:0": "pool", "mkfluid:1": "falling_drop"},
            "initial_mass_by_source_kg": {"pool": 1.0, "drop": 1.0},
            "continuum_mass_by_source_kg": {"pool": 1.0, "drop": 1.0},
            "initial_mass_total_kg": 2.0,
            "mass_policy": "native_rho_dp_cubed_no_rescaling",
        },
        "controls": {"step_algorithm": "Verlet", "kernel": "Wendland", "viscosity": 0.08, "density_dt": 2, "density_dt_value": 0.1, "boundary": "DBC"},
        "gravity_m_s2": [0, 0, -9.81],
        "density_kg_m3": 1000,
        "parameters": {"speed_m_per_s": 1},
        "event_window": {"time_start_s": 0, "time_end_s": 1, "sequence": ["contact"], "expected_first_contact_range_s": [0, 1], "right_censor_policy": "record"},
    }
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"schema": "ds02.f4.direct-binding.v1", "case_id": "fixture", "resolution": "fine", "dp_m": 0.02, "time_variant": "native", "physical_binding": binding, "typed_identity_binding": {"fluid_mkfluid_to_native_mk": {"0": 1, "1": 2}}}, indent=2))
    operators = tmp_path / "operators.json"
    operators.write_text((Path(__file__).parents[1] / "campaigns/ds-data-02/families/F4/f4_observation_operators.v1.json").read_text())
    return h5_path, metadata, operators


def test_streaming_observation_reports_fixed_and_diagnostic_events(tmp_path: Path) -> None:
    h5_path, metadata, operators = _write_fixture(tmp_path)
    output = tmp_path / "report.json"
    report = audit_observations(h5_path=h5_path, metadata_path=metadata, operators_path=operators, output=output, particle_chunk=2)
    assert report["shape"]["frames"] == 3
    assert report["typed_identity"]["all_source_mks_preserved"] is True
    assert report["events_and_transport"]["falling_drop"]["fixed_physical_operator"]["first_contact"]["status"] == "observed"
    assert report["lifecycle_missing"]["frames_with_missing_fluid"] == 0
    assert report["mass_ledger"]["mass_normalization"] == "none"
    assert output.is_file()

