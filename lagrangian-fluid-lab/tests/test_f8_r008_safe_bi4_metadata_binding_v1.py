from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import struct

import pytest

from scripts import f8_r008_safe_bi4_decoder_v1 as decoder
from scripts import f8_r008_safe_bi4_metadata_binding_v1 as metadata


def _string(value: str | bytes) -> bytes:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return struct.pack("<I", len(payload)) + payload


def _value(name: str, type_code: int, payload: bytes) -> bytes:
    return _string(name) + struct.pack("<i", type_code) + payload


def _item(
    name: str,
    values: tuple[bytes, ...] = (),
    children: tuple[bytes, ...] = (),
) -> bytes:
    value_block = b""
    if values:
        value_block = _string(decoder.CODE_VALUES) + struct.pack("<I", len(values)) + b"".join(values)
    definition = (
        _string(decoder.CODE_ITEM)
        + _string(name)
        + struct.pack("<ii", 0, 0)
        + _string("%.7E")
        + _string("%.15E")
        + struct.pack("<III", 0, len(children), len(value_block))
    )
    return struct.pack("<I", len(definition)) + definition + value_block + b"".join(children)


def _frame(*, time_s: float = 0.10000000000000002, mass_kg: float = 0.000421875,
           mass_type: int = 12, time_type: int = 12,
           extra_root_values: tuple[bytes, ...] = ()) -> bytes:
    root_values = (
        _value("CaseNp", 10, struct.pack("<Q", 2)),
        _value("CaseNfluid", 10, struct.pack("<Q", 1)),
        _value("MassFluid", mass_type, struct.pack("<d" if mass_type == 12 else "<f", mass_kg)),
        *extra_root_values,
    )
    part_values = (
        _value("TimeStep", time_type, struct.pack("<d" if time_type == 12 else "<f", time_s)),
        _value("Npok", 8, struct.pack("<I", 2)),
    )
    part = _item("PART_0000", part_values)
    root = _item("JPartDataBi4", root_values, (part,))
    header = decoder.FILE_PREFIX + b" " * (58 - len(decoder.FILE_PREFIX)) + b"\n\0" + b"\0\0\0\0"
    return header + root


def _open_input(tmp_path: Path, payload: bytes) -> tuple[int, str]:
    path = tmp_path / "frame.bi4"
    path.write_bytes(payload)
    return os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), hashlib.sha256(payload).hexdigest()


def test_metadata_binding_preserves_raw_double_bits_and_is_canonical(tmp_path: Path) -> None:
    payload = _frame()
    fd, digest = _open_input(tmp_path, payload)
    try:
        result = metadata.bind_metadata_fd(fd, digest)
    finally:
        os.close(fd)

    manifest = result["manifest"]
    assert manifest["schema"] == metadata.SCHEMA
    assert manifest["input_sha256"] == digest
    assert result["manifest_sha256"] == hashlib.sha256(result["manifest_bytes"]).hexdigest()
    assert result["manifest_bytes"] == metadata.canonical_manifest_bytes(manifest)
    assert json.loads(result["manifest_bytes"])["input_sha256"] == digest

    fields = {(tuple(row["item_path"]), row["metadata_name"]): row
              for row in manifest["metadata_records"]}
    record_fields = {
        "item_path", "metadata_name", "type_code", "type_name",
        "raw_value_bytes_hex", "canonical_value", "float_hex_components",
    }
    assert all(set(row) == record_fields for row in manifest["metadata_records"])
    mass = fields[(("JPartDataBi4",), "MassFluid")]
    time_value = fields[(("JPartDataBi4", "PART_0000"), "TimeStep")]
    assert mass["type_code"] == 12
    assert mass["raw_value_bytes_hex"] == struct.pack("<d", 0.000421875).hex()
    assert mass["float_hex_components"] == [float(0.000421875).hex()]
    assert time_value["raw_value_bytes_hex"] == struct.pack("<d", 0.10000000000000002).hex()
    assert time_value["float_hex_components"] == [float(0.10000000000000002).hex()]
    schema = json.loads(Path("reports/F8-R008-PER-CASE-PROVENANCE-SCHEMA-V1-2026-09-24.json").read_text())
    contract = schema["stage_D_decode_table_provenance"]["decoder_contract"]["metadata_binding_api"]
    assert set(contract["exact_value_record_fields"]) == record_fields
    assert len(contract["exact_value_record_fields"]) == len(record_fields)
    decoded_contract = schema["stage_D_decode_table_provenance"]["decoder_contract"]["detached_decoded_frame_manifest"]
    assert "raw_solver_manifest_entry_sha256" not in decoded_contract["binds"]
    assert "raw_solver_manifest_sha256" in decoded_contract["binds"]
    assert "expected_time_s_ieee754_hex" in decoded_contract["binds"]
    assert "parser_observed_time_s_ieee754_hex" in decoded_contract["binds"]
    assert "only expected_time_s_ieee754_hex" in schema["stage_C_solver_attempt"]["raw_output_manifest"]["expected_time_source"]
    assert "strictly positive" in schema["stage_D_decode_table_provenance"]["decoder_contract"]["mass_density_and_identity_closure"]["mass_binding"]
    assert list(tmp_path.iterdir()) == [tmp_path / "frame.bi4"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_frame(mass_type=11), "wrong JBinaryData type"),
        (_frame(time_type=11), "wrong JBinaryData type"),
        (_frame(time_s=-0.0), "positive-zero"),
        (_frame(time_s=math.nan), "finite"),
        (_frame(time_s=math.inf), "finite"),
        (_frame(mass_kg=math.inf), "finite"),
        (_frame(mass_kg=math.nan), "finite"),
        (_frame(mass_kg=-0.0), "positive"),
        (_frame(extra_root_values=(_value("Gamma", 12, struct.pack("<d", math.inf)),)), "non-finite"),
    ],
)
def test_invalid_required_metadata_fails_closed_before_any_write(
    tmp_path: Path, payload: bytes, message: str,
) -> None:
    fd, digest = _open_input(tmp_path, payload)
    try:
        with pytest.raises(decoder.Bi4FormatError, match=message):
            metadata.bind_metadata_fd(fd, digest)
    finally:
        os.close(fd)
    assert list(tmp_path.iterdir()) == [tmp_path / "frame.bi4"]


def test_metadata_binding_requires_expected_raw_input_hash(tmp_path: Path) -> None:
    fd, _digest = _open_input(tmp_path, _frame())
    try:
        with pytest.raises(decoder.Bi4FormatError, match="does not match"):
            metadata.bind_metadata_fd(fd, "0" * 64)
    finally:
        os.close(fd)
    assert list(tmp_path.iterdir()) == [tmp_path / "frame.bi4"]
