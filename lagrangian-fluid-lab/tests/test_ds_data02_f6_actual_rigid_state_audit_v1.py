"""Tests for DS-DATA-02 F6 Actual Rigid State and Node Velocity Audit v1.

Verifies:
1. Synthetic FloatingInfo CSV parse and motion audit (initial state [0.08, 0.12, 0.06] rad/s, center [2.4, 1.2, 1.08] m, vel=0).
2. Synthetic PartVTK floating particles CSV parse and audit (Frame 0 vel=0, mass sum 256 kg, Frame 1 rigid kinematics consistency).
3. Mass semantics separation (observed CSV mass vs declared physical mass vs solver massp vs derived node mass).
4. Strict runner request compliance for all 3 generated requests in handoff 003.
5. Manifest and bindings integrity.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
INTEGRATION_SCRIPTS_DIR = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts")
CAMPAIGN_DIR = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/families/F6/handoff_20261003/f6_angular_release_actual_rigid_state_audit_003"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(INTEGRATION_SCRIPTS_DIR))

import ds_data02_f6_actual_rigid_state_audit_v1 as audit_mod
from ds_data02_strict_dispatch_v1 import validate_request


def test_audit_floating_motion_synthetic(tmp_path: Path):
    """Verifies audit_floating_motion on synthetic FloatingInfo data."""
    csv_path = tmp_path / "FloatingInfo_mk60.csv"
    headers = [
        "part", "time [s]", "fvel.x [m/s]", "fvel.y [m/s]", "fvel.z [m/s]",
        "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]",
        "center.x [m]", "center.y [m]", "center.z [m]",
        "surge [m]", "sway [m]", "heave [m]", "roll [deg]", "pitch [deg]", "yaw [deg]"
    ]
    row0 = ["0", "0.0", "0.0", "0.0", "0.0", "0.08", "0.12", "0.06", "2.4", "1.2", "1.08", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0"]
    row1 = ["1", "0.05", "0.0", "0.0", "-0.01", "0.0799", "0.1198", "0.0599", "2.4", "1.2", "1.0795", "0.0", "0.0", "-0.0005", "0.1", "0.15", "0.08"]

    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(headers)
        writer.writerow(row0)
        writer.writerow(row1)

    rows = audit_mod.parse_floating_info_csv(csv_path)
    assert len(rows) == 2

    res = audit_mod.audit_floating_motion(
        rows, expected_omega=[0.08, 0.12, 0.06], expected_center=[2.4, 1.2, 1.08]
    )

    f0 = res["frame_0"]
    assert f0["time_zero"] is True
    assert f0["center_matches_continuous"] is True
    assert f0["linear_velocity_is_zero"] is True
    assert f0["angular_velocity_matches_declared"] is True
    assert f0["initial_displacements_zero"] is True
    assert f0["initial_euler_angles_zero"] is True

    f1 = res["frame_1"]
    assert f1["angular_motion_active"] is True
    assert f1["time_s"] == 0.05
    assert res["initial_rigid_state_verified"] is True


def test_audit_floating_particles_synthetic(tmp_path: Path):
    """Verifies audit_floating_particles with Frame 0 (vel=0) and Frame 1 (rigid rotation)."""
    f0_csv = tmp_path / "PartFloating_0000.csv"
    f1_csv = tmp_path / "PartFloating_0001.csv"

    center = [2.4, 1.2, 1.08]
    omega = [0.08, 0.12, 0.06]
    v_cm = [0.0, 0.0, -0.01]

    # Create 8 corners around center: +/- 0.4 in X, +/- 0.4 in Y, +/- 0.2 in Z
    offsets = [
        (-0.4, -0.4, -0.2), (-0.4, -0.4, 0.2), (-0.4, 0.4, -0.2), (-0.4, 0.4, 0.2),
        (0.4, -0.4, -0.2), (0.4, -0.4, 0.2), (0.4, 0.4, -0.2), (0.4, 0.4, 0.2)
    ]
    m_p = 32.0  # Total mass 256 kg across 8 particles

    # Frame 0
    with f0_csv.open("w", newline="") as f:
        f.write("TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid\n")
        f.write("0,8,8,0,0,8,0\n\n")
        f.write("Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3],Mass [kg],Type,Mk,\n")
        for i, (dx, dy, dz) in enumerate(offsets):
            x, y, z = center[0] + dx, center[1] + dy, center[2] + dz
            f.write(f"{x},{y},{z},0,{i},0.0,0.0,0.0,1000.0,{m_p},2,60\n")

    # Frame 1
    with f1_csv.open("w", newline="") as f:
        f.write("TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid\n")
        f.write("1,8,8,0,0,8,0\n\n")
        f.write("Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3],Mass [kg],Type,Mk,\n")
        for i, (dx, dy, dz) in enumerate(offsets):
            x, y, z = center[0] + dx, center[1] + dy, center[2] + dz
            # v_p = v_cm + omega x r
            vx = v_cm[0] + (omega[1] * dz - omega[2] * dy)
            vy = v_cm[1] + (omega[2] * dx - omega[0] * dz)
            vz = v_cm[2] + (omega[0] * dy - omega[1] * dx)
            f.write(f"{x},{y},{z},0,{i},{vx},{vy},{vz},1000.0,{m_p},2,60\n")

    f0_data = audit_mod.parse_floating_particles_csv(f0_csv)
    f1_data = audit_mod.parse_floating_particles_csv(f1_csv)

    assert f0_data["particle_count"] == 8
    assert f0_data["all_vel_zero"] is True
    assert abs(f0_data["mass_sum_kg"] - 256.0) < 1e-4

    cfg = {
        "expected_counts": {"floating": 8},
        "expected_center": center,
        "massbody_kg": 128.0,
        "masspart_kg": 0.015625,
        "native_csv_mass_sum_kg": 256.0,
        "derived_node_mass_kg": 16.0,
    }

    fl_row1 = {
        "linear_velocity_m_s": v_cm,
        "angular_velocity_rad_s": omega,
        "center_m": center,
    }

    res = audit_mod.audit_floating_particles(f0_data, f1_data, cfg, None, fl_row1)

    assert res["floating_nodes_verified"] is True
    assert res["frame_0"]["count_matches"] is True
    assert res["frame_0"]["centroid_matches"] is True
    assert res["frame_0"]["all_velocities_zero"] is True

    f1_res = res["frame_1"]
    assert f1_res["velocities_are_nonzero"] is True
    kin = f1_res["kinematic_consistency"]
    assert kin["consistent_with_rigid_kinematics"] is True
    assert kin["rmse_m_s"] < 1e-5


def test_runner_requests_compliance():
    """Validates that all requests in handoff 003 comply with strict dispatch v1."""
    req_dir = CAMPAIGN_DIR / "requests"
    assert req_dir.is_dir()
    requests = sorted(req_dir.glob("*.json"))
    assert len(requests) == 3

    for req_p in requests:
        req = json.loads(req_p.read_text())
        validate_request(req)
        assert req["schema"] == "ds02.runner-request.v2"
        assert req["family_id"] == "F6"
        assert req["case_id"] == "F6_ANGULAR_RELEASE_DP025"
        assert req["kind"] == "cpu"
        assert req["launch_allowed"] is False
        assert req["root_review_required"] is True
        assert req["cpu_threads"] <= 2
        assert req["max_wall_seconds"] <= 1800


def test_manifest_and_bindings():
    """Validates manifest and bindings files in handoff 003."""
    manifest_p = CAMPAIGN_DIR / "manifest.json"
    bindings_p = CAMPAIGN_DIR / "bindings.json"

    assert manifest_p.is_file()
    assert bindings_p.is_file()

    manifest = json.loads(manifest_p.read_text())
    bindings = json.loads(bindings_p.read_text())

    assert manifest["schema"] == "ds02.f6.angular-release-rigid-state-audit-manifest.v1"
    assert manifest["family_id"] == "F6"
    assert manifest["launch_allowed"] is False
    assert manifest["root_review_required"] is True
    assert manifest["coarse_completed_gpu_021"]["status"] == "completed"
    assert manifest["coarse_completed_gpu_021"]["returncode"] == 0

    assert "bound_inputs" in bindings
    for path_str, info in bindings["bound_inputs"].items():
        p = Path(path_str)
        assert p.is_file(), f"Bound input missing: {p}"
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        assert digest == info["sha256"], f"Digest mismatch for: {p}"
