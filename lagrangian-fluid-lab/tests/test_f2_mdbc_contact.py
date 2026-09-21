from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
PREPARED = LAB / "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_closed_catchment_mdbc_cfl010_v1/prepared.json"
JOB = LAB / "campaigns/core-v1/cfd/f2-resting-fill-side-wet-full-cup-closed-catchment-mdbc-cfl010-canary-v1-job.json"
FORENSICS = LAB / "campaigns/core-v1/cfd/f2-full-cup-closed-catchment-mdbc-v2-motion-contact-preflight-v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_contact_forensics_binds_native_and_motion_evidence():
    report = json.loads(FORENSICS.read_text())
    assert report["read_only"] is True
    assert report["solver_relaunched"] is False
    assert report["qualification_claim"] is None
    assert report["forensic_code"]["sha256"] == _sha256(LAB / "scripts/f2_full_cup_closed_catchment_mdbc_contact.py")
    assert report["normal_audit"]["normal_preflight_pass"] is True
    assert report["normal_audit"]["zero_normals"] == 0
    assert report["motion_and_time_audit"]["motion"]["axis1"]["y"] == "-1"
    assert report["motion_and_time_audit"]["motion"]["axis2"]["y"] == "1"
    assert report["motion_and_time_audit"]["motion"]["wall_velocity_check"]["max_abs_difference_m_s"] < 2e-4
    assert report["motion_and_time_audit"]["dtmin_adjustment_before_first_cup_event"] is False


def test_cfl_repair_prepared_is_single_variable_and_native_clean():
    prepared = json.loads(PREPARED.read_text())
    config = prepared["config"]
    assert prepared["preflight_pass"] is True
    assert prepared["qualification_only"] is True
    assert config["stage"] == "repair_canary"
    assert config["split"] == "qualification_only"
    assert config["repair_candidate_id"] == "moving_mdbc_contact_time_resolution_cfl_half"
    assert config["cfl"] == 0.1
    assert config["time_control"] == {"cflnumber": 0.1, "DtIni": 0.0, "DtMin": 0.0, "DtFixed": 0.0}
    assert config["physical_geometry_changed"] is True
    assert config["initial_condition_changed"] is False
    assert config["mass_rescaling"] is False
    native = prepared["native_candidate_preflight"]
    assert native["pass"] is True
    assert native["zero_boundary_normals"] == 0
    generated = ET.parse(Path(prepared["generated_prefix"]).with_suffix(".xml")).getroot()
    assert {float(node.get("value")) for node in generated.findall(".//cflnumber")} == {0.1}
    assert all(Path(path).is_file() and _sha256(Path(path)) == digest for path, digest in prepared["inputs"].items())


def test_cfl_repair_job_remains_candidate_only():
    job = json.loads(JOB.read_text())
    assert job["qualification_only"] is True
    assert job["split"] == "qualification_only"
    assert job["qualification_claim"] == "none"
    assert job["single_variable_change"] == {
        "field": "time_control.cflnumber",
        "baseline": 0.2,
        "candidate": 0.1,
        "all_other_prepared_fields_equal_to_v2": True,
    }
    assert job["resources"] == {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2}
    assert job["required_outputs"] == [
        "product/result.json",
        "product/trajectory.h5",
        "product/audit.json",
        "product/observations.json",
    ]
