from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts.ds_data02_integrity import (
    FINITE_INITIAL_NUMERICAL_COHORT_WITH_EXCLUSIONS,
    audit_hdf5,
)


def _write_trajectory(path: Path, *, excluded: bool) -> None:
    frames, particles = 4, 6
    valid = np.ones((frames, particles), dtype=bool)
    if excluded:
        valid[2:, 0] = False
    position = np.zeros((frames, particles, 3), dtype=np.float32)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=np.arange(frames, dtype=np.float64))
        handle.create_dataset("particle_id", data=np.arange(particles, dtype=np.int64))
        handle.create_dataset("particle_zone", data=np.zeros(particles, dtype=np.int16))
        handle.create_dataset("valid", data=valid)
        handle.create_dataset("type", data=np.asarray([[3, 3, 3, 2, 2, 3]] * frames, dtype=np.int8))
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=np.ones_like(position))
        handle.create_dataset("density", data=np.full((frames, particles), 1000.0, dtype=np.float32))
        handle.create_dataset("mass", data=np.ones((frames, particles), dtype=np.float32))
        handle.create_dataset("pressure", data=np.zeros((frames, particles), dtype=np.float32))
        handle.create_dataset("mk", data=np.ones((frames, particles), dtype=np.int16))


def _write_log(path: Path, *, excluded: int) -> None:
    path.write_text(
        "**3D-Simulation parameters:\n"
        "Particles of simulation (initial): 6\n"
        "CaseNfluid=4\n"
        "CaseNfloat=2\n"
        f"Excluded particles...............: {excluded}\n",
        encoding="utf-8",
    )


def _metadata(*, ledger: dict[str, object]) -> dict[str, object]:
    return {
        "units": {"time": "s", "position": "m", "velocity": "m/s",
                  "density": "kg/m^3", "mass": "kg", "pressure": "Pa"},
        "coordinate_frame": "world",
        "geometry": {"id": "synthetic-box"},
        "control": {"id": "synthetic-control"},
        "boundary_mode": "open",
        "lifecycle_mode": FINITE_INITIAL_NUMERICAL_COHORT_WITH_EXCLUSIONS,
        "rigid_body_state": "synthetic-sidecar",
        "native_exclusion_ledger": ledger,
    }


def _ledger(*, valid: bool = True) -> dict[str, object]:
    row: dict[str, object] = {
        "zone": 0,
        "idp": 0,
        "first_missing_frame": 2,
        "motive": "native_solver_excluded_numerical_unknown",
        "motive_code": 1,
        "partvtkout_position_m": [0.1, 0.2, 0.3],
        "partvtkout_density_kg_m3": 998.5,
    }
    if not valid:
        row["first_missing_frame"] = 1
    return {
        "h5_full_timeline_checked": True,
        "h5_full_timeline_frames": 4,
        "runparts_counts": {"npout_sum": 1, "npoutpos_sum": 1, "npoutrho_sum": 0},
        "excluded_particles": [row],
    }


def test_finite_initial_cohort_with_complete_native_loss_ledger_passes_qi(tmp_path: Path) -> None:
    trajectory, log = tmp_path / "trajectory.h5", tmp_path / "Run.out"
    _write_trajectory(trajectory, excluded=True)
    _write_log(log, excluded=1)

    report = audit_hdf5(trajectory, solver_log=log, metadata=_metadata(ledger=_ledger()), particle_chunk=2)

    assert report["q_i_status"] == "Q-I-structure-pass"
    assert report["native_exclusion_ledger"]["status"] == "pass"
    assert report["native_exclusion_ledger"]["excluded_typed_count"] == 1
    assert report["lifecycle"]["initial_missing_at_final_count"] == 1
    json.dumps(report)


def test_incomplete_native_loss_ledger_stays_structural_fail(tmp_path: Path) -> None:
    trajectory, log = tmp_path / "trajectory.h5", tmp_path / "Run.out"
    _write_trajectory(trajectory, excluded=True)
    _write_log(log, excluded=1)

    report = audit_hdf5(trajectory, solver_log=log,
                        metadata=_metadata(ledger=_ledger(valid=False)), particle_chunk=2)

    assert report["q_i_status"] == "Q-I-structure-fail"
    assert "native_exclusion_ledger_incomplete" in report["structural_failures"]
    assert report["native_exclusion_ledger"]["status"] == "fail"


def test_density_exclusion_is_accounted_without_relabeling_as_position_or_physical_exit(tmp_path):
    trajectory, log = tmp_path / 'trajectory.h5', tmp_path / 'Run.out'
    _write_trajectory(trajectory, excluded=True)
    _write_log(log, excluded=1)
    ledger = _ledger()
    ledger['excluded_particles'][0]['motive_code'] = 2
    ledger['excluded_particles'][0]['partvtkout_density_kg_m3'] = 699.0
    ledger['runparts_counts'].update(npoutpos_sum=0, npoutrho_sum=1, npoutmov_sum=0)
    report = audit_hdf5(trajectory, solver_log=log, metadata=_metadata(ledger=ledger), particle_chunk=2)
    assert report['q_i_status'] == 'Q-I-structure-pass'
    assert report['native_exclusion_ledger']['native_exclusion_is_numerical_unknown'] is True
    ledger['runparts_counts']['npoutrho_sum'] = 0
    report = audit_hdf5(trajectory, solver_log=log, metadata=_metadata(ledger=ledger), particle_chunk=2)
    assert report['q_i_status'] == 'Q-I-structure-fail'
