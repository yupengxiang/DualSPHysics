from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

import pytest

from scripts import f8_r008_runparts_timestep_diagnostic_v1 as runparts


def _row(part: int, time_s: str, steps: int, dtmin: str, dtmax: str) -> str:
    cells = ["0"] * len(runparts.RUNPARTS_HEADER)
    cells[0] = str(part)
    cells[1] = time_s
    cells[2] = str(steps)
    cells[19] = dtmin
    cells[20] = dtmax
    return ";".join(cells)


def _payload(first_part: int = 0, first_time: str = "0") -> bytes:
    header = ";".join(runparts.RUNPARTS_HEADER)
    lines = [
        header,
        _row(first_part, first_time, 0, "0", "0"),
        _row(first_part + 1, str(float(first_time) + 0.1), 10, "0.001", "0.002"),
        _row(first_part + 2, str(float(first_time) + 0.2), 10, "0.0015", "0.0018"),
        "",
        *runparts.RUNPARTS_FOOTER,
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_parser_recomputes_max_recorded_dtmax_but_keeps_execution_unverified() -> None:
    parsed = runparts.parse_runparts_csv(_payload())

    assert parsed["data_row_count"] == 3
    assert parsed["first_part"] == 0
    assert parsed["last_part"] == 2
    assert parsed["last_recorded_time_s"] == pytest.approx(0.2)
    assert parsed["maximum_recorded_part_dtmax_s"] == pytest.approx(0.002)
    assert parsed["footer_present"] is True
    assert parsed["attempt_identity_verified"] is False
    assert parsed["normal_completion_verified"] is False
    assert parsed["frozen_end_time_reached"] is False
    assert parsed["qualification_credit"] == 0


def test_parser_accepts_native_restart_part_and_time_origin() -> None:
    parsed = runparts.parse_runparts_csv(_payload(first_part=7, first_time="2.5"))

    assert parsed["first_part"] == 7
    assert parsed["last_part"] == 9
    assert parsed["last_recorded_time_s"] == pytest.approx(2.7)


@pytest.mark.parametrize("mutation", [
    "header", "duplicate_header", "part_gap", "time_not_increasing", "zero_noninitial_steps",
    "dtmin_gt_dtmax", "zero_noninitial_dt", "nonfinite_dt", "extra_column",
    "footer_text", "missing_footer", "reordered_footer", "data_after_footer", "invalid_utf8", "bom",
    "quoted_field", "padded_field", "missing_final_newline", "cr",
])
def test_parser_rejects_malformed_or_incomplete_runparts_structure(mutation: str) -> None:
    payload = _payload()
    text = payload.decode("utf-8")
    lines = text.splitlines()
    if mutation == "header":
        lines[0] = lines[0].replace("Part;", "PART;", 1)
    elif mutation == "duplicate_header":
        lines.insert(2, lines[0])
    elif mutation == "part_gap":
        cells = lines[3].split(";")
        cells[0] = "4"
        lines[3] = ";".join(cells)
    elif mutation == "time_not_increasing":
        cells = lines[3].split(";")
        cells[1] = "0.1"
        lines[3] = ";".join(cells)
    elif mutation == "zero_noninitial_steps":
        cells = lines[2].split(";")
        cells[2] = "0"
        lines[2] = ";".join(cells)
    elif mutation == "dtmin_gt_dtmax":
        cells = lines[2].split(";")
        cells[19] = "0.003"
        lines[2] = ";".join(cells)
    elif mutation == "zero_noninitial_dt":
        cells = lines[2].split(";")
        cells[20] = "0"
        lines[2] = ";".join(cells)
    elif mutation == "nonfinite_dt":
        cells = lines[2].split(";")
        cells[20] = "nan"
        lines[2] = ";".join(cells)
    elif mutation == "extra_column":
        lines[2] += ";unexpected"
    elif mutation == "footer_text":
        lines[-1] += " altered"
    elif mutation == "missing_footer":
        lines.pop()
    elif mutation == "reordered_footer":
        lines[-1], lines[-2] = lines[-2], lines[-1]
    elif mutation == "data_after_footer":
        lines.append(_row(3, "0.3", 10, "0.001", "0.0015"))
    elif mutation == "invalid_utf8":
        payload = payload + b"\xff"
    elif mutation == "bom":
        payload = b"\xef\xbb\xbf" + payload
    elif mutation == "quoted_field":
        cells = lines[2].split(";")
        cells[1] = '"0.1"'
        lines[2] = ";".join(cells)
    elif mutation == "padded_field":
        cells = lines[2].split(";")
        cells[1] = " 0.1"
        lines[2] = ";".join(cells)
    elif mutation == "missing_final_newline":
        payload = payload[:-1]
    elif mutation == "cr":
        payload = payload.replace(b"\n", b"\r\n")
    if mutation not in {"invalid_utf8", "bom", "missing_final_newline", "cr"}:
        payload = ("\n".join(lines) + "\n").encode("utf-8")

    with pytest.raises(runparts.RunPartsDiagnosticError):
        runparts.parse_runparts_csv(payload)


def test_footer_contract_exactly_matches_dualsphysics_writer_source() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (repository / "src/source/JSph.cpp").read_text(encoding="utf-8")
    start = source.index("void JSph::SaveRunPartsCsvFinal()")
    end = source.index("/// Stores files of particle data.", start)
    footer_section = source[start:end]
    actual_footer = tuple(re.findall(r'scsv << "(#.*)" << jcsv::Endl\(\);', footer_section))
    assert actual_footer == runparts.RUNPARTS_FOOTER


def test_header_contract_exactly_matches_dualsphysics_writer_source() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (repository / "src/source/JSph.cpp").read_text(encoding="utf-8")
    start = source.index("void JSph::SaveRunPartsCsv(")
    end = source.index("//-Saves data.", start)
    header_section = source[start:end]
    fragments = re.findall(r'scsv << "([^"]*)";', header_section)
    actual_header = tuple(";".join(fragments).split(";"))
    assert actual_header == runparts.RUNPARTS_HEADER


def test_parser_applies_fixed_byte_cap_before_decoding(monkeypatch) -> None:
    monkeypatch.setattr(runparts, "MAX_RUNPARTS_BYTES", 32)
    with pytest.raises(runparts.RunPartsDiagnosticError, match="fixed byte limit"):
        runparts.parse_runparts_csv(b"x" * 33)


def test_parser_applies_fixed_data_row_cap(monkeypatch) -> None:
    monkeypatch.setattr(runparts, "MAX_RUNPARTS_ROWS", 2)
    with pytest.raises(runparts.RunPartsDiagnosticError, match="data-row limit"):
        runparts.parse_runparts_csv(_payload())


def test_build_receipt_hashes_exact_csv_and_never_claims_execution(tmp_path: Path) -> None:
    source = tmp_path / "RunPARTs.csv"
    payload = _payload()
    source.write_bytes(payload)

    receipt = runparts.build_diagnostic_receipt(source, "synthetic-case")

    assert receipt["schema"] == runparts.SCHEMA
    assert receipt["status"] == "diagnostic_only_execution_unverified"
    assert receipt["case_id_claim"] == "synthetic-case"
    assert receipt["maximum_recorded_part_dtmax_s"] == pytest.approx(0.002)
    assert receipt["source_runparts"] == {
        "path": "RunPARTs.csv",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    assert receipt["attempt_identity_verified"] is False
    assert receipt["runtime_configuration_verified"] is False
    assert receipt["normal_completion_verified"] is False
    assert receipt["qualification_credit"] == 0


@pytest.mark.parametrize("mutation", ["symlink", "hardlink", "fifo", "parent_symlink"])
def test_builder_rejects_unsafe_runparts_paths(tmp_path: Path, mutation: str) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    source = real_dir / "RunPARTs.csv"
    source.write_bytes(_payload())
    if mutation == "symlink":
        source.unlink()
        source.symlink_to("target.csv")
    elif mutation == "hardlink":
        source.with_name("other.csv").hardlink_to(source)
    elif mutation == "fifo":
        source.unlink()
        os.mkfifo(source)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(real_dir, target_is_directory=True)
        source = alias / "RunPARTs.csv"

    with pytest.raises(runparts.RunPartsDiagnosticError):
        runparts.build_diagnostic_receipt(source, "synthetic-case")


def test_builder_requires_exact_runparts_basename(tmp_path: Path) -> None:
    other = tmp_path / "arbitrary.log"
    other.write_bytes(_payload())
    with pytest.raises(runparts.RunPartsDiagnosticError, match="RunPARTs.csv"):
        runparts.build_diagnostic_receipt(other, "synthetic-case")
