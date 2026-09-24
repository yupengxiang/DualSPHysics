from __future__ import annotations

import hashlib
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import f8_r008_native_fluid_gate_reducer_v1 as reducer
from tests import test_f8_r008_t1_metric_adapter_v2 as metric_fixtures


CASE_ID = metric_fixtures.CASE_ID


def _table(tmp_path: Path, mutation=None, *, writable: bool = False):
    path = tmp_path / "synthetic-native-fluid-table.h5"
    fd, verification, _byte_count, _digest = metric_fixtures._metric_fixture(path)
    os.close(fd)
    with h5py.File(path, "r+") as handle:
        handle["velocity"][:] = np.zeros(handle["velocity"].shape, dtype="<f4")
        if mutation is not None:
            mutation(handle)
    payload = path.read_bytes()
    byte_count = len(payload)
    digest = hashlib.sha256(payload).hexdigest()
    verification["table_bytes"] = byte_count
    verification["table_sha256"] = digest
    flags = os.O_RDWR if writable else os.O_RDONLY
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))
    return path, fd, verification, byte_count, digest


def _window_ordinals() -> tuple[int, int]:
    scope, _pack = reducer.registry._read_frozen_inputs()
    row = next(row for row in scope["matrix"]["rows"] if row["case_id"] == CASE_ID)
    return int(row["observation_start_output_index"]), int(row["observation_end_output_index"])


def test_reduces_only_the_inclusive_fluid_window_and_keeps_other_gates_open(tmp_path) -> None:
    _path, fd, verification, byte_count, digest = _table(tmp_path)
    try:
        result = reducer.evaluate_native_fluid_window_gates_fd(
            fd, table_verification=verification,
            expected_table_bytes=byte_count, expected_table_sha256=digest,
        )
    finally:
        os.close(fd)

    assert result["schema"] == reducer.SCHEMA
    assert result["status"] == "partial_native_fluid_gate_subset_evaluated"
    assert result["case_id"] == CASE_ID
    assert result["observation_window"]["sample_count"] == 193
    assert result["observation_window"]["expected_sample_count"] == 193
    assert result["observation_window"]["start_ordinal"] == 128
    assert result["observation_window"]["end_ordinal"] == 320
    assert result["observed"]["density_min_kg_m3"] == 1000.0
    assert result["observed"]["density_max_kg_m3"] == 1000.0
    assert result["observed"]["density_outside_count"] == 0
    assert result["observed"]["mach_max"] <= 0.0010125
    assert result["observed"]["mach_exceedance_count"] == 0
    assert result["gate_results"]["density_range"]["status"] == "defined_pass"
    assert result["gate_results"]["mach_limit"]["status"] == "defined_pass"
    assert result["gate_results"]["inclusive_three_period_window_complete"]["status"] == "defined_pass"
    assert all(item["evidence_sha256"] == digest for item in result["gate_results"].values())
    assert result["unevaluated_gate_ids"] == list(reducer.UNEVALUATED_GATE_IDS)
    assert result["caller_must_revalidate_B_C_D_chain"] is True
    assert result["B_C_D_chain_validation_performed_by_reducer"] is False
    assert result["evidence_bindings_verified"] is False
    assert result["native_integrity_evaluated"] is False
    assert result["T1_numerical"] is False
    assert result["readiness_pass"] is False
    assert result["qualification_credit"] == 0


def test_density_interval_is_closed_at_both_frozen_endpoints(tmp_path) -> None:
    start, end = _window_ordinals()

    def set_boundaries(handle):
        handle["density"][start, 0] = np.float32(950.0)
        handle["density"][end, 1] = np.float32(1050.0)

    _path, fd, verification, byte_count, digest = _table(tmp_path, set_boundaries)
    try:
        result = reducer.evaluate_native_fluid_window_gates_fd(
            fd, table_verification=verification,
            expected_table_bytes=byte_count, expected_table_sha256=digest,
        )
    finally:
        os.close(fd)

    assert result["gate_results"]["density_range"]["status"] == "defined_pass"
    assert result["observed"]["density_min_kg_m3"] == 950.0
    assert result["observed"]["density_max_kg_m3"] == 1050.0


def test_density_outside_closed_interval_is_a_defined_failure(tmp_path) -> None:
    start, _end = _window_ordinals()

    def exceed_upper(handle):
        handle["density"][start, 0] = np.float32(1050.25)

    _path, fd, verification, byte_count, digest = _table(tmp_path, exceed_upper)
    try:
        result = reducer.evaluate_native_fluid_window_gates_fd(
            fd, table_verification=verification,
            expected_table_bytes=byte_count, expected_table_sha256=digest,
        )
    finally:
        os.close(fd)

    assert result["gate_results"]["density_range"]["status"] == "defined_fail"
    assert result["observed"]["density_outside_count"] == 1


def test_mach_limit_uses_maximum_fluid_speed_over_frozen_sound_speed(tmp_path) -> None:
    start, _end = _window_ordinals()

    def exceed_mach(handle):
        handle["velocity"][start, 0, :] = np.asarray([0.010126, 0.0, 0.0], dtype="<f4")

    _path, fd, verification, byte_count, digest = _table(tmp_path, exceed_mach)
    try:
        result = reducer.evaluate_native_fluid_window_gates_fd(
            fd, table_verification=verification,
            expected_table_bytes=byte_count, expected_table_sha256=digest,
        )
    finally:
        os.close(fd)

    assert result["gate_results"]["mach_limit"]["status"] == "defined_fail"
    assert result["observed"]["mach_exceedance_count"] == 1
    assert result["observed"]["mach_max"] > 0.0010125


