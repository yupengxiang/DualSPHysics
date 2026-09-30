from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import h5py
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_f4_science as science


def _operators() -> dict:
    return {
        "schema": science.OPERATORS_SCHEMA,
        "physical_support": {
            "support_radius_m": 0.02,
            "minimum_cross_support_pairs": 1,
            "minimum_support_mass_fraction_of_smaller_source": 0.01,
        },
        "comparison": {"macro_error_budget_fraction": 0.05},
    }


def _metadata() -> dict:
    return {
        "mechanism_id": "finite_drop_pool",
        "resolution": "fine",
        "time_variant": "native",
        "physical_binding_sha256": "physical-hash",
        "physical_binding": {
            "mechanism_id": "finite_drop_pool",
            "initial_state": {
                "source_labels": {"mkfluid:0": "pool", "mkfluid:1": "falling_drop"},
                "source_regions": {
                    "pool": {"low_m": [0.0, 0.0, 0.0], "size_m": [1.0, 1.0, 1.0], "mkfluid": 0},
                    "drop": {"low_m": [1.2, 0.0, 0.0], "size_m": [0.2, 1.0, 1.0], "mkfluid": 1},
                },
            },
            "geometry": {
                "pool": {"low_m": [0.0, 0.0, 0.0], "size_m": [1.0, 1.0, 1.0], "mkfluid": 0},
                "drop": {"low_m": [1.2, 0.0, 0.0], "size_m": [0.2, 1.0, 1.0], "mkfluid": 1},
            },
        },
        "typed_identity_binding": {"fluid_mkfluid_to_native_mk": {"0": 1, "1": 2}},
        "initialization_evidence": {"native_initial_mass_by_source_kg": {"pool": 2.0, "falling_drop": 2.0}},
    }


def _write_h5(path: Path, *, revive: bool = False) -> None:
    frames, particles = 3, 4
    initial_type = np.array([3, 3, 3, 3], dtype=np.int8)
    initial_mk = np.array([1, 1, 2, 2], dtype=np.int16)
    positions = np.zeros((frames, particles, 3), dtype=np.float32)
    positions[:, 0] = [0.1, 0.1, 0.1]
    positions[:, 1] = [0.1, 0.1, 0.1]
    positions[:, 2] = [[1.3, 0.1, 0.1], [0.9, 0.1, 0.1], [0.9, 0.1, 0.1]]
    positions[:, 3] = [[1.3, 0.1, 0.1], [0.9, 0.1, 0.1], [0.9, 0.1, 0.1]]
    valid = np.ones((frames, particles), dtype=bool)
    if revive:
        valid[1, 2] = False
        valid[2, 2] = True
    else:
        valid[2, 2] = False
    velocity = np.zeros_like(positions)
    density = np.full((frames, particles), 1000.0, dtype=np.float32)
    mass = np.ones((frames, particles), dtype=np.float32)
    mass[~valid] = np.nan
    pressure = np.zeros((frames, particles), dtype=np.float32)
    typ = np.where(valid, 3, -1).astype(np.int8)
    mk = np.where(valid, initial_mk[None, :], -1).astype(np.int16)
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=np.array([0.0, 1.0, 2.0]))
        h5.create_dataset("particle_id", data=np.arange(particles, dtype=np.uint32))
        h5.create_dataset("particle_zone", data=np.zeros(particles, dtype=np.int16))
        h5.create_dataset("initial_type", data=initial_type)
        h5.create_dataset("initial_mk", data=initial_mk)
        h5.create_dataset("initial_mass", data=np.ones(particles, dtype=np.float32))
        h5.create_dataset("valid", data=valid)
        h5.create_dataset("type", data=typ)
        h5.create_dataset("mk", data=mk)
        h5.create_dataset("position", data=positions)
        h5.create_dataset("velocity", data=velocity)
        h5.create_dataset("density", data=density)
        h5.create_dataset("mass", data=mass)
        h5.create_dataset("pressure", data=pressure)


