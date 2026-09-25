from __future__ import annotations

import hashlib
import os
import struct

import pytest

from scripts import f8_r008_native_state_finite_inventory_v1 as inventory
from scripts import f8_r008_definition_control_pack_v1 as control_pack
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from scripts import f8_t1_scope_design_v1 as scope
from tests import test_f8_r008_native_state_finite_scan_v1 as state_fixture


def _scan_tmp(tmp_path, payload: bytes):
    path = tmp_path / "synthetic-inventory.bi4"
    path.write_bytes(payload)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    digest = hashlib.sha256(payload).hexdigest()
    return fd, decoder.scan_bi4_fd(fd, digest), digest


def _control_table(*, nonfinite_column: int | None = None, bad_time_tick: int | None = None) -> bytes:
    lines = [";".join(inventory.CONTROL_HEADER)]
    for tick in range(inventory.MAX_CONTROL_ROWS):
        fields = [format(float(tick), ".17g"), "0", "0", "0", "0", "0", "0"]
        if tick == 11 and nonfinite_column is not None:
            fields[nonfinite_column] = "NaN"
        if tick == bad_time_tick:
            fields[0] = format(float(tick) + 0.125, ".17g")
        lines.append(";".join(fields))
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_native_inventory_scans_primary_state_and_float_metadata(tmp_path) -> None:
    payload = state_fixture._synthetic_bi4()
    fd, scan, digest = _scan_tmp(tmp_path, payload)
    try:
        result = inventory.summarize_native_frame_fd(fd, digest, case_np=2)
    finally:
        os.close(fd)

    assert result["status"] == "diagnostic_only_not_adjudicated"
    assert [row["array_name"] for row in result["array_inventory"]["state_arrays"]] == [
        "Posd", "Vel", "Rhop",
    ]
    assert result["array_inventory"]["identifier_array"]["dtype"] == "<u4"
    assert result["array_inventory"]["all_required_state_values_finite"] is True
    assert result["floating_metadata"]["all_floating_metadata_finite"] is True
    assert result["floating_metadata"]["all_floating_metadata_semantics_classified"] is True
    assert result["floating_metadata"]["finite_count"] == 2  # root MassFluid + PART TimeStep
    assert all(item["unit"] and item["semantic"] and item["source_frame_sha256"] == digest
               for item in result["array_inventory"]["state_arrays"])
    assert result["native_integrity_evaluated"] is False
    assert result["qualification_credit"] == 0


def test_native_inventory_counts_nonfinite_float_metadata(tmp_path) -> None:
    payload = state_fixture._synthetic_bi4()
    finite_mass = struct.pack("<d", 0.000421875)
    assert payload.count(finite_mass) == 1
    payload = payload.replace(finite_mass, struct.pack("<d", float("nan")), 1)
    fd, scan, digest = _scan_tmp(tmp_path, payload)
    try:
        result = inventory.summarize_native_frame_fd(fd, digest, case_np=2)
    finally:
        os.close(fd)

    assert result["floating_metadata"]["finite_count"] == 1
    assert result["floating_metadata"]["nonfinite_count"] == 1
    assert result["floating_metadata"]["all_floating_metadata_finite"] is False
    assert result["native_integrity_evaluated"] is False


def test_native_inventory_rejects_unclassified_frame_array_from_held_bytes(tmp_path) -> None:
    payload = state_fixture._synthetic_bi4(extra_array_name="UnclassifiedExtension")
    fd, _scan, digest = _scan_tmp(tmp_path, payload)
    try:
        with pytest.raises(inventory.NativeStateFiniteInventoryError, match="unclassified extension array"):
            inventory.summarize_native_frame_fd(fd, digest, case_np=2)
    finally:
        os.close(fd)


def test_control_inventory_covers_max_frozen_horizon_and_all_columns() -> None:
    result = inventory.summarize_control_table_bytes(
        _control_table(),
        expected_t_end_s=float(inventory.MAX_CONTROL_ROWS - 1),
        expected_period_s=64.0,
    )
    assert result["rows"] == inventory.MAX_CONTROL_ROWS == 1497
    assert result["numeric_value_count"] == inventory.MAX_CONTROL_ROWS * 7
    assert result["nonfinite_value_count"] == 0
    assert result["all_seven_control_columns_finite"] is True
    assert result["time_axis_covers_zero_to_t_end_on_t_over_64_grid"] is True
    assert result["frozen_control_binding_verified"] is False
    assert result["solver_control_consumption_verified"] is False
    assert result["qualification_credit"] == 0


