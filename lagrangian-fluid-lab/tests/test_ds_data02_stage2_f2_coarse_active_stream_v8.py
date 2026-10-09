from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v8.py"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/contracts/f2-coarse-active-stream-v8-full-stream-contract.json"
DIRECT_CONVERTER = ROOT / "scripts/ds_data02_direct_convert.py"
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v8_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _source_contract():
    return {
        "schema": "ds02.stage2.f2.coarse-active-stream.v7.massfluid-source-contract.v1",
        "status": "SOURCE_BOUND_RAW_SCALAR_PROOF_ONLY",
        "source_files": {"jsph_source": {"sha256": "a" * 64}},
        "serialization": {
            "format": "JBinaryData",
            "header_layout": {"size_bytes": 64, "byte_order": "little"},
            "target": {
                "item_path": ["JPartDataBi4"],
                "field_name": "MassFluid",
                "type_enum": 12,
                "type_name": "DatDouble",
                "value_bytes": 8,
                "byte_order": "little",
            },
        },
    }


def _v7_report(value: float, source_contract_path: Path, *, status="RAW_HEADER_DOUBLE_BYTES_MATCH_XML_BINARY64"):
    raw = struct.pack("<d", value)
    contract_sha = hashlib.sha256(source_contract_path.read_bytes()).hexdigest()
    return {
        "schema": "ds02.stage2.f2.coarse-active-stream.v7",
        "status": "RAW_HEADER_SCALAR_PROOF_COMPLETED_NO_FULL_STREAM_CREDIT",
        "case_key": CASE_KEY,
        "physical_case_id": CASE_KEY,
        "probe_scope": {"remaining_frames_opened": 0, "decoded_binary_arrays_read_by_worker": False},
        "source_contract": {
            "contract": {"sha256": contract_sha},
            "source_files": {"jsph_source": {"sha256": "a" * 64}},
        },
        "raw_source": {
            "massfluid_scalar": {
                "raw_bytes_hex": raw.hex(),
                "raw_bytes_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_value_binary64_kg": value,
                "source_xml_value_kg": value,
                "matches_v6_typed_binary64": True,
                "status": status,
            }
        },
        "claim_boundary": {
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
    }


def test_v8_contract_is_locked_to_v7_and_exact_bits():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["status"] == "SOURCE_READY_WAITING_FOR_V7_ACTUAL_RAW_SCALAR"
    assert contract["preconditions"]["v7_status"] == "RAW_HEADER_SCALAR_PROOF_COMPLETED_NO_FULL_STREAM_CREDIT"
    assert contract["massfluid_contract"]["absolute_tolerance"] is None
    assert contract["massfluid_contract"]["mass_rescaling"] is False
    assert contract["massfluid_contract"]["framewise_gate"] is True
    assert contract["mass_denominators"]["unknown_identity_fraction_max"] == 0.003
    assert contract["input_stability"]["first_frame_sha_provenance"].startswith("V7 worker")


def test_v8_precondition_accepts_completed_raw_scalar_and_official_path(tmp_path):
    loaded = module()
    source_path = tmp_path / "v7-source-contract.json"
    source_path.write_text(json.dumps(_source_contract()), encoding="utf-8")
    report_path = tmp_path / "v7-report.json"
    report = _v7_report(0.000681472010910511, source_path)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    result = loaded._validate_v7_precondition(
        report,
        report_path,
        json.loads(source_path.read_text(encoding="utf-8")),
        source_path,
    )
    assert result["expected_native_massfluid_bits_hex"] == struct.pack("<d", 0.000681472010910511).hex()
    assert result["raw_comparison_status"] == "RAW_HEADER_DOUBLE_BYTES_MATCH_XML_BINARY64"


def test_v8_precondition_rejects_raw_value_bit_mismatch(tmp_path):
    loaded = module()
    source_path = tmp_path / "v7-source-contract.json"
    source_path.write_text(json.dumps(_source_contract()), encoding="utf-8")
    report = _v7_report(0.000681472010910511, source_path)
    report["raw_source"]["massfluid_scalar"]["raw_value_binary64_kg"] = 0.000681472010910512
    with __import__("pytest").raises(loaded.StreamObservationError, match="does not round-trip"):
        loaded._validate_v7_precondition(report, source_path, json.loads(source_path.read_text()), source_path)


def test_v8_precondition_rejects_incomplete_v7(tmp_path):
    loaded = module()
    source_path = tmp_path / "v7-source-contract.json"
    source_path.write_text(json.dumps(_source_contract()), encoding="utf-8")
    report = _v7_report(0.000681472010910511, source_path)
    report["status"] = "RAW_HEADER_SCALAR_PROOF_FAILED"
    with __import__("pytest").raises(loaded.StreamObservationError, match="no completed raw-scalar proof"):
        loaded._validate_v7_precondition(report, source_path, json.loads(source_path.read_text()), source_path)


def test_v8_precondition_rejects_typed_only_without_raw_match(tmp_path):
    loaded = module()
    source_path = tmp_path / "v7-source-contract.json"
    source_path.write_text(json.dumps(_source_contract()), encoding="utf-8")
    report = _v7_report(0.000681472010910511, source_path)
    report["raw_source"]["massfluid_scalar"]["matches_v6_typed_binary64"] = False
    with __import__("pytest").raises(loaded.StreamObservationError, match="do not match"):
        loaded._validate_v7_precondition(report, source_path, json.loads(source_path.read_text()), source_path)


def test_v8_binary64_gate_has_no_tolerance():
    loaded = module()
    value = 0.000681472010910511
    assert loaded._binary64_bits(value, "value") == struct.pack("<d", value).hex()
    assert loaded._binary64_bits(value + 1e-16, "value") != loaded._binary64_bits(value, "value")
    assert "MASS_TOLERANCE" not in SCRIPT.read_text(encoding="utf-8")


def test_v8_registers_dataclass_backend_before_import(tmp_path):
    loaded = module()
    backend_path = tmp_path / "dataclass_backend.py"
    backend_path.write_text(
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class DecodedFrame:\n"
        "    value: int\n",
        encoding="utf-8",
    )
    backend = loaded.load_backend(backend_path)
    assert backend.__name__ == "ds02_direct_convert_for_f2_stream_v8"
    assert sys.modules[backend.__name__] is backend
    assert hasattr(backend, "DecodedFrame")


def test_v8_keeps_real_converter_as_a_bound_source():
    assert DIRECT_CONVERTER.is_file()
    assert "class DecodedFrame" in DIRECT_CONVERTER.read_text(encoding="utf-8")
