from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_root270_impact_sidecar_v3 as subject


def _records(path: Path, rows: list[dict]) -> dict:
    header = {
        "schema": subject.RECORD_SCHEMA,
        "status": "COMPLETED_TYPED_LIFECYCLE_RECORDS_NO_PHYSICAL_CREDIT",
        "family_id": "F6",
        "physical_case_id": "FIXTURE",
        "record_fields": subject.RECORD_FIELDS,
    }
    path.write_text("\n".join(json.dumps(item, sort_keys=True) for item in [header, *rows]) + "\n", encoding="utf-8")
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "rows": len(rows),
        "sha256": digest,
        "deferred": True,
        "content_opened_by_preparer": False,
        "read_after_parent_reservation": True,
    }


def _case(ref: dict, *ids: int) -> dict:
    return {
        "physical_case_id": "FIXTURE",
        "family_id": "F6",
        "selected_native_ids": [
            {
                "identity_key": [0, value],
                "zone": 0,
                "idp": value,
                "native_motive_code": 1,
                "native_first_missing_frame": 2,
                "native_first_missing_time_s": 1.0,
                "native_saved_bracket_s": [0.5, 1.0],
                "native_row_initial_mass_kg": None,
            }
            for value in ids
        ],
        "selected_native_id_count": len(ids),
        "typed_records_deferred": ref,
    }


def test_exact_mass_and_missing_mass_are_distinct(tmp_path: Path) -> None:
    ref = _records(
        tmp_path / "records.jsonl",
        [
            {"zone": 0, "idp": 10, "initial_type_code": 3, "initial_role": "fluid", "initial_mass_kg": 0.001, "first_disappeared_frame": 2},
            {"zone": 0, "idp": 11, "initial_type_code": 3, "initial_role": "fluid", "initial_mass_kg": None, "first_disappeared_frame": 2},
        ],
    )
    result = subject._stream_typed_records(_case(ref, 10, 11))
    assert result["found"][(0, 10)]["initial_mass_kg"] == pytest.approx(0.001)
    assert result["found"][(0, 11)]["initial_mass_kg"] is None
    assert result["fluid_initial_mass_kg"] is None


def test_role_average_proxy_is_never_invented(tmp_path: Path) -> None:
    ref = _records(tmp_path / "records.jsonl", [{"zone": 0, "idp": 10, "initial_type_code": 3, "initial_role": "fluid", "initial_mass_kg": 0.001}])
    case = _case(ref, 10)
    result = subject._stream_typed_records(case)
    assert "role_average_mass_proxy_kg" not in result
    assert case["selected_native_ids"][0].get("role_average_proxy_mass_kg") is None


def test_duplicate_identity_is_rejected(tmp_path: Path) -> None:
    ref = _records(
        tmp_path / "duplicate.jsonl",
        [
            {"zone": 0, "idp": 10, "initial_type_code": 3, "initial_role": "fluid", "initial_mass_kg": 0.001},
            {"zone": 0, "idp": 10, "initial_type_code": 3, "initial_role": "fluid", "initial_mass_kg": 0.001},
        ],
    )
    with pytest.raises(subject.ImpactV3Error, match="duplicate identity"):
        subject._stream_typed_records(_case(ref, 10))


def test_producer_header_and_selected_id_contract_are_strict(tmp_path: Path) -> None:
    path = tmp_path / "bad-header.jsonl"
    path.write_text(json.dumps({"schema": "wrong", "record_fields": []}) + "\n", encoding="utf-8")
    stat = path.stat()
    ref = {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "rows": 0,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "deferred": True,
        "content_opened_by_preparer": False,
        "read_after_parent_reservation": True,
    }
    with pytest.raises(subject.ImpactV3Error, match="header"):
        subject._stream_typed_records(_case(ref, 10))


def test_deferred_contract_requires_parent_reservation_and_jsonl() -> None:
    with pytest.raises(subject.ImpactV3Error, match="deferred"):
        subject._deferred_ref({"path": "/tmp/a.jsonl", "sha256": "0" * 64, "bytes": 1, "mtime_ns": 1, "ctime_ns": 1, "st_dev": 1, "st_ino": 1, "rows": 1}, "fixture")
    with pytest.raises(subject.ImpactV3Error, match="JSONL"):
        subject._deferred_ref({"path": "/tmp/a.h5", "sha256": "0" * 64, "bytes": 1, "mtime_ns": 1, "ctime_ns": 1, "st_dev": 1, "st_ino": 1, "rows": 1, "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}, "fixture")
