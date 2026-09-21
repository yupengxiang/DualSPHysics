import hashlib
import json
from pathlib import Path

import pytest


LAB = Path(__file__).resolve().parents[1]
PREPARED_DIR = LAB / "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_canary_v3"
PREPARED = PREPARED_DIR / "prepared.json"
PREFLIGHT = PREPARED_DIR / "static-preflight.json"
JOB = LAB / "campaigns/core-v1/cfd/f2-resting-fill-side-wet-full-cup-v3-canary-job.json"
CARD = LAB / "campaigns/core-v1/cfd/f2-resting-fill-side-wet-full-cup-v3-candidate-card.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def test_full_cup_continuum_and_native_preflight_are_independent_and_valid():
    prepared = json.loads(PREPARED.read_text())
    preflight = json.loads(PREFLIGHT.read_text())
    config = prepared["config"]
    box = config["fluid_boxes"][0]
    assert config["scope_id"] == "F2_resting_fill_side_wet_full_cup_x_v3"
    assert config["revision_id"] == "F2_resting_fill_side_wet_full_cup_v3"
    assert config["qualification_only"] is True
    assert config["qualified"] is False
    assert config["stage"] == "repair_canary"
    assert config["split"] == "qualification_only"
    assert config["physical_case_id"].endswith("_v3")
    assert box["low"] == [0.0, -0.15, 0.65]
    assert box["size"] == pytest.approx([0.425, 0.30, 0.18505882352941177])
    assert box["size"][0] * box["size"][1] * box["size"][2] == pytest.approx(0.023595)
    assert config["initial_condition"]["continuous_fluid_faces_are_physical_cup_faces"] is True
    assert config["initial_condition"]["mass_rescaling"] is False
    assert prepared["preflight_pass"] is True
    assert preflight["preflight_pass"] is True
    assert all(preflight["checks"].values())
    assert preflight["checks"]["fluid_inside_physical_cup"] is True
    assert preflight["checks"]["target_native_position_bounds"] is True
    assert preflight["native_source"]["fluid_particles"] == 54720
    assert preflight["native_fluid_position_bounds_m"]["low"] == pytest.approx([0.0025, -0.145, 0.66])
    assert preflight["native_fluid_position_bounds_m"]["high"] == pytest.approx([0.4225, 0.1475, 0.8325])
    assert preflight["physical_face_clearance_m"]["left"] == pytest.approx(0.0025)
    assert preflight["physical_face_clearance_m"]["right"] == pytest.approx(0.0025)
    assert preflight["physical_face_clearance_m"]["front"] == pytest.approx(0.005)
    assert preflight["physical_face_clearance_m"]["back"] == pytest.approx(0.0025)
    assert preflight["native_source"]["fluid_particles"] != 56115
    assert preflight["mass_preflight"]["mass_rescaling"] is False
    assert preflight["mass_preflight"]["mass_gate_pass"] is True
    assert preflight["mass_preflight"]["total_relative_error"] == pytest.approx(-0.021614748887476387)


def test_previous_sampling_attempts_are_retained_as_nonqualification_records():
    v1 = LAB / "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_canary_v1/static-preflight.json"
    v2 = LAB / "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_canary_v2/static-preflight.json"
    assert v1.is_file()
    assert v2.is_file()
    assert json.loads(v1.read_text())["preflight_pass"] is True
    assert json.loads(v2.read_text())["preflight_pass"] is False
    card = json.loads(CARD.read_text())
    records = {item["id"]: item for item in card["source_failure_context"]["prior_candidate_preflight_records"]}
    assert records["F2_resting_fill_side_wet_v1"]["status"] == "prepared_but_not_frozen"
    assert records["F2_resting_fill_side_wet_full_cup_v2"]["status"] == "preflight_failed_and_retained"


def test_job_and_candidate_card_bind_frozen_inputs_without_launch_claim():
    prepared = json.loads(PREPARED.read_text())
    job = json.loads(JOB.read_text())
    card = json.loads(CARD.read_text())
    assert job["qualification_only"] is True
    assert job["qualification_claim"] == "none"
    assert job["scope_id"] == prepared["config"]["scope_id"]
    assert job["revision_id"] == prepared["config"]["revision_id"]
    assert job["physical_geometry_changed"] is False
    assert job["initial_condition_changed"] is True
    assert job["mass_rescaling"] is False
    assert job["argv"][1].endswith("scripts/f2_resting_fill_side_wet_v3.py")
    assert job["resources"] == {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 0.25}
    assert {item["path"]: item["sha256"] for item in job["input_files"]}[str(PREPARED)] == digest(PREPARED)
    for item in job["input_files"]:
        assert Path(item["path"]).is_file()
        assert digest(Path(item["path"])) == item["sha256"]
    assert card["status"] == "cpu_prepared_unsubmitted"
    assert card["qualification_claim"].startswith("none;")
    assert card["qualified"] is False
    assert card["qualification_only"] is True
    assert card["supersedes_nothing"] is True
    assert card["gpu_launch_by_subagent"] is False
    assert card["central_ledger_mutation"] == 0
    assert card["launch_policy"]["gpu_submit"] is False
    assert card["launch_policy"]["ledger_submit"] is False
    assert card["artifacts"]["prepared"]["sha256"] == digest(PREPARED)
    assert card["artifacts"]["static_preflight"]["sha256"] == digest(PREFLIGHT)
    assert card["artifacts"]["job"]["sha256"] == digest(JOB)