def test_control_row_cap_covers_every_frozen_r008_qualification_case() -> None:
    rows = scope.qualification_matrix()
    assert len(rows) == 15
    observed_rows = []
    for row in rows:
        control_dt = row["period_s"] / inventory.CONTROL_SAMPLES_PER_PERIOD
        end_tick = round(row["observation_end_s"] / control_dt)
        observed_rows.append(end_tick + 1)
        assert end_tick + 1 <= inventory.MAX_CONTROL_ROWS
        assert abs(end_tick * control_dt - row["observation_end_s"]) <= 1e-12
    assert max(observed_rows) == inventory.MAX_CONTROL_ROWS


def test_frozen_control_generator_outputs_all_pass_finite_and_horizon_checks() -> None:
    rows = scope.qualification_matrix()
    summaries = []
    for row in rows:
        payload = control_pack.render_control(row)
        summary = inventory.summarize_control_table_bytes(
            payload,
            expected_t_end_s=row["observation_end_s"],
            expected_period_s=row["period_s"],
        )
        summaries.append(summary)
        assert summary["all_seven_control_columns_finite"] is True
        assert summary["time_axis_covers_zero_to_t_end_on_t_over_64_grid"] is True
        expected_tick = round(
            row["observation_end_s"]
            / (row["period_s"] / inventory.CONTROL_SAMPLES_PER_PERIOD)
        )
        assert summary["rows"] == expected_tick + 1
    assert len(summaries) == 15
    assert max(summary["rows"] for summary in summaries) == inventory.MAX_CONTROL_ROWS


@pytest.mark.parametrize("column", range(7))
def test_control_inventory_detects_nonfinite_in_each_column(column: int) -> None:
    result = inventory.summarize_control_table_bytes(
        _control_table(nonfinite_column=column),
        expected_t_end_s=float(inventory.MAX_CONTROL_ROWS - 1),
        expected_period_s=64.0,
    )
    assert result["all_seven_control_columns_finite"] is False
    assert result["columns"][column]["nonfinite_count"] == 1
    assert all(
        result["columns"][index]["nonfinite_count"] == (1 if index == column else 0)
        for index in range(7)
    )
    assert result["native_integrity_evaluated"] is False


def test_nonfinite_time_disables_coverage_without_hiding_control_counts() -> None:
    payload = _control_table(nonfinite_column=0)
    result = inventory.summarize_control_table_bytes(
        payload,
        expected_t_end_s=float(inventory.MAX_CONTROL_ROWS - 1),
        expected_period_s=64.0,
    )
    assert result["columns"][0]["nonfinite_count"] == 1
    assert result["time_axis_covers_zero_to_t_end_on_t_over_64_grid"] is False


def test_misaligned_time_axis_is_not_reported_as_covered() -> None:
    result = inventory.summarize_control_table_bytes(
        _control_table(bad_time_tick=11),
        expected_t_end_s=float(inventory.MAX_CONTROL_ROWS - 1),
        expected_period_s=64.0,
    )
    assert result["all_seven_control_columns_finite"] is True
    assert result["time_axis_covers_zero_to_t_end_on_t_over_64_grid"] is False


@pytest.mark.parametrize(
    "payload",
    [
        b"Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ\n",
        b"#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ\n0;0;0\n",
    ],
)
def test_control_inventory_rejects_wrong_header_and_truncated_table(payload: bytes) -> None:
    with pytest.raises(inventory.NativeStateFiniteInventoryError):
        inventory.summarize_control_table_bytes(
            payload, expected_t_end_s=float(inventory.MAX_CONTROL_ROWS - 1), expected_period_s=64.0,
        )


def test_control_inventory_rejects_horizon_off_grid_or_above_r008_bound() -> None:
    payload = _control_table()
    with pytest.raises(inventory.NativeStateFiniteInventoryError, match="T/64 grid bound"):
        inventory.summarize_control_table_bytes(
            payload, expected_t_end_s=319.5, expected_period_s=64.0,
        )
    with pytest.raises(inventory.NativeStateFiniteInventoryError, match="T/64 grid bound"):
        inventory.summarize_control_table_bytes(
            payload, expected_t_end_s=float(inventory.MAX_CONTROL_ROWS), expected_period_s=64.0,
        )


def test_control_inventory_rejects_t64_timestep_underflow() -> None:
    with pytest.raises(inventory.NativeStateFiniteInventoryError, match="underflows"):
        inventory.summarize_control_table_bytes(
            b"#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ\n",
            expected_t_end_s=1e-323,
            expected_period_s=1e-323,
        )
