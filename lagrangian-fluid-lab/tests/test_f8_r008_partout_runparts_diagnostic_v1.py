from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct

import pytest

from scripts import f8_r008_partout_runparts_diagnostic_v1 as diagnostic
from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts
from scripts import f8_r008_safe_bi4_decoder_v1 as bi4


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _value(name: str, type_code: int, payload: bytes) -> bytes:
    return _string(name) + struct.pack("<i", type_code) + payload


def _array(name: str, type_code: int, count: int, payload: bytes) -> bytes:
    definition = (
        _string("\nARRAY") + _string(name)
        + struct.pack("<iiII", 1, type_code, count, len(payload))
    )
    return struct.pack("<I", len(definition)) + definition + payload


def _item(
    name: str,
    *,
    values: tuple[bytes, ...] = (),
    arrays: tuple[bytes, ...] = (),
) -> bytes:
    values_block = b""
    if values:
        values_block = _string("\nVALUES") + struct.pack("<I", len(values)) + b"".join(values)
    definition = (
        _string("\nITEM\n") + _string(name) + struct.pack("<ii", 0, 0)
        + _string("%.7E") + _string("%.15E")
        + struct.pack("<III", len(arrays), 0, len(values_block))
    )
    return struct.pack("<I", len(definition)) + definition + values_block + b"".join(arrays)


def _partout_record(
    part: int,
    ids: tuple[int, ...],
    motives: bytes,
    *,
    position: str = "Posd",
    id_double: bool = False,
    omit: str | None = None,
    float_values: dict[str, tuple[float, ...]] | None = None,
    time_step: float | None = None,
) -> bytes:
    count = len(ids)
    float_values = float_values or {}
    id_name = "Idpd" if id_double else "Idp"
    id_code = "Q" if id_double else "I"
    id_type = 10 if id_double else 8
    arrays = [
        _array(id_name, id_type, count, struct.pack("<" + id_code * count, *ids)),
        _array(position, 23 if position == "Posd" else 22,
               count, struct.pack("<" + ("d" if position == "Posd" else "f") * count * 3,
                                  *float_values.get(position, tuple([0.25] * count * 3)))),
        _array("Vel", 22, count, struct.pack(
            "<" + "f" * count * 3, *float_values.get("Vel", tuple([0.5] * count * 3))
        )),
        _array("Rhop", 11, count, struct.pack(
            "<" + "f" * count, *float_values.get("Rhop", tuple([1000.0] * count))
        )),
        _array("Motive", 4, count, motives),
    ]
    if omit is not None:
        arrays = [entry for entry, name in zip(arrays, (id_name, position, "Vel", "Rhop", "Motive")) if name != omit]
    values = (
        _value("Cpart", 8, struct.pack("<I", part)),
        _value("TimeStep", 12, struct.pack("<d", part / 10.0 if time_step is None else time_step)),
        _value("Nout", 8, struct.pack("<I", count)),
    )
    return _item(f"PART_{part:04d}", values=values, arrays=tuple(arrays))


def _partout_block(
    block: int,
    records: tuple[bytes, ...] = (),
    *,
    root_name: str = "JPartOutBi4",
    case_np: int = 10752,
    extra_root_values: tuple[bytes, ...] = (),
) -> bytes:
    values = (
        _value("Piece", 8, struct.pack("<I", 0)),
        _value("Npiece", 8, struct.pack("<I", 1)),
        _value("Block", 8, struct.pack("<I", block)),
        _value("CaseNp", 10, struct.pack("<Q", case_np)),
    )
    prefix = b"#FileJBD " + root_name.encode("ascii")
    header = prefix + b" " * (58 - len(prefix)) + b"\n\0\0\0\0\0"
    assert len(header) == bi4.HEADER_BYTES
    return header + _item("JPartOutBi4", values=values + extra_root_values) + b"".join(records)


def _row(
    part: int,
    *,
    counts: tuple[int, int, int] = (0, 0, 0),
    time_step_text: str | None = None,
) -> str:
    cells = ["0"] * len(runparts.RUNPARTS_HEADER)
    cells[0] = str(part)
    cells[1] = str(part / 10.0) if time_step_text is None else time_step_text
    cells[2] = "0" if part == 0 else "10"
    cells[19] = "0" if part == 0 else "0.001"
    cells[20] = "0" if part == 0 else "0.002"
    cells[runparts.RUNPARTS_HEADER.index("NpOut")] = str(sum(counts))
    for name, value in zip(("NpOutPos", "NpOutRho", "NpOutMov"), counts):
        cells[runparts.RUNPARTS_HEADER.index(name)] = str(value)
    return ";".join(cells)


