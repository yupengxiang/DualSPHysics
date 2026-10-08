"""Manufactured F6 rigid-state semantics and SO(3) diagnostic tests."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_f6_rigid_state_ledger_v1.py"
SPEC = importlib.util.spec_from_file_location("f6_rigid_state_ledger_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import F6 rigid-state ledger")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_observer(path: Path, rows: list[tuple[int, float]]):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["part", "time [s]", "center.x [m]", "center.y [m]", "center.z [m]",
                         "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]"])
        for part, time_s in rows:
            writer.writerow([part, time_s, 1.0 + part, 2.0, 3.0, 0.1, 0.2, 0.3])
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path: Path):
    csv_path = tmp_path / "FloatingInfo.csv"
    csv_sha = write_observer(csv_path, [(0, 0.0), (1, 0.1)])
    conversion_path = tmp_path / "conversion-report.json"
    conversion_path.write_text(json.dumps({"conversion_status": "completed"}), encoding="utf-8")
    conversion_sha = hashlib.sha256(conversion_path.read_bytes()).hexdigest()
    conversion_contract = {"schema": "ds02.stage2.f6-conversion-contract.v1", "report": {"path": str(conversion_path), "sha256": conversion_sha}}
    manifest_row = {
        "sentinel_id": "F6-S1",
        "physical_case_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
        "small_sources": {"floating_csv_path": {"path": str(csv_path), "sha256": csv_sha}},
        "conversion_report": {"path": str(conversion_path), "sha256": conversion_sha},
        "conversion_contract": conversion_contract,
    }
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    output_row = {
        "physical_case_id": manifest_row["physical_case_id"],
        "conversion_contract": conversion_contract,
        "h5_read_ledger": {"opened_once": True, "closed_after_static_and_kabsch": True},
        "static": {"floating_support_mass_kg": 256.0, "floating_support_particle_count": 16384},
        "kabsch": {
            "status": "completed",
            "frozen_contract": {
                "so3_error_tolerances_deg": {"rmse": 2.0, "max": 5.0},
                "rotation_convention": "active column-vector world-from-initial; row positions transformed by R.T",
                "body_mass_kg": 128.0, "support_sample_mass_kg": 256.0,
            },
            "frames": [
                {"part": 0, "time_s": 0.0, "rotation_world_from_initial": identity,
                 "residual_rmse_m": 0.0, "residual_max_m": 0.0,
                 "singular_values": [3.0, 2.0, 1.0], "rank_relative": 1.0,
                 "sample_centroid_current_m": [1.0, 2.0, 3.0],
                 "observer_center_m": [1.0, 2.0, 3.0], "observer_omega_rad_s": [0.1, 0.2, 0.3]},
                {"part": 1, "time_s": 0.1, "rotation_world_from_initial": identity,
                 "residual_rmse_m": 0.01, "residual_max_m": 0.02,
                 "singular_values": [3.0, 2.0, 1.0], "rank_relative": 1.0,
                 "sample_centroid_current_m": [2.0, 2.0, 3.0],
                 "observer_center_m": [2.0, 2.0, 3.0], "observer_omega_rad_s": [0.1, 0.2, 0.3]},
            ],
        },
    }
    return manifest_row, output_row


def test_cross_pi_rotation_is_finite_without_euler_or_axis_claim():
    rotation = [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]]
    result = MODULE.so3_diagnostics(rotation)
    assert result["rotation_angle_deg"] == pytest.approx(180.0)
    assert result["near_pi_axis_ambiguity"] is True
    assert result["axis_semantics"].startswith("not reported")
    assert result["physical_orientation_claim"] == "UNKNOWN"


def test_noncommuting_matrix_is_checked_directly_without_euler_order():
    # Rz(90) Ry(90) is proper; no Euler labels are parsed or inferred.
    rotation = [[0.0, -1.0, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]]
    result = MODULE.so3_diagnostics(rotation)
    assert result["fit_status"] == "KABSCH_PROPER_ROTATION_DIAGNOSTIC"
    assert result["physical_orientation_claim"] == "UNKNOWN"


def test_reflection_is_rejected():
    with pytest.raises(MODULE.RigidLedgerError):
        MODULE.so3_diagnostics([[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])


def test_per_native_frame_sidecar_keeps_com_and_mass_semantics_unknown(tmp_path: Path):
    manifest_row, output_row = fixture(tmp_path)
    result = MODULE.validate_case(manifest_row, output_row)
    assert result["frame_count"] == 2
    assert result["mass_semantics"]["physical_body_mass_kg"] == 128.0
    assert result["mass_semantics"]["sampled_support_mass_kg"] == 256.0
    assert result["mass_semantics"]["physical_COM"] == "UNKNOWN_NOT_IDENTIFIED_BY_SUPPORT_SAMPLE_CENTROID"
    assert result["frames"][0]["observer_center_semantics"].startswith("FloatingInfo producer center")
    assert result["frames"][0]["physical_COM_m"] == "UNKNOWN"
    assert result["so3_contract"]["Euler_order"] == "UNKNOWN_NOT_USED"
    assert result["physical_fate"] == "UNKNOWN"


def test_body_sample_mass_swap_is_rejected():
    static = {"floating_support_mass_kg": 128.0, "floating_support_particle_count": 16384}
    frozen = {"body_mass_kg": 256.0, "support_sample_mass_kg": 128.0}
    with pytest.raises(MODULE.RigidLedgerError):
        MODULE.validate_mass_semantics(static, frozen)
