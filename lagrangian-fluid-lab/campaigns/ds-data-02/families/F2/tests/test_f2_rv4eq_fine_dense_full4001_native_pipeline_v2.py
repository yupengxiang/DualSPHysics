"""Unit tests for F2 RV4EQ fine dense full-4001 native pipeline v2.

All test evidence and fixtures in this file are strictly SYNTHETIC MOCK FIXTURES ONLY.
Label: synthetic_mock_fixture_only.

Verifies:
1. Pipeline manifest, configs, requests, sidecars, and errata schema and provenance.
2. Saved solver telemetry verification against actual save report (attempt 021).
3. Dual mass authority: native float32 24.5760011673 kg vs historical XML decimal 24.576 kg.
4. Refusal to fabricate: routine cleanly raises SourceUnavailableError when actual sources are missing.
5. Mandatory 13 datasets typed contract and fluid UID cohort invariance.
6. Synthetic end-to-end execution of fresh v7 native-weight event operator.
7. Strict dispatcher request validation via ds_data02_runtime_v2.validate_request.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import pytest

import h5py
import numpy as np

F2_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
sys.path.insert(0, str(INTEGRATION_LAB / "scripts"))
sys.path.insert(0, str(F2_ROOT))

from ds_data02_runtime_v2 import validate_request
from f2_rv4eq_fine_dense_full4001_event_semantics_v7 import (
    observe,
    operator_spec,
    SourceUnavailableError,
    ObservationError,
    NATIVE_FLOAT32_PARTICLE_KG,
    XML_DECIMAL_PARTICLE_KG,
    TOTAL_FLUID_PARTICLES,
    NATIVE_COHORT_MASS_KG,
    XML_COHORT_MASS_KG,
    SAVE_HALF_WIDTH_BUDGET_S,
)
from f2_rv4eq_fine_dense_full4001_event_validation_v2 import (
    audit_static_provenance,
    audit_saved_telemetry,
    audit_mass_precision_authority,
    audit_repeat_count_vs_cohort_mass,
    audit_trajectory_payload,
    run_dense_full4001_event_validation_v2,
    MANDATORY_PAYLOAD_13_DATASETS,
    PHYSICAL_HASH,
)

HANDOFF_DIR = F2_ROOT / "handoff_20261003/dense_full4001_native_pipeline_v2"
CONFIGS_DIR = HANDOFF_DIR / "configs"
REQUESTS_DIR = HANDOFF_DIR / "requests"
MANIFEST_PATH = HANDOFF_DIR / "manifest/dense_full4001_native_pipeline_manifest_v2.json"
OWNER_META_PATH = HANDOFF_DIR / "owner_metadata/F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001.owner.v2.json"
SIDECAR_PATH = HANDOFF_DIR / "sidecars/f2_rv4eq_fine_dense_full4001_sidecar_v2.json"
ERRATA_PATH = F2_ROOT / "handoff_20261003/dense_full4001_event_validation_v1/ERRATA_V1.md"


def test_pipeline_manifest_and_config_provenance_v2():
    assert MANIFEST_PATH.is_file(), f"Manifest missing: {MANIFEST_PATH}"
    assert OWNER_META_PATH.is_file(), f"Owner metadata missing: {OWNER_META_PATH}"
    assert SIDECAR_PATH.is_file(), f"Sidecar missing: {SIDECAR_PATH}"
    assert ERRATA_PATH.is_file(), f"Errata missing: {ERRATA_PATH}"

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001"
    assert manifest["frames"] == 4001
    assert manifest["dt_save_s"] == 0.001

    owner = json.loads(OWNER_META_PATH.read_text(encoding="utf-8"))
    assert owner["physical_condition_hash"] == PHYSICAL_HASH
    assert owner["effective_execution"]["cli_effective_time_out_s"] == 0.001
    assert owner["effective_execution"]["xml_nominal_time_out_s"] == 0.01

    sidecar = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))
    assert sidecar["errata_reference"]["unadopted_v1_commit"].startswith("5b1d0f78")
    assert sidecar["mandatory_payload_13_datasets"] == list(MANDATORY_PAYLOAD_13_DATASETS)


def test_saved_telemetry_compliance_with_actual_saving_report_021():
    config_path = CONFIGS_DIR / "f2_rv4eq_fine_dense_full4001_event_validation_config_v2.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    telem = audit_saved_telemetry(config)
    assert telem["compliance_status"] == "pass_satisfied"
    assert telem["within_registered_native_saving_allocation"] is True
    assert telem["actual_native_maximum_halfwidth_s"] == 0.0005126755832800534
    assert telem["actual_native_maximum_halfwidth_s"] <= SAVE_HALF_WIDTH_BUDGET_S
    assert telem["total_DT_min_adjustments"] == 0
    assert telem["native_NpOut_interval_sum"] == 2151
    assert telem["steps_after_initial_row"] == 201238
    assert telem["margin_fraction"] > 0.30  # ~30.1% margin


def test_mass_precision_dual_authority_provenance():
    config_path = CONFIGS_DIR / "f2_rv4eq_fine_dense_full4001_event_validation_config_v2.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    audit = audit_mass_precision_authority(config)
    native_auth = audit["native_float32_authority"]
    xml_bench = audit["historical_xml_decimal_benchmark"]

    assert math.isclose(native_auth["massfluid_particle_kg"], NATIVE_FLOAT32_PARTICLE_KG, rel_tol=1e-12)
    assert math.isclose(native_auth["cohort_total_mass_kg"], NATIVE_COHORT_MASS_KG, rel_tol=1e-12)
    assert math.isclose(xml_bench["cohort_total_mass_kg"], XML_COHORT_MASS_KG, rel_tol=1e-12)
    assert math.isclose(native_auth["delta_to_continuous_kg"], 1.1672973627696592e-06, rel_tol=1e-6)
    assert audit["policy_compliance"]["no_rescaling_native_h5"] is True


def test_refusal_to_fabricate_when_actual_source_missing():
    # Calling audit_repeat_count_vs_cohort_mass with missing observations and allow_missing=False MUST fail!
    with pytest.raises(SourceUnavailableError, match="Actual observations file is missing"):
        audit_repeat_count_vs_cohort_mass(Path("/nonexistent/f2-v7-observations.json"), allow_missing=False)

    # In allow_missing=True mode (prospective), it reports awaiting status without inventing numbers
    res = audit_repeat_count_vs_cohort_mass(Path("/nonexistent/f2-v7-observations.json"), allow_missing=True)
    assert res["status"] == "awaiting_actual_observations"
    assert "refusing to fabricate" in res["note"]


def test_mandatory_13_datasets_contract_and_uid_range_with_synthetic_h5(tmp_path: Path):
    """Test payload contract using synthetic mock fixture only. Label: synthetic_mock_fixture_only."""
    mock_h5 = tmp_path / "synthetic_mock_trajectory.h5"
    frames = 5
    total_particles = 100
    fluid_particles = 40

    times = np.linspace(0.0, 0.004, frames, dtype=np.float64)
    ids = np.arange(1470641, 1470641 + total_particles, dtype=np.uint32)
    zones = np.zeros(total_particles, dtype=np.int16)
    itypes = np.full(total_particles, 2, dtype=np.int8)
    itypes[:fluid_particles] = 3  # fluid cohort
    imks = np.full(total_particles, 1, dtype=np.int16)
    imass = np.full(total_particles, NATIVE_FLOAT32_PARTICLE_KG, dtype=np.float32)

    with h5py.File(mock_h5, "w") as f:
        f.create_dataset("time", data=times)
        f.create_dataset("particle_id", data=ids)
        f.create_dataset("particle_zone", data=zones)
        f.create_dataset("initial_type", data=itypes)
        f.create_dataset("initial_mk", data=imks)
        f.create_dataset("initial_mass", data=imass)
        f.create_dataset("mass", data=imass)
        f.create_dataset("type", data=np.repeat(itypes[None, :], frames, axis=0))
        f.create_dataset("mk", data=np.repeat(imks[None, :], frames, axis=0))
        f.create_dataset("valid", data=np.ones((frames, total_particles), dtype=bool))
        f.create_dataset("position", data=np.zeros((frames, total_particles, 3), dtype=np.float32))
        f.create_dataset("velocity", data=np.zeros((frames, total_particles, 3), dtype=np.float32))
        f.create_dataset("density", data=np.full((frames, total_particles), 1000.0, dtype=np.float32))

    audit = audit_trajectory_payload(
        mock_h5,
        expected_particles=total_particles,
        expected_fluid_particles=fluid_particles,
        dt_target=0.001,
    )
    assert audit["mandatory_13_datasets_present"] is True
    assert len(audit["missing_mandatory_datasets"]) == 0
    assert audit["uid_metrics"]["fluid_particles"] == fluid_particles
    assert audit["uid_metrics"]["min_fluid_id"] == 1470641
    assert math.isclose(audit["mass_metrics"]["fluid_particle_initial_mass_kg"], NATIVE_FLOAT32_PARTICLE_KG, rel_tol=1e-12)


def test_synthetic_end_to_end_v7_event_semantics_observation(tmp_path: Path):
    """Synthetic end-to-end execution of fresh v7 operator. Label: synthetic_mock_fixture_only."""
    mock_h5 = tmp_path / "synthetic_pose_trajectory.h5"
    frames = 5
    n_fluid = 20

    times = np.linspace(0.0, 0.004, frames, dtype=np.float64)
    ids = np.arange(1470641, 1470641 + n_fluid, dtype=np.uint32)
    zones = np.zeros(n_fluid, dtype=np.int16)
    itypes = np.full(n_fluid, 3, dtype=np.int8)
    imks = np.full(n_fluid, 1, dtype=np.int16)
    imass = np.full(n_fluid, NATIVE_FLOAT32_PARTICLE_KG, dtype=np.float32)

    # Synthetic positions: initial in cup [0.2, 0.0, 0.8]
    pos = np.zeros((frames, n_fluid, 3), dtype=np.float32)
    pos[:, :, 0] = 0.2
    pos[:, :, 1] = 0.0
    pos[:, :, 2] = 0.8

    # Rigid body state
    rigid_dtype = np.dtype([
        ("actual_angle_rad", "<f8"),
        ("angular_velocity_rad_s", "<f8"),
    ])
    rigid_arr = np.zeros(frames, dtype=rigid_dtype)

    with h5py.File(mock_h5, "w") as f:
        f.create_dataset("time", data=times)
        f.create_dataset("particle_id", data=ids)
        f.create_dataset("particle_zone", data=zones)
        f.create_dataset("initial_type", data=itypes)
        f.create_dataset("initial_mk", data=imks)
        f.create_dataset("initial_mass", data=imass)
        f.create_dataset("mass", data=imass)
        f.create_dataset("type", data=np.repeat(itypes[None, :], frames, axis=0))
        f.create_dataset("mk", data=np.repeat(imks[None, :], frames, axis=0))
        f.create_dataset("valid", data=np.ones((frames, n_fluid), dtype=bool))
        f.create_dataset("position", data=pos)
        f.create_dataset("velocity", data=np.zeros((frames, n_fluid, 3), dtype=np.float32))
        f.create_dataset("density", data=np.full((frames, n_fluid), 1000.0, dtype=np.float32))
        f.create_dataset("rigid_body_state", data=rigid_arr)

    output_labels = tmp_path / "synthetic_f2-v7-labels.h5"
    output_report = tmp_path / "synthetic_f2-v7-observations.json"

    report = observe(
        trajectory=mock_h5,
        owner_metadata=OWNER_META_PATH,
        output=output_labels,
        report=output_report,
    )

    assert output_labels.is_file()
    assert output_report.is_file()

    # All particles were statically inside cup -> final destination inventory must classify 100% in cup
    inv = report["final_mutually_exclusive_inventory"]
    assert inv["particle_counts_by_destination"]["cup"] == n_fluid
    assert inv["inventory_intact"] is True
    expected_cohort_kg = n_fluid * NATIVE_FLOAT32_PARTICLE_KG
    assert math.isclose(inv["sum_final_native_mass_kg"], expected_cohort_kg, rel_tol=1e-12)


def test_runner_requests_pass_strict_dispatcher_validation():
    for req_name in (
        "offset_fine_dense_pose_request_v2.json",
        "offset_fine_dense_labels_request_v2.json",
        "f2_rv4eq_fine_dense_full4001_event_validation_request_v2.json",
    ):
        req_path = REQUESTS_DIR / req_name
        assert req_path.is_file(), f"Request missing: {req_path}"
        req_data = json.loads(req_path.read_text(encoding="utf-8"))
        verified = validate_request(req_data)
        assert len(verified) >= 10, f"Expected verified input files for {req_name}"
        assert req_data["kind"] == "cpu"
        assert req_data["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001"
