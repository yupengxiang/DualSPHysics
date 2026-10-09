from __future__ import annotations

import importlib.util
import json
import hashlib
import struct
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v7.py"
REQUEST_DIR = ROOT / "campaigns/ds-data-02/stage2/requests/f2-coarse-active-stream-v7-root-forward-119-001"
MANIFEST = REQUEST_DIR / "f2-coarse-active-stream-v7-manifest.json"
REQUEST = REQUEST_DIR / "f2-coarse-active-stream-v7-request.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v7_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def jstr(value: str) -> bytes:
    payload = value.encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def jvalue(name: str, type_enum: int, payload: bytes) -> bytes:
    return jstr(name) + struct.pack("<i", type_enum) + payload


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_bi4(*, mass_type: int = 12, mass_value: float = 0.000681472010910511) -> tuple[bytes, int]:
    values = jstr("\nVALUES") + struct.pack("<I", 2)
    values += jvalue("Dp", 12, struct.pack("<d", 0.0088))
    mass_payload = struct.pack("<d", mass_value) if mass_type == 12 else struct.pack("<f", mass_value)
    values += jvalue("MassFluid", mass_type, mass_payload)
    base = b"".join(
        (
            jstr("\nITEM\n"),
            jstr("JPartDataBi4"),
            struct.pack("<i", 0),
            struct.pack("<i", 0),
            jstr("%.7E"),
            jstr("%.15E"),
            struct.pack("<I", 0),
            struct.pack("<I", 0),
            struct.pack("<I", len(values)),
        )
    )
    item = struct.pack("<I", len(base)) + base + values
    title = b"#FileJBD Part_0000.bi4".ljust(58, b" ") + b"\n\0"
    header = title + bytes((0, 0, 0, 0))
    offset = len(header) + 4 + len(base) + len(jstr("\nVALUES")) + 4
    # First value contributes its name/type/payload before MassFluid's bytes.
    offset += len(jstr("Dp")) + 4 + 8 + len(jstr("MassFluid")) + 4
    return header + item, offset


def test_v7_contract_is_raw_scalar_only_and_forward_schema():
    loaded = module()
    assert loaded.SCHEMA == "ds02.stage2.f2.coarse-active-stream.v7"
    assert loaded.MANIFEST_SCHEMA == "ds02.stage2.f2.coarse-active-stream.manifest.v7"
    assert "full-stream" in loaded.__doc__.lower()


def test_v7_discovers_root_massfluid_offset_and_original_bytes(tmp_path):
    loaded = module()
    payload, expected_offset = synthetic_bi4()
    path = tmp_path / "Part_0000.bi4"
    path.write_bytes(payload)
    found = loaded.discover_massfluid(path)
    assert found["item_path"] == ["JPartDataBi4"]
    assert found["field_name"] == "MassFluid"
    assert found["type_enum"] == 12
    assert found["type_name"] == "DatDouble"
    assert found["offset"] == expected_offset
    assert found["byte_count"] == 8
    assert found["raw_bytes_hex"] == struct.pack("<d", 0.000681472010910511).hex()
    assert found["payload_bytes_read"] == 0


def test_v7_raw_comparison_distinguishes_xml_and_float32_widening():
    loaded = module()
    source = 0.000681472
    widened = struct.unpack("<f", struct.pack("<f", source))[0]
    v6 = {
        "mass_header": {"value": widened},
        "source_xml_value_kg": source,
    }
    raw = {
        "raw_bytes_hex": struct.pack("<d", widened).hex(),
        "raw_bytes_sha256": "unused",
        "value_binary64_little": widened,
    }
    result = loaded._compare_raw(raw, v6)
    assert result["matches_v6_typed_binary64"] is True
    assert result["matches_xml_binary64"] is False
    assert result["matches_float32_widened_binary64"] is True
    assert result["status"] == "RAW_HEADER_DOUBLE_BYTES_MATCH_FLOAT32_WIDENED_VALUE"
    assert result["scientific_credit"] == "NONE"


