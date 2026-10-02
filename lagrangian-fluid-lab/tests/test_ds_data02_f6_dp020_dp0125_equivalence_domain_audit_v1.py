from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/dp020_dp0125_cpu_003"
AUDIT = ROOT / "equivalence_domain_audit_001.json"
REQUESTS = ROOT / "qualification_requests_003/qualification_request_manifest_003.json"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_native_mass_rigid_and_continuous_equivalence_pass_but_domain_stays_pending():
    value = read(AUDIT)
    assert value["status"] == "continuous_contract_pass_domain_pending"
    assert value["gpu_launch"] is False
    assert len(value["cases"]) == 4
    for case in value["cases"]:
        checks = case["checks"]
        assert checks["actual_3d"]
        assert checks["authoritative_fluid_mass_pass"]
        assert checks["authoritative_rigid_contract_pass"]
        assert checks["continuous_physical_equivalence_pass"]
        assert checks["simulationdomain_coverage_pass"] is False
        assert case["authoritative_mass_and_rigid_checks"]["aggregate_inertia_positive"]
        assert case["authoritative_mass_and_rigid_checks"]["type2_particle_mass_is_not_aggregate_mass"]
        assert case["phase_aligned_native_geometry"]["phase_offset_is_discretization_record_only"]
        assert case["simulationdomain_coverage"]["status"] == "pending_solver_MapRealPos_or_root_domain_repair"


def test_wave_motion_and_moving_particles_are_bound_to_canonical_evidence():
    value = read(AUDIT)
    waves = [case for case in value["cases"] if case["mechanism_id"] == "wave_no_contact"]
    assert len(waves) == 2
    for case in waves:
        assert case["checks"]["moving_control_covered"]
        controls = case["wave_control_and_motion"]
        assert controls["height_matches_canonical"]
        assert controls["period_matches_canonical"]
        assert controls["depth_matches_canonical"]
        assert controls["ramp_matches_canonical"]
        assert controls["motion_sweep_in_canonical_physical_envelope"]
        assert controls["motion"]["time_s"] == [0.0, 12.8]
        assert case["phase_aligned_native_geometry"]["moving_bounds_initial_and_swept"]["guarded_swept_x_bounds_m"]


def test_storage_corrected_requests_are_additive_and_root_only():
    value = read(REQUESTS)
    assert value["status"] == "root_dispatch_pending_storage_and_domain_review"
    assert value["gpu_launch"] is False
    assert len(value["requests"]) == 4
    for row in value["requests"]:
        request = read(Path(row["path"]))
        assert request["attempt_id"].endswith("SOLVER_QUAL_FINE_STORAGE_DOMAIN_001")
        assert request["qualification_claim"].startswith("none_until_root")
        assert request["simulationdomain_gate"]["status"] == "pending_root_domain_review"
        assert request["estimated_storage_bytes"] >= request["cost_estimate"]["calculated_minimum_bytes"]
        assert request["max_wall_seconds"] > request["cost_estimate"]["linear_particle_scaled_seconds"]
        assert request["solver_launch_authority"].startswith("root only")
        assert len(request["input_sha256"]) == len(request["input_files"])

