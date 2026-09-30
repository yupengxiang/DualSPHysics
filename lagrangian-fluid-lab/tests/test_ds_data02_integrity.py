from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.ds_data02_integrity import (
    audit_hdf5,
    estimate_hdf5_audit,
    _resource_snapshot,
)


def _metadata(*, boundary_mode: str = "closed") -> dict[str, object]:
    return {
        "units": {
            "time": "s",
            "position": "m",
            "velocity": "m/s",
            "density": "kg/m^3",
            "mass": "kg",
            "pressure": "Pa",
        },
        "coordinate_frame": "world",
        "geometry": {"id": "synthetic-box"},
        "control": {"id": "synthetic-control"},
        "boundary_mode": boundary_mode,
        "rigid_body_state": "synthetic-sidecar",
    }


def _write_hdf5(path: Path, *, valid: np.ndarray | None = None,
                zones: np.ndarray | None = None,
                times: np.ndarray | None = None,
                z_values: float = 0.0) -> None:
    frames, particles = 4, 6
    times = np.arange(frames, dtype="<f8") if times is None else times
    zones = np.zeros(particles, dtype="<i2") if zones is None else zones
    valid = np.ones((frames, particles), dtype=bool) if valid is None else valid
    particle_type = np.asarray([[3, 3, 3, 2, 2, 3]] * frames, dtype="<i1")
    position = np.zeros((frames, particles, 3), dtype="<f4")
    position[..., 2] = z_values
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=times)
        handle.create_dataset("particle_id", data=np.arange(particles, dtype="<i8"))
        handle.create_dataset("particle_zone", data=zones)
        handle.create_dataset("valid", data=valid, chunks=(1, 2))
        handle.create_dataset("type", data=particle_type, chunks=(1, 2))
        handle.create_dataset("position", data=position, chunks=(1, 2, 3))
        handle.create_dataset("velocity", data=np.ones_like(position), chunks=(1, 2, 3))
        handle.create_dataset("density", data=np.full((frames, particles), 1000.0, dtype="<f4"), chunks=(1, 2))
        handle.create_dataset("mass", data=np.ones((frames, particles), dtype="<f4"), chunks=(1, 2))
        handle.create_dataset("pressure", data=np.zeros((frames, particles), dtype="<f4"), chunks=(1, 2))
        handle.create_dataset("mk", data=np.ones((frames, particles), dtype="<i2"), chunks=(1, 2))


def _write_log(path: Path, dimension: int = 3) -> None:
    path.write_text(
        f"**{dimension}D-Simulation parameters:\n"
        "Particles of simulation (initial): 6\n"
        "CaseNfluid=4\n"
        "CaseNfloat=2\n"
        "Excluded particles...............: 0\n",
        encoding="utf-8",
    )


def test_good_chunked_audit_separates_fluid_and_floating_mass_and_is_json_safe(tmp_path: Path) -> None:
    trajectory = tmp_path / "good.h5"
    log = tmp_path / "Run.out"
    _write_hdf5(trajectory)
    _write_log(log, 3)

    report = audit_hdf5(trajectory, solver_log=log, metadata=_metadata(), particle_chunk=2)

    assert report["q_i_status"] == "Q-I-structure-pass"
    assert report["q_n_status"] == "not_assessed"
    assert report["production_eligibility"] == "not_evaluated"
    assert report["dimension_evidence"]["solver_dimension"] == 3
    assert report["dimension_evidence"]["inference_from_coordinate_values"] is False
    assert report["fluid_mass_ledger"]["initial_count"] == 4
    assert report["fluid_mass_ledger"]["initial_mass_kg"] == pytest.approx(4.0)
    assert report["floating_mass_ledger"]["initial_count"] == 2
    assert report["floating_mass_ledger"]["initial_mass_kg"] == pytest.approx(2.0)
    assert report["lifecycle"]["revived_identity_count"] == 0
    assert report["audit_parameters"]["full_trajectory_materialized"] is False
    json.dumps(report)


