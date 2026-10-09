from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v5.py"
REQUEST_DIR = ROOT / "campaigns/ds-data-02/stage2/requests/f2-coarse-active-stream-v5-root-forward-116-001"
MANIFEST = REQUEST_DIR / "f2-coarse-active-stream-v5-manifest.json"
REQUEST = REQUEST_DIR / "f2-coarse-active-stream-v5-request.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v5_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def field(name: str, tag: str, value, raw: str | None = None) -> dict:
    return {"name": name, "tag": tag, "value": value, "raw": raw if raw is not None else str(value)}


def test_v5_request_binds_new_worker_and_first_frame_only_manifest():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    worker = SCRIPT.resolve()
    manifest_path = MANIFEST.resolve()
    assert request["request_schema"] == "ds02.stage2.f2.coarse-active-stream.v5-request.v1"
    assert request["attempt_id"] == "f2-coarse-active-stream-v5-root-forward-116-001"
    assert request["command"][1] == str(worker)
    assert request["command"][3] == str(manifest_path)
    assert manifest["schema"] == "ds02.stage2.f2.coarse-active-stream.manifest.v5"
    assert manifest["probe_mode"] == "first_frame_header_only"
    assert request["input_hashes"][str(worker)] == digest(worker)
    assert request["input_sha256"] == request["input_hashes"]
    assert request["input_hashes"][str(manifest_path)] == digest(manifest_path)
    deferred_paths = [entry["path"] for entry in request["deferred_input_files"]]
    assert any(path.endswith("Part_0000.bi4") for path in deferred_paths)
    assert not any("Part_0001.bi4" in path for path in deferred_paths)
    assert request["estimated_hdf5_read_bytes"] == 0
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    assert request["probe_contract"]["full_stream_credit"] == "NONE"


def test_v5_mass_contract_confirms_observed_float32_bits():
    loaded = module()
    source_value = 0.000681472
    observed = struct.unpack("<f", struct.pack("<f", source_value))[0]
    result = loaded._mass_contract(
        {"xml_value_kg": source_value, "manifest_value_kg": source_value},
        {"MassFluid": field("MassFluid", "float", observed)},
    )
    assert result["status"] == "TYPED_HEADER_MATCHES_EXPECTED_ENCODING_NO_RAW_SERIALIZATION_PROOF"
    assert result["observed_encoding"] == "float32"
    assert result["bits_match"] is True
    assert result["raw_header_bytes_observed"] is False
    assert result["float32_precision_correction"] == "NOT_APPLIED"


def test_v5_mass_contract_rejects_float32_value_claimed_as_binary64():
    loaded = module()
    source_value = 0.000681472
    observed_float32 = struct.unpack("<f", struct.pack("<f", source_value))[0]
    result = loaded._mass_contract(
        {"xml_value_kg": source_value, "manifest_value_kg": source_value},
        {"MassFluid": field("MassFluid", "double", observed_float32)},
    )
    assert result["status"] == "MASS_SERIALIZATION_MISMATCH_NO_FULL_STREAM"
    assert result["bits_match"] is False
    assert result["observed_encoding"] == "binary64"
    assert result["scientific_credit"] == "NONE"


def test_v5_header_parser_preserves_type_and_raw_value():
    loaded = module()
    root = ET.fromstring(
        '<root><item name="header"><float name="MassFluid" v="0.000681472010910511"/>'
        '<int name="Npiece" v="1"/></item></root>'
    )
    fields = loaded._named_fields(root)
    assert fields["MassFluid"]["tag"] == "float"
    assert fields["MassFluid"]["raw"] == "0.000681472010910511"
    assert fields["Npiece"]["value"] == 1


def test_v5_dynamic_header_contract_rejects_nonstatic_stream():
    loaded = module()
    fields = {
        "Npiece": field("Npiece", "int", 1),
        "Piece": field("Piece", "int", 0),
        "NpDynamic": field("NpDynamic", "int", 0),
        "ReuseIds": field("ReuseIds", "int", 1),
        "PeriMode": field("PeriMode", "int", 0),
    }
    with pytest.raises(loaded.StreamHeaderError, match="ReuseIds=1"):
        loaded._validate_dynamic_contract(fields)


def test_v5_rejects_ambiguous_real_mass_type():
    loaded = module()
    source_value = 0.000681472
    with pytest.raises(loaded.StreamHeaderError, match="ambiguous 'real'"):
        loaded._mass_contract(
            {"xml_value_kg": source_value, "manifest_value_kg": source_value},
            {"MassFluid": field("MassFluid", "real", source_value)},
        )


def test_v5_source_contract_closes_without_opening_raw_frame():
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths = loaded._source_paths(manifest)
    raw_root = Path(manifest["raw_data_root"]["path"]).resolve()
    contract = loaded._validate_native_source_contract(paths, manifest, raw_root)
    assert contract["native_qa"]["report_status"] == "COMPLETED_F2_COARSE_CANARY_NATIVE_IDENTITY_MOTIVE_QA"
    assert contract["solver"]["receipt_status"] == "COMPLETED_DEVELOPMENT_UNKNOWN"
    assert contract["source_scope"]["arrays_opened_by_header_probe"] is False


def test_v5_frame_inventory_rejects_noncontiguous_manifest():
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    broken = json.loads(json.dumps(manifest))
    broken["frames"][1]["path"] = broken["frames"][1]["path"].replace("Part_0001.bi4", "Part_0002.bi4")
    with pytest.raises(loaded.StreamHeaderError, match="contiguous"):
        loaded._frame_inventory(broken, Path(manifest["raw_data_root"]["path"]).resolve())
