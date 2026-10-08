from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load("stage2_native_identity_audit_v2", ROOT / "scripts" / "ds_data02_stage2_native_identity_audit_v2.py")
BUILDER = _load(
    "stage2_native_identity_audit_v2_builder",
    ROOT / "scripts" / "ds_data02_stage2_native_identity_audit_v2_request_builder.py",
)


def test_source_gap_is_visible_and_receives_no_native_credit() -> None:
    case = {
        "case_key": "F2/scan-F2-S1-001",
        "family_id": "F2",
        "physical_case_id": "F2-S1",
        "expected_native_motive": "position",
        "expected_native_count": 3,
        "source_refs": {
            "scan": {"path": "/evidence/scan.json", "sha256": "a" * 64},
            "scan_receipt": {"path": "/evidence/receipt.json", "sha256": "b" * 64},
        },
    }
    impact = {"cases": [{
        "case_key": "F2/scan-F2-S1-001", "family_id": "F2", "physical_case_id": "F2-S1",
        "native_numerical_cause": {"motive": "position", "native_count": 3},
    }]}
    current = {"cases": [{"family_id": "F2", "physical_case_id": "F2-S1"}]}
    missing = V2._missing_sources(case)
    result = V2._source_incomplete_case(case, missing, impact, current)
    assert result["case_status"] == "SOURCE_INCOMPLETE"
    assert result["native_identity"]["status"] == "UNKNOWN_SOURCE_INCOMPLETE"
    assert result["native_cause"]["status"] == "NOT_CREDITED_BY_V2"
    assert {item["key"] for item in result["source_closure"]["missing_sources"]} >= {
        "native_csv", "decoder_receipt", "conversion_report", "raw_partout"
    }


def test_closed_case_adds_whole_initial_mass_fraction_without_fate_credit() -> None:
    result = V2._enrich_closed_case({
        "native_identity": {"typed_total_mass_kg": 20.0, "missing_mass_kg": 0.1},
        "native_cause": {"physical_fate": "UNKNOWN_NOT_PROVEN"},
    })
    assert result["case_status"] == "NATIVE_IDENTITY_SOURCE_CLOSED"
    assert result["native_identity"]["whole_initial_mass_denominator_kg"] == 20.0
    assert result["native_identity"]["missing_mass_fraction_of_whole_initial"] == pytest.approx(0.005)
    assert result["native_cause"]["physical_fate"] == "UNKNOWN_NOT_PROVEN"


def test_builder_rejects_trajectory_and_part_frame_inputs_but_allows_raw_partout() -> None:
    with pytest.raises(BUILDER.NativeIdentityBuilderError, match="forbidden scientific content"):
        BUILDER._reject_scientific_path("/data/trajectory.h5")
    with pytest.raises(BUILDER.NativeIdentityBuilderError, match="forbidden scientific content"):
        BUILDER._reject_scientific_path("/data/Part_0000.bi4")
    BUILDER._reject_scientific_path("/data/PartOut_000.obi4")

