"""Static contract checks for the unsubmitted F2 DBC repair canary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
PREPARED = LAB / (
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2/prepared.json"
)
JOB = LAB / "campaigns/core-v1/cfd/f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-v2-job.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_dbc_prepared_contract_is_cpu_preflighted_and_qualification_only():
    prepared = json.loads(PREPARED.read_text())
    config = prepared["config"]
    assert prepared["preflight_pass"] is True
    assert prepared["qualification_only"] is True
    assert config["stage"] == "repair_canary"
    assert config["split"] == "qualification_only"
    assert config["boundary_method"] == 1
    assert config["recipe"] == "native_dbc"
    assert config["repair_candidate_id"] == "moving_boundary_formulation_dbc"
    assert config["cfl"] == 0.2
    assert config["repair_hypothesis"]["same_as_cfl010"] is False
    assert config["initial_condition_changed"] is False
    assert config["mass_rescaling"] is False
    assert prepared["solver_arguments"] == []


def test_dbc_reuses_passed_fluid_lattice_without_mdbc_normal_gate():
    prepared = json.loads(PREPARED.read_text())
    native = prepared["native_initial"]
    preflight = prepared["dynamic_canary_preflight"]
    assert native["fluid_particles"] == 54720
    assert native["expected_fluid_particles"] == 54720
    assert native["unique_ids"] is True
    assert native["finite_initial_arrays"] is True
    assert native["initial_fluid_zero_velocity"] is True
    assert native["native_sampling_matches_passed_static"] is True
    assert native["normal_preflight_applicability"] == "not_applicable_for_DBC"
    assert preflight["normal_preflight_applicability"] == "not_applicable_for_DBC"
    assert preflight["catchment_wall_particles_present"] is True

    definition = ET.parse(prepared["definition_audit"]["definition"]).getroot()
    boundary = definition.find(".//execution/parameters/parameter[@key='Boundary']")
    assert boundary is not None and boundary.get("value") == "1"
    assert definition.find("./casedef/normals") is None


def test_dbc_job_is_hash_closed_and_does_not_claim_t1():
    prepared = json.loads(PREPARED.read_text())
    job = json.loads(JOB.read_text())
    assert job["qualification_only"] is True
    assert job["split"] == "qualification_only"
    assert job["qualification_claim"] == "none"
    assert job["boundary_method"] == "native DBC Boundary=1; no -mdbc_noslip argument"
    assert job["resources"]["gpu_peak_mib"] == 12288
    assert job["registered_window_s"] == 2.5

    files = {item["path"]: item["sha256"] for item in job["input_files"]}
    assert files[str(PREPARED)] == _sha256(PREPARED)
    for path, expected in prepared["inputs"].items():
        assert files[path] == expected
    for item in job["input_files"]:
        path = Path(item["path"])
        assert path.is_file(), path
        assert _sha256(path) == item["sha256"], path
