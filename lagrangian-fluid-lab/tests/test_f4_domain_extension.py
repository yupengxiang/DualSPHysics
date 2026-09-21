import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts.f4_domain_extension import ballistic_projection, cell_allocation


LAB = Path(__file__).resolve().parents[1]
PREPARED = LAB / "campaigns/core-v1/cfd/prepared/F4_resting_pool_laminar_domain_extension_q075_dp005_canary_v1/prepared.json"
JOB = LAB / "campaigns/core-v1/cfd/f4-domain-extension-q075-dp005-canary-job.json"
BUDGET = LAB / "campaigns/core-v1/cfd/f4-domain-extension-budget-v1.json"


def test_cell_allocation_matches_registered_and_extension_bounds():
    cell = 0.0159217038434
    baseline = cell_allocation([-1.2, -0.4, -0.6], [2.4, 0.8, 1.8], cell)
    extended = cell_allocation([-1.2, -1.8, -72.0], [2.4, 0.8, 1.8], cell)
    assert baseline["counts"] == [227, 76, 151]
    assert baseline["allocated_cells"] == 2_605_052
    assert extended["counts"] == [227, 164, 4636]
    assert extended["allocated_cells"] == 172_589_008
    assert extended["allocated_cells"] > 60 * baseline["allocated_cells"]


def test_ballistic_projection_applies_gravity_only_to_z():
    result = ballistic_projection(
        [{"particle_id": 7, "position_m": [1.0, 2.0, -0.6], "velocity_mps": [0.5, -1.0, -2.0]}],
        source_time_s=1.0,
        horizon_s=2.0,
    )
    projected = result["particles"][0]["projected_position_m"]
    assert projected[0] == pytest.approx(1.5)
    assert projected[1] == pytest.approx(1.0)
    assert projected[2] == pytest.approx(-7.505)


def test_budget_keeps_q025_failure_separate_from_q075_domain_loss():
    report = json.loads(BUDGET.read_text())
    q025 = report["evidence"]["q025"]
    assert q025["native_loss_count"] == 0
    assert q025["hard_integrity_pass"] is False
    assert "not a repair" in q025["control_policy"]
    assert report["evidence"]["q075_exact_id_join"] is True
    assert report["q075_ballistic_projection"]["particle_count"] == 10
    assert report["proposed_physical_preserving_extension"]["physical_geometry_unchanged"] is True


def test_prepared_candidate_has_same_particles_and_only_domain_changes():
    prepared = json.loads(PREPARED.read_text())
    assert prepared["preflight_pass"] is True
    assert prepared["native_initial"]["zero_boundary_normals"] == 0
    assert prepared["native_initial"]["fluid_particles"] == 737_792
    assert prepared["mass_preflight"]["mass_gate_pass"] is True
    assert prepared["config"]["qualification_claim"] == "none"
    assert prepared["config"]["qualification_only"] is True
    assert prepared["geometry_identity"]["unchanged"] is True
    assert prepared["geometry_identity"]["source_casedef_sha256"] == prepared["geometry_identity"]["candidate_casedef_sha256"]
    generated = ET.parse(prepared["generated_prefix"] + ".xml").getroot()
    domain = generated.find(".//simulationdomain")
    assert [float(domain.find("posmin").get(a)) for a in "xyz"] == pytest.approx([-1.2, -1.8, -72.0])
    assert [float(domain.find("posmax").get(a)) for a in "xyz"] == pytest.approx([2.4, 0.8, 1.8])
    assert prepared["config"]["domain_extension"]["physical_geometry_unchanged"] is True


def test_job_uses_lab_venv_and_has_memory_headroom():
    job = json.loads(JOB.read_text())
    assert job["attempt_role"] == "repair_canary"
    assert job["qualification_claim"] == "none"
    assert job["argv"][0].endswith("/.venv/bin/python")
    assert job["resources"]["gpu_peak_mib"] == 4096
    assert job["resources"]["ram_mib"] == 32768
    assert job["registered_window_s"] == pytest.approx(4.34)
