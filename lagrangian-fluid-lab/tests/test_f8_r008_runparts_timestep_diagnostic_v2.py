from __future__ import annotations

from pathlib import Path
import re

import pytest

from scripts import f8_r008_runparts_timestep_diagnostic_v1 as runparts_v1
from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts


def _row(part: int, time_s: str, steps: int, dtmin: str, dtmax: str) -> str:
    cells = ["0"] * len(runparts.RUNPARTS_HEADER)
    cells[0] = str(part)
    cells[1] = time_s
    cells[2] = str(steps)
    cells[19] = dtmin
    cells[20] = dtmax
    return ";".join(cells)


def _payload(*, first_part: int = 0, first_time: str = "0") -> bytes:
    return ("\n".join((
        ";".join(runparts.RUNPARTS_HEADER),
        _row(first_part, first_time, 0, "0", "0"),
        _row(first_part + 1, str(float(first_time) + 0.1), 10, "0.001", "0.002"),
        "",
        *runparts.RUNPARTS_FOOTER,
        "",
    ))).encode("utf-8")


def test_v2_parser_validates_all_columns_and_keeps_scope_untrusted() -> None:
    parsed = runparts.parse_runparts_csv(_payload())

    assert parsed["data_row_count"] == 2
    assert parsed["first_part"] == 0
    assert parsed["last_part"] == 1
    assert parsed["last_recorded_time_s"] == pytest.approx(0.1)
    assert parsed["maximum_recorded_part_dtmax_s"] == pytest.approx(0.002)
    assert parsed["input_scope"] == runparts.INPUT_SCOPE
    assert parsed["all_26_fields_type_and_range_checked"] is True
    assert parsed["cross_field_native_semantics_verified"] is False
    assert parsed["attempt_identity_verified"] is False
    assert parsed["normal_completion_verified"] is False
    assert parsed["qualification_credit"] == 0


@pytest.mark.parametrize("column", range(26))
def test_v2_parser_rejects_nonnumeric_value_in_every_native_column(column: int) -> None:
    lines = _payload().decode("utf-8").splitlines()
    cells = lines[2].split(";")
    cells[column] = "not-a-number"
    lines[2] = ";".join(cells)

    with pytest.raises(runparts.RunPartsDiagnosticError):
        runparts.parse_runparts_csv(("\n".join(lines) + "\n").encode("utf-8"))


@pytest.mark.parametrize("column", [4, 10, 11, 12, 21, 22, 23])
def test_v2_parser_rejects_negative_native_float_fields(column: int) -> None:
    lines = _payload().decode("utf-8").splitlines()
    cells = lines[2].split(";")
    cells[column] = "-1"
    lines[2] = ";".join(cells)

    with pytest.raises(runparts.RunPartsDiagnosticError, match="unsigned decimal representation"):
        runparts.parse_runparts_csv(("\n".join(lines) + "\n").encode("utf-8"))


@pytest.mark.parametrize("value", ["-0", "-0.0", "+0.0"])
def test_v2_parser_rejects_signed_float_zero(value: str) -> None:
    lines = _payload().decode("utf-8").splitlines()
    cells = lines[2].split(";")
    cells[10] = value
    lines[2] = ";".join(cells)

    with pytest.raises(runparts.RunPartsDiagnosticError, match="unsigned decimal representation"):
        runparts.parse_runparts_csv(("\n".join(lines) + "\n").encode("utf-8"))


def test_v2_parser_rejects_nonzero_restart_origin_outside_diagnostic_policy() -> None:
    with pytest.raises(runparts.RunPartsDiagnosticError, match="input policy"):
        runparts.parse_runparts_csv(_payload(first_part=7, first_time="2.5"))


def test_v2_parser_rejects_appended_restart_segment_after_native_footer() -> None:
    appended = _payload() + (_row(2, "0.2", 0, "0", "0") + "\n").encode("utf-8")

    with pytest.raises(runparts.RunPartsDiagnosticError):
        runparts.parse_runparts_csv(appended)


def test_v2_parser_uses_exact_source_header_and_footer_contract() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (repository / "src/source/JSph.cpp").read_text(encoding="utf-8")
    header_start = source.index("void JSph::SaveRunPartsCsv(")
    header_end = source.index("//-Saves data.", header_start)
    header_fragments = re.findall(r'scsv << "([^"]*)";', source[header_start:header_end])
    source_header = tuple(";".join(header_fragments).split(";"))
    footer_start = source.index("void JSph::SaveRunPartsCsvFinal()")
    footer_end = source.index("/// Stores files of particle data.", footer_start)
    source_footer = tuple(re.findall(
        r'scsv << "(#.*)" << jcsv::Endl\(\);', source[footer_start:footer_end]
    ))

    assert source_header == runparts.RUNPARTS_HEADER == runparts_v1.RUNPARTS_HEADER
    assert source_footer == runparts.RUNPARTS_FOOTER == runparts_v1.RUNPARTS_FOOTER


def test_v2_builder_uses_bounded_no_follow_source_reader(tmp_path: Path) -> None:
    source = tmp_path / "RunPARTs.csv"
    source.write_bytes(_payload())

    receipt = runparts.build_diagnostic_receipt(source, "synthetic-case")

    assert receipt["schema"] == runparts.SCHEMA
    assert receipt["input_scope"] == runparts.INPUT_SCOPE
    assert receipt["status"] == "diagnostic_only_fresh_segment_execution_unverified"
    assert receipt["checks"] == {
        "all_26_fields_type_and_range_checked": True,
        "single_segment_part0_time0_input_policy": True,
    }
    assert receipt["maximum_recorded_part_dtmax_s"] == pytest.approx(0.002)
    assert receipt["attempt_identity_verified"] is False
    assert receipt["runtime_configuration_verified"] is False
    assert receipt["normal_completion_verified"] is False
    assert receipt["cross_field_native_semantics_verified"] is False
    assert receipt["qualification_credit"] == 0


def test_v2_builder_rejects_symlink_source(tmp_path: Path) -> None:
    link = tmp_path / "RunPARTs.csv"
    link.symlink_to("elsewhere.csv")
    with pytest.raises(runparts.RunPartsDiagnosticError):
        runparts.build_diagnostic_receipt(link, "synthetic-case")