def test_support_uses_actual_clouds_after_initial_boxes() -> None:
    a = np.array([[0.0, 0.0, 0.0], [0.0, 0.02, 0.0], [0.0, 0.0, 0.02]])
    b = a + np.array([0.015, 0.0, 0.0])
    result = science._support_detector(a, b, np.ones(3), np.ones(3), minimum_pairs=1, source_mass_scale_kg=3.0)
    assert result["contact"] is True
    assert result["support_pairs"] >= 1


def test_calibration_exposes_translation_rotation_and_sampling() -> None:
    calibration = science._calibration()
    assert calibration["translation"][0]["contact"] is False
    assert calibration["translation"][-1]["contact"] is True
    assert "rotation_fixture" in calibration
    assert "sampling_fixture" in calibration


def test_runparts_sums_full_window_including_nonzero_early_row(tmp_path: Path) -> None:
    path = tmp_path / "RunPARTs.csv"
    path.write_text(
        "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov;NpSim;NpfSim\n"
        "0;0;0;0;0;0;4;4\n"
        "1;1;2;1;1;0;2;2\n"
        "2;2;0;0;0;0;2;2\n",
        encoding="utf-8",
    )
    result = science._read_runparts(path)
    assert result["totals"] == {"NpOut": 2, "NpOutPos": 1, "NpOutRho": 1, "NpOutMov": 0}
    assert result["first_nonzero"]["NpOut"]["part"] == 1


def test_lifecycle_closes_exclusion_as_unknown_not_physical_exit(tmp_path: Path) -> None:
    h5_path = tmp_path / "trajectory.h5"
    _write_h5(h5_path)
    runparts = {"status": "available", "totals": {"NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0}, "rows": [{"part": 2, "time_s": 2.0, "NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0}]}
    partout = {"status": "available", "rows": [{"idp": 2, "zone": 0, "part_out": 2, "motive_code": 1, "motive": "position", "position_m": [0.9, 0.1, 0.1], "density_kg_m3": 1000.0}], "motive_counts": {"1": 1}}
    native = {"facts": {"saved_frames": 3, "excluded_interval_sums": {"NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0}}}
    result = science.audit_lifecycle(h5_path=h5_path, metadata=_metadata(), runparts=runparts, partout=partout, native_accounting=native)
    assert result["status"] == "pass"
    assert result["lifecycle"]["terminal_missing_fluid_typed_count"] == 1
    record = result["lifecycle"]["missing_typed_identity_records"][0]
    assert record["state"] == "numerical_unknown"
    assert record["physical_exit_inferred"] is False
    assert result["native_exclusion_ledger"]["closure"] == "closed_numerical_unknown"


def test_lifecycle_revival_is_a_failure(tmp_path: Path) -> None:
    h5_path = tmp_path / "trajectory.h5"
    _write_h5(h5_path, revive=True)
    zero = {"NpOut": 0, "NpOutPos": 0, "NpOutRho": 0, "NpOutMov": 0}
    result = science.audit_lifecycle(
        h5_path=h5_path,
        metadata=_metadata(),
        runparts={"status": "available", "totals": zero, "rows": []},
        partout={"status": "available", "rows": [], "motive_counts": {}},
        native_accounting={"facts": {"saved_frames": 3, "excluded_interval_sums": zero}},
    )
    assert result["status"] == "fail"
    assert "identity_revived_after_missing" in result["errors"]


def test_curve_reports_mass_time_and_particle_seconds(tmp_path: Path) -> None:
    h5_path = tmp_path / "trajectory.h5"
    _write_h5(h5_path)
    output = tmp_path / "curve.csv"
    result = science.compute_curve_and_events(h5_path=h5_path, metadata=_metadata(), operators=_operators(), output_csv=output)
    # Both source particles enter the finite downstream aperture for one
    # second.  The ledger keeps kg*s and an unweighted per-particle seconds
    # statistic as different quantities.
    assert result["source_event_data"]["falling_drop"]["residence_mass_time_kg_s"] >= 0.0
    assert result["source_event_data"]["falling_drop"]["residence_particle_time_s"] is not None
    with output.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3
    assert "source_support_contact" in rows[0]
