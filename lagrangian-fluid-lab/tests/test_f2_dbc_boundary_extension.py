"""Static contract checks for the unsubmitted DBC 5 s extension proposal."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
PREPARED = LAB / (
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2_extension5s_v2/prepared.json"
)
JOB = LAB / "campaigns/core-v1/cfd/f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-extension5s-v2-job.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_extension_is_one_time_window_extension_only():
    prepared = json.loads(PREPARED.read_text())
    config = prepared["config"]
    assert prepared["preflight_pass"] is True
    assert prepared["qualification_only"] is True
    assert config["extension_only"] is True
    assert config["stage"] == "extension_canary"
    assert config["split"] == "qualification_only"
    assert config["time_max_s"] == 5.0
    assert config["maximum_extended_time_s"] == 5.0
    assert config["boundary_method"] == 1
    assert config["cfl"] == 0.2
    assert config["initial_condition_changed"] is False
    assert config["mass_rescaling"] is False
    assert config["qualified"] is False


def test_extension_keeps_decoded_native_and_geometry_assets():
    prepared = json.loads(PREPARED.read_text())
    native = prepared["native_initial"]
    preflight = prepared["dynamic_canary_preflight"]
    assert native["fluid_particles"] == 54720
    assert native["native_sampling_matches_passed_static"] is True
    assert native["finite_initial_arrays"] is True
    assert preflight["geometry_asset_reuse"] == {
        "bi4_decoded_native_state": True,
        "all_vtk": True,
        "bound_vtk": True,
        "fluid_vtk": True,
        "mkcells_vtk": True,
    }
    assert preflight["native_equivalence"]["only_case_name_metadata_changed"] is True
    assert preflight["native_equivalence"]["pass"] is True

    definition = ET.parse(prepared["definition_audit"]["definition"]).getroot()
    assert definition.find("./casedef/normals") is None
    assert definition.find(".//execution/parameters/parameter[@key='Boundary']").get("value") == "1"
    assert definition.find(".//execution/parameters/parameter[@key='TimeMax']").get("value") == "5.0"
    assert definition.find(".//mvrotfile").get("duration") == "5"
    assert definition.find(".//begin").get("finish") == "5"
    motion = Path(prepared["definition_audit"]["motion_file"]).read_text().splitlines()
    assert motion[-1] == "5.000000;-105.000000000"


def test_extension_job_is_hash_closed_and_does_not_claim_qualification():
    prepared = json.loads(PREPARED.read_text())
    job = json.loads(JOB.read_text())
    assert job["extension_only"] is True
    assert job["qualification_only"] is True
    assert job["qualification_claim"] == "none"
    assert job["registered_window_s"] == 5.0
    assert job["maximum_extended_window_s"] == 5.0
    assert job["gate_policy"].startswith("unchanged")

    files = {item["path"]: item["sha256"] for item in job["input_files"]}
    assert files[str(PREPARED)] == _sha256(PREPARED)
    for path, expected in prepared["inputs"].items():
        assert files[path] == expected
    for item in job["input_files"]:
        path = Path(item["path"])
        assert path.is_file(), path
        assert _sha256(path) == item["sha256"], path