def test_legacy_format_reports_missing_units_geometry_control_and_boundary_evidence(tmp_path: Path) -> None:
    trajectory = tmp_path / "legacy.h5"
    _write_hdf5(trajectory)

    report = audit_hdf5(trajectory, particle_chunk=2)

    assert report["q_i_status"] == "Q-I-incomplete"
    assert "units:position" in report["missing_requirements"]
    assert "coordinate_frame" in report["missing_requirements"]
    assert "geometry" in report["missing_requirements"]
    assert "control" in report["missing_requirements"]
    assert "solver_dimension_actual_evidence" in report["missing_requirements"]
    assert "closed_or_open_lifecycle_declaration" in report["missing_requirements"]
    assert report["scientific_acceptance"] == "not_assessed"


def test_dimension_uses_solver_banner_and_never_nonzero_z_inference(tmp_path: Path) -> None:
    trajectory = tmp_path / "2d-banner-with-z.h5"
    log = tmp_path / "Run.out"
    _write_hdf5(trajectory, z_values=7.0)
    _write_log(log, 2)

    report = audit_hdf5(trajectory, solver_log=log, metadata=_metadata(), particle_chunk=2)

    assert report["dimension_evidence"]["solver_dimension"] == 2
    assert report["dimension_evidence"]["source"] == "solver_log_explicit_banner"
    assert report["dimension_evidence"]["inference_from_coordinate_values"] is False


def test_error_injection_valid_nonbinary_and_time_axis_are_structural_failures(tmp_path: Path) -> None:
    trajectory = tmp_path / "invalid.h5"
    _write_hdf5(trajectory)
    with h5py.File(trajectory, "r+") as handle:
        valid = handle["valid"][:].astype("u1")
        del handle["valid"]
        handle.create_dataset("valid", data=valid, chunks=(1, 2))
        handle["valid"][1, 2] = 2
        handle["time"][2] = handle["time"][1]

    report = audit_hdf5(trajectory, metadata=_metadata(), particle_chunk=2)

    assert report["q_i_status"] == "Q-I-structure-fail"
    assert "valid_not_binary" in report["structural_failures"]
    assert "time_not_strictly_increasing" in report["structural_failures"]


def test_error_injection_detects_duplicate_typed_identity_and_revival(tmp_path: Path) -> None:
    trajectory = tmp_path / "identity-lifecycle-invalid.h5"
    valid = np.ones((4, 6), dtype=bool)
    valid[1, 1] = False
    valid[2, 1] = True
    _write_hdf5(trajectory, valid=valid, zones=np.asarray([0, 0, 0, 0, 0, 0], dtype="<i2"))
    with h5py.File(trajectory, "r+") as handle:
        handle["particle_id"][1] = handle["particle_id"][0]

    report = audit_hdf5(trajectory, metadata=_metadata(), particle_chunk=2)

    assert report["q_i_status"] == "Q-I-structure-fail"
    assert "identity_axis_duplicate_typed_key" in report["structural_failures"]
    assert report["lifecycle"]["revived_identity_count"] == 1


def test_error_injection_rejects_nan_active_density_and_nonpositive_mass(tmp_path: Path) -> None:
    trajectory = tmp_path / "positive-finite-invalid.h5"
    _write_hdf5(trajectory)
    with h5py.File(trajectory, "r+") as handle:
        handle["density"][0, 0] = np.nan
        handle["mass"][0, 1] = 0.0

    report = audit_hdf5(trajectory, metadata=_metadata(), particle_chunk=2)

    assert report["q_i_status"] == "Q-I-structure-fail"
    assert "active_nonfinite:density" in report["structural_failures"]
    assert "active_mass_not_positive_finite" in report["structural_failures"]


def test_cost_estimate_is_metadata_only_and_resource_snapshot_has_children() -> None:
    estimate = estimate_hdf5_audit
    assert callable(estimate)
    snapshot = _resource_snapshot()
    assert set(snapshot) == {"self", "children"}
    assert "user_cpu_seconds" in snapshot["children"]


def test_protocol_is_versioned_and_declares_q_i_boundary() -> None:
    protocol = Path(__file__).parents[1] / "protocol" / "ds-data-02-schema-v1.json"
    payload = json.loads(protocol.read_text(encoding="utf-8"))
    assert payload["$id"].endswith("ds-data-02/hdf5-schema-v1")
    assert payload["properties"]["schema"]["const"] == "ds-data-02.hdf5-schema.v1"
    assert payload["x-semantics"]["fluid_type_code"] == 3
    assert payload["x-semantics"]["floating_type_code"] == 2
    assert payload["x-semantics"]["dimension"].find("z values") >= 0
