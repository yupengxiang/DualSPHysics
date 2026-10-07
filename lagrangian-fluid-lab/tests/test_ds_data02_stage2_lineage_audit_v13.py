from __future__ import annotations

import json
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_lineage_audit_v13 as audit  # noqa: E402


def test_manifest_identity_keeps_physical_and_manifest_alias_axes() -> None:
    case = {
        "family_id": "F1",
        "runtime_case_alias": "runtime-f1",
        "physical_case_id": "canonical-f1",
        "manifest_physical_case_id": "manifest-f1",
    }
    manifest = {"case_id": "manifest-f1", "physical_case_id": "manifest-f1"}
    matched, evidence = audit._manifest_identity_match(case, manifest)
    assert matched is True
    assert evidence["family_status"] == "UNDECLARED_MANIFEST_FAMILY; ID_MATCH_ONLY"
    assert evidence["matched_ids"] == ["manifest-f1"]


def test_family_card_is_json_serializable_and_stays_unknown() -> None:
    case = {
        "case_index": 0,
        "physical_case_id": "F1-case",
        "frames": 4,
        "particles": 8,
        "actual_time_window_s": [0.0, 1.0],
        "known_numeric_physical_parameters": {"gap_m": 0.2},
        "source_closure": {"status": "SMALL_SOURCE_HASH_CLOSURE_COMPLETE"},
        "control": {"class": "STATIC_OR_UNFORCED_DECLARATION", "signature_sha256": "a"},
        "geometry": {"signature_sha256": "b"},
        "resolution": {"xml_dp_values": ["0.01"], "tokens": ["010"]},
        "effective_condition": {
            "owner_condition_hashes": ["c"], "manifest_condition_hashes": [],
        },
        "recovery": {"status": "UNKNOWN_NO_EXPLICIT_RECOVERY_PROVENANCE"},
        "lineage": {"explicit_link_values": {"mechanism_id": ["m"]}},
    }
    card = audit.family_card("F1", [case], audit_path="audit.json")
    json.dumps(card)
    assert card["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert card["lineage"]["split_status"].startswith("PROVISIONAL_ONLY")