def _runparts(
    *,
    counts: dict[int, tuple[int, int, int]] | None = None,
    time_steps: dict[int, str] | None = None,
) -> bytes:
    counts = counts or {}
    time_steps = time_steps or {}
    lines = [
        ";".join(runparts.RUNPARTS_HEADER),
        *(_row(
            part,
            counts=counts.get(part, (0, 0, 0)),
            time_step_text=time_steps.get(part),
        ) for part in range(3)),
        "",
        *runparts.RUNPARTS_FOOTER,
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _source(tmp_path: Path, filename: str, payload: bytes) -> diagnostic.PartOutSource:
    path = tmp_path / filename
    path.write_bytes(payload)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    return diagnostic.PartOutSource(filename, fd, hashlib.sha256(payload).hexdigest())


def _close(sources: tuple[diagnostic.PartOutSource, ...]) -> None:
    for source in sources:
        os.close(source.fd)


def test_consistent_synthetic_partout_join_stays_open_and_zero_credit(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(0, (_partout_record(1, (10, 11, 12), bytes((1, 2, 3))),)),
    )
    try:
        result = diagnostic.diagnose(
            _runparts(counts={1: (1, 1, 1)}), (source,), expected_pos_double=True
        )
    finally:
        _close((source,))

    assert result["status"] == "diagnostic_only_consistent_inputs_gate_open"
    assert result["excluded_fluid_particles_zero"] == "open"
    assert result["source_attempt_identity_verified"] is False
    assert result["output_mode_verified"] is False
    assert result["execution_horizon_verified"] is False
    assert result["terminal_flush_verified"] is False
    assert result["gate_decision_eligible"] is False
    assert result["qualification_credit"] == 0
    assert result["execution_authority"]["solver_started"] is False
    assert result["checks"]["motive_histograms_match_runparts"] is True
    assert result["part_diagnostics"][1]["motive_histogram"] == {"1": 1, "2": 1, "3": 1}


def test_all_partout_float_arrays_and_metadata_are_counted(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(
            0,
            (_partout_record(1, (10, 11, 12), bytes((1, 2, 3))),),
            extra_root_values=(
                _value("MapPosMin", 23, struct.pack("<ddd", -1.0, -2.0, -3.0)),
                _value("RhopMax", 11, struct.pack("<f", 1200.0)),
            ),
        ),
    )
    try:
        result = diagnostic.diagnose(
            _runparts(counts={1: (1, 1, 1)}), (source,), expected_pos_double=True
        )
    finally:
        _close((source,))

    inventory = result["partout_float_value_inventory"]
    assert inventory["status"] == "all_observed_values_scanned"
    assert inventory["finite_count"] == 26  # 4 root + PART timestep + 21 array components.
    assert inventory["nonfinite_count"] == 0
    assert inventory["all_observed_floating_values_finite"] is True
    part_floats = result["part_diagnostics"][1]["floating_value_inventory"]
    assert {item["name"] for item in part_floats["arrays"]} == {"Posd", "Vel", "Rhop"}
    assert all(item["raw_array_sha256"] for item in part_floats["arrays"])


def test_nonfinite_partout_float_is_reported_without_gate_adjudication(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(0, (
            _partout_record(
                1, (10,), b"\x01",
                float_values={"Posd": (float("nan"), 0.0, 0.0)},
            ),
        )),
    )
    try:
        result = diagnostic.diagnose(
            _runparts(counts={1: (1, 0, 0)}), (source,), expected_case_np=10752,
        )
    finally:
        _close((source,))

    assert result["status"] == "diagnostic_only_consistent_inputs_gate_open"
    assert result["excluded_fluid_particles_zero"] == "open"
    assert result["partout_float_value_inventory"]["nonfinite_count"] == 1
    assert result["partout_float_value_inventory"]["all_observed_floating_values_finite"] is False
    assert result["part_diagnostics"][1]["floating_value_inventory"]["all_floating_values_finite"] is False
    assert result["qualification_credit"] == 0
    assert result["runparts_input"]["sha256"] == hashlib.sha256(_runparts(counts={1: (1, 0, 0)})).hexdigest()


def test_nonfinite_partout_root_metadata_is_included_in_inventory(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(0, extra_root_values=(
            _value("MapPosMax", 23, struct.pack("<ddd", 1.0, float("inf"), 3.0)),
        )),
    )
    try:
        result = diagnostic.diagnose(_runparts(), (source,))
    finally:
        _close((source,))

    assert result["status"] == "diagnostic_only_consistent_inputs_gate_open"
    assert result["partout_float_value_inventory"]["finite_count"] == 2
    assert result["partout_float_value_inventory"]["nonfinite_count"] == 1
    assert result["partout_float_value_inventory"]["all_observed_floating_values_finite"] is False


def test_partout_case_population_must_match_verified_b_claim(tmp_path: Path) -> None:
    source = _source(tmp_path, "PartOut_000.obi4", _partout_block(0, case_np=2))
    try:
        result = diagnostic.diagnose(_runparts(), (source,), expected_case_np=3)
    finally:
        _close((source,))

    assert result["status"] == "diagnostic_only_missing_or_inconsistent"
    assert result["excluded_fluid_particles_zero"] == "missing"
    assert "verified B materialization population" in result["diagnostic_findings"][0]["detail"]


def test_partout_timestep_must_match_runparts_realstr_value(tmp_path: Path) -> None:
    source = _source(
        tmp_path, "PartOut_000.obi4",
        _partout_block(0, (_partout_record(1, (0,), b"\x01", time_step=0.2),)),
    )
    try:
        result = diagnostic.diagnose(_runparts(counts={1: (1, 0, 0)}), (source,))
    finally:
        _close((source,))

    assert result["status"] == "diagnostic_only_missing_or_inconsistent"
    assert "TimeStep disagrees with RunPARTs" in result["diagnostic_findings"][0]["detail"]


def test_appended_blocks_are_joined_by_part_not_aggregate_count(tmp_path: Path) -> None:
    sources = (
        _source(tmp_path, "PartOut_000.obi4", _partout_block(
            0, (_partout_record(1, (100,), bytes((1,))),), case_np=10752,
        )),
        _source(tmp_path, "PartOut_001.obi4", _partout_block(
            1, (_partout_record(2, (200, 201), bytes((2, 3))),), case_np=10752,
        )),
    )
    try:
        result = diagnostic.diagnose(
            _runparts(counts={1: (1, 0, 0), 2: (0, 1, 1)}), sources
        )
    finally:
        _close(sources)
    assert result["excluded_fluid_particles_zero"] == "open"
    assert result["summary"]["partout_blocks"] == 2
    assert result["summary"]["matched_nonzero_parts"] == 2


def test_current_cpu_profile_accepts_float_positions_with_uint32_ids(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(0, (_partout_record(
            1, (10751,), bytes((1,)), position="Pos"
        ),), case_np=10752),
    )
    try:
        result = diagnostic.diagnose(
            _runparts(counts={1: (1, 0, 0)}), (source,), expected_pos_double=False
        )
    finally:
        _close((source,))
    assert result["excluded_fluid_particles_zero"] == "open"
    assert result["checks"]["position_precision_expected_value"] is False
    assert result["part_diagnostics"][1]["position_array"] == "Pos"


def test_uint64_idpd_is_rejected_for_the_current_cpu_r008_profile(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(0, (_partout_record(
            1, (2**32 + 5,), bytes((1,)), id_double=True
        ),)),
    )
    try:
        result = diagnostic.diagnose(_runparts(counts={1: (1, 0, 0)}), (source,))
    finally:
        _close((source,))
    assert result["status"] == "diagnostic_only_missing_or_inconsistent"
    assert result["excluded_fluid_particles_zero"] == "missing"
    assert result["gate_decision_eligible"] is False


def test_particle_id_must_be_below_the_partout_declared_case_count(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(0, (_partout_record(1, (10752,), bytes((1,))),)),
    )
    try:
        result = diagnostic.diagnose(_runparts(counts={1: (1, 0, 0)}), (source,))
    finally:
        _close((source,))
    assert result["status"] == "diagnostic_only_missing_or_inconsistent"
    assert result["excluded_fluid_particles_zero"] == "missing"
    assert result["gate_decision_eligible"] is False


def test_partout_root_requires_positive_uint64_case_count(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(0, case_np=0),
    )
    try:
        result = diagnostic.diagnose(_runparts(), (source,))
    finally:
        _close((source,))
    assert result["status"] == "diagnostic_only_missing_or_inconsistent"
    assert result["excluded_fluid_particles_zero"] == "missing"
    assert result["gate_decision_eligible"] is False


def test_absent_partout_file_never_proves_zero_events() -> None:
    result = diagnostic.diagnose(_runparts())
    assert result["status"] == "diagnostic_only_consistent_inputs_gate_open"
    assert result["excluded_fluid_particles_zero"] == "open"
    assert result["checks"]["partout_absence_treated_as_zero"] is False
    assert result["diagnostic_findings"][0]["code"] == "PARTOUT_ABSENCE_NOT_ZERO_EVIDENCE"


def test_nonzero_runparts_count_without_partout_is_missing() -> None:
    result = diagnostic.diagnose(_runparts(counts={1: (1, 0, 0)}))
    assert result["status"] == "diagnostic_only_missing_or_inconsistent"
    assert result["excluded_fluid_particles_zero"] == "missing"
    assert result["gate_decision_eligible"] is False


@pytest.mark.parametrize(
    "ids,motives,counts,expected_pos_double,omit,filename,block",
    [
        ((10, 11), bytes((1, 1)), (1, 0, 0), None, None, "PartOut_000.obi4", 0),
        ((10, 10), bytes((1, 1)), (2, 0, 0), None, None, "PartOut_000.obi4", 0),
        ((10, 11), bytes((1, 9)), (1, 1, 0), None, None, "PartOut_000.obi4", 0),
        ((10, 11), bytes((1, 2)), (2, 0, 0), None, None, "PartOut_000.obi4", 0),
        ((10, 11), bytes((1, 1)), (2, 0, 0), True, "Vel", "PartOut_000.obi4", 0),
        ((10, 11), bytes((1, 1)), (2, 0, 0), True, None, "PartOut_000.obi4", 1),
    ],
)
def test_structural_or_cross_count_mismatches_are_missing(
    tmp_path: Path,
    ids: tuple[int, ...],
    motives: bytes,
    counts: tuple[int, int, int],
    expected_pos_double: bool | None,
    omit: str | None,
    filename: str,
    block: int,
) -> None:
    source = _source(
        tmp_path,
        filename,
        _partout_block(block, (_partout_record(1, ids, motives, omit=omit),)),
    )
    try:
        result = diagnostic.diagnose(
            _runparts(counts={1: counts}), (source,), expected_pos_double=expected_pos_double
        )
    finally:
        _close((source,))
    assert result["status"] == "diagnostic_only_missing_or_inconsistent"
    assert result["excluded_fluid_particles_zero"] == "missing"
    assert result["gate_decision_eligible"] is False
    assert result["qualification_credit"] == 0


def test_payload_for_zero_part_is_rejected_and_not_cancelled_by_another_part(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(0, (_partout_record(1, (10,), bytes((1,))),)),
    )
    try:
        result = diagnostic.diagnose(_runparts(), (source,))
    finally:
        _close((source,))
    assert result["excluded_fluid_particles_zero"] == "missing"
    assert "although RunPARTs NpOut is zero" in result["diagnostic_findings"][0]["detail"]


def test_partout_part_identity_and_block_continuity_are_required(tmp_path: Path) -> None:
    mismatched = _source(
        tmp_path,
        "PartOut_000.obi4",
        _partout_block(0, (_partout_record(2, (10,), bytes((1,))),)),
    )
    try:
        mismatch_result = diagnostic.diagnose(
            _runparts(counts={1: (1, 0, 0)}), (mismatched,)
        )
    finally:
        _close((mismatched,))
    assert mismatch_result["excluded_fluid_particles_zero"] == "missing"

    sources = (
        _source(tmp_path, "PartOut_000.obi4", _partout_block(0)),
        _source(tmp_path, "PartOut_002.obi4", _partout_block(2)),
    )
    try:
        gap_result = diagnostic.diagnose(_runparts(), sources)
    finally:
        _close(sources)
    assert gap_result["excluded_fluid_particles_zero"] == "missing"


def test_digest_binding_and_unsupported_piece_filename_fail_closed(tmp_path: Path) -> None:
    source = _source(tmp_path, "PartOut_000.obi4", _partout_block(0))
    wrong_digest = diagnostic.PartOutSource(source.filename, source.fd, "0" * 64)
    try:
        digest_result = diagnostic.diagnose(_runparts(), (wrong_digest,))
        piece_result = diagnostic.diagnose(
            _runparts(), (diagnostic.PartOutSource("PartOut_p00_000.obi4", source.fd, source.expected_sha256),)
        )
    finally:
        _close((source,))
    assert digest_result["excluded_fluid_particles_zero"] == "missing"
    assert piece_result["excluded_fluid_particles_zero"] == "missing"


def test_partout_append_framing_does_not_widen_safe_single_frame_api(tmp_path: Path) -> None:
    payload = _partout_block(0)
    path = tmp_path / "PartOut_000.obi4"
    path.write_bytes(payload)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with pytest.raises(bi4.Bi4FormatError, match="filecode"):
            bi4.scan_bi4_fd(fd, hashlib.sha256(payload).hexdigest())
    finally:
        os.close(fd)
    source = _source(tmp_path, "PartOut_000.obi4", payload)
    try:
        result = diagnostic.diagnose(_runparts(), (source,))
    finally:
        _close((source,))
    assert result["excluded_fluid_particles_zero"] == "open"
