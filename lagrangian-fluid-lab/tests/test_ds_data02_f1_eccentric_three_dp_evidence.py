import importlib.util
import json
from pathlib import Path

import h5py
import numpy as np
import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f1_eccentric_three_dp_evidence.py"
SPEC = importlib.util.spec_from_file_location("f1_eccentric_three_dp_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _case(case_id, resolution, offset, mass):
    rows = []
    for i in range(3):
        rows.append(
            {
                "time_s": i * 0.1 + (offset if i else 0.0),
                "center_of_mass_m": [0.1 + i * 0.01, 0.2, 0.3],
                "coordinate_quantiles_m": [[0.0, 0.1, 0.2], [0.0, 0.2, 0.4], [0.0, 0.3, 0.6]],
                "kinetic_energy_J": float(i),
                "fluid_mass_kg": mass,
                "mean_velocity_m_s": [float(i), 0.0, 0.0],
            }
        )
    observation = {
        "schema": "ds-data-02.native-observations.v1",
        "coordinate_frame": "case xyz",
        "geometry_sha256": "geom",
        "control_sha256": "control",
        "continuous_initial_mass_kg": 80.4,
        "numerical_initial_mass_kg": mass,
        "initial_mass_relative_error": mass / 80.4 - 1.0,
        "rows": rows,
    }
    integrity = {"dimensions": {"frames": 3, "particles": 4}}
    return MODULE._observation_case(
        {"case_id": case_id, "resolution": resolution, "dp_m": 0.01, "observation": "", "integrity": ""},
        observation,
        integrity,
    )


def test_pairwise_macro_comparison_aligns_actual_timestamps_and_keeps_mass():
    reference = _case("a", "coarse", 0.0, 76.8)
    candidate = _case("b", "fine", 1e-5, 79.2)
    result = MODULE.compare_pair(
        reference,
        candidate,
        cadence=0.1,
        max_offset=0.0002,
        H0=0.3,
        continuous_mass=80.4,
        macro_budget=0.05,
    )
    assert result["time_alignment"]["common_frame_count"] == 3
    assert result["initial_mass"]["mass_normalization"] == "none"
    assert result["metrics"]["fluid_mass_max_absolute_kg"] == pytest.approx(2.4)
    assert result["q_n_status"] == "not_granted"


def test_label_binding_reports_geometry_mismatch_without_loading_arrays(tmp_path):
    label_path = tmp_path / "labels.h5"
    receipt_path = tmp_path / "receipt.json"
    config_path = tmp_path / "config.json"
    config = {
        "geometry_sha256": "stale",
        "coordinate_frame": "case xyz",
        "source_regions": [{"id": "source", "bounds": [[-1, 1], [-1, 1], [-1, 1]]}],
        "destination_regions": [{"id": "dest", "bounds": [[-1, 1], [-1, 1], [-1, 1]]}],
    }
    config_path.write_text(json.dumps(config))
    with h5py.File(label_path, "w") as h:
        h.attrs.update(
            complete=True,
            schema="ds-data-02.native-labels.v1",
            coordinate_frame="case xyz",
            config_json=json.dumps(config),
            source_hdf5_sha256="source",
            q_n_status="not_assessed",
        )
        shapes = {
            "time": (3,),
            "particle_id": (4,),
            "particle_zone": (4,),
            "source_label": (4,),
            "destination_time_series": (3, 4),
            "final_category": (4,),
            "failure_reason": (4,),
            "first_passage_interval": (4, 0, 2),
            "first_passage_chord_time": (4, 0),
            "first_passage_censor": (4, 0),
            "residence_time_s": (4, 1),
            "unresolved_interval_time_s": (4,),
            "forward_backward_mass_kg": (3, 0, 2),
            "cumulative_net_flux_kg": (3, 0),
            "unknown_mass_kg": (3,),
            "numerical_loss_mass_kg": (3,),
            "invalid_state_mass_kg": (3,),
            "source_final_mass_kg": (2, 4),
        }
        for name, shape in shapes.items():
            h.create_dataset(name, shape=shape, dtype="f8")
    receipt_path.write_text(json.dumps({"input_hashes_after_run": {str(config_path): MODULE.sha256(config_path)}}))
    case = _case("a", "coarse", 0.0, 76.8)
    result = MODULE.inspect_label(
        case,
        {
            "case_id": "a",
            "label_h5": str(label_path),
            "receipt": str(receipt_path),
            "config": str(config_path),
            "source_hdf5_sha256": "source",
        },
        "current-geometry",
        16 * 1024 * 1024,
    )
    assert result["binding_status"] == "mismatch_or_incomplete"
    assert result["checks"]["geometry_binding_matches_expected"] is False
