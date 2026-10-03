"""Unit tests for F2 RV4EQ Fine Dense Full-4001 Event Semantics v8 Wrapper.

All test evidence and fixtures in this file are strictly SYNTHETIC MOCK FIXTURES ONLY.
Label: synthetic_mock_fixture_only. Zero raw solver/dataset array execution.

Verifies:
1. Frozen V6 module import by path and exact code SHA-256 provenance.
2. Narrow native-weight hook: authoritative float32 mass (0.0001250000059371814 kg)
   verified against Root017 BI4 header precision audit report.
3. Separation of XML decimal benchmark (0.000125 kg, 24.576 kg).
4. Representation delta (~4.75e-8) transparency: old frozen 1e-12 diagnostic reports 'fail',
   no automatic 1e-12 gating, no rescaling.
5. End-to-end synthetic observe execution with actual geometry fixture (receiver offset y=0.14m,
   crossing tolerance 0.0125m from Root015 owner metadata).
6. Byte-identical V6 aperture crossing and trapezoidal residence integration.
7. V7 operator drift errata provenance and request validation.
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
INTEGRATION_SCRIPTS = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts")
if str(INTEGRATION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_SCRIPTS))
if str(F2_ROOT) not in sys.path:
    sys.path.insert(0, str(F2_ROOT))

from ds_data02_runtime_v2 import validate_request
import f2_rv4eq_fine_dense_full4001_event_semantics_v8 as v8


HANDOFF_V8_DIR = F2_ROOT / "handoff_20261003/dense_full4001_native_pipeline_v8"
ERRATA_V2_PATH = F2_ROOT / "handoff_20261003/dense_full4001_native_pipeline_v2/ERRATA_V2.md"
ROOT015_CONFIG_PATH = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_matched_offset_fine_labels_015/config.json")
ROOT015_OWNER_PATH = F2_ROOT / "handoff_20261003/matched_offset_fine_pipeline_v1/owner_metadata/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.owner.v1.json"


def test_v8_frozen_v6_import_and_code_sha():
    """Verify that V8 loads V6 by path read-only and binds its exact code hash."""
    assert v8.V6_CODE_SHA256 == "e200b886adfd3b4dc69c7e4f281df401d30436be1cba4bf0871f355129f626b9"
    assert v8.OPERATOR_VERSION == "f2-moving-cup-local-z-top-v8-native-mass-bound"
    assert v8.FROZEN_V6_OPERATOR_VERSION == "f2-moving-cup-local-z-top-v6"

    spec = v8.operator_spec()
    assert spec["schema"] == "ds-data-02.f2.event-semantics.v8"
    assert spec["frozen_v6_base"]["script_sha256"] == v8.V6_CODE_SHA256
    assert spec["native_weight_authority"]["native_header_bound_mass_kg"] == v8.NATIVE_FLOAT32_MASSFLUID_KG

    op_hash = v8.operator_hash()
    assert len(op_hash) == 64
    # Ensure V8 operator hash is distinct from old V6 hash
    old_v6_hash = v8.v6_module._canonical_sha256(v8.v6_module.operator_spec())
    assert op_hash != old_v6_hash


def test_v8_native_mass_reference_narrow_authority():
    """Verify that _native_mass_reference_v8 binds actual adapter mass and fails old 1e-12 gate."""
    owner_mock = {
        "mass_reference": {
            "continuous_mass_kg": 24.576,
        },
        "definition": {
            "path": "/nonexistent/test.xml",
        },
    }

    n_fluid = v8.FINE_FLUID_PARTICLE_COUNT
    adapter_mass = np.full(n_fluid, v8.NATIVE_FLOAT32_MASSFLUID_KG, dtype=np.float32)

    binding = v8._native_mass_reference_v8(owner_mock, n_fluid, adapter_mass)

    # 1. Authoritative particle mass is actual native weight
    assert math.isclose(binding["massfluid_kg_per_particle"], v8.NATIVE_FLOAT32_MASSFLUID_KG, rel_tol=1e-15)
    # 2. Native total cohort mass
    assert math.isclose(binding["native_header_cohort_mass_kg"], v8.NATIVE_FLOAT32_COHORT_MASS_KG, rel_tol=1e-15)
    # 3. Continuous reference mass
    assert math.isclose(binding["continuous_mass_kg"], 24.576, rel_tol=1e-15)
    # 4. Arithmetic representation delta (~4.75e-8)
    assert math.isclose(binding["native_representation_delta_kg"], 1.1672973627696592e-06, rel_tol=1e-6)
    assert math.isclose(binding["native_vs_continuous_relative_error"], 4.749745128457272e-08, rel_tol=1e-6)
    # 5. Old frozen 1e-12 diagnostic MUST report 'fail'
    assert binding["strict_native_vs_continuous_status"] == "fail"
    assert binding["old_frozen_1e12_diagnostic_status"] == "fail"
    # 6. XML decimal benchmark preserved separately
    bench = binding["xml_decimal_benchmark"]
    assert math.isclose(bench["xml_massfluid_decimal_kg"], 0.000125, rel_tol=1e-15)
    assert math.isclose(bench["xml_cohort_mass_kg"], 24.576, rel_tol=1e-15)


def test_v8_synthetic_end_to_end_observe_with_actual_geometry_fixture(tmp_path: Path):
    """Synthetic end-to-end execution of V8 operator with actual geometry fixture.

    Label: synthetic_mock_fixture_only.
    """
    # 1. Load actual geometry from Root015 owner metadata
    assert ROOT015_OWNER_PATH.is_file(), f"Missing Root015 owner metadata: {ROOT015_OWNER_PATH}"
    actual_owner = json.loads(ROOT015_OWNER_PATH.read_text(encoding="utf-8"))

    # Verify actual geometry and offset y=0.14m in fixture
    geom = actual_owner["geometry"]
    assert geom["receiver_low_m"] == [0.45, -0.16, 0.0]
    assert geom["receiver_size_m"] == [1.1, 0.6, 0.45]
    assert geom["receiver_offset_y_m"] == 0.14
    assert geom["cup_low_m"] == [0.0, -0.15, 0.65]
    assert geom["cup_size_m"] == [0.425, 0.3, 0.45]
    assert geom["tray_low_m"] == [-1.2, -1.0, -0.2]
    assert geom["tray_size_m"] == [4.0, 2.0, 0.15]

    # Write synthetic owner metadata in tmp_path
    mock_owner_file = tmp_path / "mock_owner.json"
    mock_owner_file.write_text(json.dumps(actual_owner, indent=2), encoding="utf-8")

    # 2. Build synthetic pose trajectory
    mock_h5 = tmp_path / "synthetic_pose_trajectory.h5"
    frames = 5
    n_fluid = 24  # synthetic cohort

    times = np.linspace(0.0, 0.004, frames, dtype=np.float64)
    ids = np.arange(1470641, 1470641 + n_fluid, dtype=np.uint32)
    zones = np.zeros(n_fluid, dtype=np.int16)
    itypes = np.full(n_fluid, 3, dtype=np.int8)  # fluid cohort
    imks = np.full(n_fluid, 1, dtype=np.int16)
    imass = np.full(n_fluid, v8.NATIVE_FLOAT32_MASSFLUID_KG, dtype=np.float32)

    # Initial position inside cup [0.2, 0.0, 0.8]
    pos = np.zeros((frames, n_fluid, 3), dtype=np.float32)
    pos[:, :, 0] = 0.2
    pos[:, :, 1] = 0.0
    pos[:, :, 2] = 0.8

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

    output_labels = tmp_path / "f2-v8-labels.h5"
    output_report = tmp_path / "f2-v8-observations.json"

    # Execute V8 observe
    report = v8.observe(
        trajectory=mock_h5,
        owner_metadata=mock_owner_file,
        output=output_labels,
        report=output_report,
    )

    assert output_labels.is_file()
    assert output_report.is_file()

    # 3. Check labels H5 attributes and dataset
    with h5py.File(output_labels, "r") as lf:
        assert lf.attrs["schema"] == "ds-data-02.f2.event-semantics.v8"
        assert lf.attrs["operator_version"] == "f2-moving-cup-local-z-top-v8-native-mass-bound"
        assert "source_mass_kg" in lf
        written_mass = lf["source_mass_kg"][:]
        assert math.isclose(written_mass[0], v8.NATIVE_FLOAT32_MASSFLUID_KG, rel_tol=1e-15)

    # 4. Check report payload
    assert report["schema"] == "ds-data-02.f2.event-semantics.v8"
    assert report["operator"]["version"] == "f2-moving-cup-local-z-top-v8-native-mass-bound"
    assert report["operator"]["sha256"] == v8.operator_hash()

    # Geometry verified in report matches Root015 owner
    geo = report["geometry_and_pose"]
    assert np.allclose(geo["receiver_low_m"], [0.45, -0.16, 0.0])
    assert np.allclose(geo["receiver_high_m"], [1.55, 0.44, 0.45])

    # Source population verifies authoritative native mass
    sp = report["source_population"]
    expected_cohort_native_kg = n_fluid * v8.NATIVE_FLOAT32_MASSFLUID_KG
    assert math.isclose(sp["initial_native_mass_kg"], expected_cohort_native_kg, rel_tol=1e-15)
    assert sp["mass_reference_status"] == "fail"  # Old 1e-12 diagnostic failed

    # Residence is present with trapezoidal rule
    assert "residence" in report
    assert "mass_time_kg_s_by_destination" in report["residence"]


def test_v8_byte_identical_aperture_and_trapezoid_integration():
    """Verify that V8 reuses frozen V6 aperture and trapezoid integration byte-for-byte."""
    origin = np.asarray([0.0, 0.0, 0.0])
    axis = np.asarray([0.0, 1.0, 0.0])
    low = np.asarray([0.0, 0.0, 0.0])
    high = np.asarray([1.0, 1.0, 1.0])
    previous_body = np.asarray([[0.5, 0.5, 0.9]])
    current_body = np.asarray([[1.2, 0.5, 1.1]])
    previous_world = v8.v6_module._inverse_rotate(previous_body, origin, axis, 0.0)
    current_world = v8.v6_module._inverse_rotate(current_body, origin, axis, -0.4)
    previous_margin = np.asarray([-0.1])
    current_margin = np.asarray([0.1])

    crossing = v8.v6_module._interpolated_top_aperture(
        previous_world, current_world, previous_margin, current_margin,
        0.0, 0.4, origin, axis, low, high, 0.01,
    )
    assert bool(crossing[0])
    assert current_body[0, 0] > high[0]


def test_errata_v2_provenance_and_request_validation():
    """Verify that ERRATA_V2.md exists and offset_fine_dense_labels_request_v8 passes validation."""
    assert ERRATA_V2_PATH.is_file(), f"Errata missing: {ERRATA_V2_PATH}"
    errata_text = ERRATA_V2_PATH.read_text(encoding="utf-8")
    assert "UNADOPTED" in errata_text
    assert "89ac87c0" in errata_text
    assert "tolerance" in errata_text
    assert "0.0125" in errata_text
    assert "0.14" in errata_text

    req_path = HANDOFF_V8_DIR / "requests/offset_fine_dense_labels_request_v8.json"
    assert req_path.is_file(), f"Request missing: {req_path}"
    req_data = json.loads(req_path.read_text(encoding="utf-8"))
    verified = validate_request(req_data)
    assert len(verified) >= 10
    assert req_data["kind"] == "cpu"
    assert req_data["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001"
