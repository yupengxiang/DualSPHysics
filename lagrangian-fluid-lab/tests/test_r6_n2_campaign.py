from __future__ import annotations

from scripts import r6_n2_campaign as campaign


def test_registered_height_endpoint_matrix_is_exact_and_unique():
    records = campaign.records()
    assert len(records) == 6
    assert {record["height_label"] for record in records} == {"h09", "h11"}
    assert {record["resolution"] for record in records} == {"coarse", "medium", "fine"}
    assert len({record["case_id"] for record in records}) == 6
    assert {record["dp_m"] for record in records} == {0.035, 0.024, 0.014}
    assert all(record["continuous_initial_fluid_z_bounds_m"][0] == 0.04 for record in records)
    bounds = {tuple(round(value, 6) for value in record["continuous_initial_fluid_z_bounds_m"]) for record in records}
    assert bounds == {(0.04, 0.454), (0.04, 0.546)}


def _audit(label, level, tv=0.01, com=0.01, q90=0.01):
    grid = []
    for index in range(21):
        grid.append({
            "requested_time_s": index * 1.5 / 20,
            "distribution": {"a": 0.5, "b": 0.5},
            "com_m": [float(index), 0.0, 0.0],
            "front_quantiles_m": {"q90": float(index)},
            "kinetic_energy_proxy_j": 1.0,
        })
    # Pair comparison uses both sides' values, so inject the desired offsets
    # in the right-hand audit through the caller below when needed.
    return {
        "height_label": label,
        "resolution": level,
        "r6_full_time_audit_status": "pass",
        "fixed_time_grid": grid,
    }


def test_full_time_pair_gate_has_explicit_thresholds():
    left = _audit("h09", "coarse")
    right = _audit("h09", "medium")
    decision = campaign._pair_comparison(left, right)
    assert decision["time_grid_count"] == 21
    assert decision["thresholds"] == {
        "distribution_tv": 0.05,
        "com_l2_m": 0.06,
        "front_q90_abs_delta_m": 0.06,
    }
    assert decision["status"] == "pass_diagnostic"


def test_pair_gate_keeps_open_top_mass_as_explicit_category():
    import math

    closed = campaign._closed_distribution({"upstream": 0.7, "downstream": 0.2})
    assert math.isclose(closed["unclassified_or_lost"], 0.1)
    assert math.isclose(sum(closed.values()), 1.0)
    assert math.isclose(campaign._closed_distribution(closed)["unclassified_or_lost"], 0.1)


def test_pair_gate_rejects_mass_distribution_above_initial_mass():
    import pytest

    with pytest.raises(ValueError, match="exceeds initial mass"):
        campaign._closed_distribution({"upstream": 1.001})


def test_missing_identity_classifier_requires_registered_open_exit_evidence(tmp_path):
    import h5py
    import numpy as np

    path = tmp_path / "identity.h5"
    with h5py.File(path, "w") as h5:
        h5["time"] = np.asarray([0.0, 0.1])
        h5["valid"] = np.asarray([[True], [False]])
        h5["position"] = np.asarray([[[0.2, 0.1, 0.59]], [[0.0, 0.0, 0.0]]])
        h5["velocity"] = np.asarray([[[0.0, 0.0, 0.2]], [[0.0, 0.0, 0.0]]])
        result = campaign._classify_missing_identities(
            h5,
            {"dp_m": 0.014, "registered_absorbing_exit_faces": ["top"]},
            {
                "status": "available",
                "by_particle_id": {
                    "0": {
                        "native_reason": "position",
                        "position_m": [0.2, 0.1, 0.61],
                    }
                },
                "reason_counts": {"position": 1},
            },
        )
    assert result["status"] == "legal_open_top_exit_only"