def test_v7_rejects_non_double_massfluid_before_claiming_offset(tmp_path):
    loaded = module()
    payload, _ = synthetic_bi4(mass_type=11)
    path = tmp_path / "Part_0000.bi4"
    path.write_bytes(payload)
    with pytest.raises(loaded.RawHeaderError, match="type is 11"):
        loaded.discover_massfluid(path)


def test_v7_rejects_big_endian_header(tmp_path):
    loaded = module()
    payload, _ = synthetic_bi4()
    payload = payload[:60] + bytes((1, 0, 0, 0)) + payload[64:]
    path = tmp_path / "Part_0000.bi4"
    path.write_bytes(payload)
    with pytest.raises(loaded.RawHeaderError, match="byte order marker"):
        loaded.discover_massfluid(path)


def test_v7_requires_parent_full_sha_without_rehashing_frame(tmp_path):
    loaded = module()
    frame = tmp_path / "Part_0000.bi4"
    frame.write_bytes(b"header")
    ref = {
        "path": str(frame),
        "bytes": frame.stat().st_size,
        "mtime_ns": frame.stat().st_mtime_ns,
        "ctime_ns": frame.stat().st_ctime_ns,
        "st_dev": frame.stat().st_dev,
        "st_ino": frame.stat().st_ino,
        "sha256": "PARENT_GUARD_COMPUTED",
    }
    with pytest.raises(loaded.RawHeaderError, match="completed V6 parent full SHA"):
        loaded.bind_frame_ref(ref, "first BI4 frame")


def test_v7_prefix_cap_is_enforced_before_large_header_read(tmp_path):
    loaded = module()
    payload, _ = synthetic_bi4()
    path = tmp_path / "Part_0000.bi4"
    path.write_bytes(payload)
    loaded.MAX_HEADER_PREFIX_BYTES = 8
    with pytest.raises(loaded.RawHeaderError, match="prefix exceeded"):
        loaded.discover_massfluid(path)


def test_v7_source_target_contract_requires_serialized_discovery():
    loaded = module()
    with pytest.raises(loaded.RawHeaderError, match="offset"):
        loaded._validate_source_contract(
            {
                "schema": loaded.SOURCE_CONTRACT_SCHEMA,
                "serialization": {
                    "format": "JBinaryData",
                    "header_layout": {"size_bytes": 64, "byte_order": "little"},
                    "target": {
                        "item_path": ["JPartDataBi4"],
                        "field_name": "MassFluid",
                        "type_enum": 12,
                        "type_name": "DatDouble",
                        "value_bytes": 8,
                        "offset_mode": "fixed_guess",
                    },
                },
                "source_files": {},
            },
            {"source_files": {}},
            Path("/dev/null"),
        )


def test_v7_prepared_request_is_first_frame_only_and_source_bound():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert request["request_schema"] == "ds02.stage2.f2.coarse-active-stream.v7-request.v1"
    assert request["cpu_task_kind"] == "audit"
    assert request["input_sha256"] == request["input_hashes"]
    declared_worker = Path(request["command"][1]).resolve()
    declared_manifest = Path(request["command"][3]).resolve()
    assert declared_worker.is_file()
    assert declared_manifest.is_file()
    assert request["input_hashes"][str(declared_worker)] == digest(declared_worker)
    assert request["input_hashes"][str(declared_manifest)] == digest(declared_manifest)
    assert manifest["schema"] == "ds02.stage2.f2.coarse-active-stream.manifest.v7"
    assert manifest["probe_mode"] == "first_frame_raw_massfluid_scalar_only"
    assert manifest["guard_policy"]["remaining_frames_not_opened"] is True
    assert request["estimated_hdf5_read_bytes"] == 0
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    deferred = request["deferred_input_files"]
    assert len(deferred) == 1
    assert deferred[0]["path"].endswith("Part_0000.bi4")
    assert "Part_0001.bi4" not in json.dumps(request)
    assert request["probe_contract"]["type_enum"] == 12
    assert request["probe_contract"]["target_item_path"] == ["JPartDataBi4"]
    assert request["probe_contract"]["offset_recorded_in_output"] is True