@pytest.mark.parametrize(
    ("direction", "expected_status", "comparison"),
    [("below", "defined_pass", "below"), ("above", "defined_fail", "above")],
)
def test_mach_threshold_uses_adjacent_float32_values_without_tolerance(
    tmp_path, direction: str, expected_status: str, comparison: str,
) -> None:
    start, _end = _window_ordinals()
    target = np.float32(0.010125)
    adjacent = np.nextafter(
        target,
        np.float32(-np.inf if direction == "below" else np.inf),
    )

    def set_adjacent_velocity(handle):
        handle["velocity"][start, 0, :] = np.asarray([adjacent, 0.0, 0.0], dtype="<f4")

    _path, fd, verification, byte_count, digest = _table(tmp_path, set_adjacent_velocity)
    try:
        result = reducer.evaluate_native_fluid_window_gates_fd(
            fd, table_verification=verification,
            expected_table_bytes=byte_count, expected_table_sha256=digest,
        )
    finally:
        os.close(fd)

    assert result["gate_results"]["mach_limit"]["status"] == expected_status
    if comparison == "below":
        assert result["observed"]["mach_max"] < 0.0010125
    else:
        assert result["observed"]["mach_max"] > 0.0010125


def test_rejects_nonfinite_values_even_if_caller_claims_table_passed(tmp_path) -> None:
    start, _end = _window_ordinals()

    def set_nan(handle):
        handle["density"][start, 0] = np.float32(np.nan)

    _path, fd, verification, byte_count, digest = _table(tmp_path, set_nan)
    try:
        with pytest.raises(reducer.NativeFluidGateReducerError, match="non-finite"):
            reducer.evaluate_native_fluid_window_gates_fd(
                fd, table_verification=verification,
                expected_table_bytes=byte_count, expected_table_sha256=digest,
            )
    finally:
        os.close(fd)


def test_rejects_a_writable_table_descriptor(tmp_path) -> None:
    _path, writable_fd, verification, byte_count, digest = _table(tmp_path, writable=True)
    try:
        with pytest.raises(reducer.NativeFluidGateReducerError, match="read-only"):
            reducer.evaluate_native_fluid_window_gates_fd(
                writable_fd, table_verification=verification,
                expected_table_bytes=byte_count, expected_table_sha256=digest,
            )
    finally:
        os.close(writable_fd)


def test_rejects_table_mutation_during_gate_reduction(tmp_path, monkeypatch) -> None:
    path, fd, verification, byte_count, digest = _table(tmp_path)
    original = reducer._reduce_window

    def mutate_after_read(*args, **kwargs):
        result = original(*args, **kwargs)
        writer = os.open(path, os.O_WRONLY)
        try:
            os.pwrite(writer, b"X", 128)
        finally:
            os.close(writer)
        return result

    monkeypatch.setattr(reducer, "_reduce_window", mutate_after_read)
    try:
        with pytest.raises(reducer.NativeFluidGateReducerError, match="changed during"):
            reducer.evaluate_native_fluid_window_gates_fd(
                fd, table_verification=verification,
                expected_table_bytes=byte_count, expected_table_sha256=digest,
            )
    finally:
        os.close(fd)


def test_rejects_table_bytes_that_do_not_match_verification(tmp_path) -> None:
    _path, fd, verification, byte_count, digest = _table(tmp_path)
    try:
        with pytest.raises(reducer.NativeFluidGateReducerError, match="verification"):
            reducer.evaluate_native_fluid_window_gates_fd(
                fd, table_verification=verification,
                expected_table_bytes=byte_count, expected_table_sha256="f" * 64,
            )
    finally:
        os.close(fd)


def test_rejects_native_time_axis_drift(tmp_path) -> None:
    def perturb_time(handle):
        handle["time"][130] = handle["time"][130] + 1e-5

    _path, fd, verification, byte_count, digest = _table(tmp_path, perturb_time)
    try:
        with pytest.raises(reducer.NativeFluidGateReducerError, match="frozen full axis"):
            reducer.evaluate_native_fluid_window_gates_fd(
                fd, table_verification=verification,
                expected_table_bytes=byte_count, expected_table_sha256=digest,
            )
    finally:
        os.close(fd)


def test_rejects_unverified_table_semantics_and_unknown_case(tmp_path) -> None:
    _path, fd, verification, byte_count, digest = _table(tmp_path)
    try:
        invalid = dict(verification)
        invalid["all_valid"] = False
        with pytest.raises(reducer.NativeFluidGateReducerError, match="zero-credit"):
            reducer.evaluate_native_fluid_window_gates_fd(
                fd, table_verification=invalid,
                expected_table_bytes=byte_count, expected_table_sha256=digest,
            )
        invalid = dict(verification)
        invalid["case_id"] = "production-case"
        with pytest.raises(reducer.NativeFluidGateReducerError, match="frozen 15-case"):
            reducer.evaluate_native_fluid_window_gates_fd(
                fd, table_verification=invalid,
                expected_table_bytes=byte_count, expected_table_sha256=digest,
            )
    finally:
        os.close(fd)
