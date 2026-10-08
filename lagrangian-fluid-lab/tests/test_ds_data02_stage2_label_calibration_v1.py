#!/usr/bin/env python3
"""Manufactured source-label and censoring controls for label calibration v1."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_label_calibration_v1.py"
SPEC = importlib.util.spec_from_file_location("stage2_label_calibration_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import label calibration v1")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_exact_typed_block_resolves_source_mk_without_using_zone() -> None:
    conversion = {
        "typed_identity": {
            "blocks": [
                {"begin": 100, "count": 4, "mk": 1, "mkfluid": 0, "tag": "fluid", "type": 3},
                {"begin": 104, "count": 4, "mk": 2, "mkfluid": 1, "tag": "fluid", "type": 3},
            ]
        }
    }
    result = MODULE.source_mk_match(101, 3, 99, conversion)
    assert result["status"] == "VALID_SOURCE_MK_MAPPING"
    assert result["source_mk"] == 1
    assert result["source_mkfluid"] == 0
    assert result["legacy_zone"] == 99
    assert "not an MK" in result["legacy_zone_semantics"]


def test_outside_and_overlapping_typed_ranges_do_not_receive_source_credit() -> None:
    conversion = {
        "typed_identity": {
            "blocks": [
                {"begin": 100, "count": 4, "mk": 1, "mkfluid": 0, "tag": "fluid", "type": 3},
                {"begin": 102, "count": 4, "mk": 2, "mkfluid": 1, "tag": "fluid", "type": 3},
            ]
        }
    }
    outside = MODULE.source_mk_match(99, 3, 0, conversion)
    ambiguous = MODULE.source_mk_match(103, 3, 0, conversion)
    assert outside["status"] == "UNKNOWN_SOURCE_MK_MAPPING"
    assert outside["error"] == "id_outside_typed_block_ranges"
    assert ambiguous["status"] == "ERROR_SOURCE_MK_MAPPING"
    assert ambiguous["error"] == "ambiguous_typed_block_range"


def test_repeated_crossing_and_destination_are_conservatively_unknown() -> None:
    conversion = {
        "typed_identity": {
            "blocks": [{"begin": 100, "count": 1, "mk": 1, "mkfluid": 0, "tag": "fluid", "type": 3}]
        }
    }
    scan = {
        "missing_id_records": [{"idp": 100, "zone": 7, "type_code": 3, "initial_mass_kg": 0.001, "first_missing_frame": 4}],
        "type_ledgers": {"fluid": {"typed_initial_mass_kg": 0.001}},
    }
    case = {
        "particle_observations": [{
            "idp": 100,
            "native_motive": "position",
            "native_motive_code": 1,
            "saved_record_bracket_s": [0.1, 0.2],
        }],
        "native_gate": {"native_count": 1},
        "mass_visibility": {
            "missing_source_visible_mass_lower_bound_kg": 0.001,
            "missing_source_visible_fraction_lower_bound": 1.0,
        },
    }
    labels, errors = MODULE.particle_label(case, scan, conversion)
    assert errors == []
    assert labels[0]["labels"]["source_mk"] == "VALID_SOURCE_MK_MAPPING"
    assert labels[0]["censoring"]["reentry_or_repeated_crossing"] == "UNKNOWN"
    assert labels[0]["censoring"]["signed_net_flux"] == "UNKNOWN"
    assert labels[0]["labels"]["material_region_destination"] == "UNKNOWN_DESTINATION_MATERIAL_REGION"
    assert labels[0]["labels"]["physical_fate"] == "UNKNOWN_PHYSICAL_FATE"


def test_malformed_observation_cannot_be_promoted_to_native_cause() -> None:
    conversion = {
        "typed_identity": {
            "blocks": [{"begin": 100, "count": 1, "mk": 1, "mkfluid": 0, "tag": "fluid", "type": 3}]
        }
    }
    scan = {
        "missing_id_records": [{"idp": 100, "zone": 7, "type_code": 3, "initial_mass_kg": 0.001, "first_missing_frame": 4}],
        "type_ledgers": {"fluid": {"typed_initial_mass_kg": 0.001}},
    }
    case = {"particle_observations": [{"idp": 100, "native_motive": "position"}], "native_gate": {"native_count": 1}}
    labels, errors = MODULE.particle_label(case, scan, conversion)
    assert "saved_record_bracket_missing_or_invalid" in labels[0]["errors"]
    assert labels[0]["labels"]["native_cause"] == "ERROR_NATIVE_CAUSE"
    assert errors == []


def test_forbidden_raw_extension_is_rejected(tmp_path: Path) -> None:
    raw = tmp_path / "PartOut_000.obi4"
    raw.write_bytes(b"manufactured raw placeholder")
    with pytest.raises(MODULE.LabelCalibrationError):
        MODULE.require_file(raw, "manufactured raw")


def test_runtime_bindings_are_source_files_and_exist() -> None:
    paths = MODULE.runtime_source_paths()
    assert set(paths) == {"runtime_v8", "runtime_v6", "dispatch_v8", "strict_v8"}
    assert all(path.is_file() for path in paths.values())


def test_receipt_allows_normalized_interpreter_alias_but_rejects_foreign_input(tmp_path: Path) -> None:
    output_root = tmp_path / "producer"
    output_root.mkdir()
    output = output_root / "small.json"
    output.write_text("{}", encoding="utf-8")
    declared = tmp_path / "declared.json"
    declared.write_text("declared", encoding="utf-8")
    declared_hash = MODULE.sha256(declared)
    receipt_path = output_root / "execution-receipt.json"
    receipt = {
        "schema": "ds02.execution-receipt.v1",
        "status": "completed",
        "returncode": 0,
        "output_root": str(output_root),
        "request": {"input_sha256": {str(declared): declared_hash}},
        "input_hashes_at_launch": {str(declared): declared_hash, "/usr/bin/python3.10": "interpreter"},
        "input_hashes_after_run": {str(declared): declared_hash, "/usr/bin/python3.10": "interpreter"},
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    item = {"path": str(receipt_path), "bytes": receipt_path.stat().st_size, "sha256": MODULE.sha256(receipt_path)}
    _, errors = MODULE.validate_completed_receipt(item, "manufactured receipt", output_root)
    assert errors == []

    bad = copy.deepcopy(receipt)
    bad["input_hashes_at_launch"][str(tmp_path / "foreign.json")] = "foreign"
    bad["input_hashes_after_run"][str(tmp_path / "foreign.json")] = "foreign"
    bad_path = output_root / "bad-receipt.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    bad_item = {"path": str(bad_path), "bytes": bad_path.stat().st_size, "sha256": MODULE.sha256(bad_path)}
    _, bad_errors = MODULE.validate_completed_receipt(bad_item, "bad receipt", output_root)
    assert "bad receipt_unexpected_runner_inputs" in bad_errors