def test_missing_identity_classifier_does_not_promote_top_geometry_without_evidence(tmp_path):
    import h5py
    import numpy as np

    path = tmp_path / "identity.h5"
    with h5py.File(path, "w") as h5:
        h5["time"] = np.asarray([0.0, 0.1])
        h5["particle_id"] = np.asarray([0], dtype=np.int64)
        h5["valid"] = np.asarray([[True], [False]])
        h5["position"] = np.asarray([[[0.2, 0.1, 0.59]], [[0.0, 0.0, 0.0]]])
        h5["velocity"] = np.asarray([[[0.0, 0.0, 0.2]], [[0.0, 0.0, 0.0]]])
        result = campaign._classify_missing_identities(
            h5, {"dp_m": 0.014, "registered_absorbing_exit_faces": ["top"]}
        )
    assert result["status"] == "unresolved_missing_identities"
    assert result["categories"]["top_crossing_without_registered_absorber"] == 1


def test_missing_identity_classifier_records_native_density_exclusion(tmp_path):
    import h5py
    import numpy as np

    path = tmp_path / "identity.h5"
    with h5py.File(path, "w") as h5:
        h5["time"] = np.asarray([0.0, 0.1])
        h5["particle_id"] = np.asarray([42], dtype=np.int64)
        h5["valid"] = np.asarray([[True], [False]])
        h5["position"] = np.asarray([[[0.2, 0.1, 0.2]], [[0.0, 0.0, 0.0]]])
        h5["velocity"] = np.zeros((2, 1, 3))
        result = campaign._classify_missing_identities(
            h5,
            {"dp_m": 0.014},
            {
                "status": "available",
                "by_particle_id": {
                    "42": {
                        "native_reason": "density",
                        "position_m": [0.2, 0.1, 0.2],
                    }
                },
                "reason_counts": {"density": 1},
            },
        )
    assert result["status"] == "solver_exclusions_only"
    assert result["categories"]["solver_density_exclusion"] == 1


def test_missing_identity_classifier_does_not_hide_inside_domain_loss(tmp_path):
    import h5py
    import numpy as np

    path = tmp_path / "identity.h5"
    with h5py.File(path, "w") as h5:
        h5["time"] = np.asarray([0.0, 0.1])
        h5["valid"] = np.asarray([[True], [False]])
        h5["position"] = np.asarray([[[0.2, 0.1, 0.2]], [[0.0, 0.0, 0.0]]])
        h5["velocity"] = np.zeros((2, 1, 3))
        result = campaign._classify_missing_identities(h5, {"dp_m": 0.014})
    assert result["status"] == "unresolved_missing_identities"


def test_missing_identity_classifier_separates_finite_wall_from_runtime_domain(tmp_path):
    import copy
    import h5py
    import numpy as np
    from scripts import r5_f1_solver_gate as gate

    path = tmp_path / "identity.h5"
    with h5py.File(path, "w") as h5:
        h5["time"] = np.asarray([0.0, 0.1])
        h5["particle_id"] = np.asarray([7, 8], dtype=np.int64)
        h5["valid"] = np.asarray([[True, True], [False, False]])
        h5["position"] = np.asarray([
            [[1.19, 0.20, 0.20], [0.90, 0.20, 0.20]],
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        ])
        h5["velocity"] = np.asarray([
            [[0.20, 0.0, 0.0], [1.10, 0.0, 0.0]],
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        ])
        spec = copy.deepcopy(gate.WALL_SPECS["plain_dam_break"])
        spec["runtime_domain"] = {
            "xmin": 0.0, "xmax": 1.0, "ymin": 0.0, "ymax": 0.4,
            "zmin": 0.0, "zmax": 0.6,
        }
        result = campaign._classify_missing_identities(
            h5, {"dp_m": 0.014, "wall_spec": spec}
        )
    assert result["categories"]["finite_closed_wall_candidate"] == 1
    assert result["categories"]["runtime_domain_candidate"] == 1
    assert result["categories"]["closed_wall_or_domain_candidate"] == 0
    assert result["status"] == "classified_with_closed_domain_candidates"


def test_plain_material_spec_is_a_single_wall_control():
    import json

    path = campaign.CAMPAIGN / "r6-f1-material-task" / "transport_spec.plain.v1.json"
    spec = json.loads(path.read_text())
    assert spec["case_variant"] == "plain_control"
    assert list(spec["wall"]["component_roles"]) == ["17"]
    assert spec["sources"]["layer_definition"]["reference"] == "declared_continuous_initial_fluid_bounds"
    assert spec["sources"]["layer_definition"]["default_bounds_m"] == [0.03, 0.52]
