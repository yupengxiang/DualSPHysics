from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_t1_metric_adapter_v1 as metric_v1
from scripts import f8_r008_t1_metric_adapter_v2 as adapter
from scripts.f8_womersley_oracle import ChannelParameters, steady_velocity


CASE_ID = "space-q0-dp0p0090"
HDF5_BOOLEAN = h5py.enum_dtype({"FALSE": 0, "TRUE": 1}, basetype=np.dtype("u1"))


def _metric_fixture(path: Path) -> tuple[int, dict, int, str]:
    adapter._frozen_inputs(CASE_ID)
    scope = json.loads(metric_v1.FROZEN_SCOPE_RECEIPT.read_text(encoding="utf-8"))
    case = next(row for row in scope["matrix"]["rows"] if row["case_id"] == CASE_ID)
    parameters = json.loads(metric_v1.FROZEN_PARAMETER_CONTRACT.read_text(encoding="utf-8"))
    h = float(parameters["geometry_and_fluid"]["half_height_m"])
    dp = float(case["dp_m"])
    plane_count = round(2.0 * h / dp) + 1
    plane_z = -h + np.arange(plane_count, dtype=np.float64) * dp
    particle_ids = np.arange(plane_count, dtype="<u4")
    samples_per_period = int(case["native_output_samples_per_period"])
    row_count = int(round(float(case["observation_end_s"]) / float(case["period_s"])
                          * samples_per_period)) + 1
    period = float(case["period_s"])
    times = np.arange(row_count, dtype=np.float64) * (period / samples_per_period)
    forcing = parameters["parameterization"]
    oracle_parameters = ChannelParameters(
        h, float(parameters["geometry_and_fluid"]["kinematic_viscosity_m2_s"]),
        float(case["omega_rad_s"]), float(forcing["acceleration_amplitude_m_s2"]),
    )
    velocity = np.zeros((row_count, plane_count, 3), dtype="<f4")
    velocity[:, 1:-1, 0] = steady_velocity(times, plane_z[1:-1], oracle_parameters).astype("<f4")
    velocity[:, :, 1] = (1e-5 * np.sin(float(case["omega_rad_s"]) * times))[:, None]
    velocity[:, :, 2] = (2e-5 * np.cos(float(case["omega_rad_s"]) * times))[:, None]
    position = np.zeros((row_count, plane_count, 3), dtype="<f8")
    position[:, :, 2] = plane_z[None, :]
    mass = np.full((row_count, plane_count), 1e-4, dtype="<f4")
    density = np.full((row_count, plane_count), 1000.0, dtype="<f4")
    valid = np.ones((row_count, plane_count), dtype="u1")
    attrs = table_v2.expected_root_attributes(
        case_id=CASE_ID,
        generated_xml_sha256="1" * 64,
        definition_sha256="2" * 64,
        materialization_receipt_sha256="3" * 64,
        raw_solver_manifest_sha256="4" * 64,
        scope_receipt_sha256=metric_v1.FROZEN_INPUT_SHA256["scope"],
        parameter_contract_sha256=metric_v1.FROZEN_INPUT_SHA256["parameter_contract"],
    )
    with h5py.File(path, "w") as handle:
        for name, value in attrs.items():
            if name == "schema_version":
                handle.attrs.create(name, np.asarray(value, dtype="<u4"), dtype="<u4")
            elif name == "conversion_complete":
                handle.attrs.create(name, np.asarray(value, dtype="u1"), dtype=HDF5_BOOLEAN)
            else:
                handle.attrs.create(name, value, dtype=h5py.string_dtype("utf-8", len(value.encode("utf-8"))))
        handle.create_dataset("time", data=times, dtype="<f8")
        handle.create_dataset("particle_id", data=particle_ids, dtype="<u4")
        handle.create_dataset("position", data=position, dtype="<f8")
        handle.create_dataset("velocity", data=velocity, dtype="<f4")
        handle.create_dataset("density", data=density, dtype="<f4")
        handle.create_dataset("mass", data=mass, dtype="<f4")
        handle.create_dataset("valid", data=valid, dtype=HDF5_BOOLEAN)
    payload = path.read_bytes()
    verification = {
        "schema": table_v2.SCHEMA,
        "table_schema": table_v2.TABLE_SCHEMA,
        "case_id": CASE_ID,
        "table_bytes": len(payload),
        "table_sha256": hashlib.sha256(payload).hexdigest(),
        "time_rows": row_count,
        "fluid_particle_count": plane_count,
        "raw_frames_recomputed": row_count,
        "full_time_axis_matches": True,
        "fluid_id_projection_matches": True,
        "position_velocity_density_mass_recomputed": True,
        "all_valid": True,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    return fd, verification, len(payload), hashlib.sha256(payload).hexdigest()


def test_v2_adapter_computes_case_metrics_from_held_fd_without_t1_credit(tmp_path: Path) -> None:
    path = tmp_path / "native-fluid-frame-table-v2.h5"
    fd, verification, byte_count, digest = _metric_fixture(path)
    try:
        result = adapter.evaluate_case_metrics_fd(
            fd, table_verification=verification, expected_table_bytes=byte_count,
            expected_table_sha256=digest,
        )
    finally:
        os.close(fd)

    assert result["schema"] == adapter.SCHEMA
    assert result["case_id"] == CASE_ID
    assert result["status"] == "case_metric_gates_evaluated_native_integrity_pending"
    assert result["semantic_source_checks"]["density_used_as_metric_input"] is False
    assert result["semantic_source_checks"]["position_velocity_density_mass_recomputed"] is True
    assert result["metric_gates_passed"] is True
    assert result["metrics"]["transverse_velocity_rms_m_s"] > 0.0
    assert result["solver_max_dt_s"] is None
    assert result["native_integrity_gates_evaluated"] is False
    assert result["full_t1_decision"] is False
    assert result["qualification_credit"] == 0


@pytest.mark.parametrize("field", ["position_velocity_density_mass_recomputed", "all_valid"])
def test_v2_adapter_rejects_unverified_density_or_valid_semantics(tmp_path: Path, field: str) -> None:
    path = tmp_path / "native-fluid-frame-table-v2.h5"
    fd, verification, byte_count, digest = _metric_fixture(path)
    verification[field] = False
    try:
        with pytest.raises(adapter.NativeFluidMetricAdapterError, match="complete zero-credit"):
            adapter.evaluate_case_metrics_fd(
                fd, table_verification=verification, expected_table_bytes=byte_count,
                expected_table_sha256=digest,
            )
    finally:
        os.close(fd)


def test_v2_adapter_rejects_a_writable_table_fd(tmp_path: Path) -> None:
    path = tmp_path / "native-fluid-frame-table-v2.h5"
    _fd, verification, byte_count, digest = _metric_fixture(path)
    os.close(_fd)
    fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        with pytest.raises(adapter.NativeFluidMetricAdapterError, match="requires a read-only held table FD"):
            adapter.evaluate_case_metrics_fd(
                fd, table_verification=verification, expected_table_bytes=byte_count,
                expected_table_sha256=digest,
            )
    finally:
        os.close(fd)


def test_v2_adapter_rechecks_the_held_fd_after_hdf5_metric_reads(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "native-fluid-frame-table-v2.h5"
    fd, verification, byte_count, digest = _metric_fixture(path)
    compute = adapter._metric_values

    def mutate_after_compute(*args, **kwargs):
        result = compute(*args, **kwargs)
        writer = os.open(path, os.O_WRONLY)
        try:
            os.pwrite(writer, b"X", 128)
        finally:
            os.close(writer)
        return result

    monkeypatch.setattr(adapter, "_metric_values", mutate_after_compute)
    try:
        with pytest.raises(adapter.NativeFluidMetricAdapterError, match="changed while case metrics were read"):
            adapter.evaluate_case_metrics_fd(
                fd, table_verification=verification, expected_table_bytes=byte_count,
                expected_table_sha256=digest,
            )
    finally:
        os.close(fd)
