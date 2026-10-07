from __future__ import annotations

from pathlib import Path
import sys

import h5py
import numpy as np
import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_f5_bi4 as converter  # noqa: E402
import ds_data02_stage2_f2_native_raw_to_typed_compare_v4 as worker  # noqa: E402


def _write_typed(path: Path, *, missing: bool = True, mutate_mass: bool = False) -> None:
    frames, particles = 2, 3
    valid = np.array([[True, True, True], [True, False, True]], dtype=bool)
    if not missing:
        valid[1, 1] = True
    position = np.full((frames, particles, 3), np.nan, dtype="f4")
    velocity = np.full_like(position, np.nan)
    density = np.full((frames, particles), np.nan, dtype="f4")
    mass = np.full_like(density, np.nan)
    pressure = np.full_like(density, np.nan)
    for frame in range(frames):
        position[frame, valid[frame]] = frame + 0.1
        velocity[frame, valid[frame]] = 0.2
        density[frame, valid[frame]] = 1000.0
        mass[frame, valid[frame]] = 0.001
        pressure[frame, valid[frame]] = 2.0
    if mutate_mass:
        mass[0, 0] = 0.002
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=np.array([0.0, 1.0]))
        h5.create_dataset("particle_id", data=np.array([10, 11, 12], dtype="u4"))
        h5.create_dataset("particle_zone", data=np.zeros(particles, dtype="i2"))
        h5.create_dataset("valid", data=valid)
        h5.create_dataset("position", data=position)
        h5.create_dataset("velocity", data=velocity)
        h5.create_dataset("density", data=density)
        h5.create_dataset("mass", data=mass)
        h5.create_dataset("pressure", data=pressure)
        h5.create_dataset("type", data=np.where(valid, 3, -1).astype("i1"))
        h5.create_dataset("mk", data=np.where(valid, 1, -1).astype("i2"))


def _compare(a: Path, b: Path) -> dict:
    return worker.compare_typed_to_reference(
        a, b, particle_chunk=2, expected_frames=2, expected_particles=3,
        converter_module=converter)


def test_compare_proves_identity_and_invalid_id_inheritance(tmp_path: Path) -> None:
    direct, reference = tmp_path / "direct.h5", tmp_path / "reference.h5"
    _write_typed(direct)
    _write_typed(reference)
    result = _compare(direct, reference)
    assert result["passed"] is True
    assert result["exact_structural_datasets"] is True
    assert result["identity_lifecycle"]["identity_axis_equal"] is True
    assert result["identity_lifecycle"]["missing_id_frames"][1]["direct_missing_count"] == 1
    assert result["identity_lifecycle"]["missing_id_frames"][1]["missing_id_inheritance_equal"] is True


def test_compare_rejects_wrong_missing_id_state_even_when_shape_matches(tmp_path: Path) -> None:
    direct, reference = tmp_path / "direct.h5", tmp_path / "reference.h5"
    _write_typed(direct, missing=True)
    _write_typed(reference, missing=False)
    result = _compare(direct, reference)
    assert result["passed"] is False
    assert result["identity_lifecycle"]["missing_id_frames"][1]["missing_id_inheritance_equal"] is False


def test_compare_rejects_wrong_particle_mass(tmp_path: Path) -> None:
    direct, reference = tmp_path / "direct.h5", tmp_path / "reference.h5"
    _write_typed(direct, mutate_mass=True)
    _write_typed(reference)
    result = _compare(direct, reference)
    assert result["passed"] is False
    assert result["numeric_within_tolerance"]["mass"] is False


def test_compare_rejects_wrong_shape(tmp_path: Path) -> None:
    direct, reference = tmp_path / "direct.h5", tmp_path / "reference.h5"
    _write_typed(direct)
    _write_typed(reference)
    with h5py.File(reference, "a") as h5:
        del h5["mk"]
        h5.create_dataset("mk", data=np.zeros((2, 2), dtype="i2"))
    with pytest.raises(worker.ReferenceCompareError, match="trusted typed/reference comparison failed"):
        _compare(direct, reference)


def test_compare_rejects_same_shape_wrong_content(tmp_path: Path) -> None:
    direct, reference = tmp_path / "direct.h5", tmp_path / "reference.h5"
    _write_typed(direct)
    _write_typed(reference, mutate_mass=True)
    assert _compare(direct, reference)["passed"] is False


def test_mass_semantics_never_infers_rigid_body_from_particle_sum() -> None:
    request = {"mass_semantics": {
        "particle_mass_dataset": "mass",
        "particle_mass_source": "BI4 MassFluid for type=3",
        "support_weight_source": "BI4 MassBound for support particles",
        "rigid_body_mass_source": "explicit floating XML massbody/rigid telemetry only",
        "rigid_body_inference_from_particle_sum": False,
    }}
    result = worker._mass_semantics_report(request, {})
    assert result["particle_mass"]["dataset"] == "mass"
    assert result["rigid_body"]["status"] == "UNKNOWN_NOT_INFERRED"
    assert result["rigid_body"]["massbody_kg"] is None


@pytest.mark.parametrize("value", [0, -1, 1.0, True, "1"])
def test_chunk_must_be_positive_integer(value: object) -> None:
    with pytest.raises(worker.ReferenceCompareError, match="positive integer"):
        worker._positive_int(value, "chunk")
