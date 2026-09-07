import json

import numpy as np

from scripts.r3_g2_f6_static_buoyancy import (
    DEFAULT_REPORT,
    StaticVolumeModel,
    solve_static_equilibrium,
    static_probe,
    tetra_fraction_below,
)


def _unit_cube_surface() -> np.ndarray:
    """Outward-oriented unit-cube triangles, including horizontal duplicates."""
    return np.asarray([
        # z = 0, outward -z
        [[0, 0, 0], [0, 1, 0], [1, 0, 0]],
        [[0, 1, 0], [1, 1, 0], [1, 0, 0]],
        # z = 1, outward +z
        [[0, 0, 1], [1, 0, 1], [0, 1, 1]],
        [[1, 0, 1], [1, 1, 1], [0, 1, 1]],
        # x = 0, outward -x
        [[0, 0, 0], [0, 0, 1], [0, 1, 0]],
        [[0, 0, 1], [0, 1, 1], [0, 1, 0]],
        # x = 1, outward +x
        [[1, 0, 0], [1, 1, 0], [1, 0, 1]],
        [[1, 1, 0], [1, 1, 1], [1, 0, 1]],
        # y = 0, outward -y
        [[0, 0, 0], [1, 0, 0], [0, 0, 1]],
        [[1, 0, 0], [1, 0, 1], [0, 0, 1]],
        # y = 1, outward +y
        [[0, 1, 0], [0, 1, 1], [1, 1, 0]],
        [[1, 1, 0], [0, 1, 1], [1, 1, 1]],
    ], dtype=float)


def test_repeated_height_tetra_fraction_is_stable_without_height_jitter():
    assert np.isclose(tetra_fraction_below(np.asarray([0.0, 0.0, 0.0, 1.0]), 0.5), 0.875)
    assert np.isclose(tetra_fraction_below(np.asarray([0.0, 0.0, 1.0, 1.0]), 0.5), 0.5)
    assert tetra_fraction_below(np.asarray([0.0, 0.0, 0.0, 1.0]), -0.01) == 0.0
    assert tetra_fraction_below(np.asarray([0.0, 0.0, 0.0, 1.0]), 1.01) == 1.0


def test_closed_cube_volume_and_horizontal_slice():
    model = StaticVolumeModel.from_triangles(_unit_cube_surface())
    assert np.isclose(model.total_volume_m3, 1.0)
    assert np.isclose(model.volume_below(-0.1), 0.0)
    assert np.isclose(model.volume_below(0.5), 0.5)
    assert np.isclose(model.volume_below(1.1), 1.0)


def test_reversed_closed_cube_keeps_positive_displaced_volume():
    model = StaticVolumeModel.from_triangles(_unit_cube_surface()[::-1, ::-1])
    assert np.isclose(model.total_volume_m3, 1.0)
    assert np.isclose(model.volume_below(0.25), 0.25)


def test_static_equilibrium_solves_mass_over_density_and_probe_sign():
    model = StaticVolumeModel.from_triangles(_unit_cube_surface())
    equilibrium = solve_static_equilibrium(
        model, target_volume_m3=0.4, waterline_z_m=0.4,
        base_z_m=0.0, cog_above_base_m=0.5,
    )
    assert np.isclose(equilibrium["equilibrium_local_waterline_m"], 0.4)
    assert np.isclose(equilibrium["predicted_heave_from_reference_m"], 0.0)
    assert np.isclose(equilibrium["equilibrium_volume_m3"], 0.4)
    assert static_probe(model, -0.1)["force_balance_buoyancy_minus_weight_N"] > 0.0
    assert static_probe(model, 0.9)["force_balance_buoyancy_minus_weight_N"] < 0.0


def test_report_retains_diagnostic_only_status_and_blockers():
    report = json.loads(DEFAULT_REPORT.read_text())
    assert report["acceptance_status"] == "diagnostic_only_not_physical_acceptance"
    assert report["scientific_acceptance"] == "not_accepted_physical_validation"
    assert report["conclusion"]["physical_acceptance_claim"] is False
    assert report["conclusion"]["mdbc_claim"] is False
    assert report["open_blockers"]
    assert report["resource_policy"]["gpu_indices_used"] == []
