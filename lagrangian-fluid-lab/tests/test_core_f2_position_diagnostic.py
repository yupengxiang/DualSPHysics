import json
from pathlib import Path

from scripts.core_f2_position_diagnostic import CASES, candidate_config


LAB = Path(__file__).resolve().parents[1]
H0 = LAB / "campaigns/core-v1/cfd/prepared/F2_H0_static_cup_hold_canary"
H1 = LAB / "campaigns/core-v1/cfd/prepared/F2_H1_runtime_domain_extension_canary"
H2 = LAB / "campaigns/core-v1/cfd/prepared/F2_H2_mdbc_boundary_repair_canary"
FORENSICS = LAB / "campaigns/core-v1/cfd/f2-h0-position-loss-forensics.json"


def test_candidates_keep_physical_geometry_fixed_and_use_distinct_axes():
    domain = candidate_config("domain_extension")
    mdbc = candidate_config("mdbc_boundary")
    assert domain["physical_geometry_changed"] is False
    assert mdbc["physical_geometry_changed"] is False
    assert domain["boundary_method"] == 1
    assert mdbc["boundary_method"] == 2
    assert domain["runtime_domain"]["posmax"][2] == 2.4
    assert set(CASES) == {"domain_extension", "mdbc_boundary"}


def test_domain_candidate_is_cpu_ready_but_mdbc_stops_on_zero_normals():
    h1 = json.loads((H1 / "prepared.json").read_text())
    h2 = json.loads((H2 / "prepared.json").read_text())
    assert h1["preflight_pass"] is True
    assert h1["static_diagnostic_preflight"]["runtime_domain_zmax_m"] == 2.4
    assert h2["preflight_pass"] is False
    assert h2["native_initial"]["zero_boundary_normals"] > 0
    assert h2["static_diagnostic_preflight"]["mdbc_normals_complete_nonzero"] is False


def test_forensics_retains_position_loss_and_distinguishes_cup_escape():
    report = json.loads(FORENSICS.read_text())
    loss = report["position_loss"]
    assert loss["lost_particle_count"] == 598
    assert loss["first_loss_time_s"] == 0.4200382466835175
    assert loss["all_losses_above_open_cup_mouth"] is True
    assert loss["runtime_domain_ceiling_candidate_count"] == 598
    assert loss["endpoint_closed_wall_violation_count"] == 0
