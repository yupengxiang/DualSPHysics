#!/usr/bin/env python3
"""Validate the fresh195 metadata-only cleanup package.

The validator reads only package JSON/README/Python and stats the explicitly
listed external paths.  It never opens or hashes a science payload.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
REPORT = PACKAGE / "metadata" / "fresh195-audit-report.json"
MANIFEST = PACKAGE / "metadata" / "manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["schema"] == "ds02.f5.cleanup-audit.v2"
    scope = report["scope"]
    assert scope["read_science_payload_bytes"] is False
    assert scope["hash_science_payload"] is False
    assert scope["copy_science_payload"] is False
    assert scope["delete_anything"] is False
    assert scope["launch_anything"] is False
    assert scope["modify_shared_state"] is False
    assert report["decision"]["safe_to_delete_now"] is False
    assert report["decision"]["immediate_deletion_candidates"] == []
    assert report["current_336_stage_membership_evidence"]["row_count"] == 48
    assert report["receipt_inventory"]["receipt_count"] >= 663
    assert len(report["cleanup_candidates"]) == 6
    assert len(report["protected_negative_or_recovery_evidence"]) == 8

    candidate_ids = {item["id"] for item in report["cleanup_candidates"]}
    assert candidate_ids == {
        "failed_solver_runup_coarse_055",
        "failed_solver_runup_medium_055",
        "failed_solver_weir_coarse_055",
        "failed_solver_a061_short_091",
        "compact_geometry_qa_052_payload",
        "compact_runup_geometry_qa_049_payload",
    }
    protected_ids = {item["id"] for item in report["protected_negative_or_recovery_evidence"]}
    assert {
        "a061_dynamic_penetration_negative",
        "b071_dynamic_penetration_negative",
        "a061_initial_qa_negative",
        "c082r1_precision_and_geometry_negative",
        "c082s1_precision_negative",
        "c082_thick_bed_geometry_negative",
        "a080_a120_terminated_render_provenance",
        "failed_typed_preflight_no_payload",
    } <= protected_ids

    # External checks are metadata/stat-only.  Never open the files named in
    # `payload_files`; checking that their parent tree still exists is enough.
    for item in report["cleanup_candidates"]:
        assert item["found"] is True
        for match in item["matches"]:
            assert match["status"] in {"failed", "completed"}
            assert Path(match["output_root"]).is_dir()
            assert match["pid_snapshot"]["alive"] is False
            assert match["directory"]["payload_files"]

    for item in report["protected_negative_or_recovery_evidence"]:
        assert item["matches"], item["id"]
        for match in item["matches"]:
            assert Path(match["output_root"]).is_dir()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else None
    if manifest is not None:
        for entry in manifest["files"]:
            path = PACKAGE / entry["path"]
            assert path.is_file(), path
            assert sha256(path) == entry["sha256"], path

    print("PASS fresh195: metadata-only F5 cleanup audit; immediate deletion candidates=0")
    print("  receipts=%d candidates=%d protected_groups=%d" % (
        report["receipt_inventory"]["receipt_count"],
        len(report["cleanup_candidates"]),
        len(report["protected_negative_or_recovery_evidence"]),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
