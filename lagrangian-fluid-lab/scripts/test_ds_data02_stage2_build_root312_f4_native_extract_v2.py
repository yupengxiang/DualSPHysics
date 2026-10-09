from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_root312_f4_native_extract_v2 as subject


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deferred(path: Path, rows: int = 2) -> dict:
    stat = path.stat()
    return {
        "path": str(path),
        "sha256": _sha(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "rows": rows,
        "deferred": True,
        "content_opened_by_preparer": False,
        "read_after_parent_reservation": True,
    }


def _proof(tmp_path: Path, bundle_id: str, start: int, count: int = 8) -> Path:
    rows = []
    for offset in range(count):
        case_id = f"{bundle_id}_CASE_{start + offset}"
        summary = _write(tmp_path / "summaries" / f"{case_id}.json", {"physical_case_id": case_id, "status": "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT"})
        records = _write(tmp_path / "records" / f"{case_id}.jsonl", "fixture-records\n")
        case_manifest = _write(tmp_path / "case-manifests" / f"{case_id}.json", {"physical_case_id": case_id, "family_id": "F4"})
        receipt = _write(tmp_path / "receipts" / f"{case_id}.json", {"status": "COMPLETED", "returncode": 0})
        rows.append({
            "physical_case_id": case_id,
            "family_id": "F4",
            "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
            "case_manifest": str(case_manifest),
            "case_manifest_sha256": _sha(case_manifest),
            "receipt": str(receipt),
            "receipt_sha256": _sha(receipt),
            "summary": str(summary),
            "summary_sha256": _sha(summary),
            "records_stat_only": _deferred(records),
            "source_H5_prepost_known_SHA_and_current_stat_equal": True,
            "native_cause_fate_legal_flux_dynamics": "UNKNOWN",
        })
    batch_summary = _write(tmp_path / "batch" / f"{bundle_id}-batch-summary.json", {"cases_requested": count, "completed": count, "failed": 0})
    proof = {
        "schema": subject.PROOF_SCHEMA,
        "status": "VERIFIED_ACTUAL_F4_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT",
        "counts": {"cases_requested": count, "completed": count, "failed": 0},
        "batch_summary": str(batch_summary),
        "batch_summary_sha256": _sha(batch_summary),
        "report": str(batch_summary),
        "report_sha256": _sha(batch_summary),
        "case_verifications": rows,
    }
    return _write(tmp_path / "proofs" / f"{bundle_id}.json", proof)


def _selection(tmp_path: Path, ids_a: list[str], ids_b: list[str]) -> Path:
    return _write(tmp_path / "selection.json", {
        "schema": subject.SELECTION_SCHEMA,
        "bundles": [
            {"bundle_id": "ROOT296", "selected_case_ids": ids_a},
            {"bundle_id": "ROOT297", "selected_case_ids": ids_b},
        ],
    })


def test_actual_lifecycle_shape_preserves_two_complete_8_case_proofs_and_3_plus_4_subset(tmp_path: Path) -> None:
    proof_a = _proof(tmp_path, "ROOT296", 0)
    proof_b = _proof(tmp_path, "ROOT297", 100)
    loaded_a = subject._load_full_proof(proof_a, "ROOT296")
    loaded_b = subject._load_full_proof(proof_b, "ROOT297")
    selection = _selection(tmp_path, list(loaded_a["rows"])[:3], list(loaded_b["rows"])[:4])
    selected = subject._validate_selection_against_bundles(subject._load_selection(selection), {"ROOT296": loaded_a, "ROOT297": loaded_b})
    assert len(loaded_a["rows"]) == 8
    assert len(loaded_b["rows"]) == 8
    assert len(selected) == 7
    assert loaded_a["proof_value"]["counts"] == {"cases_requested": 8, "completed": 8, "failed": 0}
    assert all("summary" in loaded_a["row_edges"][case_id] and "records_stat_only" in loaded_a["row_edges"][case_id] for case_id in loaded_a["rows"])
    assert all("receipt" in loaded_b["row_edges"][case_id] and "case_manifest" in loaded_b["row_edges"][case_id] for case_id in loaded_b["rows"])


def test_old_3_case_or_report_shape_is_rejected(tmp_path: Path) -> None:
    proof = _proof(tmp_path, "ROOT296", 0)
    value = json.loads(proof.read_text(encoding="utf-8"))
    value["counts"] = {"cases_requested": 3, "completed": 3, "failed": 0}
    value["case_verifications"] = value["case_verifications"][:3]
    _write(proof, value)
    with pytest.raises(subject.Root312V2Error, match="8"):
        subject._load_full_proof(proof, "ROOT296")

    proof = _proof(tmp_path, "ROOT297", 100)
    value = json.loads(proof.read_text(encoding="utf-8"))
    value.pop("counts")
    value["actual_completed_physical_cases"] = 8
    _write(proof, value)
    with pytest.raises(subject.Root312V2Error, match="cases_requested"):
        subject._load_full_proof(proof, "ROOT297")


def test_missing_or_incomplete_proof_creates_no_ready_artifact(tmp_path: Path) -> None:
    proof_a = _proof(tmp_path, "ROOT296", 0)
    selection = _selection(tmp_path, [f"ROOT296_CASE_{i}" for i in range(3)], [f"ROOT297_CASE_{i}" for i in range(100, 104)])
    with pytest.raises(subject.Root312V2Error, match="missing"):
        subject.prepare(argparse.Namespace(
            proof296=proof_a,
            proof297=tmp_path / "ROOT297-not-available.json",
            selection_spec=selection,
            current=subject.CURRENT_DEFAULT,
            inventory=subject.INVENTORY_DEFAULT,
            output_root=tmp_path / "prepared",
            request_output=tmp_path / "request.json",
        ))
    assert not (tmp_path / "prepared").exists()
    assert not (tmp_path / "request.json").exists()


def test_selection_overlap_and_wrong_bundle_are_rejected(tmp_path: Path) -> None:
    proof_a = _proof(tmp_path, "ROOT296", 0)
    proof_b = _proof(tmp_path, "ROOT297", 100)
    loaded = {"ROOT296": subject._load_full_proof(proof_a, "ROOT296"), "ROOT297": subject._load_full_proof(proof_b, "ROOT297")}
    overlap = _write(tmp_path / "overlap.json", {
        "schema": subject.SELECTION_SCHEMA,
        "bundles": [
            {"bundle_id": "ROOT296", "selected_case_ids": ["ROOT296_CASE_0", "ROOT296_CASE_1", "ROOT296_CASE_2"]},
            {"bundle_id": "ROOT297", "selected_case_ids": ["ROOT296_CASE_0", "ROOT297_CASE_101", "ROOT297_CASE_102", "ROOT297_CASE_103"]},
        ],
    })
    with pytest.raises(subject.Root312V2Error, match="overlap"):
        subject._validate_selection_against_bundles(subject._load_selection(overlap), loaded)


def test_self_test_is_source_only() -> None:
    result = subject._self_test()
    assert result["status"] == "PASS"
    assert result["full_producer_proof_case_count"] == 16
    assert result["selected_original118_case_count"] == 7
    assert result["payload_opened"] is False
